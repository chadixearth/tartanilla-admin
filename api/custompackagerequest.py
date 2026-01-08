# custompackagerequest.py
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase, execute_with_retry, safe_query
from core.error_handlers import handle_api_errors, safe_supabase_operation, APIErrorHandler
from datetime import datetime
import traceback
import uuid
import logging
from uuid import UUID as _UUID

# Prefer admin client for audit logs (bypasses RLS if available)
try:
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# Try to parse JWT if present for actor extraction
try:
    from core.jwt_auth import verify_token, get_token_from_request
except Exception:
    verify_token = None
    get_token_from_request = None

from .serializers import (
    CustomTourRequestSerializer,
    SpecialEventRequestSerializer,
    CustomTourRequestViewSerializer,
    SpecialEventRequestViewSerializer,
    ResponseSerializer
)
from .data import get_owners, get_drivers

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Audit helpers
# ────────────────────────────────────────────────────────────

def _get_audit_client():
    return supabase_admin or supabase

def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")

def _as_uuid_or_none(v):
    if not v:
        return None
    try:
        return str(_UUID(str(v)))
    except Exception:
        return None

def _clean_nullable(actor):
    # Coerce blanks → None and validate UUID
    actor["user_id"]  = _as_uuid_or_none(actor.get("user_id"))
    actor["username"] = (actor.get("username").strip() or None) if isinstance(actor.get("username"), str) else actor.get("username")
    actor["role"]     = (actor.get("role").strip() or None) if isinstance(actor.get("role"), str) else actor.get("role")
    return actor

def _extract_actor(request, overrides=None):
    """
    Best-effort actor extraction. If no actor is available, returns None values
    (no 'anonymous' fallback).
    Sources used in order:
      1) JWT in Authorization header
      2) request.session['auth']
      3) Cookies: admin_id/admin_email/admin_role
      4) Proxy headers: X-Actor-Id / X-Actor-Username (or X-Actor-Email) / X-Actor-Role
      5) request.user (Django auth)
      6) overrides (final)
    """
    actor = {"user_id": None, "username": None, "role": None}

    # 1) JWT
    if get_token_from_request and verify_token:
        try:
            token = get_token_from_request(request)
            if token:
                decoded = verify_token(token)
                actor["user_id"] = decoded.get("user_id") or decoded.get("sub") or decoded.get("id")
                actor["username"] = decoded.get("username") or decoded.get("email") or decoded.get("name")
                actor["role"] = (
                    decoded.get("role")
                    or (decoded.get("app_metadata") or {}).get("role")
                    or (decoded.get("user_metadata") or {}).get("role")
                )
        except Exception:
            logger.debug("JWT actor extraction failed", exc_info=True)

    # 2) Session
    try:
        auth = request.session.get("auth") or {}
        actor["user_id"]  = actor["user_id"]  or auth.get("id") or auth.get("user_id")
        actor["username"] = actor["username"] or auth.get("username") or auth.get("email")
        actor["role"]     = actor["role"]     or auth.get("role")
    except Exception:
        pass

    # 3) Cookies (dashboard-style)
    actor["user_id"]  = actor["user_id"]  or request.COOKIES.get("admin_id")
    actor["username"] = actor["username"] or request.COOKIES.get("admin_email")
    actor["role"]     = actor["role"]     or request.COOKIES.get("admin_role")

    # 4) Proxy headers (great for Postman / API gateway)
    actor["user_id"]  = actor["user_id"]  or request.META.get("HTTP_X_ACTOR_ID")
    actor["username"] = actor["username"] or request.META.get("HTTP_X_ACTOR_USERNAME") or request.META.get("HTTP_X_ACTOR_EMAIL")
    actor["role"]     = actor["role"]     or request.META.get("HTTP_X_ACTOR_ROLE")

    # 5) Django auth user (if using DRF’s SessionAuthentication)
    try:
        if getattr(request, "user", None) and getattr(request.user, "is_authenticated", False):
            actor["user_id"]  = actor["user_id"]  or getattr(request.user, "id", None)
            actor["username"] = actor["username"] or getattr(request.user, "get_username", lambda: None)()
            actor["role"]     = actor["role"]     or getattr(request.user, "role", None)
    except Exception:
        pass

    # 6) Overrides win
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                actor[k] = v

    return _clean_nullable(actor)

def _insert_audit_log(request, *, action, entity_name, entity_id=None, old_data=None, new_data=None, overrides=None):
    try:
        actor = _extract_actor(request, overrides=overrides)
        log_row = {
            "user_id": actor.get("user_id") or None,
            "username": actor.get("username") or None,
            "role": actor.get("role") or None,
            "action": action,
            "entity_name": entity_name,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "old_data": old_data if old_data is not None else None,
            "new_data": new_data if new_data is not None else None,
            "ip_address": (_client_ip(request) or None),
            "device_info": (request.META.get("HTTP_USER_AGENT", "") or None),
            # created_at defaults in DB
        }
        client = _get_audit_client()
        def _q():
            return client.table("audit_logs").insert(log_row).execute()
        execute_with_retry(_q)
    except Exception:
        # Never break main flow because of audit logging
        logger.warning("Failed to insert audit log", exc_info=True)

# ────────────────────────────────────────────────────────────
# ViewSets
# ────────────────────────────────────────────────────────────

class CustomTourRequestViewSet(viewsets.ViewSet):
    """ViewSet for custom tour requests"""
    permission_classes = [AllowAny]
    
    def create(self, request):
        """Create a new custom tour request"""
        try:
            serializer = CustomTourRequestSerializer(data=request.data)
            
            if not serializer.is_valid():
                return Response({
                    'success': False,
                    'error': 'Validation failed',
                    'details': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
            
            tour_data = serializer.validated_data
            request_id = str(uuid.uuid4())
            
            hours = tour_data.get('preferred_duration_hours') or 0
            minutes = tour_data.get('preferred_duration_minutes') or 0
            
            request_data = {
                'id': request_id,
                'customer_id': str(tour_data['customer_id']),
                'destination': tour_data['destination'],
                'pickup_location': tour_data.get('pickup_location', ''),
                'preferred_duration_hours': hours,
                'preferred_duration_minutes': minutes,
                'number_of_pax': tour_data['number_of_pax'],
                'preferred_date': tour_data.get('preferred_date').isoformat() if tour_data.get('preferred_date') else None,
                'special_requests': tour_data.get('special_requests', ''),
                'contact_number': tour_data['contact_number'],
                'contact_email': tour_data.get('contact_email', ''),
                'status': 'waiting_for_driver',
                'available_for_drivers': True,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            # Remove None values
            request_data = {k: v for k, v in request_data.items() if v is not None}
            
            # Insert into database
            response = supabase.table('custom_tour_requests').insert(request_data).execute()
            
            if hasattr(response, 'data') and response.data:
                # AUDIT: CREATE (actor: the customer creating the request if known)
                _insert_audit_log(
                    request,
                    action="CREATE",
                    entity_name="custom_tour_requests",
                    entity_id=request_id,
                    old_data=None,
                    new_data=response.data[0],
                    overrides={
                        "user_id": request_data.get("customer_id"),
                        "username": request_data.get("contact_email"),
                        "role": "customer",
                    }
                )
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': 'Custom tour request created and sent to all drivers for acceptance'
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to create custom tour request'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error("Error creating custom tour request: %s", str(e))
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def list(self, request):
        """Get all custom tour requests with optimized batch customer data fetching"""
        try:
            # Get query parameters for filtering
            customer_id = request.query_params.get('customer_id')
            driver_id = request.query_params.get('driver_id')
            status_filter = request.query_params.get('status')
            
            # Step 1: Get all custom tour requests
            def main_query():
                query = supabase.table('custom_tour_requests').select('*')
                
                if customer_id:
                    query = query.eq('customer_id', customer_id)
                if driver_id:
                    query = query.eq('driver_id', driver_id)
                if status_filter:
                    query = query.eq('status', status_filter)
                
                return query.order('created_at', desc=True).execute()
            
            response = execute_with_retry(main_query)
            requests_data = response.data if hasattr(response, 'data') else []
            
            if not requests_data:
                return Response({
                    'success': True,
                    'data': [],
                    'count': 0
                })
            
            # Step 2: Get unique customer IDs
            customer_ids = list(set(req['customer_id'] for req in requests_data if req.get('customer_id')))
            
            # Step 3: Batch fetch all customer data in ONE query
            def customer_batch_query():
                return supabase.table('users').select('id, name, email').in_('id', customer_ids).execute()
            
            customer_response = execute_with_retry(customer_batch_query)
            customers_data = customer_response.data if hasattr(customer_response, 'data') else []
            
            # Step 4: Create customer lookup dictionary
            customers_dict = {customer['id']: customer for customer in customers_data}
            
            # Step 5: Enrich request data with customer info
            for req_data in requests_data:
                customer_info = customers_dict.get(req_data.get('customer_id'))
                if customer_info:
                    req_data['customer_name'] = customer_info.get('name', 'Unknown Customer')
                    req_data['customer_email'] = customer_info.get('email', '')
                else:
                    req_data['customer_name'] = 'Unknown Customer'
                    req_data['customer_email'] = ''
            
            return Response({
                'success': True,
                'data': requests_data,
                'count': len(requests_data)
            })
            
        except Exception as e:
            logger.error(f"Error listing custom tour requests: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def retrieve(self, request, pk=None):
        """Get a specific custom tour request by ID"""
        try:
            response = supabase.table('custom_tour_requests').select('*').eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
                req_data = response.data[0]
                
                # Enrich with customer data
                try:
                    customer_response = supabase.table('users').select('name, email').eq('id', req_data['customer_id']).execute()
                    if hasattr(customer_response, 'data') and customer_response.data:
                        customer = customer_response.data[0]
                        req_data['customer_name'] = customer.get('name', '')
                        req_data['customer_email'] = customer.get('email', '')
                except Exception as e:
                    logger.debug(f"Error getting customer data: {e}")
                    req_data['customer_name'] = 'Unknown Customer'
                    req_data['customer_email'] = ''
                
                return Response({
                    'success': True,
                    'data': req_data
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Custom tour request not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Error retrieving custom tour request: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def partial_update(self, request, pk=None):
        """Update custom tour request (admin operations)"""
        try:
            # Allow updating admin fields, status, and driver assignment fields
            allowed_fields = ['status', 'package_name', 'description', 'approved_price', 'available_days', 'driver_id', 'driver_name', 'available_for_drivers']
            update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
            
            if not update_data:
                return Response({
                    'success': False,
                    'error': 'No valid fields to update'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Add updated timestamp
            update_data['updated_at'] = datetime.now().isoformat()
            
            # Validate status if provided
            if 'status' in update_data:
                valid_statuses = ['pending', 'under_review', 'approved', 'rejected', 'waiting_for_driver', 'driver_assigned', 'in_progress', 'completed']
                if update_data['status'] not in valid_statuses:
                    return Response({
                        'success': False,
                        'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # When status changes to 'approved', make it available for drivers
            if update_data.get('status') == 'approved':
                update_data['available_for_drivers'] = True
                update_data['status'] = 'waiting_for_driver'
            
            # Validate driver assignment if driver_id is provided
            if 'driver_id' in update_data and update_data['driver_id']:
                try:
                    driver_response = supabase.table('users').select('id, name, role').eq('id', update_data['driver_id']).execute()
                    if not (hasattr(driver_response, 'data') and driver_response.data):
                        return Response({
                            'success': False,
                            'error': 'Driver not found'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    driver = driver_response.data[0]
                    if driver['role'] != 'driver':
                        return Response({
                            'success': False,
                            'error': 'User is not a driver'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    # Set driver assignment fields
                    update_data['driver_name'] = driver['name']
                    update_data['driver_assigned_at'] = datetime.now().isoformat()
                    update_data['status'] = 'driver_assigned'
                    update_data['available_for_drivers'] = False
                except Exception as e:
                    return Response({
                        'success': False,
                        'error': f'Error validating driver: {str(e)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Fetch old data for audit
            old_resp = supabase.table('custom_tour_requests').select('*').eq('id', pk).execute()
            old_data = (old_resp.data[0] if hasattr(old_resp, 'data') and old_resp.data else None)

            # Update the request
            response = supabase.table('custom_tour_requests').update(update_data).eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
                # AUDIT: UPDATE
                _insert_audit_log(
                    request,
                    action="UPDATE",
                    entity_name="custom_tour_requests",
                    entity_id=pk,
                    old_data=old_data,
                    new_data=response.data[0],
                    overrides={
                        "username": "system (automatic)",
                        "role": "system",
                    }
                )
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': 'Custom tour request updated successfully'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to update custom tour request'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Error updating custom tour request: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='available-for-drivers')
    @handle_api_errors(fallback_data=[])
    def available_for_drivers(self, request):
        """Get custom tour requests available for drivers to accept with optimized batch customer data fetching"""
        # Step 1: Get all custom tour requests with status 'waiting_for_driver' and available_for_drivers = true
        def main_query():
            return supabase.table('custom_tour_requests').select('*').eq('status', 'waiting_for_driver').eq('available_for_drivers', True).order('created_at', desc=True).execute()
        
        response = safe_supabase_operation(main_query, fallback_data=[])
        requests_data = response.data if hasattr(response, 'data') else []
        
        if not requests_data:
            return Response(APIErrorHandler.create_success_response([], count=0))
        
        # Step 2: Get unique customer IDs
        customer_ids = list(set(req['customer_id'] for req in requests_data if req.get('customer_id')))
        
        if customer_ids:
            # Step 3: Batch fetch all customer data in ONE query
            def customer_batch_query():
                return supabase.table('users').select('id, name, email').in_('id', customer_ids).execute()
            
            customer_response = safe_supabase_operation(customer_batch_query, fallback_data=[])
            customers_data = customer_response.data if hasattr(customer_response, 'data') else []
            
            # Step 4: Create customer lookup dictionary
            customers_dict = {customer['id']: customer for customer in customers_data}
            
            # Step 5: Enrich request data with customer info
            for req_data in requests_data:
                customer_info = customers_dict.get(req_data.get('customer_id'))
                if customer_info:
                    req_data['customer_name'] = customer_info.get('name', 'Unknown Customer')
                    req_data['customer_email'] = customer_info.get('email', '')
                else:
                    req_data['customer_name'] = 'Unknown Customer'
                    req_data['customer_email'] = ''
        
        return Response(APIErrorHandler.create_success_response(requests_data))
    
    @action(detail=False, methods=['post'], url_path='driver-accept/(?P<request_id>[^/.]+)')
    def driver_accept_request(self, request, request_id=None):
        """Driver accepts a custom tour request"""
        try:
            driver_id = request.data.get('driver_id')
            driver_name = request.data.get('driver_name')
            
            if not driver_id or not driver_name:
                return Response({
                    'success': False,
                    'error': 'driver_id and driver_name are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verify driver exists and has correct role
            driver_response = supabase.table('users').select('id, name, role').eq('id', driver_id).execute()
            if not (hasattr(driver_response, 'data') and driver_response.data):
                return Response({
                    'success': False,
                    'error': 'Driver not found'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            driver = driver_response.data[0]
            if driver['role'] != 'driver':
                return Response({
                    'success': False,
                    'error': 'User is not a driver'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Fetch old data for audit
            old_resp = supabase.table('custom_tour_requests').select('*').eq('id', request_id).execute()
            old_data = (old_resp.data[0] if hasattr(old_resp, 'data') and old_resp.data else None)
            
            if not old_data:
                return Response({
                    'success': False,
                    'error': 'Custom tour request not found'
                }, status=status.HTTP_404_NOT_FOUND)

            # Update custom tour request with driver information
            update_data = {
                'status': 'driver_assigned',
                'driver_id': driver_id,
                'driver_name': driver_name,
                'driver_assigned_at': datetime.now().isoformat(),
                'available_for_drivers': False,
                'updated_at': datetime.now().isoformat()
            }
            
            response = supabase.table('custom_tour_requests').update(update_data).eq('id', request_id).execute()
            
            if hasattr(response, 'data') and response.data:
                # Add to driver's calendar on the preferred date
                try:
                    preferred_date = old_data.get('preferred_date')
                    if preferred_date:
                        calendar_data = {
                            'driver_id': driver_id,
                            'booking_id': request_id,
                            'booking_date': preferred_date.split('T')[0] if 'T' in str(preferred_date) else str(preferred_date),
                            'booking_time': '09:00:00',
                            'package_name': f"Custom Tour: {old_data.get('destination', 'N/A')}",
                            'customer_name': old_data.get('customer_name', 'Customer'),
                            'status': 'confirmed',
                            'booking_type': 'custom_tour',
                            'created_at': datetime.now().isoformat()
                        }
                        supabase.table('driver_calendar').insert(calendar_data).execute()
                except Exception as cal_error:
                    logger.warning(f'Failed to add to driver calendar: {cal_error}')
                
                # AUDIT: DRIVER_ACCEPT
                _insert_audit_log(
                    request,
                    action="DRIVER_ACCEPT",
                    entity_name="custom_tour_requests",
                    entity_id=request_id,
                    old_data=old_data,
                    new_data=response.data[0],
                    overrides={
                        "user_id": driver_id,
                        "username": driver_name,
                        "role": "driver",
                    }
                )
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': f'Custom tour request accepted by {driver_name}'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to assign driver to custom tour request'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.error(f'Error driver accepting custom tour request: {str(e)}')
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SpecialEventRequestViewSet(viewsets.ViewSet):
    """ViewSet for special event requests"""
    permission_classes = [AllowAny]
    
    def create(self, request):
        """Create a new special event request"""
        try:
            serializer = SpecialEventRequestSerializer(data=request.data)
            
            if not serializer.is_valid():
                return Response({
                    'success': False,
                    'error': 'Validation failed',
                    'details': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
            
            event_data = serializer.validated_data
            request_id = str(uuid.uuid4())
            request_data = {
                'id': request_id,
                'customer_id': str(event_data['customer_id']),
                'event_type': event_data['event_type'],
                'event_date': event_data['event_date'].isoformat(),
                'event_time': event_data.get('event_time').isoformat() if event_data.get('event_time') else None,
                'event_address': event_data['event_address'],
                'number_of_pax': event_data['number_of_pax'],
                'special_requirements': event_data.get('special_requirements', ''),
                'contact_number': event_data['contact_number'],
                'contact_email': event_data.get('contact_email', ''),
                'status': 'waiting_for_owner',
                'available_for_owners': True,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            # Remove None values
            request_data = {k: v for k, v in request_data.items() if v is not None}
            
            # Insert into database
            response = supabase.table('special_event_requests').insert(request_data).execute()
            
            if hasattr(response, 'data') and response.data:
                # AUDIT: CREATE
                _insert_audit_log(
                    request,
                    action="CREATE",
                    entity_name="special_event_requests",
                    entity_id=request_id,
                    old_data=None,
                    new_data=response.data[0],
                    overrides={
                        "user_id": request_data.get("customer_id"),
                        "username": request_data.get("contact_email"),
                        "role": "customer",
                    }
                )
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': 'Special event request created and sent to all owners for acceptance'
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to create special event request'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Error creating special event request: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def list(self, request):
        """Get all special event requests with optimized batch customer data fetching"""
        try:
            # Get query parameters for filtering
            customer_id = request.query_params.get('customer_id')
            status_filter = request.query_params.get('status')
            event_type = request.query_params.get('event_type')
            
            # Step 1: Get all special event requests
            def main_query():
                query = supabase.table('special_event_requests').select('*')
                
                if customer_id:
                    query = query.eq('customer_id', customer_id)
                if status_filter:
                    query = query.eq('status', status_filter)
                if event_type:
                    query = query.eq('event_type', event_type)
                
                return query.order('created_at', desc=True).execute()
            
            response = execute_with_retry(main_query)
            requests_data = response.data if hasattr(response, 'data') else []
            
            if not requests_data:
                return Response({
                    'success': True,
                    'data': [],
                    'count': 0
                })
            
            # Step 2: Get unique customer IDs
            customer_ids = list(set(req['customer_id'] for req in requests_data if req.get('customer_id')))
            
            # Step 3: Batch fetch all customer data in ONE query
            def customer_batch_query():
                return supabase.table('users').select('id, name, email').in_('id', customer_ids).execute()
            
            customer_response = execute_with_retry(customer_batch_query)
            customers_data = customer_response.data if hasattr(customer_response, 'data') else []
            
            # Step 4: Create customer lookup dictionary
            customers_dict = {customer['id']: customer for customer in customers_data}
            
            # Step 5: Enrich request data with customer info
            for req_data in requests_data:
                customer_info = customers_dict.get(req_data.get('customer_id'))
                if customer_info:
                    req_data['customer_name'] = customer_info.get('name', 'Unknown Customer')
                    req_data['customer_email'] = customer_info.get('email', '')
                else:
                    req_data['customer_name'] = 'Unknown Customer'
                    req_data['customer_email'] = ''
            
            return Response({
                'success': True,
                'data': requests_data,
                'count': len(requests_data)
            })
            
        except Exception as e:
            logger.error(f"Error listing special event requests: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def retrieve(self, request, pk=None):
        """Get a specific special event request by ID"""
        try:
            response = supabase.table('special_event_requests').select('*').eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
                req_data = response.data[0]
                
                # Enrich with customer data
                try:
                    customer_response = supabase.table('users').select('name, email').eq('id', req_data['customer_id']).execute()
                    if hasattr(customer_response, 'data') and customer_response.data:
                        customer = customer_response.data[0]
                        req_data['customer_name'] = customer.get('name', '')
                        req_data['customer_email'] = customer.get('email', '')
                except Exception as e:
                    logger.debug(f"Error getting customer data: {e}")
                    req_data['customer_name'] = 'Unknown Customer'
                    req_data['customer_email'] = ''
                
                return Response({
                    'success': True,
                    'data': req_data
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Special event request not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Error retrieving special event request: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def partial_update(self, request, pk=None):
        """Update special event request (admin operations)"""
        try:
            # Allow updating admin fields, status, and owner acceptance fields
            allowed_fields = ['status', 'approved_price_range', 'package_details', 'owner_id', 'owner_name', 'available_for_owners']
            update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
            
            if not update_data:
                return Response({
                    'success': False,
                    'error': 'No valid fields to update'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Add updated timestamp
            update_data['updated_at'] = datetime.now().isoformat()
            
            # Validate status if provided
            if 'status' in update_data:
                valid_statuses = ['pending', 'under_review', 'approved', 'rejected', 'waiting_for_owner', 'owner_accepted', 'in_progress', 'completed']
                if update_data['status'] not in valid_statuses:
                    return Response({
                        'success': False,
                        'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # When status changes to 'approved', make it available for owners
            if update_data.get('status') == 'approved':
                update_data['available_for_owners'] = True
                update_data['status'] = 'waiting_for_owner'
            
            # Validate owner acceptance if owner_id is provided
            if 'owner_id' in update_data and update_data['owner_id']:
                try:
                    owner_response = supabase.table('users').select('id, name, role').eq('id', update_data['owner_id']).execute()
                    if not (hasattr(owner_response, 'data') and owner_response.data):
                        return Response({
                            'success': False,
                            'error': 'Owner not found'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    owner = owner_response.data[0]
                    if owner['role'] != 'owner':
                        return Response({
                            'success': False,
                            'error': 'User is not an owner'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    # Set owner acceptance fields
                    update_data['owner_name'] = owner['name']
                    update_data['owner_accepted_at'] = datetime.now().isoformat()
                    update_data['status'] = 'owner_accepted'
                    update_data['available_for_owners'] = False
                except Exception as e:
                    return Response({
                        'success': False,
                        'error': f'Error validating owner: {str(e)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Fetch old data for audit
            old_resp = supabase.table('special_event_requests').select('*').eq('id', pk).execute()
            old_data = (old_resp.data[0] if hasattr(old_resp, 'data') and old_resp.data else None)

            # Update the request
            response = supabase.table('special_event_requests').update(update_data).eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
                # AUDIT: UPDATE
                _insert_audit_log(
                    request,
                    action="UPDATE",
                    entity_name="special_event_requests",
                    entity_id=pk,
                    old_data=old_data,
                    new_data=response.data[0]
                )
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': 'Special event request updated successfully'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to update special event request'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Error updating special event request: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='available-for-owners')
    def available_for_owners(self, request):
        """Get special event requests available for owners to accept with optimized batch customer data fetching"""
        try:
            # Step 1: Get all special event requests with status 'waiting_for_owner' and available_for_owners = true
            def main_query():
                return supabase.table('special_event_requests').select('*').eq('status', 'waiting_for_owner').eq('available_for_owners', True).order('created_at', desc=True).execute()
            
            response = execute_with_retry(main_query)
            requests_data = response.data if hasattr(response, 'data') else []
            
            if not requests_data:
                return Response({
                    'success': True,
                    'data': [],
                    'count': 0
                })
            
            # Step 2: Get unique customer IDs
            customer_ids = list(set(req['customer_id'] for req in requests_data if req.get('customer_id')))
            
            # Step 3: Batch fetch all customer data in ONE query
            def customer_batch_query():
                return supabase.table('users').select('id, name, email').in_('id', customer_ids).execute()
            
            customer_response = execute_with_retry(customer_batch_query)
            customers_data = customer_response.data if hasattr(customer_response, 'data') else []
            
            # Step 4: Create customer lookup dictionary
            customers_dict = {customer['id']: customer for customer in customers_data}
            
            # Step 5: Enrich request data with customer info
            for req_data in requests_data:
                customer_info = customers_dict.get(req_data.get('customer_id'))
                if customer_info:
                    req_data['customer_name'] = customer_info.get('name', 'Unknown Customer')
                    req_data['customer_email'] = customer_info.get('email', '')
                else:
                    req_data['customer_name'] = 'Unknown Customer'
                    req_data['customer_email'] = ''
            
            return Response({
                'success': True,
                'data': requests_data,
                'count': len(requests_data)
            })
            
        except Exception as e:
            logger.error(f"Error listing available special event requests for owners: {str(e)}")
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='owner-accept/(?P<request_id>[^/.]+)')
    def owner_accept_request(self, request, request_id=None):
        """Owner accepts a special event request"""
        try:
            owner_id = request.data.get('owner_id')
            owner_name = request.data.get('owner_name')
            
            if not owner_id or not owner_name:
                return Response({
                    'success': False,
                    'error': 'owner_id and owner_name are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verify owner exists and has correct role
            owner_response = supabase.table('users').select('id, name, role').eq('id', owner_id).execute()
            if not (hasattr(owner_response, 'data') and owner_response.data):
                return Response({
                    'success': False,
                    'error': 'Owner not found'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            owner = owner_response.data[0]
            if owner['role'] != 'owner':
                return Response({
                    'success': False,
                    'error': 'User is not an owner'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Fetch old data for audit
            old_resp = supabase.table('special_event_requests').select('*').eq('id', request_id).execute()
            old_data = (old_resp.data[0] if hasattr(old_resp, 'data') and old_resp.data else None)

            # Update special event request with owner information
            update_data = {
                'status': 'owner_accepted',
                'owner_id': owner_id,
                'owner_name': owner_name,
                'owner_accepted_at': datetime.now().isoformat(),
                'available_for_owners': False,
                'updated_at': datetime.now().isoformat()
            }
            
            response = supabase.table('special_event_requests').update(update_data).eq('id', request_id).execute()
            
            if hasattr(response, 'data') and response.data:
                # AUDIT: OWNER_ACCEPT
                _insert_audit_log(
                    request,
                    action="OWNER_ACCEPT",
                    entity_name="special_event_requests",
                    entity_id=request_id,
                    old_data=old_data,
                    new_data=response.data[0],
                    overrides={
                        "user_id": owner_id,
                        "username": owner_name,
                        "role": "owner",
                    }
                )
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': f'Special event request accepted by {owner_name}'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to assign owner to special event request'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.error(f'Error owner accepting special event request: {str(e)}')
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
