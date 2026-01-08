# custompackagerequest.py - FIXED VERSION
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase, execute_with_retry
from core.error_handlers import handle_api_errors, safe_supabase_operation, APIErrorHandler
from datetime import datetime
import traceback
import uuid
import logging

logger = logging.getLogger(__name__)

from .serializers import (
    CustomTourRequestSerializer,
    SpecialEventRequestSerializer,
    ResponseSerializer
)

def _insert_audit_log(request, *, action, entity_name, entity_id=None, old_data=None, new_data=None, overrides=None):
    """Simplified audit logging - never breaks main flow"""
    try:
        actor = overrides or {"user_id": None, "username": None, "role": None}
        log_row = {
            "user_id": actor.get("user_id"),
            "username": actor.get("username"),
            "role": actor.get("role"),
            "action": action,
            "entity_name": entity_name,
            "entity_id": str(entity_id) if entity_id else None,
            "old_data": old_data,
            "new_data": new_data,
            "ip_address": request.META.get("REMOTE_ADDR", ""),
        }
        supabase.table("audit_logs").insert(log_row).execute()
    except Exception:
        logger.warning("Audit log failed", exc_info=True)


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
            
            # CRITICAL FIX: Always set duration (default 4 hours if not provided)
            duration = tour_data.get('preferred_duration_hours') or 4
            
            request_data = {
                'id': request_id,
                'customer_id': str(tour_data['customer_id']),
                'destination': tour_data['destination'],
                'pickup_location': tour_data.get('pickup_location', ''),
                'preferred_duration_hours': duration,
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
            
            response = supabase.table('custom_tour_requests').insert(request_data).execute()
            
            if hasattr(response, 'data') and response.data:
                _insert_audit_log(
                    request,
                    action="CREATE",
                    entity_name="custom_tour_requests",
                    entity_id=request_id,
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
                    'message': 'Custom tour request created successfully'
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to create custom tour request'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error("Error creating custom tour request: %s", str(e))
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def list(self, request):
        """Get all custom tour requests"""
        try:
            customer_id = request.query_params.get('customer_id')
            status_filter = request.query_params.get('status')
            
            def main_query():
                query = supabase.table('custom_tour_requests').select('*')
                if customer_id:
                    query = query.eq('customer_id', customer_id)
                if status_filter:
                    query = query.eq('status', status_filter)
                return query.order('created_at', desc=True).execute()
            
            response = execute_with_retry(main_query)
            requests_data = response.data if hasattr(response, 'data') else []
            
            if not requests_data:
                return Response({'success': True, 'data': [], 'count': 0})
            
            # Batch fetch customer data
            customer_ids = list(set(req['customer_id'] for req in requests_data if req.get('customer_id')))
            
            def customer_batch_query():
                return supabase.table('users').select('id, name, email').in_('id', customer_ids).execute()
            
            customer_response = execute_with_retry(customer_batch_query)
            customers_data = customer_response.data if hasattr(customer_response, 'data') else []
            customers_dict = {c['id']: c for c in customers_data}
            
            # Enrich with customer info
            for req_data in requests_data:
                customer_info = customers_dict.get(req_data.get('customer_id'))
                if customer_info:
                    req_data['customer_name'] = customer_info.get('name', 'Unknown')
                    req_data['customer_email'] = customer_info.get('email', '')
            
            return Response({'success': True, 'data': requests_data, 'count': len(requests_data)})
            
        except Exception as e:
            logger.error(f"Error listing custom tour requests: {str(e)}")
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def retrieve(self, request, pk=None):
        """Get a specific custom tour request"""
        try:
            response = supabase.table('custom_tour_requests').select('*').eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
                req_data = response.data[0]
                
                try:
                    customer_response = supabase.table('users').select('name, email').eq('id', req_data['customer_id']).execute()
                    if hasattr(customer_response, 'data') and customer_response.data:
                        customer = customer_response.data[0]
                        req_data['customer_name'] = customer.get('name', '')
                        req_data['customer_email'] = customer.get('email', '')
                except Exception:
                    pass
                
                return Response({'success': True, 'data': req_data})
            else:
                return Response({
                    'success': False,
                    'error': 'Custom tour request not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Error retrieving custom tour request: {str(e)}")
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def partial_update(self, request, pk=None):
        """Update custom tour request"""
        try:
            allowed_fields = ['status', 'package_name', 'description', 'approved_price', 'available_days', 'driver_id', 'driver_name']
            update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
            
            if not update_data:
                return Response({
                    'success': False,
                    'error': 'No valid fields to update'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            update_data['updated_at'] = datetime.now().isoformat()
            
            # Validate status
            if 'status' in update_data:
                valid_statuses = ['pending', 'under_review', 'approved', 'rejected', 'waiting_for_driver', 'driver_assigned', 'in_progress', 'completed']
                if update_data['status'] not in valid_statuses:
                    return Response({
                        'success': False,
                        'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate driver if provided
            if 'driver_id' in update_data and update_data['driver_id']:
                driver_response = supabase.table('users').select('id, name, role').eq('id', update_data['driver_id']).execute()
                if not (hasattr(driver_response, 'data') and driver_response.data):
                    return Response({'success': False, 'error': 'Driver not found'}, status=status.HTTP_400_BAD_REQUEST)
                
                driver = driver_response.data[0]
                if driver['role'] != 'driver':
                    return Response({'success': False, 'error': 'User is not a driver'}, status=status.HTTP_400_BAD_REQUEST)
                
                update_data['driver_name'] = driver['name']
                update_data['status'] = 'driver_assigned'
            
            response = supabase.table('custom_tour_requests').update(update_data).eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
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
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
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
            
            request_data = {k: v for k, v in request_data.items() if v is not None}
            
            response = supabase.table('special_event_requests').insert(request_data).execute()
            
            if hasattr(response, 'data') and response.data:
                _insert_audit_log(
                    request,
                    action="CREATE",
                    entity_name="special_event_requests",
                    entity_id=request_id,
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
                    'message': 'Special event request created successfully'
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to create special event request'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Error creating special event request: {str(e)}")
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def list(self, request):
        """Get all special event requests"""
        try:
            customer_id = request.query_params.get('customer_id')
            status_filter = request.query_params.get('status')
            event_type = request.query_params.get('event_type')
            
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
                return Response({'success': True, 'data': [], 'count': 0})
            
            # Batch fetch customer data
            customer_ids = list(set(req['customer_id'] for req in requests_data if req.get('customer_id')))
            
            def customer_batch_query():
                return supabase.table('users').select('id, name, email').in_('id', customer_ids).execute()
            
            customer_response = execute_with_retry(customer_batch_query)
            customers_data = customer_response.data if hasattr(customer_response, 'data') else []
            customers_dict = {c['id']: c for c in customers_data}
            
            for req_data in requests_data:
                customer_info = customers_dict.get(req_data.get('customer_id'))
                if customer_info:
                    req_data['customer_name'] = customer_info.get('name', 'Unknown')
                    req_data['customer_email'] = customer_info.get('email', '')
            
            return Response({'success': True, 'data': requests_data, 'count': len(requests_data)})
            
        except Exception as e:
            logger.error(f"Error listing special event requests: {str(e)}")
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def retrieve(self, request, pk=None):
        """Get a specific special event request"""
        try:
            response = supabase.table('special_event_requests').select('*').eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
                req_data = response.data[0]
                
                try:
                    customer_response = supabase.table('users').select('name, email').eq('id', req_data['customer_id']).execute()
                    if hasattr(customer_response, 'data') and customer_response.data:
                        customer = customer_response.data[0]
                        req_data['customer_name'] = customer.get('name', '')
                        req_data['customer_email'] = customer.get('email', '')
                except Exception:
                    pass
                
                return Response({'success': True, 'data': req_data})
            else:
                return Response({
                    'success': False,
                    'error': 'Special event request not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Error retrieving special event request: {str(e)}")
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def partial_update(self, request, pk=None):
        """Update special event request"""
        try:
            allowed_fields = ['status', 'approved_price_range', 'package_details', 'owner_id', 'owner_name']
            update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
            
            if not update_data:
                return Response({
                    'success': False,
                    'error': 'No valid fields to update'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            update_data['updated_at'] = datetime.now().isoformat()
            
            if 'status' in update_data:
                valid_statuses = ['pending', 'under_review', 'approved', 'rejected', 'waiting_for_owner', 'owner_accepted', 'in_progress', 'completed']
                if update_data['status'] not in valid_statuses:
                    return Response({
                        'success': False,
                        'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            if 'owner_id' in update_data and update_data['owner_id']:
                owner_response = supabase.table('users').select('id, name, role').eq('id', update_data['owner_id']).execute()
                if not (hasattr(owner_response, 'data') and owner_response.data):
                    return Response({'success': False, 'error': 'Owner not found'}, status=status.HTTP_400_BAD_REQUEST)
                
                owner = owner_response.data[0]
                if owner['role'] != 'owner':
                    return Response({'success': False, 'error': 'User is not an owner'}, status=status.HTTP_400_BAD_REQUEST)
                
                update_data['owner_name'] = owner['name']
                update_data['status'] = 'owner_accepted'
            
            response = supabase.table('special_event_requests').update(update_data).eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
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
            return Response({
                'success': False,
                'error': f'Internal server error: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
