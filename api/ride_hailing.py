from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from datetime import datetime, timedelta, timezone
from tartanilla_admin.supabase import supabase, execute_with_retry, safe_query
from core.error_handlers import handle_api_errors, safe_supabase_operation, APIErrorHandler
from api.driver_metrics import record_driver_cancellation, record_driver_completion, check_and_suspend_driver_if_needed
import uuid
import json
import logging
import math
import threading
import time

# Prefer admin client for audit_logs (bypass RLS) if available
try:
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# JWT helpers (optional)
try:
    from core.jwt_auth import verify_token, get_token_from_request
except Exception:
    verify_token = None
    get_token_from_request = None

logger = logging.getLogger(__name__)


class RideHailingViewSet(viewsets.ViewSet):
    """Dedicated ViewSet for ride-hailing (separate from tour packages)."""
    permission_classes = [AllowAny]

    TABLE = 'ride_hailing_bookings'

    # ─────────────────────────────────────────────
    # Audit helpers
    # ─────────────────────────────────────────────
    def _client(self):
        return supabase_admin or supabase

    def _get_ip(self, request):
        try:
            xff = request.META.get('HTTP_X_FORWARDED_FOR')
            if xff:
                return xff.split(',')[0].strip()
            return request.META.get('REMOTE_ADDR')
        except Exception:
            return None

    def _get_actor(self, request, fallback_user_id=None):
        """
        Returns dict: { user_id, username, role }
        Priority: JWT → request.user → fallback_user_id (lookup from users table)
        """
        actor = {'user_id': None, 'username': None, 'role': None}
        try:
            # JWT-based
            if get_token_from_request and verify_token:
                token = get_token_from_request(request)
                if token:
                    claims = verify_token(token) or {}
                    if isinstance(claims, dict):
                        actor['user_id'] = claims.get('sub') or claims.get('user_id') or claims.get('id')
                        actor['username'] = claims.get('username') or claims.get('email')
                        actor['role'] = claims.get('role') or claims.get('user_role')

            # Django user
            if not actor['user_id']:
                u = getattr(request, 'user', None)
                if getattr(u, 'is_authenticated', False):
                    actor['user_id'] = getattr(u, 'id', None)
                    actor['username'] = getattr(u, 'username', None) or getattr(u, 'email', None)
                    try:
                        actor['role'] = getattr(u, 'role', None) or getattr(getattr(u, 'role', None), 'name', None)
                    except Exception:
                        pass

            # Fallback lookup
            if not actor['user_id'] and fallback_user_id:
                actor['user_id'] = fallback_user_id
                try:
                    uresp = supabase.table('users').select('name, email, role').eq('id', fallback_user_id).single().execute()
                    if hasattr(uresp, 'data') and uresp.data:
                        actor['username'] = uresp.data.get('name') or uresp.data.get('email')
                        actor['role'] = uresp.data.get('role')
                except Exception:
                    pass
        except Exception:
            pass
        return actor

    def _audit(self, request, *, action, entity_name, entity_id=None, new_data=None, old_data=None, actor=None):
        """
        Inserts an audit row; failure should not break main flow.
        """
        try:
            actor = actor or self._get_actor(request)
            payload = {
                'user_id': actor.get('user_id'),
                'username': actor.get('username'),
                'role': actor.get('role'),
                'action': action,
                'entity_name': entity_name,
                'entity_id': str(entity_id) if entity_id is not None else None,
                'old_data': old_data or None,
                'new_data': new_data or None,
                'ip_address': self._get_ip(request),
                'device_info': request.META.get('HTTP_USER_AGENT') if request else None,
            }
            self._client().table('audit_logs').insert(payload).execute()
        except Exception as e:
            logger.warning(f"[AUDIT] insert failed: {e}")

    # ─────────────────────────────────────────────
    # Core endpoints
    # ─────────────────────────────────────────────
    def list(self, request):
        try:
            status_filter = request.query_params.get('status') if hasattr(request, 'query_params') else request.GET.get('status')
            
            def query_func():
                query = supabase.table(self.TABLE).select('*').order('created_at', desc=True)
                if status_filter:
                    query = query.eq('status', status_filter)
                return query.execute()
            
            resp = execute_with_retry(query_func)
            rides = getattr(resp, 'data', [])
            
            # Enrich with driver and carriage info
            enriched_rides = self._enrich_rides_with_details(rides)
            
            return Response({'success': True, 'data': enriched_rides})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def retrieve(self, request, pk=None):
        try:
            resp = supabase.table(self.TABLE).select('*').eq('id', pk).single().execute()
            if not getattr(resp, 'data', None):
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            
            # Enrich with driver and carriage info
            enriched_rides = self._enrich_rides_with_details([resp.data])
            ride_data = enriched_rides[0] if enriched_rides else resp.data
            
            return Response({'success': True, 'data': ride_data})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request):
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            required = ['customer_id', 'pickup_address', 'dropoff_address']
            missing = [f for f in required if not data.get(f)]
            if missing:
                return Response({'success': False, 'error': f"Missing: {', '.join(missing)}"}, status=status.HTTP_400_BAD_REQUEST)
            
            customer_id = data['customer_id']
            passenger_count = int(data.get('passenger_count', 1))
            pickup_address = data['pickup_address']
            dropoff_address = data['dropoff_address']
            ride_type = data.get('ride_type', 'shared')  # 'instant' or 'shared'
            
            if passenger_count <= 0 or passenger_count > 4:
                passenger_count = 1
            
            # Check if customer has active rides
            active_check = supabase.table(self.TABLE).select('*').eq('customer_id', customer_id).in_('status', ['waiting_for_driver', 'driver_assigned', 'in_progress']).execute()
            
            if hasattr(active_check, 'data') and active_check.data:
                return Response({
                    'success': False, 
                    'error': 'You already have an active ride request. Please wait for it to complete or cancel it first.',
                    'error_code': 'ACTIVE_RIDE_EXISTS',
                    'active_rides': active_check.data
                }, status=status.HTTP_400_BAD_REQUEST)
            

            
            # Create new ride with pricing based on type
            if ride_type == 'instant':
                total_fare = 40.00
                fare_per_person = 40.00
            else:  # shared
                fare_per_person = 10.00
                total_fare = passenger_count * 10.00
            
            booking_status = 'waiting_for_driver'
            
            payload = {
                'customer_id': customer_id,
                'pickup_address': pickup_address,
                'dropoff_address': dropoff_address,
                'status': booking_status,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'notes': data.get('notes', ''),
                'passenger_count': passenger_count,
                'fare_per_person': fare_per_person,
                'total_fare': total_fare,
                'ride_type': ride_type
            }
            
            # Store coordinates if provided
            if data.get('pickup_latitude') and data.get('pickup_longitude'):
                payload['pickup_latitude'] = float(data['pickup_latitude'])
                payload['pickup_longitude'] = float(data['pickup_longitude'])
            if data.get('dropoff_latitude') and data.get('dropoff_longitude'):
                payload['dropoff_latitude'] = float(data['dropoff_latitude'])
                payload['dropoff_longitude'] = float(data['dropoff_longitude'])
            
            resp = supabase.table(self.TABLE).insert(payload).execute()
            if hasattr(resp, 'data') and resp.data:
                inserted = resp.data[0]
                # AUDIT
                actor = self._get_actor(request, fallback_user_id=customer_id)
                self._audit(
                    request,
                    action='RIDEHAIL_CREATE',
                    entity_name=self.TABLE,
                    entity_id=inserted.get('id'),
                    new_data=inserted,
                    old_data=None,
                    actor=actor
                )
                
                # Notify available drivers
                try:
                    self._notify_available_drivers_for_ride(inserted)
                except Exception as notify_error:
                    print(f"[RIDE_HAILING] Failed to notify drivers: {notify_error}")
                
                return Response({
                    'success': True, 
                    'data': inserted, 
                    'message': f'{ride_type.title()} ride created with {passenger_count} passengers - ₱{total_fare}',
                    'ride_type': ride_type
                }, status=status.HTTP_201_CREATED)
            return Response({'success': False, 'error': 'Failed to create ride booking'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, pk=None):
        try:
            # Fetch old before update (for audit)
            select_old = supabase.table(self.TABLE).select('*').eq('id', pk).single().execute()
            old_row = getattr(select_old, 'data', None)

            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            allowed = {k: v for k, v in data.items() if k in ['pickup_address', 'dropoff_address', 'notes', 'status']}
            allowed['updated_at'] = datetime.now().isoformat()
            resp = supabase.table(self.TABLE).update(allowed).eq('id', pk).execute()
            if hasattr(resp, 'data') and resp.data:
                updated = resp.data[0]
                # AUDIT
                fallback_uid = (data.get('customer_id')
                                or (old_row.get('customer_id') if isinstance(old_row, dict) else None))
                actor = self._get_actor(request, fallback_user_id=fallback_uid)
                self._audit(
                    request,
                    action='RIDEHAIL_UPDATE',
                    entity_name=self.TABLE,
                    entity_id=pk,
                    new_data=updated,
                    old_data=old_row,
                    actor=actor
                )
                return Response({'success': True, 'data': updated})
            return Response({'success': False, 'error': 'Failed to update ride booking'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, pk=None):
        try:
            # Fetch old before delete (for audit)
            select_old = supabase.table(self.TABLE).select('*').eq('id', pk).single().execute()
            old_row = getattr(select_old, 'data', None)

            resp = supabase.table(self.TABLE).delete().eq('id', pk).execute()
            success = hasattr(resp, 'data') and resp.data is not None
            if success:
                # AUDIT
                fallback_uid = (old_row.get('customer_id') if isinstance(old_row, dict) else None)
                actor = self._get_actor(request, fallback_user_id=fallback_uid)
                self._audit(
                    request,
                    action='RIDEHAIL_DELETE',
                    entity_name=self.TABLE,
                    entity_id=pk,
                    new_data=None,
                    old_data=old_row,
                    actor=actor
                )
                return Response({'success': True, 'message': 'Ride booking deleted'}, status=status.HTTP_204_NO_CONTENT)
            return Response({'success': False, 'error': 'Failed to delete ride booking'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='driver-accept/(?P<booking_id>[^/.]+)')
    def driver_accept(self, request, booking_id=None):
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            driver_id = data.get('driver_id')
            driver_name = data.get('driver_name')
            if not driver_id or not driver_name:
                return Response({'success': False, 'error': 'Missing driver_id or driver_name'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if driver has an assigned tartanilla
            carriage_check = supabase.table('tartanilla_carriages').select('id').eq('assigned_driver_id', driver_id).in_('status', ['driver_assigned', 'active', 'in_use']).execute()
            if not (hasattr(carriage_check, 'data') and carriage_check.data):
                return Response({
                    'success': False, 
                    'error': 'You must be assigned to a tartanilla before accepting rides. Please contact your carriage owner.',
                    'error_code': 'NO_CARRIAGE_ASSIGNED'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if driver has active rides
            active_check = supabase.table(self.TABLE).select('*').eq('driver_id', driver_id).in_('status', ['driver_assigned', 'in_progress']).execute()
            
            if hasattr(active_check, 'data') and active_check.data:
                return Response({
                    'success': False, 
                    'error': 'You already have an active ride. Please complete or cancel your current ride first.',
                    'error_code': 'DRIVER_ACTIVE_RIDE_EXISTS',
                    'active_rides': active_check.data
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Fetch booking (old data for audit)
            resp = supabase.table(self.TABLE).select('*').eq('id', booking_id).single().execute()
            ride = getattr(resp, 'data', None)
            if not ride:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            if ride.get('status') != 'waiting_for_driver':
                return Response({'success': False, 'error': 'Booking is not available'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Update with WHERE clause to prevent race conditions
            upd = supabase.table(self.TABLE).update({
                'status': 'driver_assigned',
                'driver_id': driver_id,
                'driver_name': driver_name,
                'driver_assigned_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }).eq('id', booking_id).eq('status', 'waiting_for_driver').execute()
            
            print(f"[RIDE_HAILING] ✅ Driver {driver_name} accepted ride {booking_id} - auto-cancel timer will be stopped")

            updated_row = getattr(upd, 'data', None)
            if isinstance(updated_row, list) and updated_row:
                updated_row = updated_row[0]
            
            # Enrich with driver and carriage info
            if updated_row:
                enriched = self._enrich_rides_with_details([updated_row])
                updated_row = enriched[0] if enriched else updated_row

            # AUDIT
            actor = self._get_actor(request, fallback_user_id=driver_id)
            self._audit(
                request,
                action='RIDEHAIL_DRIVER_ACCEPT',
                entity_name=self.TABLE,
                entity_id=booking_id,
                new_data=updated_row,
                old_data=ride,
                actor=actor
            )
            
            # Notify all passengers
            try:
                self._notify_passengers_driver_assigned(updated_row, driver_name)
            except Exception as e:
                print(f"Failed to notify passengers: {e}")
            
            return Response({'success': True, 'data': updated_row or {}, 'message': f'Accepted by {driver_name}'})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='customer-cancel/(?P<booking_id>[^/.]+)')
    def customer_cancel(self, request, booking_id=None):
        """Tourist cancels the ride."""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            customer_id = data.get('customer_id')
            reason = data.get('reason', '')
            resp = supabase.table(self.TABLE).select('*').eq('id', booking_id).single().execute()
            ride = getattr(resp, 'data', None)
            if not ride:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            if ride.get('customer_id') != customer_id:
                return Response({'success': False, 'error': 'Unauthorized cancellation'}, status=status.HTTP_403_FORBIDDEN)
            if ride.get('status') in ['completed', 'cancelled']:
                return Response({'success': False, 'error': 'Booking already finalized'}, status=status.HTTP_400_BAD_REQUEST)
            upd = supabase.table(self.TABLE).update({
                'status': 'cancelled',
                'cancel_reason': reason,
                'cancelled_by': 'customer',
                'cancelled_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }).eq('id', booking_id).execute()

            updated_row = getattr(upd, 'data', None)
            if isinstance(updated_row, list) and updated_row:
                updated_row = updated_row[0]

            # AUDIT
            actor = self._get_actor(request, fallback_user_id=customer_id)
            self._audit(
                request,
                action='RIDEHAIL_CUSTOMER_CANCEL',
                entity_name=self.TABLE,
                entity_id=booking_id,
                new_data=updated_row,
                old_data=ride,
                actor=actor
            )
            return Response({'success': True, 'data': updated_row or {}, 'message': 'Booking cancelled by customer'})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='driver-cancel/(?P<booking_id>[^/.]+)')
    def driver_cancel(self, request, booking_id=None):
        """Driver cancels; record and check suspension."""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            driver_id = data.get('driver_id')
            reason = data.get('reason', '')
            resp = supabase.table(self.TABLE).select('*').eq('id', booking_id).single().execute()
            ride = getattr(resp, 'data', None)
            if not ride:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            if not driver_id or (ride.get('driver_id') and str(ride.get('driver_id')) != str(driver_id)):
                return Response({'success': False, 'error': 'Unauthorized driver'}, status=status.HTTP_403_FORBIDDEN)
            # Reset to waiting_for_driver for reassignment instead of cancelling
            upd = supabase.table(self.TABLE).update({
                'status': 'waiting_for_driver',
                'driver_id': None,
                'driver_name': None,
                'driver_assigned_at': None,
                'cancel_reason': reason,
                'last_cancelled_by': 'driver',
                'last_cancelled_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }).eq('id', booking_id).execute()
            updated_row = getattr(upd, 'data', None)
            if isinstance(updated_row, list) and updated_row:
                updated_row = updated_row[0]

            # Log and check suspension
            record_driver_cancellation(driver_id=driver_id, booking_id=booking_id, reason=reason, booking_type='ride')
            suspension = check_and_suspend_driver_if_needed(driver_id)

            # AUDIT
            actor = self._get_actor(request, fallback_user_id=driver_id)
            self._audit(
                request,
                action='RIDEHAIL_DRIVER_CANCEL',
                entity_name=self.TABLE,
                entity_id=booking_id,
                new_data=updated_row,
                old_data=ride,
                actor=actor
            )

            # Notify available drivers for reassignment
            try:
                if updated_row:
                    self._notify_available_drivers_for_ride(updated_row)
            except Exception as notify_error:
                print(f"[RIDE_HAILING] Failed to notify drivers for reassignment: {notify_error}")
            
            payload = {'success': True, 'data': updated_row or {}, 'message': 'Ride reassigned to other drivers'}
            if suspension and suspension.get('success'):
                payload['driver_suspended'] = True
                payload['suspension'] = suspension
            else:
                payload['driver_suspended'] = False
            return Response(payload)
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='start/(?P<booking_id>[^/.]+)')
    def start_ride(self, request, booking_id=None):
        """Driver starts the ride (transitions to in_progress)."""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            driver_id = data.get('driver_id')
            
            resp = supabase.table(self.TABLE).select('*').eq('id', booking_id).single().execute()
            ride = getattr(resp, 'data', None)
            if not ride:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            
            if ride.get('status') == 'in_progress':
                print(f"[RIDE_HAILING] Ride {booking_id} already in progress")
                return Response({'success': True, 'data': ride, 'message': 'Ride already started'})
            
            if ride.get('driver_id') != driver_id:
                return Response({'success': False, 'error': 'Only assigned driver can start this ride'}, status=status.HTTP_403_FORBIDDEN)
            
            # Update with WHERE clause to prevent race conditions
            upd = supabase.table(self.TABLE).update({
                'status': 'in_progress',
                'started_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }).eq('id', booking_id).eq('status', 'driver_assigned').execute()
            
            updated_row = getattr(upd, 'data', None)
            if isinstance(updated_row, list) and updated_row:
                updated_row = updated_row[0]
            else:
                # Check if already started
                check = supabase.table(self.TABLE).select('*').eq('id', booking_id).single().execute()
                current_ride = getattr(check, 'data', None)
                if current_ride and current_ride.get('status') == 'in_progress':
                    return Response({'success': True, 'data': current_ride, 'message': 'Ride already started'})
                else:
                    return Response({'success': False, 'error': f'Failed to start ride - current status: {current_ride.get("status") if current_ride else "unknown"}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            print(f"[RIDE_HAILING] ✅ Ride {booking_id} started by driver {driver_id}")
            return Response({'success': True, 'data': updated_row or {}, 'message': 'Ride started'})
        except Exception as e:
            print(f"[RIDE_HAILING] ❌ Error starting ride {booking_id}: {str(e)}")
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='complete/(?P<booking_id>[^/.]+)')
    def complete(self, request, booking_id=None):
        """Mark ride as completed and record completion for metrics."""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            driver_id = data.get('driver_id')
            
            # Fetch current ride data
            resp = supabase.table(self.TABLE).select('*').eq('id', booking_id).single().execute()
            ride = getattr(resp, 'data', None)
            if not ride:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            
            # Check if already completed or cancelled
            if ride.get('status') == 'completed':
                print(f"[RIDE_HAILING] Ride {booking_id} already completed")
                return Response({'success': True, 'data': ride, 'message': 'Ride already completed'})
            
            if ride.get('status') == 'cancelled':
                return Response({'success': False, 'error': 'Cannot complete a cancelled ride'}, status=status.HTTP_400_BAD_REQUEST)
            
            if ride.get('status') not in ['driver_assigned', 'in_progress']:
                return Response({'success': False, 'error': f'Ride not in progress (current status: {ride.get("status")})'}, status=status.HTTP_400_BAD_REQUEST)
            
            if ride.get('driver_id') != driver_id:
                return Response({'success': False, 'error': 'Only assigned driver can complete this ride'}, status=status.HTTP_403_FORBIDDEN)
            
            # Update to completed - use WHERE clause to prevent race conditions
            upd = supabase.table(self.TABLE).update({
                'status': 'completed',
                'completed_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }).eq('id', booking_id).in_('status', ['driver_assigned', 'in_progress']).execute()
            
            updated_row = getattr(upd, 'data', None)
            if isinstance(updated_row, list) and updated_row:
                updated_row = updated_row[0]
            else:
                # If update failed, fetch current status
                check = supabase.table(self.TABLE).select('*').eq('id', booking_id).single().execute()
                current_ride = getattr(check, 'data', None)
                if current_ride and current_ride.get('status') == 'completed':
                    print(f"[RIDE_HAILING] Ride {booking_id} was completed by another request")
                    return Response({'success': True, 'data': current_ride, 'message': 'Ride completed'})
                else:
                    return Response({'success': False, 'error': f'Failed to complete ride - current status: {current_ride.get("status") if current_ride else "unknown"}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # AUDIT
            actor = self._get_actor(request, fallback_user_id=driver_id)
            self._audit(
                request,
                action='RIDEHAIL_COMPLETE',
                entity_name=self.TABLE,
                entity_id=booking_id,
                new_data=updated_row,
                old_data=ride,
                actor=actor
            )

            if driver_id:
                record_driver_completion(driver_id=driver_id, booking_id=booking_id, booking_type='ride')
                # Record ride hailing earnings - use updated_row if available, otherwise ride
                earnings_data = updated_row if updated_row else ride
                print(f"[RIDE_HAILING] 💰 Calling earnings recording for ride {booking_id}")
                print(f"[RIDE_HAILING] Earnings data: total_fare={earnings_data.get('total_fare')}, driver_id={driver_id}")
                self._record_ride_hailing_earnings(earnings_data, driver_id)
            
            print(f"[RIDE_HAILING] ✅ Ride {booking_id} completed successfully by driver {driver_id}")
            return Response({'success': True, 'data': updated_row or {}, 'message': 'Ride completed'})
        except Exception as e:
            print(f"[RIDE_HAILING] ❌ Error completing ride {booking_id}: {str(e)}")
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='available-for-drivers')
    @handle_api_errors(fallback_data=[])
    def available_for_drivers(self, request):
        try:
            driver_id = request.query_params.get('driver_id') if hasattr(request, 'query_params') else request.GET.get('driver_id')
            
            def query_func():
                return supabase.table(self.TABLE).select('*').in_('status', ['waiting_for_driver', 'driver_assigned']).order('created_at', desc=True).execute()
            
            resp = safe_supabase_operation(query_func, fallback_data=[])
            rides = getattr(resp, 'data', [])
            
            # Filter rides that are waiting for drivers
            available_rides = []
            for ride in rides:
                if ride.get('status') == 'waiting_for_driver':
                    # Check if driver is available if driver_id provided
                    if driver_id:
                        is_available = self._check_driver_availability_for_ride(driver_id)
                        if is_available:
                            available_rides.append(ride)
                    else:
                        available_rides.append(ride)
            
            return Response(APIErrorHandler.create_success_response(available_rides))
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='check-active-ride')
    def check_active_ride(self, request):
        try:
            user_id = request.query_params.get('user_id') if hasattr(request, 'query_params') else request.GET.get('user_id')
            user_type = request.query_params.get('user_type', 'customer') if hasattr(request, 'query_params') else request.GET.get('user_type', 'customer')
            
            if not user_id:
                return Response({'success': False, 'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Optimized query with limit and minimal fields
            if user_type == 'driver':
                active_check = supabase.table(self.TABLE).select('id,status,created_at').eq('driver_id', user_id).in_('status', ['driver_assigned', 'in_progress']).limit(5).execute()
            else:
                active_check = supabase.table(self.TABLE).select('id,status,created_at').eq('customer_id', user_id).in_('status', ['waiting_for_driver', 'driver_assigned', 'in_progress']).limit(5).execute()
            
            active_rides = getattr(active_check, 'data', [])
            has_active_ride = len(active_rides) > 0
            suggest_cancel = False
            
            if active_rides:
                for ride in active_rides:
                    if ride.get('status') == 'waiting_for_driver':
                        try:
                            created_at = datetime.fromisoformat(ride['created_at'].replace('Z', '+00:00'))
                            time_elapsed = datetime.now(created_at.tzinfo) - created_at
                            if time_elapsed.total_seconds() > 300:
                                suggest_cancel = True
                                break
                        except:
                            pass
            
            return Response({
                'success': True,
                'has_active_ride': has_active_ride,
                'count': len(active_rides),
                'suggest_cancel': suggest_cancel
            })
        except Exception as e:
            logger.error(f"check_active_ride error: {e}")
            return Response({'success': False, 'has_active_ride': False, 'count': 0}, status=status.HTTP_200_OK)
    
    def _check_driver_availability_for_ride(self, driver_id):
        """Check if driver is available for immediate ride hailing (current time)"""
        try:
            from datetime import datetime, date
            
            today = date.today().isoformat()
            current_time = datetime.now().strftime('%H:%M')
            
            # Check driver schedule for today
            schedule_response = supabase.table('driver_schedule').select('*').eq('driver_id', driver_id).eq('date', today).execute()
            
            if hasattr(schedule_response, 'data') and schedule_response.data:
                schedule = schedule_response.data[0]
                if not schedule.get('is_available', True):
                    return False
                
                # Check if current time is in unavailable times
                unavailable_times = schedule.get('unavailable_times', [])
                if current_time in unavailable_times:
                    return False
            
            # Check if driver has active rides or bookings
            active_rides = supabase.table(self.TABLE).select('*').eq('driver_id', driver_id).in_('status', ['driver_assigned', 'in_progress']).execute()
            if hasattr(active_rides, 'data') and active_rides.data:
                return False
            
            return True
        except Exception as e:
            print(f"Error checking driver availability: {e}")
            return False
    
    def _calculate_distance(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two points using Haversine formula"""
        R = 6371  # Earth's radius in kilometers
        
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    def _get_drivers_by_distance(self, pickup_lat, pickup_lon):
        """Get available drivers sorted by distance from pickup location"""
        try:
            # Get all active drivers
            drivers_response = supabase.table('users').select('id, name').in_('role', ['driver', 'driver-owner']).eq('status', 'active').execute()
            
            if not (hasattr(drivers_response, 'data') and drivers_response.data):
                return []
            
            # Get driver locations (only recent ones with location sharing enabled)
            from datetime import datetime, timedelta
            cutoff_time = datetime.now() - timedelta(minutes=10)
            locations_response = supabase.table('driver_locations').select('*').gte('updated_at', cutoff_time.isoformat()).execute()
            locations_data = getattr(locations_response, 'data', [])
            
            # Create location lookup
            location_map = {loc['user_id']: loc for loc in locations_data}
            
            drivers_with_distance = []
            for driver in drivers_response.data:
                # Check availability
                if not self._check_driver_availability_for_ride(driver['id']):
                    continue
                
                # Check if driver has recent location (implies location sharing is on)
                location = location_map.get(driver['id'])
                if not location:
                    continue
                
                # Calculate distance
                distance = self._calculate_distance(
                    pickup_lat, pickup_lon,
                    float(location['latitude']), float(location['longitude'])
                )
                
                drivers_with_distance.append({
                    'id': driver['id'],
                    'name': driver['name'],
                    'distance': distance,
                    'latitude': location['latitude'],
                    'longitude': location['longitude']
                })
            
            # Sort by distance (closest first)
            drivers_with_distance.sort(key=lambda x: x['distance'])
            return drivers_with_distance
            
        except Exception as e:
            print(f"[RIDE_HAILING] Error getting drivers by distance: {e}")
            return []
    
    def _notify_driver_sequential(self, ride_id, driver_queue, attempt=1):
        """Notify drivers sequentially with timeout"""
        try:
            if not driver_queue:
                print(f"[RIDE_HAILING] No more drivers to notify for ride {ride_id}")
                self._auto_cancel_ride(ride_id, "No available drivers")
                return
            
            # Get current driver
            current_driver = driver_queue[0]
            remaining_drivers = driver_queue[1:]
            
            print(f"[RIDE_HAILING] Notifying driver {current_driver['name']} (attempt {attempt}, distance: {current_driver['distance']:.2f}km)")
            
            # Get ride data
            ride_response = supabase.table(self.TABLE).select('*').eq('id', ride_id).single().execute()
            if not (hasattr(ride_response, 'data') and ride_response.data):
                print(f"[RIDE_HAILING] Ride {ride_id} not found")
                return
            
            ride_data = ride_response.data
            
            # Check if ride is still waiting
            if ride_data.get('status') != 'waiting_for_driver':
                print(f"[RIDE_HAILING] Ride {ride_id} no longer waiting (status: {ride_data.get('status')})")
                return
            
            # Create notification for current driver
            pickup_address = ride_data.get('pickup_address', 'Unknown location')
            dropoff_address = ride_data.get('dropoff_address', 'Unknown destination')
            
            notification_data = {
                'title': f'New Ride Request! 🚗 ({current_driver["distance"]:.1f}km away)',
                'message': f'Ride from {pickup_address} to {dropoff_address}. Tap to accept!',
                'type': 'booking',
                'created_at': datetime.now().isoformat(),
                'ride_id': ride_id,
                'priority_driver': current_driver['id']
            }
            
            notification = supabase.table('notifications').insert(notification_data).execute()
            
            if notification.data:
                notification_id = notification.data[0]['id']
                
                # Send to current driver only
                recipient_data = {
                    'notification_id': notification_id,
                    'user_id': current_driver['id'],
                    'role': 'driver',
                    'delivery_status': 'sent'
                }
                
                supabase.table('notification_recipients').insert(recipient_data).execute()
                print(f"[RIDE_HAILING] Notified driver {current_driver['name']}")
                
                # Set timer for next driver (2 minutes)
                def notify_next():
                    time.sleep(120)  # 2 minutes
                    # Check if ride is still waiting
                    check_response = supabase.table(self.TABLE).select('status').eq('id', ride_id).single().execute()
                    if (hasattr(check_response, 'data') and check_response.data and 
                        check_response.data.get('status') == 'waiting_for_driver'):
                        self._notify_driver_sequential(ride_id, remaining_drivers, attempt + 1)
                
                # Start timer in background thread
                timer_thread = threading.Thread(target=notify_next)
                timer_thread.daemon = True
                timer_thread.start()
            
        except Exception as e:
            print(f"[RIDE_HAILING] Error in sequential notification: {e}")
    
    def _auto_cancel_ride(self, ride_id, reason="No driver available after 5 minutes"):
        """Auto-cancel ride after timeout"""
        try:
            # Check current status before cancelling
            check = supabase.table(self.TABLE).select('status').eq('id', ride_id).single().execute()
            if not (hasattr(check, 'data') and check.data):
                return
            
            current_status = check.data.get('status')
            # ONLY cancel if still waiting for driver - DO NOT cancel completed/in_progress rides
            if current_status != 'waiting_for_driver':
                print(f"[RIDE_HAILING] Skipping auto-cancel for ride {ride_id} - status is {current_status}")
                return
            
            print(f"[RIDE_HAILING] Auto-cancelling ride {ride_id}: {reason}")
            
            # Update ride status - ONLY if still waiting_for_driver (double check with WHERE clause)
            result = supabase.table(self.TABLE).update({
                'status': 'cancelled',
                'cancel_reason': reason,
                'cancelled_by': 'system',
                'cancelled_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
            }).eq('id', ride_id).eq('status', 'waiting_for_driver').execute()
            
            # Log if update actually happened
            if hasattr(result, 'data') and result.data:
                print(f"[RIDE_HAILING] Auto-cancelled ride {ride_id}")
            else:
                print(f"[RIDE_HAILING] Auto-cancel skipped - ride {ride_id} status changed")
            
            # Notify customer about cancellation
            ride_response = supabase.table(self.TABLE).select('customer_id, pickup_address').eq('id', ride_id).single().execute()
            if hasattr(ride_response, 'data') and ride_response.data:
                customer_id = ride_response.data.get('customer_id')
                pickup_address = ride_response.data.get('pickup_address', 'your location')
                
                if customer_id:
                    notification_data = {
                        'title': 'Ride Cancelled 😔',
                        'message': f'Sorry, no drivers available for pickup at {pickup_address}. Please try again later.',
                        'type': 'cancellation',
                        'created_at': datetime.now().isoformat()
                    }
                    
                    notification = supabase.table('notifications').insert(notification_data).execute()
                    
                    if notification.data:
                        notification_id = notification.data[0]['id']
                        supabase.table('notification_recipients').insert({
                            'notification_id': notification_id,
                            'user_id': customer_id,
                            'role': 'tourist',
                            'delivery_status': 'sent'
                        }).execute()
            
        except Exception as e:
            print(f"[RIDE_HAILING] Error auto-cancelling ride: {e}")
    
    def _notify_available_drivers_for_ride(self, ride_data):
        """Start sequential driver notification based on distance"""
        try:
            ride_id = ride_data.get('id')
            pickup_lat = ride_data.get('pickup_latitude')
            pickup_lon = ride_data.get('pickup_longitude')
            
            if not (pickup_lat and pickup_lon):
                print('[RIDE_HAILING] No pickup coordinates provided, using fallback notification')
                self._fallback_notify_all_drivers(ride_data)
                return
            
            # Get drivers sorted by distance
            drivers_by_distance = self._get_drivers_by_distance(float(pickup_lat), float(pickup_lon))
            
            if not drivers_by_distance:
                print('[RIDE_HAILING] No available drivers with locations found')
                # Set auto-cancel timer for 5 minutes
                def auto_cancel():
                    time.sleep(300)  # 5 minutes
                    self._auto_cancel_ride(ride_id, "No available drivers")
                
                timer_thread = threading.Thread(target=auto_cancel)
                timer_thread.daemon = True
                timer_thread.start()
                return
            
            print(f'[RIDE_HAILING] Found {len(drivers_by_distance)} available drivers, starting sequential notification')
            
            # Start sequential notification
            self._notify_driver_sequential(ride_id, drivers_by_distance)
            
            # Set overall auto-cancel timer for 5 minutes
            def auto_cancel():
                time.sleep(300)  # 5 minutes
                self._auto_cancel_ride(ride_id, "No driver accepted within 5 minutes")
            
            timer_thread = threading.Thread(target=auto_cancel)
            timer_thread.daemon = True
            timer_thread.start()
            
        except Exception as e:
            print(f"[RIDE_HAILING] Error in driver notification: {e}")
            self._fallback_notify_all_drivers(ride_data)
    



    


    def _fallback_notify_all_drivers(self, ride_data):
        """Fallback to notify all available drivers at once"""
        try:
            # Get all active drivers with recent location updates (location sharing enabled)
            from datetime import datetime, timedelta
            cutoff_time = datetime.now() - timedelta(minutes=10)
            
            drivers_response = supabase.table('users').select('id, name').in_('role', ['driver', 'driver-owner']).eq('status', 'active').execute()
            locations_response = supabase.table('driver_locations').select('user_id').gte('updated_at', cutoff_time.isoformat()).execute()
            
            if not (hasattr(drivers_response, 'data') and drivers_response.data):
                print('[RIDE_HAILING] No drivers found')
                return
            
            # Get drivers with active location sharing
            active_location_drivers = {loc['user_id'] for loc in getattr(locations_response, 'data', [])}
            
            available_drivers = []
            for driver in drivers_response.data:
                if (driver['id'] in active_location_drivers and 
                    self._check_driver_availability_for_ride(driver['id'])):
                    available_drivers.append(driver)
            
            if not available_drivers:
                print('[RIDE_HAILING] No available drivers with location sharing found')
                return
            
            # Create notification for available drivers
            pickup_address = ride_data.get('pickup_address', 'Unknown location')
            dropoff_address = ride_data.get('dropoff_address', 'Unknown destination')
            
            notification_data = {
                'title': 'New Ride Request! 🚗',
                'message': f'Ride from {pickup_address} to {dropoff_address}. Tap to accept!',
                'type': 'booking',
                'created_at': datetime.now().isoformat()
            }
            
            notification = supabase.table('notifications').insert(notification_data).execute()
            
            if notification.data:
                notification_id = notification.data[0]['id']
                recipients = []
                
                for driver in available_drivers:
                    try:
                        # Validate UUID format
                        import uuid
                        uuid.UUID(driver['id'])
                        recipients.append({
                            'notification_id': notification_id,
                            'user_id': driver['id'],
                            'role': 'driver',
                            'delivery_status': 'sent'
                        })
                    except ValueError:
                        print(f"[RIDE_HAILING] Skipping invalid driver ID: {driver['id']}")
                
                if recipients:
                    supabase.table('notification_recipients').insert(recipients).execute()
                    print(f"[RIDE_HAILING] Notified {len(recipients)} available drivers")
            
        except Exception as e:
            print(f"[RIDE_HAILING] Error notifying drivers: {e}")

    def _notify_passengers_driver_assigned(self, ride_data, driver_name):
        """Notify all passengers that a driver has been assigned"""
        try:
            passengers = ride_data.get('passengers', [])
            dropoff_address = ride_data.get('dropoff_address', 'your destination')
            
            notification_data = {
                'title': 'Driver Assigned! ✅',
                'message': f'{driver_name} will take you to {dropoff_address}. Get ready for your ride!',
                'type': 'ride_hailing',
                'created_at': datetime.now().isoformat()
            }
            
            notification = supabase.table('notifications').insert(notification_data).execute()
            
            if notification.data:
                notification_id = notification.data[0]['id']
                recipients = []
                
                for passenger in passengers:
                    customer_id = passenger.get('customer_id')
                    if customer_id:
                        try:
                            import uuid
                            uuid.UUID(customer_id)
                            recipients.append({
                                'notification_id': notification_id,
                                'user_id': customer_id,
                                'role': 'tourist',
                                'delivery_status': 'sent'
                            })
                        except ValueError:
                            print(f"[RIDE_HAILING] Skipping invalid customer ID: {customer_id}")
                
                if recipients:
                    supabase.table('notification_recipients').insert(recipients).execute()
                    print(f"[RIDE_HAILING] Notified {len(recipients)} passengers")
            
        except Exception as e:
            print(f"[RIDE_HAILING] Error notifying passengers: {e}")

    def _notify_driver_passenger_joined(self, ride_data, new_customer_id, passenger_count):
        """Notify driver that a new passenger joined the ride"""
        try:
            driver_id = ride_data.get('driver_id')
            if not driver_id:
                return
            
            current_passengers = ride_data.get('current_passenger_count', 0)
            max_capacity = ride_data.get('max_passenger_capacity', 4)
            dropoff_address = ride_data.get('dropoff_address', 'destination')
            
            notification_data = {
                'title': f'New Passenger Joined! 👥 ({current_passengers}/{max_capacity})',
                'message': f'{passenger_count} more passenger(s) joined your ride to {dropoff_address}. {"Ride is now full!" if current_passengers >= max_capacity else f"{max_capacity - current_passengers} spots remaining."}',
                'type': 'ride_hailing',
                'created_at': datetime.now().isoformat()
            }
            
            notification = supabase.table('notifications').insert(notification_data).execute()
            
            if notification.data:
                notification_id = notification.data[0]['id']
                supabase.table('notification_recipients').insert({
                    'notification_id': notification_id,
                    'user_id': driver_id,
                    'role': 'driver',
                    'delivery_status': 'sent'
                }).execute()
                print(f"[RIDE_HAILING] Notified driver of new passenger")
            
        except Exception as e:
            print(f"[RIDE_HAILING] Error notifying driver: {e}")
    
    def _enrich_rides_with_details(self, rides):
        """Enrich ride data with driver name and carriage details"""
        try:
            if not rides:
                return rides
            
            # Get unique driver IDs
            driver_ids = list(set([r.get('driver_id') for r in rides if r.get('driver_id')]))
            
            # Fetch driver details
            driver_map = {}
            if driver_ids:
                try:
                    drivers_resp = supabase.table('users').select('id, name, email').in_('id', driver_ids).execute()
                    if hasattr(drivers_resp, 'data') and drivers_resp.data:
                        driver_map = {d['id']: d for d in drivers_resp.data}
                except Exception as e:
                    print(f"[RIDE_HAILING] Error fetching driver details: {e}")
            
            # Fetch carriage assignments for drivers
            carriage_map = {}
            if driver_ids:
                try:
                    assignments_resp = supabase.table('tartanilla_carriages').select('assigned_driver_id, capacity').in_('assigned_driver_id', driver_ids).in_('status', ['driver_assigned', 'active']).execute()
                    if hasattr(assignments_resp, 'data') and assignments_resp.data:
                        for assignment in assignments_resp.data:
                            driver_id = assignment.get('assigned_driver_id')
                            if driver_id:
                                carriage_map[driver_id] = {
                                    'capacity': assignment.get('capacity', 4)
                                }
                except Exception as e:
                    print(f"[RIDE_HAILING] Error fetching carriage assignments: {e}")
            
            # Enrich rides
            enriched = []
            for ride in rides:
                enriched_ride = dict(ride)
                driver_id = ride.get('driver_id')
                
                if driver_id and driver_id in driver_map:
                    driver = driver_map[driver_id]
                    enriched_ride['driver_display_name'] = driver.get('name', driver.get('email', 'Driver'))
                    
                    # Add carriage info if available
                    if driver_id in carriage_map:
                        carriage = carriage_map[driver_id]
                        enriched_ride['carriage_capacity'] = carriage.get('capacity', 4)
                
                enriched.append(enriched_ride)
            
            return enriched
        except Exception as e:
            print(f"[RIDE_HAILING] Error enriching rides: {e}")
            return rides
    
    def _record_ride_hailing_earnings(self, ride_data, driver_id):
        """Record ride hailing earnings to earnings table - 100% to driver, 0% admin"""
        try:
            booking_id = ride_data.get('id')
            total_fare_raw = ride_data.get('total_fare', 0)
            
            print(f"[RIDE_HAILING_EARNINGS] 🔍 Starting earnings recording for ride {booking_id}")
            print(f"[RIDE_HAILING_EARNINGS] Raw total_fare value: {total_fare_raw} (type: {type(total_fare_raw)})")
            
            # Handle Decimal type from database
            if total_fare_raw is None:
                total_fare = 0.0
            else:
                total_fare = float(total_fare_raw)
            
            print(f"[RIDE_HAILING_EARNINGS] Converted total fare: ₱{total_fare}")
            
            if total_fare <= 0:
                print(f"[RIDE_HAILING_EARNINGS] ⚠️ Skipping - total_fare is {total_fare}")
                logger.warning(f"[RIDE_HAILING] Skipping earnings - total_fare is {total_fare}")
                return
            
            # Calculate split: 100% driver, 0% admin for ride hailing
            driver_earnings = total_fare
            admin_earnings = 0.0
            
            print(f"[RIDE_HAILING_EARNINGS] Split: Driver=₱{driver_earnings} (100%), Admin=₱{admin_earnings} (0%)")
            
            # Check duplicate
            check = supabase.table('earnings').select('id').eq('booking_id', booking_id).execute()
            if hasattr(check, 'data') and check.data:
                print(f"[RIDE_HAILING_EARNINGS] ⚠️ Earnings already exist for {booking_id}")
                logger.info(f"[RIDE_HAILING] Earnings already exist for {booking_id}")
                return
            
            # Get driver name
            driver_name = ride_data.get('driver_name', 'Unknown')
            if driver_name == 'Unknown':
                try:
                    u = supabase.table('users').select('name').eq('id', driver_id).single().execute()
                    if hasattr(u, 'data') and u.data:
                        driver_name = u.data.get('name', 'Unknown')
                except:
                    pass
            
            print(f"[RIDE_HAILING_EARNINGS] Driver: {driver_name} (ID: {driver_id})")
            
            earnings_payload = {
                'booking_id': booking_id,
                'driver_id': driver_id,
                'driver_name': driver_name,
                'amount': total_fare,
                'total_amount': total_fare,
                'driver_earnings': driver_earnings,
                'admin_earnings': 0,
                'package_name': f"Ride Hailing - {ride_data.get('pickup_address', 'Pickup')} to {ride_data.get('dropoff_address', 'Dropoff')}",
                'booking_type': 'ride_hailing',
                'earning_date': datetime.now().isoformat(),
                'status': 'finalized',
                'created_at': datetime.now().isoformat()
            }
            
            print(f"[RIDE_HAILING_EARNINGS] 📝 Inserting earnings payload:")
            print(f"  - booking_id: {booking_id}")
            print(f"  - driver_id: {driver_id}")
            print(f"  - amount: ₱{total_fare}")
            print(f"  - driver_earnings: ₱{driver_earnings}")
            print(f"  - admin_earnings: ₱{admin_earnings}")
            print(f"  - booking_type: ride_hailing")
            print(f"  - status: finalized")
            print(f"  - package_name: {earnings_payload['package_name']}")
            
            print(f"[RIDE_HAILING_EARNINGS] 🚀 Executing database insert...")
            result = supabase.table('earnings').insert(earnings_payload).execute()
            print(f"[RIDE_HAILING_EARNINGS] 📊 Insert result: {result}")
            if hasattr(result, 'data') and result.data:
                earnings_id = result.data[0].get('id')
                print(f"[RIDE_HAILING_EARNINGS] ✅ SUCCESS! Earnings recorded:")
                print(f"  - Earnings ID: {earnings_id}")
                print(f"  - Booking ID: {booking_id}")
                print(f"  - Amount: ₱{total_fare}")
                print(f"  - Driver gets: ₱{driver_earnings} (100%)")
                print(f"  - Admin gets: ₱{admin_earnings} (0%)")
                logger.info(f"[RIDE_HAILING] ✅ Earnings recorded: ID={earnings_id}, Amount=₱{total_fare}, Driver=₱{driver_earnings}")
            else:
                print(f"[RIDE_HAILING_EARNINGS] ❌ FAILED! No data returned from insert")
                print(f"  - Result: {result}")
                logger.error(f"[RIDE_HAILING] ❌ Failed to record earnings for ride {booking_id}")
        except Exception as e:
            print(f"[RIDE_HAILING_EARNINGS] ❌ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            logger.error(f"[RIDE_HAILING] Error recording earnings: {e}", exc_info=True)

    @action(detail=False, methods=['get'], url_path='test-route-data')
    def test_route_data(self, request):
        """Test endpoint to check route data integrity"""
        try:
            # Test route_summary table
            summaries = supabase.table('route_summary').select('*').limit(5).execute()
            summary_count = len(summaries.data) if hasattr(summaries, 'data') else 0
            
            # Test map_points table
            points = supabase.table('map_points').select('*').limit(5).execute()
            points_count = len(points.data) if hasattr(points, 'data') else 0
            
            # Test road_highlights table
            roads = supabase.table('road_highlights').select('*').limit(5).execute()
            roads_count = len(roads.data) if hasattr(roads, 'data') else 0
            
            return Response({
                'success': True,
                'data': {
                    'route_summaries': summary_count,
                    'map_points': points_count,
                    'road_highlights': roads_count,
                    'sample_summary': summaries.data[0] if summary_count > 0 else None,
                    'sample_point': points.data[0] if points_count > 0 else None,
                    'sample_road': roads.data[0] if roads_count > 0 else None
                },
                'message': f'Tables accessible: summaries({summary_count}), points({points_count}), roads({roads_count})'
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
                'message': 'Error testing route data'
            })
    
    @action(detail=False, methods=['post'], url_path='create-route')
    def create_route(self, request):
        """Create pickup, roads, dropoffs in bulk transaction"""
        try:
            data = request.data
            route_id = str(uuid.uuid4())
            
            # Create pickup point
            pickup_data = {
                'name': data['pickup_name'],
                'latitude': float(data['pickup_latitude']),
                'longitude': float(data['pickup_longitude']),
                'point_type': 'pickup',
                'icon_color': data['color'],
                'route_id': route_id
            }
            pickup_result = supabase.table('map_points').insert(pickup_data).execute()
            if not pickup_result.data:
                raise Exception("Failed to create pickup")
            pickup_id = pickup_result.data[0]['id']
            
            # Create dropoff points and roads, collect IDs
            road_ids = []
            dropoff_ids = []
            
            for i, dropoff in enumerate(data['dropoff_points']):
                dropoff_data = {
                    'name': dropoff['name'],
                    'latitude': float(dropoff['latitude']),
                    'longitude': float(dropoff['longitude']),
                    'point_type': 'dropoff',
                    'icon_color': data['color'],
                    'route_id': route_id,
                    'pickup_id': pickup_id
                }
                dropoff_result = supabase.table('map_points').insert(dropoff_data).execute()
                if not dropoff_result.data:
                    raise Exception("Failed to create dropoff")
                dropoff_id = dropoff_result.data[0]['id']
                dropoff_ids.append(dropoff_id)
                
                # Create road highlights for this specific dropoff
                if i < len(data['road_highlights']):
                    road = data['road_highlights'][i]
                    road_data = {
                        'name': road['name'],
                        'coordinates': road['coordinates'],
                        'color': data['color'],
                        'route_id': route_id,
                        'pickup_id': pickup_id,
                        'dropoff_id': dropoff_id
                    }
                    road_result = supabase.table('road_highlights').insert(road_data).execute()
                    if not road_result.data:
                        raise Exception("Failed to create road")
                    road_ids.append(road_result.data[0]['id'])
            
            # Store route summary
            summary_data = {
                'route_id': route_id,
                'color': data['color'],
                'pickup_point_id': pickup_id,
                'road_highlight_ids': road_ids,
                'dropoff_point_ids': dropoff_ids
            }
            supabase.table('route_summary').insert(summary_data).execute()
            
            return Response({
                'success': True, 
                'route_id': route_id,
                'pickup_id': pickup_id,
                'road_ids': road_ids,
                'dropoff_ids': dropoff_ids,
                'color': data['color'],
                'message': 'Route created'
            })
            
        except Exception as e:
            # Rollback
            try:
                supabase.table('map_points').delete().eq('route_id', route_id).execute()
                supabase.table('road_highlights').delete().eq('route_id', route_id).execute()
                supabase.table('route_summary').delete().eq('route_id', route_id).execute()
            except:
                pass
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['delete'], url_path='delete-pickup/(?P<pickup_id>[^/.]+)')
    def delete_pickup(self, request, pickup_id=None):
        """Delete pickup and ALL connected roads/dropoffs"""
        try:
            pickup = supabase.table('map_points').select('route_id').eq('id', pickup_id).single().execute()
            if not pickup.data:
                return Response({'success': False, 'error': 'Pickup not found'}, status=status.HTTP_404_NOT_FOUND)
            
            route_id = pickup.data['route_id']
            supabase.table('road_highlights').delete().eq('route_id', route_id).execute()
            supabase.table('map_points').delete().eq('route_id', route_id).execute()
            supabase.table('route_summary').delete().eq('route_id', route_id).execute()
            
            return Response({'success': True, 'message': 'Entire route deleted'})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['delete'], url_path='delete-dropoff/(?P<dropoff_id>[^/.]+)')
    def delete_dropoff(self, request, dropoff_id=None):
        """Delete dropoff and ONLY its specific road highlights"""
        try:
            # Delete only roads linked to this specific dropoff
            supabase.table('road_highlights').delete().eq('dropoff_id', dropoff_id).execute()
            # Delete the dropoff point
            supabase.table('map_points').delete().eq('id', dropoff_id).execute()
            
            return Response({'success': True, 'message': 'Dropoff and its specific roads deleted'})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='route-info/(?P<route_id>[^/.]+)')
    def route_info(self, request, route_id=None):
        """Get complete route information by route_id"""
        try:
            summary = supabase.table('route_summary').select('*').eq('route_id', route_id).single().execute()
            if not summary.data:
                return Response({'success': False, 'error': 'Route not found'}, status=status.HTTP_404_NOT_FOUND)
            
            return Response({'success': True, 'data': summary.data})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='routes-by-pickup/(?P<pickup_id>[^/.]+)')
    def routes_by_pickup(self, request, pickup_id=None):
        """Get all routes and destinations for a specific pickup point"""
        try:
            # Get route summary for this pickup
            summary = supabase.table('route_summary').select('*').eq('pickup_point_id', pickup_id).execute()
            if not summary.data:
                return Response({'success': True, 'data': [], 'message': 'No routes found for this pickup'})
            
            route_data = summary.data[0]
            
            # Get pickup point name
            pickup = supabase.table('map_points').select('name').eq('id', pickup_id).single().execute()
            pickup_name = pickup.data['name'] if pickup.data else 'Unknown'
            
            # Get dropoff points names
            dropoff_ids = route_data['dropoff_point_ids']
            print(f"Raw dropoff_ids: {dropoff_ids}, type: {type(dropoff_ids)}")
            
            # Handle different array formats
            if isinstance(dropoff_ids, list):
                # Already a list
                dropoff_ids = [int(id) for id in dropoff_ids]
            elif isinstance(dropoff_ids, str):
                # Handle PostgreSQL array string format
                dropoff_ids = dropoff_ids.strip('{}').replace('"', '').split(',')
                dropoff_ids = [int(id.strip()) for id in dropoff_ids if id.strip()]
            
            print(f"Parsed dropoff_ids: {dropoff_ids}")
            dropoffs = supabase.table('map_points').select('id, name, latitude, longitude').in_('id', dropoff_ids).execute()
            print(f"Dropoffs query result: {dropoffs.data}")
            
            # Get road highlights
            road_ids = route_data['road_highlight_ids']
            print(f"Raw road_ids: {road_ids}, type: {type(road_ids)}")
            
            if isinstance(road_ids, list):
                # Already a list
                road_ids = [int(id) for id in road_ids]
            elif isinstance(road_ids, str):
                # Handle PostgreSQL array string format
                road_ids = road_ids.strip('{}').replace('"', '').split(',')
                road_ids = [int(id.strip()) for id in road_ids if id.strip()]
            
            print(f"Parsed road_ids: {road_ids}")
            roads = supabase.table('road_highlights').select('*').in_('id', road_ids).execute()
            print(f"Roads query result: {roads.data}")
            
            result_data = {
                'pickup_name': pickup_name,
                'pickup_id': pickup_id,
                'color': route_data['color'],
                'available_destinations': dropoffs.data or [],
                'road_highlights': roads.data or [],
                'route_id': route_data['route_id']
            }
            print(f"Final result: {result_data}")
            
            return Response({
                'success': True, 
                'data': result_data,
                'message': f'{pickup_name} has {len(dropoffs.data or [])} destinations'
            })
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='ride-wait-time/(?P<booking_id>[^/.]+)')
    def ride_wait_time(self, request, booking_id=None):
        """Get ride wait time and suggest cancellation if over 5 minutes"""
        try:
            resp = supabase.table(self.TABLE).select('*').eq('id', booking_id).single().execute()
            ride = getattr(resp, 'data', None)
            if not ride:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            
            if ride.get('status') != 'waiting_for_driver':
                return Response({
                    'success': True,
                    'waiting': False,
                    'suggest_cancel': False,
                    'status': ride.get('status')
                })
            
            # Calculate wait time
            created_at = datetime.fromisoformat(ride['created_at'].replace('Z', '+00:00'))
            time_elapsed = datetime.now(created_at.tzinfo) - created_at
            wait_minutes = time_elapsed.total_seconds() / 60
            
            suggest_cancel = wait_minutes > 5
            
            return Response({
                'success': True,
                'waiting': True,
                'wait_minutes': round(wait_minutes, 1),
                'suggest_cancel': suggest_cancel,
                'status': ride.get('status'),
                'message': f'Waiting for {wait_minutes:.1f} minutes' + (' - Consider cancelling' if suggest_cancel else '')
            })
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='route-summaries')
    def route_summaries(self, request):
        """Get all route summaries for color mapping"""
        try:
            # Add timeout and limit to prevent connection exhaustion
            summaries = supabase.table('route_summary').select('*').limit(100).execute()
            
            # Ensure we have data
            data = summaries.data if hasattr(summaries, 'data') else []
            
            return Response({
                'success': True,
                'data': data,
                'message': f'Retrieved {len(data)} route summaries'
            })
        except Exception as e:
            print(f'Route summaries error: {str(e)}')
            # Check if it's a table not found error
            if 'does not exist' in str(e).lower() or 'relation' in str(e).lower():
                print('Route summary table does not exist, returning empty data')
            # Return empty data instead of error to prevent UI crashes
            return Response({
                'success': True,
                'data': [],
                'message': 'Route summaries not available'
            })
    
    @action(detail=False, methods=['get'], url_path='driver-history')
    def driver_history(self, request):
        """Get driver's ride hailing history"""
        try:
            driver_id = request.query_params.get('driver_id') if hasattr(request, 'query_params') else request.GET.get('driver_id')
            if not driver_id:
                return Response({'success': False, 'error': 'driver_id required'}, status=status.HTTP_400_BAD_REQUEST)
            
            resp = supabase.table(self.TABLE).select('*').eq('driver_id', driver_id).in_('status', ['completed', 'cancelled']).order('completed_at', desc=True).limit(50).execute()
            rides = getattr(resp, 'data', [])
            enriched = self._enrich_rides_with_details(rides)
            
            return Response({'success': True, 'data': enriched, 'count': len(enriched)})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='customer-history')
    def customer_history(self, request):
        """Get customer's ride hailing history"""
        try:
            customer_id = request.query_params.get('customer_id') if hasattr(request, 'query_params') else request.GET.get('customer_id')
            if not customer_id:
                return Response({'success': False, 'error': 'customer_id required'}, status=status.HTTP_400_BAD_REQUEST)
            
            resp = supabase.table(self.TABLE).select('*').eq('customer_id', customer_id).in_('status', ['completed', 'cancelled']).order('completed_at', desc=True).limit(50).execute()
            rides = getattr(resp, 'data', [])
            enriched = self._enrich_rides_with_details(rides)
            
            return Response({'success': True, 'data': enriched, 'count': len(enriched)})
        except Exception as e:
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='ridehailing-routes')
    def ridehailing_routes(self, request):
        """Get all ridehailing routes with full details"""
        try:
            # Get route summaries
            summaries = supabase.table('route_summary').select('*').execute()
            routes_data = summaries.data if hasattr(summaries, 'data') else []
            
            # Get detailed information for each route
            detailed_routes = []
            for route in routes_data:
                try:
                    # Get pickup point details
                    pickup_response = supabase.table('map_points').select('*').eq('id', route['pickup_point_id']).single().execute()
                    pickup_data = pickup_response.data if hasattr(pickup_response, 'data') else None
                    
                    # Get dropoff points details
                    dropoff_ids = route.get('dropoff_point_ids', [])
                    dropoffs_data = []
                    if dropoff_ids:
                        dropoffs_response = supabase.table('map_points').select('*').in_('id', dropoff_ids).execute()
                        dropoffs_data = dropoffs_response.data if hasattr(dropoffs_response, 'data') else []
                    
                    # Get road highlights details
                    road_ids = route.get('road_highlight_ids', [])
                    roads_data = []
                    if road_ids:
                        roads_response = supabase.table('road_highlights').select('*').in_('id', road_ids).execute()
                        roads_data = roads_response.data if hasattr(roads_response, 'data') else []
                    
                    detailed_route = {
                        'route_id': route['route_id'],
                        'color': route['color'],
                        'pickup_point': pickup_data,
                        'dropoff_points': dropoffs_data,
                        'road_highlights': roads_data,
                        'summary': route
                    }
                    detailed_routes.append(detailed_route)
                    
                except Exception as detail_error:
                    print(f"Error getting details for route {route.get('route_id')}: {detail_error}")
                    # Include route even if details fail
                    detailed_routes.append({
                        'route_id': route.get('route_id', 'unknown'),
                        'color': route.get('color', '#007bff'),
                        'pickup_point': None,
                        'dropoff_points': [],
                        'road_highlights': [],
                        'summary': route,
                        'error': str(detail_error)
                    })
            
            return Response({
                'success': True,
                'data': detailed_routes,
                'message': f'Retrieved {len(detailed_routes)} ridehailing routes'
            })
            
        except Exception as e:
            print(f'Ridehailing routes error: {str(e)}')
            return Response({
                'success': True,
                'data': [],
                'message': f'Ridehailing routes not available: {str(e)}'
            })
