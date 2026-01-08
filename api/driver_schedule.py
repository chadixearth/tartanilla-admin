from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from tartanilla_admin.supabase import supabase
from datetime import datetime, date, time
import json
import logging

# Prefer the admin client (bypasses RLS for audit_logs) if available
try:
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# JWT helpers if available
try:
    from core.jwt_auth import verify_token, get_token_from_request
except Exception:
    verify_token = None
    get_token_from_request = None

logger = logging.getLogger(__name__)


class DriverScheduleViewSet(viewsets.ViewSet):
    """ViewSet for managing driver schedules and calendar"""
    permission_classes = [AllowAny]

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
            if get_token_from_request and verify_token:
                token = get_token_from_request(request)
                if token:
                    claims = verify_token(token) or {}
                    if isinstance(claims, dict):
                        actor['user_id'] = claims.get('sub') or claims.get('user_id') or claims.get('id')
                        actor['username'] = claims.get('username') or claims.get('email')
                        actor['role'] = claims.get('role') or claims.get('user_role')

            if not actor['user_id']:
                u = getattr(request, 'user', None)
                if getattr(u, 'is_authenticated', False):
                    actor['user_id'] = getattr(u, 'id', None)
                    actor['username'] = getattr(u, 'username', None) or getattr(u, 'email', None)
                    try:
                        actor['role'] = getattr(u, 'role', None) or getattr(getattr(u, 'role', None), 'name', None)
                    except Exception:
                        pass

            if not actor['user_id'] and fallback_user_id:
                actor['user_id'] = fallback_user_id
                try:
                    uresp = supabase.table('users').select('name, email, role').eq('id', fallback_user_id).single().execute()
                    if hasattr(uresp, 'data') and uresp.data:
                        actor['username'] = uresp.data.get('name') or uresp.data.get('email')
                        actor['role'] = uresp.data.get('role')
                except Exception as e:
                    logger.warning(f"Failed to fetch user data for fallback_user_id {fallback_user_id}: {e}")
                    pass
        except Exception:
            pass
        return actor

    def _audit(self, request, *, action, entity_name, entity_id=None, new_data=None, old_data=None, actor=None):
        """
        Inserts a row into audit_logs. Never blocks the main flow.
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
    # Core logic
    # ─────────────────────────────────────────────
    def _check_schedule_conflict(self, driver_id, booking_date, booking_time):
        """Check if driver has schedule conflict for given date and time"""
        try:
            # Normalize booking_time to handle different formats
            if isinstance(booking_time, str):
                # Handle both HH:MM and HH:MM:SS formats
                if len(booking_time.split(':')) == 2:
                    booking_time = f"{booking_time}:00"
            
            # Check driver calendar for existing bookings (only confirmed ones)
            calendar_response = supabase.table('driver_calendar').select('*').eq('driver_id', driver_id).eq('booking_date', booking_date).neq('status', 'cancelled').execute()
            
            calendar_bookings = calendar_response.data if hasattr(calendar_response, 'data') and calendar_response.data else []
            
            if calendar_bookings:
                for existing_booking in calendar_bookings:
                    existing_time = str(existing_booking.get('booking_time', ''))
                    # Normalize existing time format
                    if len(existing_time.split(':')) == 2:
                        existing_time = f"{existing_time}:00"
                    
                    if existing_time == booking_time:
                        return True, f"Driver already has a booking at {booking_time} on {booking_date}"
            
            # Check driver schedule for availability
            schedule_response = supabase.table('driver_schedule').select('*').eq('driver_id', driver_id).eq('date', booking_date).execute()
            
            schedule_entries = schedule_response.data if hasattr(schedule_response, 'data') and schedule_response.data else []
            
            if schedule_entries:
                schedule = schedule_entries[0]
                is_available = schedule.get('is_available')
                unavailable_times = schedule.get('unavailable_times', [])
                
                # If driver explicitly set as unavailable for the entire day
                if is_available is False:
                    return True, f"Driver is not available on {booking_date}"
                
                # CRITICAL FIX: Only check unavailable_times if driver is setting specific unavailable slots
                # If driver sets is_available=True, they are available UNLESS specific times are marked unavailable
                if is_available is True and unavailable_times and len(unavailable_times) > 0:
                    # Normalize booking time for comparison
                    booking_time_normalized = booking_time[:5] if len(booking_time) > 5 else booking_time
                    
                    for unavailable_time in unavailable_times:
                        if unavailable_time:  # Skip empty/null entries
                            unavailable_normalized = str(unavailable_time)[:5] if len(str(unavailable_time)) > 5 else str(unavailable_time)
                            if booking_time_normalized == unavailable_normalized:
                                return True, f"Driver is not available at {booking_time} on {booking_date}"
                
                # If driver set is_available=True and time is not in unavailable_times, they are available
                # If is_available is None/null, assume available (permissive approach)
                return False, None
            
            # If no schedule entry exists, driver is available by default
            # This is the most permissive approach - drivers are available unless they explicitly say otherwise
            return False, None
            
        except Exception as e:
            print(f"Error checking schedule conflict for driver {driver_id}: {e}")
            # On error, allow booking to proceed rather than blocking it
            # This ensures the system doesn't block bookings due to technical issues
            return False, "Schedule check failed but allowing booking"

    @action(detail=False, methods=['post'], url_path='check-availability')
    def check_availability(self, request):
        """Check if driver is available for specific date and time"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            driver_id = data.get('driver_id')
            booking_date = data.get('booking_date')
            booking_time = data.get('booking_time')
            
            if not all([driver_id, booking_date, booking_time]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: driver_id, booking_date, booking_time'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            has_conflict, conflict_reason = self._check_schedule_conflict(driver_id, booking_date, booking_time)
            
            return Response({
                'success': True,
                'available': not has_conflict,
                'conflict_reason': conflict_reason,
                'driver_id': driver_id,
                'booking_date': booking_date,
                'booking_time': booking_time
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='accept-booking')
    def accept_booking(self, request):
        """Driver accepts a booking - adds to calendar if no conflict"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            driver_id = data.get('driver_id')
            booking_id = data.get('booking_id')
            booking_date = data.get('booking_date')
            booking_time = data.get('booking_time')
            package_name = data.get('package_name', 'Tour Package')
            customer_name = data.get('customer_name', 'Customer')
            
            if not all([driver_id, booking_id, booking_date, booking_time]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check for conflicts
            has_conflict, conflict_reason = self._check_schedule_conflict(driver_id, booking_date, booking_time)
            
            if has_conflict:
                return Response({
                    'success': False,
                    'error': conflict_reason,
                    'can_accept': False
                }, status=status.HTTP_409_CONFLICT)
            
            # Add to driver calendar
            calendar_data = {
                'driver_id': driver_id,
                'booking_id': booking_id,
                'booking_date': booking_date,
                'booking_time': booking_time,
                'package_name': package_name,
                'customer_name': customer_name,
                'status': 'confirmed',
                'created_at': datetime.now().isoformat()
            }
            
            calendar_response = supabase.table('driver_calendar').insert(calendar_data).execute()
            
            if hasattr(calendar_response, 'data') and calendar_response.data:
                inserted = calendar_response.data[0]
                # AUDIT
                actor = self._get_actor(request, fallback_user_id=driver_id)
                self._audit(
                    request,
                    action='DRIVER_CALENDAR_ACCEPT_BOOKING',
                    entity_name='driver_calendar',
                    entity_id=inserted.get('id') or f"{driver_id}:{booking_id}",
                    new_data=inserted,
                    old_data=None,
                    actor=actor
                )
                return Response({
                    'success': True,
                    'message': 'Booking accepted and added to calendar',
                    'calendar_entry': inserted,
                    'can_accept': True
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to add booking to calendar'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='calendar/(?P<driver_id>[^/.]+)')
    def get_driver_calendar(self, request, driver_id=None):
        """Get driver's calendar for a specific date range"""
        try:
            date_from = request.query_params.get('date_from', date.today().isoformat())
            date_to = request.query_params.get('date_to')
            
            query = supabase.table('driver_calendar').select('*').eq('driver_id', driver_id).order('booking_date', desc=False)
            
            if date_from:
                query = query.gte('booking_date', date_from)
            if date_to:
                query = query.lte('booking_date', date_to)
            
            response = query.execute()
            calendar_entries = response.data if hasattr(response, 'data') else []
            
            return Response({
                'success': True,
                'data': calendar_entries,
                'driver_id': driver_id,
                'count': len(calendar_entries)
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='set-availability')
    def set_availability(self, request):
        """Set driver availability for specific dates"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            driver_id = data.get('driver_id')
            date_str = data.get('date')
            is_available = data.get('is_available', True)
            unavailable_times = data.get('unavailable_times', [])
            notes = data.get('notes', '')
            
            if not all([driver_id, date_str]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: driver_id, date'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate date format and allow current day
            try:
                schedule_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                today = date.today()
                
                # Allow today and future dates only
                if schedule_date < today:
                    return Response({
                        'success': False,
                        'error': 'Cannot set availability for past dates'
                    }, status=status.HTTP_400_BAD_REQUEST)
            except ValueError:
                return Response({
                    'success': False,
                    'error': 'Invalid date format. Use YYYY-MM-DD'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if schedule exists for this date
            existing_response = supabase.table('driver_schedule').select('*').eq('driver_id', driver_id).eq('date', date_str).execute()
            existing = existing_response.data if hasattr(existing_response, 'data') else []

            old_row = existing[0] if existing else None
            
            schedule_data = {
                'driver_id': driver_id,
                'date': date_str,
                'is_available': is_available,
                'unavailable_times': unavailable_times,
                'notes': notes,
                'updated_at': datetime.now().isoformat()
            }
            
            if existing:
                # Update existing schedule
                response = supabase.table('driver_schedule').update(schedule_data).eq('driver_id', driver_id).eq('date', date_str).execute()
                action_name = 'DRIVER_SCHEDULE_UPDATE'
            else:
                # Create new schedule
                schedule_data['created_at'] = datetime.now().isoformat()
                response = supabase.table('driver_schedule').insert(schedule_data).execute()
                action_name = 'DRIVER_SCHEDULE_CREATE'
            
            if hasattr(response, 'data') and response.data:
                row = response.data[0]
                # AUDIT
                actor = self._get_actor(request, fallback_user_id=driver_id)
                self._audit(
                    request,
                    action=action_name,
                    entity_name='driver_schedule',
                    entity_id=row.get('id') or f"{driver_id}:{date_str}",
                    new_data=row,
                    old_data=old_row,
                    actor=actor
                )
                return Response({
                    'success': True,
                    'message': 'Schedule updated successfully' if existing else 'Schedule created successfully',
                    'data': row
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to update schedule'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='schedule/(?P<driver_id>[^/.]+)')
    def get_driver_schedule(self, request, driver_id=None):
        """Get driver's schedule for a specific date range"""
        try:
            date_from = request.query_params.get('date_from', date.today().isoformat())
            date_to = request.query_params.get('date_to')
            
            query = supabase.table('driver_schedule').select('*').eq('driver_id', driver_id).order('date', desc=False)
            
            if date_from:
                query = query.gte('date', date_from)
            if date_to:
                query = query.lte('date', date_to)
            
            response = query.execute()
            schedule_entries = response.data if hasattr(response, 'data') else []
            
            return Response({
                'success': True,
                'data': schedule_entries,
                'driver_id': driver_id,
                'count': len(schedule_entries)
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='calendar/cancel-booking')
    def cancel_calendar_booking(self, request):
        """Cancel a booking from driver's calendar"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            driver_id = data.get('driver_id')
            booking_id = data.get('booking_id')
            reason = data.get('reason', 'Driver cancelled')
            
            if not all([driver_id, booking_id]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: driver_id, booking_id'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Fetch old row for audit
            old_resp = supabase.table('driver_calendar').select('*').eq('driver_id', driver_id).eq('booking_id', booking_id).single().execute()
            old_row = old_resp.data if hasattr(old_resp, 'data') else None
            
            # Update calendar entry status
            response = supabase.table('driver_calendar').update({
                'status': 'cancelled',
                'cancel_reason': reason,
                'cancelled_at': datetime.now().isoformat()
            }).eq('driver_id', driver_id).eq('booking_id', booking_id).execute()
            
            if hasattr(response, 'data') and response.data:
                row = response.data[0]
                # AUDIT
                actor = self._get_actor(request, fallback_user_id=driver_id)
                self._audit(
                    request,
                    action='DRIVER_CALENDAR_CANCEL_BOOKING',
                    entity_name='driver_calendar',
                    entity_id=row.get('id') or f"{driver_id}:{booking_id}",
                    new_data=row,
                    old_data=old_row,
                    actor=actor
                )
                return Response({
                    'success': True,
                    'message': 'Booking cancelled from calendar',
                    'data': row
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to cancel booking or booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='debug-schedule')
    def debug_schedule_check(self, request):
        """Debug endpoint to test schedule conflicts"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            
            driver_id = data.get('driver_id')
            booking_date = data.get('booking_date')
            booking_time = data.get('booking_time')
            
            if not all([driver_id, booking_date, booking_time]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: driver_id, booking_date, booking_time'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get driver info
            driver_response = supabase.table('users').select('name, role, status').eq('id', driver_id).single().execute()
            driver_info = driver_response.data if hasattr(driver_response, 'data') and driver_response.data else {}
            
            # Check carriage assignment
            carriage_response = supabase.table('tartanilla_carriages').select('id, eligibility, status').eq('assigned_driver_id', driver_id).execute()
            carriages = carriage_response.data if hasattr(carriage_response, 'data') and carriage_response.data else []
            
            # Check schedule
            schedule_response = supabase.table('driver_schedule').select('*').eq('driver_id', driver_id).eq('date', booking_date).execute()
            schedule = schedule_response.data[0] if hasattr(schedule_response, 'data') and schedule_response.data else None
            
            # Check calendar
            calendar_response = supabase.table('driver_calendar').select('*').eq('driver_id', driver_id).eq('booking_date', booking_date).execute()
            calendar_entries = calendar_response.data if hasattr(calendar_response, 'data') and calendar_response.data else []
            
            # Run conflict check
            has_conflict, conflict_reason = self._check_schedule_conflict(driver_id, booking_date, booking_time)
            
            return Response({
                'success': True,
                'debug_info': {
                    'driver_info': driver_info,
                    'carriages': carriages,
                    'eligible_carriages': [c for c in carriages if c.get('eligibility') == 'eligible'],
                    'schedule_entry': schedule,
                    'calendar_entries': calendar_entries,
                    'has_conflict': has_conflict,
                    'conflict_reason': conflict_reason,
                    'booking_date': booking_date,
                    'booking_time': booking_time
                }
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='available-drivers')
    def get_available_drivers(self, request):
        """Get list of available drivers for specific date and time"""
        try:
            booking_date = request.query_params.get('booking_date')
            booking_time = request.query_params.get('booking_time')
            
            if not all([booking_date, booking_time]):
                return Response({
                    'success': False,
                    'error': 'Missing required parameters: booking_date, booking_time'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get all active drivers with assigned carriages
            drivers_response = supabase.table('users').select('id, name, email').in_('role', ['driver', 'driver-owner']).eq('status', 'active').execute()
            
            if not (hasattr(drivers_response, 'data') and drivers_response.data):
                return Response({
                    'success': True,
                    'data': [],
                    'message': 'No drivers found',
                    'booking_date': booking_date,
                    'booking_time': booking_time,
                    'count': 0
                })
            
            available_drivers = []
            total_drivers = len(drivers_response.data)
            drivers_with_carriages = 0
            
            for driver in drivers_response.data:
                driver_id = driver['id']
                
                # Check if driver has assigned carriage
                try:
                    carriage_response = supabase.table('tartanilla_carriages').select('id, eligibility').eq('assigned_driver_id', driver_id).eq('eligibility', 'eligible').execute()
                    
                    if not (hasattr(carriage_response, 'data') and carriage_response.data):
                        continue  # Skip drivers without eligible carriages
                    
                    drivers_with_carriages += 1
                    
                    # Check schedule availability
                    has_conflict, conflict_reason = self._check_schedule_conflict(driver_id, booking_date, booking_time)
                    
                    if not has_conflict:
                        available_drivers.append({
                            'driver_id': driver_id,
                            'driver_name': driver['name'],
                            'driver_email': driver['email'],
                            'available': True,
                            'carriage_count': len(carriage_response.data)
                        })
                    else:
                        # Include unavailable drivers with reason for debugging
                        available_drivers.append({
                            'driver_id': driver_id,
                            'driver_name': driver['name'],
                            'driver_email': driver['email'],
                            'available': False,
                            'unavailable_reason': conflict_reason,
                            'carriage_count': len(carriage_response.data)
                        })
                        
                except Exception as carriage_error:
                    print(f"Error checking carriage for driver {driver_id}: {carriage_error}")
                    continue
            
            return Response({
                'success': True,
                'data': available_drivers,
                'booking_date': booking_date,
                'booking_time': booking_time,
                'count': len([d for d in available_drivers if d['available']]),
                'total_drivers': total_drivers,
                'drivers_with_carriages': drivers_with_carriages,
                'debug_info': {
                    'all_drivers_count': total_drivers,
                    'drivers_with_carriages': drivers_with_carriages,
                    'available_count': len([d for d in available_drivers if d['available']]),
                    'unavailable_count': len([d for d in available_drivers if not d['available']])
                }
            })
            
        except Exception as e:
            print(f"Error in get_available_drivers: {e}")
            return Response({
                'success': False,
                'error': str(e),
                'booking_date': booking_date,
                'booking_time': booking_time
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
