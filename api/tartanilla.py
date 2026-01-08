from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase, supabase_admin, execute_with_retry
from datetime import datetime
import traceback
import json
import uuid

def log_audit(user_id, username, role, action, entity_name, entity_id, old_data=None, new_data=None, ip_address=None, device_info=None):
    """Helper function to log audit events"""
    try:
        # If username is missing but user_id exists, fetch from database
        if user_id and (not username or not role):
            try:
                print(f'Attempting to fetch user info for user_id: {user_id} (type: {type(user_id)})')
                user_response = supabase.table('users').select('name, role').eq('id', user_id).execute()
                print(f'User query response: {user_response}')
                if hasattr(user_response, 'data') and user_response.data:
                    user_data = user_response.data[0]
                    if not username:
                        username = user_data.get('name')
                    if not role:
                        role = user_data.get('role')
                    print(f'Fetched user info for audit: username={username}, role={role}')
                else:
                    print(f'No user data found for user_id: {user_id}')
                    print(f'Response data: {getattr(user_response, "data", "No data attribute")}')
            except Exception as e:
                print(f'Failed to fetch user info for audit: {e}')
                import traceback
                print(f'User fetch traceback: {traceback.format_exc()}')
        
        audit_data = {
            'user_id': user_id,
            'username': username,
            'role': role,
            'action': action,
            'entity_name': entity_name,
            'entity_id': entity_id,
            'old_data': old_data,
            'new_data': new_data,
            'ip_address': ip_address,
            'device_info': device_info
        }
        print(f'Final audit data to insert: {audit_data}')
        insert_response = supabase.table('audit_logs').insert(audit_data).execute()
        print(f'Audit insert response: {insert_response}')
        print('Audit log inserted successfully')
    except Exception as e:
        print(f'Audit logging failed: {str(e)}')
        import traceback
        print(f'Audit logging traceback: {traceback.format_exc()}')

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

def get_device_info(request):
    """Get device info from request headers"""
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    return user_agent

def get_user_info(request):
    """Extract user info from request"""
    # Try multiple sources for user info
    user_id = None
    username = None
    role = None
    
    # Check request data (POST body)
    if hasattr(request, 'data'):
        user_id = request.data.get('user_id') or request.data.get('assigned_owner_id')
        username = request.data.get('username')
        role = request.data.get('role')
    
    # Check query parameters
    if not user_id:
        user_id = request.GET.get('user_id')
        username = request.GET.get('username')
        role = request.GET.get('role')
    
    # Check headers (common in authenticated requests)
    if not user_id:
        user_id = request.META.get('HTTP_X_USER_ID')
        username = request.META.get('HTTP_X_USERNAME')
        role = request.META.get('HTTP_X_USER_ROLE')
    
    # Check if user is authenticated (Django auth)
    if not user_id and hasattr(request, 'user') and request.user.is_authenticated:
        user_id = str(request.user.id) if hasattr(request.user, 'id') else None
        username = request.user.username if hasattr(request.user, 'username') else None
    
    return user_id, username, role

class TartanillaCarriageViewSet(viewsets.ViewSet):
    """ViewSet for tartanilla carriages (full CRUD operations)"""
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer, BrowsableAPIRenderer]  # Allow both JSON and browsable API
    
    def list(self, request):
        """Get all tartanilla carriages"""
        try:
            # Get all carriages
            response = supabase.table('tartanilla_carriages').select('*').execute()
            carriages = response.data if hasattr(response, 'data') else []
            
            # Get owner and driver information for each carriage
            for carriage in carriages:
                # Get owner info
                if carriage.get('assigned_owner_id'):
                    owner_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_owner_id']).execute()
                    if hasattr(owner_response, 'data') and owner_response.data:
                        carriage['assigned_owner'] = owner_response.data[0]
                
                # Get driver info
                if carriage.get('assigned_driver_id'):
                    driver_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_driver_id']).execute()
                    if hasattr(driver_response, 'data') and driver_response.data:
                        carriage['assigned_driver'] = driver_response.data[0]
            
            return Response({
                'success': True,
                'data': carriages
            })
            
        except Exception as e:
            print(f'Error fetching carriages: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': 'Failed to fetch carriages',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def retrieve(self, request, pk=None):
        """Get a specific tartanilla carriage by ID"""
        try:
            # Get specific carriage
            response = supabase.table('tartanilla_carriages').select('*').eq('id', pk).single().execute()
            carriage = response.data if hasattr(response, 'data') and response.data else None
            
            if not carriage:
                return Response({
                    'success': False,
                    'error': 'Carriage not found',
                    'data': None
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Get owner info
            if carriage.get('assigned_owner_id'):
                owner_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_owner_id']).execute()
                if hasattr(owner_response, 'data') and owner_response.data:
                    carriage['assigned_owner'] = owner_response.data[0]
            
            # Get driver info
            if carriage.get('assigned_driver_id'):
                driver_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_driver_id']).execute()
                if hasattr(driver_response, 'data') and driver_response.data:
                    carriage['assigned_driver'] = driver_response.data[0]
            
            return Response({
                'success': True,
                'data': carriage
            })
            
        except Exception as e:
            print(f'Error fetching carriage: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': 'Failed to fetch carriage',
                'data': None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request):
        """Create a new tartanilla carriage"""
        try:
            # Handle both DRF and Django requests
            if hasattr(request, 'data'):
                # DRF request
                data = request.data
            else:
                # Django request - try to get data from POST or JSON
                if request.content_type == 'application/json':
                    import json
                    data = json.loads(request.body)
                else:
                    data = request.POST.dict()
            
            # Validate required fields
            required_fields = ['plate_number', 'assigned_owner_id']
            for field in required_fields:
                if not data.get(field):
                    return Response({
                        'success': False,
                        'error': f'Missing required field: {field}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            owner_id = data['assigned_owner_id']
            owner_response = supabase.table('users').select('id, role').eq('id', owner_id).execute()
            if hasattr(owner_response, 'data') and owner_response.data:
                owner_data = owner_response.data[0]
                if owner_data['role'] not in ['owner', 'driver-owner']:
                    return Response({
                        'success': False,
                        'error': 'User must be an owner to create tartanilla carriages'
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                # User doesn't exist in users table - create them from auth
                try:
                    admin_client = supabase_admin if supabase_admin else supabase
                    auth_user = admin_client.auth.admin.get_user_by_id(owner_id)
                    if auth_user and auth_user.user:
                        user_data = {
                            'id': auth_user.user.id,
                            'email': auth_user.user.email,
                            'role': auth_user.user.user_metadata.get('role', 'owner') if auth_user.user.user_metadata else 'owner',
                            'status': 'Active',
                            'account_status': 'active',
                            'created_at': datetime.now().isoformat(),
                            'updated_at': datetime.now().isoformat()
                        }
                        if auth_user.user.user_metadata:
                            if auth_user.user.user_metadata.get('name'):
                                user_data['name'] = auth_user.user.user_metadata.get('name')
                            if auth_user.user.user_metadata.get('phone'):
                                user_data['phone'] = auth_user.user.user_metadata.get('phone')
                        admin_client.table('users').insert(user_data).execute()
                except Exception as e:
                    print(f'Failed to create user in users table: {e}')
                    return Response({
                        'success': False,
                        'error': 'User not found and could not be created'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if plate number already exists
            existing_response = supabase.table('tartanilla_carriages').select('id').eq('plate_number', data['plate_number']).execute()
            if hasattr(existing_response, 'data') and existing_response.data:
                return Response({
                    'success': False,
                    'error': 'Plate number already exists'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Prepare carriage data
            carriage_data = {
                'id': str(uuid.uuid4()),
                'plate_number': data.get('plate_number'),
                'assigned_owner_id': data.get('assigned_owner_id'),
                'capacity': data.get('capacity', 4),
                'status': data.get('status', 'available'),
                'eligibility': 'eligible',  # Default value that passes constraint
                'notes': data.get('notes'),
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            # Remove None values
            carriage_data = {k: v for k, v in carriage_data.items() if v is not None}

            photos = data.get('img') or data.get('photos') or None
            if photos:
                carriage_data['img'] = photos
            
            # Insert into database
            response = supabase.table('tartanilla_carriages').insert(carriage_data).execute()
            
            if hasattr(response, 'data') and response.data:
                # Log audit - fetch user info first
                try:
                    user_resp = supabase.table('users').select('name, role').eq('id', carriage_data['assigned_owner_id']).execute()
                    username = user_resp.data[0]['name'] if user_resp.data else None
                    role = user_resp.data[0]['role'] if user_resp.data else None
                except:
                    username, role = None, None
                
                log_audit(
                    user_id=carriage_data['assigned_owner_id'],
                    username=username,
                    role=role,
                    action='CREATE',
                    entity_name='tartanilla_carriages',
                    entity_id=carriage_data['id'],
                    new_data=carriage_data,
                    ip_address=get_client_ip(request),
                    device_info=get_device_info(request)
                )
                
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': 'Tartanilla carriage created successfully'
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to create tartanilla carriage'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error creating carriage: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, pk=None):
        """Update an existing tartanilla carriage"""
        try:
            # Handle both DRF and Django requests
            if hasattr(request, 'data'):
                # DRF request
                data = request.data
            else:
                # Django request - try to get data from POST or JSON
                if request.content_type == 'application/json':
                    import json
                    data = json.loads(request.body)
                else:
                    data = request.POST.dict()
            
            # Get current carriage data
            current_response = supabase.table('tartanilla_carriages').select('*').eq('id', pk).execute()
            if not hasattr(current_response, 'data') or not current_response.data:
                return Response({
                    'success': False,
                    'error': 'Tartanilla carriage not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            current_data = current_response.data[0]
            old_data = current_data.copy()  # Store for audit log
            
            # Prepare update data
            update_data = {
                'updated_at': datetime.now().isoformat()
            }
            
            # Update allowed fields (eligibility only for admin updates)
            allowed_fields = ['plate_number', 'status', 'capacity', 'assigned_driver_id', 'notes']
            for field in allowed_fields:
                if field in data:
                    update_data[field] = data[field]
            
            # Allow eligibility updates (admin can set via web interface)
            if 'eligibility' in data:
                # Validate eligibility value
                valid_eligibility = ['eligible', 'suspended']
                if data['eligibility'] in valid_eligibility:
                    update_data['eligibility'] = data['eligibility']
                else:
                    return Response({
                        'success': False,
                        'error': f'Invalid eligibility value. Must be one of: {valid_eligibility}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # If updating plate number, check for duplicates
            if 'plate_number' in data and data['plate_number'] != current_data['plate_number']:
                existing_response = supabase.table('tartanilla_carriages').select('id').eq('plate_number', data['plate_number']).execute()
                if hasattr(existing_response, 'data') and existing_response.data:
                    return Response({
                        'success': False,
                        'error': 'Plate number already exists'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # If assigning a driver, validate the driver
            if 'assigned_driver_id' in data:
                if data['assigned_driver_id']:
                    driver_response = supabase.table('users').select('id, role').eq('id', data['assigned_driver_id']).execute()
                    if not hasattr(driver_response, 'data') or not driver_response.data:
                        return Response({
                            'success': False,
                            'error': 'Driver not found'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    driver_data = driver_response.data[0]
                    if driver_data['role'] not in ['driver', 'driver-owner']:
                        return Response({
                            'success': False,
                            'error': 'User must be a driver'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    # Enforce a maximum of 2 tartanillas per driver
                    existing_driver_response = supabase.table('tartanilla_carriages').select('id').eq('assigned_driver_id', data['assigned_driver_id']).neq('id', pk).execute()
                    current_count = len(existing_driver_response.data) if hasattr(existing_driver_response, 'data') and existing_driver_response.data else 0
                    if current_count >= 2:
                        return Response({
                            'success': False,
                            'error': 'Driver already has the maximum number of tartanilla carriages (2)'
                        }, status=status.HTTP_400_BAD_REQUEST)

                    # If driver assignment changed and status not explicitly set, mark as waiting for driver acceptance
                    if data['assigned_driver_id'] != current_data.get('assigned_driver_id') and 'status' not in data:
                        update_data['status'] = 'waiting_driver_acceptance'
            
            # Update in database
            response = supabase.table('tartanilla_carriages').update(update_data).eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
                # Log audit - fetch user info first
                try:
                    user_resp = supabase.table('users').select('name, role').eq('id', old_data['assigned_owner_id']).execute()
                    username = user_resp.data[0]['name'] if user_resp.data else None
                    role = user_resp.data[0]['role'] if user_resp.data else None
                except:
                    username, role = None, None
                
                new_data = {**old_data, **update_data}
                log_audit(
                    user_id=old_data['assigned_owner_id'],
                    username=username,
                    role=role,
                    action='UPDATE',
                    entity_name='tartanilla_carriages',
                    entity_id=pk,
                    old_data=old_data,
                    new_data=new_data,
                    ip_address=get_client_ip(request),
                    device_info=get_device_info(request)
                )
                
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': 'Tartanilla carriage updated successfully'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to update tartanilla carriage'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error updating carriage: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, pk=None):
        """Delete a tartanilla carriage"""
        try:
            # Get current data before deletion for audit log
            current_response = supabase.table('tartanilla_carriages').select('*').eq('id', pk).execute()
            old_data = current_response.data[0] if hasattr(current_response, 'data') and current_response.data else None
            
            response = supabase.table('tartanilla_carriages').delete().eq('id', pk).execute()
            
            if hasattr(response, 'data') and response.data:
                # Log audit - fetch user info first
                username, role = None, None
                if old_data and old_data.get('assigned_owner_id'):
                    try:
                        user_resp = supabase.table('users').select('name, role').eq('id', old_data['assigned_owner_id']).execute()
                        username = user_resp.data[0]['name'] if user_resp.data else None
                        role = user_resp.data[0]['role'] if user_resp.data else None
                    except:
                        pass
                
                log_audit(
                    user_id=old_data['assigned_owner_id'] if old_data else None,
                    username=username,
                    role=role,
                    action='DELETE',
                    entity_name='tartanilla_carriages',
                    entity_id=pk,
                    old_data=old_data,
                    ip_address=get_client_ip(request),
                    device_info=get_device_info(request)
                )
                
                return Response({
                    'success': True,
                    'message': 'Tartanilla carriage deleted successfully'
                }, status=status.HTTP_204_NO_CONTENT)
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to delete tartanilla carriage'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error deleting carriage: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def get_by_owner(self, request):
        """Get tartanilla carriages for a specific owner"""
        try:
            owner_id = request.query_params.get('owner_id')
            
            if not owner_id:
                return Response({
                    'success': False,
                    'error': 'Owner ID is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Always return success with empty data to prevent app crashes
            carriages = []
            
            # Try to get carriages with retry logic
            for attempt in range(3):
                try:
                    response = supabase.table('tartanilla_carriages').select('*').eq('assigned_owner_id', owner_id).execute()
                    carriages = response.data if hasattr(response, 'data') else []
                    break
                except Exception as e:
                    if attempt < 2:
                        import time
                        time.sleep(0.5 * (attempt + 1))
                    else:
                        return Response({
                            'success': True,
                            'data': [],
                            'message': 'Database temporarily unavailable'
                        })
            
            # Get owner and driver information for each carriage (with error handling)
            for carriage in carriages:
                try:
                    # Get owner info
                    if carriage.get('assigned_owner_id'):
                        owner_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_owner_id']).execute()
                        if hasattr(owner_response, 'data') and owner_response.data:
                            carriage['assigned_owner'] = owner_response.data[0]
                    
                    # Get driver info
                    if carriage.get('assigned_driver_id'):
                        driver_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_driver_id']).execute()
                        if hasattr(driver_response, 'data') and driver_response.data:
                            carriage['assigned_driver'] = driver_response.data[0]
                except Exception:
                    continue
            
            return Response({
                'success': True,
                'data': carriages
            })
            
        except Exception as e:
            return Response({
                'success': True,
                'data': [],
                'message': 'Database temporarily unavailable'
            })

    @action(detail=False, methods=['get'])
    def get_by_driver(self, request):
        """Get tartanilla carriages assigned to a specific driver"""
        try:
            driver_id = request.query_params.get('driver_id')
            
            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'Driver ID is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Retry with graceful failure - always return success with empty data on failure
            carriages = []
            last_error = None
            
            for attempt in range(3):
                try:
                    print(f'Attempt {attempt + 1}: Fetching carriages for driver {driver_id}')
                    response = supabase.table('tartanilla_carriages').select('*').eq('assigned_driver_id', driver_id).execute()
                    carriages = response.data if hasattr(response, 'data') else []
                    print(f'Successfully fetched {len(carriages)} carriages for driver {driver_id}')
                    break
                except Exception as e:
                    last_error = str(e)
                    print(f'Attempt {attempt + 1} failed for driver {driver_id}: {e}')
                    if attempt < 2:  # Not the last attempt
                        import time
                        time.sleep(0.5 * (attempt + 1))
                    else:
                        # Final attempt failed - return empty data gracefully
                        print(f'All attempts failed for driver {driver_id}. Returning empty data.')
                        return Response({
                            'success': True,
                            'data': [],
                            'message': 'No carriages found or database temporarily unavailable'
                        })
            
            # Get owner and driver information for each carriage (with error handling)
            for carriage in carriages:
                try:
                    # Get owner info
                    if carriage.get('assigned_owner_id'):
                        owner_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_owner_id']).execute()
                        if hasattr(owner_response, 'data') and owner_response.data:
                            carriage['assigned_owner'] = owner_response.data[0]
                    
                    # Get driver info
                    if carriage.get('assigned_driver_id'):
                        driver_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_driver_id']).execute()
                        if hasattr(driver_response, 'data') and driver_response.data:
                            carriage['assigned_driver'] = driver_response.data[0]
                except Exception as detail_error:
                    print(f'Error fetching details for carriage {carriage.get("id")}: {detail_error}')
                    # Continue with basic carriage data even if details fail
                    continue
            
            return Response({
                'success': True,
                'data': carriages
            })
            
        except Exception as e:
            print(f'Outer error fetching carriages for driver {driver_id}: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            # Always return success with empty data to prevent app crashes
            return Response({
                'success': True,
                'data': [],
                'message': 'Database temporarily unavailable'
            })

    @action(detail=True, methods=['post'], url_path='owner-select-driver')
    def owner_select_driver(self, request, pk=None):
        """Owner selects a driver for their tartanilla carriage; sets status to waiting for driver acceptance."""
        try:
            data = request.data if hasattr(request, 'data') else (json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict())
            owner_id = data.get('owner_id')
            driver_id = data.get('driver_id')
            if not owner_id or not driver_id:
                return Response({'success': False, 'error': 'owner_id and driver_id are required'}, status=status.HTTP_400_BAD_REQUEST)

            # Fetch carriage and validate ownership
            carriage_resp = supabase.table('tartanilla_carriages').select('*').eq('id', pk).single().execute()
            carriage = carriage_resp.data if hasattr(carriage_resp, 'data') and carriage_resp.data else None
            if not carriage:
                return Response({'success': False, 'error': 'Tartanilla carriage not found'}, status=status.HTTP_404_NOT_FOUND)
            if carriage.get('assigned_owner_id') != owner_id:
                return Response({'success': False, 'error': 'Owner does not own this tartanilla carriage'}, status=status.HTTP_403_FORBIDDEN)

            # Validate driver and capacity using admin client
            client = supabase_admin if supabase_admin else supabase
            driver_resp = client.table('users').select('id, role, name').eq('id', driver_id).execute()
            drivers = driver_resp.data if hasattr(driver_resp, 'data') and driver_resp.data else []
            driver = drivers[0] if drivers else None
            if not driver or driver.get('role') not in ['driver', 'driver-owner']:
                return Response({'success': False, 'error': 'Invalid driver'}, status=status.HTTP_400_BAD_REQUEST)
            assigned_resp = supabase.table('tartanilla_carriages').select('id').eq('assigned_driver_id', driver_id).neq('id', pk).execute()
            assigned_count = len(assigned_resp.data) if hasattr(assigned_resp, 'data') and assigned_resp.data else 0
            if assigned_count >= 2:
                return Response({'success': False, 'error': 'Driver already has the maximum number of tartanilla carriages (2)'}, status=status.HTTP_400_BAD_REQUEST)

            # Apply pending assignment
            update_data = {
                'assigned_driver_id': driver_id,
                'status': 'waiting_driver_acceptance',
                'updated_at': datetime.now().isoformat(),
            }
            update_resp = supabase.table('tartanilla_carriages').update(update_data).eq('id', pk).execute()
            if hasattr(update_resp, 'data') and update_resp.data:
                # Log audit - fetch user info first
                try:
                    user_resp = supabase.table('users').select('name, role').eq('id', owner_id).execute()
                    username = user_resp.data[0]['name'] if user_resp.data else None
                    role = user_resp.data[0]['role'] if user_resp.data else None
                except:
                    username, role = None, None
                
                log_audit(
                    user_id=owner_id,
                    username=username,
                    role=role,
                    action='DRIVER_INVITE',
                    entity_name='tartanilla_carriages',
                    entity_id=pk,
                    old_data=carriage,
                    new_data=update_resp.data[0],
                    ip_address=get_client_ip(request),
                    device_info=get_device_info(request)
                )
                return Response({'success': True, 'data': update_resp.data[0], 'message': 'Driver invited; awaiting acceptance'})
            return Response({'success': False, 'error': 'Failed to invite driver'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f'Error in owner_select_driver: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='driver-accept')
    def driver_accept_assignment(self, request, pk=None):
        """Driver accepts assignment to drive the tartanilla carriage; finalizes if under limit."""
        try:
            data = request.data if hasattr(request, 'data') else (json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict())
            driver_id = data.get('driver_id')
            if not driver_id:
                return Response({'success': False, 'error': 'driver_id is required'}, status=status.HTTP_400_BAD_REQUEST)

            carriage_resp = supabase.table('tartanilla_carriages').select('*').eq('id', pk).single().execute()
            carriage = carriage_resp.data if hasattr(carriage_resp, 'data') and carriage_resp.data else None
            if not carriage:
                return Response({'success': False, 'error': 'Tartanilla carriage not found'}, status=status.HTTP_404_NOT_FOUND)
            if carriage.get('assigned_driver_id') != driver_id:
                return Response({'success': False, 'error': 'No pending assignment for this driver'}, status=status.HTTP_403_FORBIDDEN)
            if carriage.get('status') != 'waiting_driver_acceptance':
                return Response({'success': False, 'error': 'Carriage is not awaiting driver acceptance'}, status=status.HTTP_400_BAD_REQUEST)

            # Enforce max 2 assignments excluding this carriage
            assigned_resp = supabase.table('tartanilla_carriages').select('id').eq('assigned_driver_id', driver_id).neq('id', pk).execute()
            assigned_count = len(assigned_resp.data) if hasattr(assigned_resp, 'data') and assigned_resp.data else 0
            if assigned_count >= 2:
                return Response({'success': False, 'error': 'Driver already has the maximum number of tartanilla carriages (2)'}, status=status.HTTP_400_BAD_REQUEST)

            update_data = {
                'status': 'driver_assigned',
                'updated_at': datetime.now().isoformat(),
            }
            update_resp = supabase.table('tartanilla_carriages').update(update_data).eq('id', pk).execute()
            if hasattr(update_resp, 'data') and update_resp.data:
                # Log audit - fetch user info first
                try:
                    user_resp = supabase.table('users').select('name, role').eq('id', driver_id).execute()
                    username = user_resp.data[0]['name'] if user_resp.data else None
                    role = user_resp.data[0]['role'] if user_resp.data else None
                except:
                    username, role = None, None
                
                log_audit(
                    user_id=driver_id,
                    username=username,
                    role=role,
                    action='DRIVER_ACCEPT',
                    entity_name='tartanilla_carriages',
                    entity_id=pk,
                    old_data=carriage,
                    new_data=update_resp.data[0],
                    ip_address=get_client_ip(request),
                    device_info=get_device_info(request)
                )
                return Response({'success': True, 'data': update_resp.data[0], 'message': 'Assignment accepted'})
            return Response({'success': False, 'error': 'Failed to accept assignment'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f'Error in driver_accept_assignment: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='select-for-use')
    def select_carriage_for_use(self, request, pk=None):
        """Driver selects carriage for active use (max 2 in use at once)"""
        try:
            data = request.data if hasattr(request, 'data') else (json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict())
            driver_id = data.get('driver_id')
            if not driver_id:
                return Response({'success': False, 'error': 'driver_id is required'}, status=status.HTTP_400_BAD_REQUEST)

            carriage_resp = supabase.table('tartanilla_carriages').select('*').eq('id', pk).single().execute()
            carriage = carriage_resp.data if hasattr(carriage_resp, 'data') and carriage_resp.data else None
            if not carriage:
                return Response({'success': False, 'error': 'Carriage not found'}, status=status.HTTP_404_NOT_FOUND)
            if carriage.get('assigned_driver_id') != driver_id:
                return Response({'success': False, 'error': 'Not assigned to this driver'}, status=status.HTTP_403_FORBIDDEN)
            if carriage.get('status') == 'in_use':
                return Response({'success': False, 'error': 'Carriage already in use'}, status=status.HTTP_400_BAD_REQUEST)

            # Check max 2 in use
            in_use_resp = supabase.table('tartanilla_carriages').select('id').eq('assigned_driver_id', driver_id).eq('status', 'in_use').execute()
            in_use_count = len(in_use_resp.data) if hasattr(in_use_resp, 'data') and in_use_resp.data else 0
            if in_use_count >= 2:
                return Response({'success': False, 'error': 'Maximum 2 carriages can be in use at once'}, status=status.HTTP_400_BAD_REQUEST)

            update_data = {'status': 'in_use', 'updated_at': datetime.now().isoformat()}
            update_resp = supabase.table('tartanilla_carriages').update(update_data).eq('id', pk).execute()
            if hasattr(update_resp, 'data') and update_resp.data:
                return Response({'success': True, 'data': update_resp.data[0], 'message': 'Carriage selected for use'})
            return Response({'success': False, 'error': 'Failed to select carriage'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f'Error in select_carriage_for_use: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='driver-decline')
    def driver_decline_assignment(self, request, pk=None):
        """Driver declines assignment; clears driver and resets status to available."""
        try:
            data = request.data if hasattr(request, 'data') else (json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict())
            driver_id = data.get('driver_id')
            if not driver_id:
                return Response({'success': False, 'error': 'driver_id is required'}, status=status.HTTP_400_BAD_REQUEST)

            carriage_resp = supabase.table('tartanilla_carriages').select('*').eq('id', pk).single().execute()
            carriage = carriage_resp.data if hasattr(carriage_resp, 'data') and carriage_resp.data else None
            if not carriage:
                return Response({'success': False, 'error': 'Tartanilla carriage not found'}, status=status.HTTP_404_NOT_FOUND)
            if carriage.get('assigned_driver_id') != driver_id:
                return Response({'success': False, 'error': 'No pending assignment for this driver'}, status=status.HTTP_403_FORBIDDEN)

            update_data = {
                'assigned_driver_id': None,
                'status': 'available',
                'updated_at': datetime.now().isoformat(),
            }
            update_resp = supabase.table('tartanilla_carriages').update(update_data).eq('id', pk).execute()
            if hasattr(update_resp, 'data') and update_resp.data:
                # Log audit - fetch user info first
                try:
                    user_resp = supabase.table('users').select('name, role').eq('id', driver_id).execute()
                    username = user_resp.data[0]['name'] if user_resp.data else None
                    role = user_resp.data[0]['role'] if user_resp.data else None
                except:
                    username, role = None, None
                
                log_audit(
                    user_id=driver_id,
                    username=username,
                    role=role,
                    action='DRIVER_DECLINE',
                    entity_name='tartanilla_carriages',
                    entity_id=pk,
                    old_data=carriage,
                    new_data=update_resp.data[0],
                    ip_address=get_client_ip(request),
                    device_info=get_device_info(request)
                )
                return Response({'success': True, 'data': update_resp.data[0], 'message': 'Assignment declined'})
            return Response({'success': False, 'error': 'Failed to decline assignment'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f'Error in driver_decline_assignment: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def test_connection(self, request):
        """Test Supabase connection"""
        try:
            # Test basic connection
            response = supabase.table('users').select('count', count='exact').execute()
            count = response.count if hasattr(response, 'count') else 'unknown'
            
            # Test actual data fetch
            data_response = supabase.table('users').select('*').limit(5).execute()
            users = data_response.data if hasattr(data_response, 'data') else []
            
            return Response({
                'success': True,
                'connection': 'OK',
                'user_count': count,
                'sample_users': users,
                'raw_response': str(data_response)
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            })
    
    @action(detail=False, methods=['get'])
    def debug_users(self, request):
        """Debug endpoint to see all users and their roles"""
        try:
            response = supabase.table('users').select('*').execute()
            users = response.data if hasattr(response, 'data') else []
            
            # Show detailed info about each user
            user_info = []
            role_counts = {}
            for user in users:
                role = user.get('role', 'no_role')
                role_counts[role] = role_counts.get(role, 0) + 1
                
                user_info.append({
                    'id': user.get('id'),
                    'name': user.get('name'),
                    'email': user.get('email'), 
                    'role': role,
                    'status': user.get('status'),
                    'role_type': type(role).__name__,
                    'has_driver': 'driver' in str(role).lower(),
                    'created_at': user.get('created_at')
                })
            
            # Filter drivers specifically
            drivers = [u for u in user_info if u['has_driver']]
            
            return Response({
                'success': True, 
                'data': user_info, 
                'total': len(users),
                'role_counts': role_counts,
                'drivers': drivers,
                'driver_count': len(drivers),
                'raw_data': users[:3]  # First 3 raw records
            })
        except Exception as e:
            print(f'Debug users error: {str(e)}')
            return Response({'success': False, 'error': str(e)})
    

    
    @action(detail=False, methods=['get'])
    def test_users_connection(self, request):
        """Test direct connection to users table"""
        try:
            # Test 1: Count all users
            count_response = supabase.table('users').select('*', count='exact').execute()
            total_count = count_response.count if hasattr(count_response, 'count') else 0
            
            # Test 2: Get first 5 users
            sample_response = supabase.table('users').select('*').limit(5).execute()
            sample_users = sample_response.data if hasattr(sample_response, 'data') else []
            
            # Test 3: Try the exact driver query
            driver_response = supabase.table('users').select('id, name, email, role').in_('role', ['driver', 'driver-owner']).execute()
            drivers = driver_response.data if hasattr(driver_response, 'data') else []
            
            # Test 4: Get all users and check roles manually
            all_users_response = supabase.table('users').select('id, name, email, role, status').execute()
            all_users = all_users_response.data if hasattr(all_users_response, 'data') else []
            manual_drivers = [u for u in all_users if u.get('role', '').lower() in ['driver', 'driver-owner']]
            
            # Test 5: Check role distribution
            role_distribution = {}
            for user in all_users:
                role = user.get('role', 'no_role')
                role_distribution[role] = role_distribution.get(role, 0) + 1
            
            return Response({
                'success': True,
                'tests': {
                    'total_users_count': total_count,
                    'sample_users': sample_users,
                    'drivers_found_by_query': len(drivers),
                    'drivers_by_query': drivers,
                    'drivers_found_manually': len(manual_drivers),
                    'drivers_by_manual': manual_drivers,
                    'role_distribution': role_distribution,
                    'all_users_count': len(all_users),
                    'raw_driver_response': str(driver_response)
                }
            })
        except Exception as e:
            print(f'Test users connection error: {str(e)}')
            return Response({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            })
    
    @action(detail=False, methods=['get'])
    def get_available_drivers(self, request):
        """Get all drivers with fewer than 2 assigned tartanillas"""
        try:
            from .serializers import DriverSerializer
            
            print('Fetching drivers using admin client with retry logic...')
            
            # Use the same pattern as data.py - admin client with retry
            client = supabase_admin if supabase_admin else supabase
            
            def query_drivers():
                return client.table('users').select('id, name, email, role, profile_photo_url').in_('role', ['driver', 'driver-owner']).execute()
            
            # Execute with retry logic like data.py
            response = execute_with_retry(query_drivers)
            
            if not hasattr(response, 'data') or not response.data:
                print('No drivers found in database')
                return Response({
                    'success': True,
                    'data': [],
                    'debug': {'message': 'No drivers found in database'}
                })
            
            drivers = response.data
            print(f'Found {len(drivers)} drivers from database')
            print(f'Drivers: {[(d.get("name"), d.get("role")) for d in drivers]}')
            
            # Count current assignments per driver
            def query_assignments():
                return client.table('tartanilla_carriages').select('assigned_driver_id').not_.is_('assigned_driver_id', 'null').execute()
            
            assigned_response = execute_with_retry(query_assignments)
            assignment_counts = {}
            if hasattr(assigned_response, 'data') and assigned_response.data:
                for row in assigned_response.data:
                    driver_id = row.get('assigned_driver_id')
                    if driver_id:
                        assignment_counts[driver_id] = assignment_counts.get(driver_id, 0) + 1
            
            print(f'Current driver assignments: {assignment_counts}')
            
            # Filter drivers with fewer than 2 assignments
            available_drivers = []
            for driver in drivers:
                current_assignments = assignment_counts.get(driver['id'], 0)
                if current_assignments < 2:
                    available_drivers.append(driver)
                    print(f'  -> {driver.get("name")} is available ({current_assignments}/2 assignments)')
                else:
                    print(f'  -> {driver.get("name")} is at capacity ({current_assignments}/2 assignments)')
            
            # Serialize the data using DriverSerializer
            serializer = DriverSerializer(available_drivers, many=True)
            
            print(f'Final available drivers: {len(available_drivers)} - {[d["name"] for d in available_drivers]}')
            
            return Response({
                'success': True, 
                'data': serializer.data,
                'debug': {
                    'total_drivers': len(drivers),
                    'available_drivers': len(available_drivers),
                    'assignment_counts': assignment_counts,
                    'using_admin_client': supabase_admin is not None
                }
            })
            
        except Exception as e:
            print(f'Error fetching available drivers: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': f'Failed to fetch available drivers: {str(e)}',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def get_owners(self, request):
        """Get all owners for tartanilla carriage assignment"""
        try:
            response = supabase.table('users').select('id, name, email').in_('role', ['owner', 'driver-owner']).execute()
            owners = response.data if hasattr(response, 'data') else []
            
            return Response({
                'success': True,
                'data': owners
            })
            
        except Exception as e:
            print(f'Error fetching owners: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': 'Failed to fetch owners',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def get_user_by_id(self, request):
        """Get user information by ID"""
        try:
            user_id = request.query_params.get('user_id')
            
            if not user_id:
                return Response({
                    'success': False,
                    'error': 'User ID is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            response = supabase.table('users').select('id, name, email, role').eq('id', user_id).execute()
            user = response.data[0] if hasattr(response, 'data') and response.data else None
            
            if not user:
                return Response({
                    'success': False,
                    'error': 'User not found',
                    'data': None
                }, status=status.HTTP_404_NOT_FOUND)
            
            return Response({
                'success': True,
                'data': user
            })
            
        except Exception as e:
            print(f'Error fetching user {user_id}: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': 'Failed to fetch user',
                'data': None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def get_user_by_email(self, request):
        """Get user information by email"""
        try:
            email = request.query_params.get('email')
            
            if not email:
                return Response({
                    'success': False,
                    'error': 'Email is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            response = supabase.table('users').select('id, name, email, role').eq('email', email).execute()
            user = response.data[0] if hasattr(response, 'data') and response.data else None
            
            if not user:
                return Response({
                    'success': False,
                    'error': 'User not found',
                    'data': None
                }, status=status.HTTP_404_NOT_FOUND)
            
            return Response({
                'success': True,
                'data': user
            })
            
        except Exception as e:
            print(f'Error fetching user by email {email}: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': 'Failed to fetch user by email',
                'data': None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def get_all_drivers(self, request):
        """Get all drivers (for reassignment purposes)"""
        try:
            print('Fetching all drivers using admin client with retry logic...')
            
            client = supabase_admin if supabase_admin else supabase
            
            def query_drivers():
                return client.table('users').select('id, name, email, role').in_('role', ['driver', 'driver-owner']).execute()
            
            response = execute_with_retry(query_drivers)
            
            if not hasattr(response, 'data') or not response.data:
                print('No drivers found in database')
                return Response({
                    'success': True,
                    'data': []
                })
            
            drivers = response.data
            print(f'Found {len(drivers)} drivers from database')
            
            # Format drivers for UI
            formatted_drivers = []
            for driver in drivers:
                formatted_drivers.append({
                    'id': driver['id'],
                    'name': driver.get('name', 'Unknown'),
                    'email': driver.get('email', ''),
                    'role': driver.get('role', 'driver')
                })
            
            return Response({
                'success': True, 
                'data': formatted_drivers
            })
            
        except Exception as e:
            print(f'Error fetching all drivers: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': f'Failed to fetch all drivers: {str(e)}',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='cancel-assignment')
    def cancel_assignment(self, request, pk=None):
        """Owner cancels pending driver assignment"""
        try:
            data = request.data if hasattr(request, 'data') else (json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict())
            owner_id = data.get('owner_id')
            
            if not owner_id:
                return Response({'success': False, 'error': 'owner_id is required'}, status=status.HTTP_400_BAD_REQUEST)

            # Fetch carriage and validate ownership
            carriage_resp = supabase.table('tartanilla_carriages').select('*').eq('id', pk).single().execute()
            carriage = carriage_resp.data if hasattr(carriage_resp, 'data') and carriage_resp.data else None
            
            if not carriage:
                return Response({'success': False, 'error': 'Tartanilla carriage not found'}, status=status.HTTP_404_NOT_FOUND)
            
            if carriage.get('assigned_owner_id') != owner_id:
                return Response({'success': False, 'error': 'Owner does not own this tartanilla carriage'}, status=status.HTTP_403_FORBIDDEN)
            
            if carriage.get('status') != 'waiting_driver_acceptance':
                return Response({'success': False, 'error': 'No pending assignment to cancel'}, status=status.HTTP_400_BAD_REQUEST)

            # Cancel the assignment
            update_data = {
                'assigned_driver_id': None,
                'status': 'available',
                'updated_at': datetime.now().isoformat(),
            }
            
            update_resp = supabase.table('tartanilla_carriages').update(update_data).eq('id', pk).execute()
            
            if hasattr(update_resp, 'data') and update_resp.data:
                return Response({'success': True, 'data': update_resp.data[0], 'message': 'Assignment cancelled successfully'})
            
            return Response({'success': False, 'error': 'Failed to cancel assignment'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error in cancel_assignment: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='reassign-driver')
    def reassign_driver(self, request, pk=None):
        """Owner reassigns driver to a different driver"""
        try:
            data = request.data if hasattr(request, 'data') else (json.loads(request.body) if request.content_type == 'application/json' else request.POST.dict())
            owner_id = data.get('owner_id')
            new_driver_id = data.get('new_driver_id')
            
            if not owner_id or not new_driver_id:
                return Response({'success': False, 'error': 'owner_id and new_driver_id are required'}, status=status.HTTP_400_BAD_REQUEST)

            # Fetch carriage and validate ownership
            carriage_resp = supabase.table('tartanilla_carriages').select('*').eq('id', pk).single().execute()
            carriage = carriage_resp.data if hasattr(carriage_resp, 'data') and carriage_resp.data else None
            
            if not carriage:
                return Response({'success': False, 'error': 'Tartanilla carriage not found'}, status=status.HTTP_404_NOT_FOUND)
            
            if carriage.get('assigned_owner_id') != owner_id:
                return Response({'success': False, 'error': 'Owner does not own this tartanilla carriage'}, status=status.HTTP_403_FORBIDDEN)

            # Validate new driver
            client = supabase_admin if supabase_admin else supabase
            driver_resp = client.table('users').select('id, role, name').eq('id', new_driver_id).execute()
            drivers = driver_resp.data if hasattr(driver_resp, 'data') and driver_resp.data else []
            driver = drivers[0] if drivers else None
            
            if not driver or driver.get('role') not in ['driver', 'driver-owner']:
                return Response({'success': False, 'error': 'Invalid driver'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Check driver capacity (max 2 carriages)
            assigned_resp = supabase.table('tartanilla_carriages').select('id').eq('assigned_driver_id', new_driver_id).neq('id', pk).execute()
            assigned_count = len(assigned_resp.data) if hasattr(assigned_resp, 'data') and assigned_resp.data else 0
            
            if assigned_count >= 2:
                return Response({'success': False, 'error': 'Driver already has the maximum number of tartanilla carriages (2)'}, status=status.HTTP_400_BAD_REQUEST)

            # Reassign to new driver
            update_data = {
                'assigned_driver_id': new_driver_id,
                'status': 'waiting_driver_acceptance',
                'updated_at': datetime.now().isoformat(),
            }
            
            update_resp = supabase.table('tartanilla_carriages').update(update_data).eq('id', pk).execute()
            
            if hasattr(update_resp, 'data') and update_resp.data:
                return Response({'success': True, 'data': update_resp.data[0], 'message': 'Driver reassigned successfully; awaiting acceptance'})
            
            return Response({'success': False, 'error': 'Failed to reassign driver'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error in reassign_driver: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def test_audit_logging(self, request):
        """Test audit logging functionality"""
        try:
            # Test with a known user ID
            test_user_id = request.data.get('test_user_id')
            if not test_user_id:
                return Response({'success': False, 'error': 'test_user_id required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Test the log_audit function directly
            log_audit(
                user_id=test_user_id,
                username=None,
                role=None,
                action='TEST',
                entity_name='test_entity',
                entity_id='test_123',
                new_data={'test': 'data'},
                ip_address='127.0.0.1'
            )
            
            return Response({
                'success': True,
                'message': 'Audit log test completed - check console output'
            })
            
        except Exception as e:
            print(f'Error in test_audit_logging: {str(e)}')
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'])
    def create_test_drivers(self, request):
        """Create test driver users for development - REMOVE IN PRODUCTION"""
        try:
            test_drivers = [
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Juan Dela Cruz',
                    'email': 'juan.driver@test.com',
                    'role': 'driver',
                    'status': 'active',
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Maria Santos',
                    'email': 'maria.driver@test.com', 
                    'role': 'driver',
                    'status': 'active',
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Pedro Reyes',
                    'email': 'pedro.driverowner@test.com',
                    'role': 'driver-owner',
                    'status': 'active',
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Ana Garcia',
                    'email': 'ana.driver2@test.com',
                    'role': 'driver',
                    'status': 'active',
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Carlos Mendoza',
                    'email': 'carlos.driver3@test.com',
                    'role': 'driver',
                    'status': 'active',
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
            ]
            
            created_drivers = []
            for driver_data in test_drivers:
                try:
                    # Check if user already exists
                    existing = supabase.table('users').select('id').eq('email', driver_data['email']).execute()
                    if hasattr(existing, 'data') and existing.data:
                        print(f'Driver {driver_data["email"]} already exists, skipping...')
                        continue
                        
                    # Create the user
                    print(f'Creating driver: {driver_data["name"]} ({driver_data["email"]}) with role: {driver_data["role"]}')
                    response = supabase.table('users').insert(driver_data).execute()
                    if hasattr(response, 'data') and response.data:
                        created_drivers.append(response.data[0])
                        print(f'Successfully created driver: {driver_data["name"]}')
                    else:
                        print(f'Failed to create driver: {driver_data["name"]} - No data returned')
                except Exception as driver_error:
                    print(f'Error creating individual driver {driver_data["name"]}: {driver_error}')
                    continue
            
            # Verify creation by checking the database
            verification_response = supabase.table('users').select('id, name, email, role').in_('role', ['driver', 'driver-owner']).execute()
            total_drivers = len(verification_response.data) if hasattr(verification_response, 'data') else 0
            
            return Response({
                'success': True,
                'message': f'Created {len(created_drivers)} new test drivers. Total drivers in database: {total_drivers}',
                'data': created_drivers,
                'total_drivers_in_db': total_drivers,
                'verification': verification_response.data if hasattr(verification_response, 'data') else []
            })
            
        except Exception as e:
            print(f'Error creating test drivers: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': f'Failed to create test drivers: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Standalone functions for use in Django views
def get_all_tartanilla_carriages():
    """Get all tartanilla carriages - standalone function for Django views"""
    try:
        response = supabase.table('tartanilla_carriages').select('*').execute()
        carriages = response.data if hasattr(response, 'data') else []
        
        # Get owner and driver information for each carriage
        for carriage in carriages:
            # Get owner info
            if carriage.get('assigned_owner_id'):
                owner_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_owner_id']).execute()
                if hasattr(owner_response, 'data') and owner_response.data:
                    carriage['assigned_owner'] = owner_response.data[0]
            
            # Get driver info
            if carriage.get('assigned_driver_id'):
                driver_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_driver_id']).execute()
                if hasattr(driver_response, 'data') and driver_response.data:
                    carriage['assigned_driver'] = driver_response.data[0]
        
        return carriages
    except Exception as e:
        print(f'Error fetching carriages: {str(e)}')
        return []

def create_tartanilla_carriage(data):
    """Create a new tartanilla carriage - standalone function for Django views"""
    try:
        # Validate required fields
        required_fields = ['plate_number', 'assigned_owner_id']
        for field in required_fields:
            if not data.get(field):
                return {'success': False, 'error': f'Missing required field: {field}'}
        
        # Validate that the owner exists and has the correct role
        owner_response = supabase.table('users').select('id, role').eq('id', data['assigned_owner_id']).execute()
        if not hasattr(owner_response, 'data') or not owner_response.data:
            return {'success': False, 'error': 'Owner not found'}
        
        owner_data = owner_response.data[0]
        if owner_data['role'] != 'owner':
            return {'success': False, 'error': 'User must be an owner to create tartanilla carriages'}
        
        # Check if plate number already exists
        existing_response = supabase.table('tartanilla_carriages').select('id').eq('plate_number', data['plate_number']).execute()
        if hasattr(existing_response, 'data') and existing_response.data:
            return {'success': False, 'error': 'Plate number already exists'}
        
        # Prepare carriage data
        carriage_data = {
            'id': str(uuid.uuid4()),
            'plate_number': data.get('plate_number'),
            'assigned_owner_id': data.get('assigned_owner_id'),
            'capacity': data.get('capacity', 4),
            'status': data.get('status', 'available'),
            'eligibility': 'eligible',  # Default value that passes constraint
            'notes': data.get('notes'),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        # Remove None values
        carriage_data = {k: v for k, v in carriage_data.items() if v is not None}
        
        # Insert into database
        response = supabase.table('tartanilla_carriages').insert(carriage_data).execute()
        
        if hasattr(response, 'data') and response.data:
            return {'success': True, 'data': response.data[0]}
        else:
            return {'success': False, 'error': 'Failed to create tartanilla carriage'}
            
    except Exception as e:
        print(f'Error creating carriage: {str(e)}')
        return {'success': False, 'error': str(e)}

def update_tartanilla_carriage(carriage_id, data):
    """Update an existing tartanilla carriage - standalone function for Django views"""
    try:
        # Get current carriage data
        current_response = supabase.table('tartanilla_carriages').select('*').eq('id', carriage_id).execute()
        if not hasattr(current_response, 'data') or not current_response.data:
            return {'success': False, 'error': 'Tartanilla carriage not found'}
        
        current_data = current_response.data[0]
        
        # Prepare update data
        update_data = {
            'updated_at': datetime.now().isoformat()
        }
        
        # Update allowed fields
        allowed_fields = ['plate_number', 'status', 'capacity', 'assigned_driver_id', 'notes']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]
        
        # Handle eligibility separately with validation
        if 'eligibility' in data:
            valid_eligibility = ['eligible', 'suspended']
            if data['eligibility'] in valid_eligibility:
                update_data['eligibility'] = data['eligibility']
            else:
                return {'success': False, 'error': f'Invalid eligibility value. Must be one of: {valid_eligibility}'}
        
        # If updating plate number, check for duplicates
        if 'plate_number' in data and data['plate_number'] != current_data['plate_number']:
            existing_response = supabase.table('tartanilla_carriages').select('id').eq('plate_number', data['plate_number']).execute()
            if hasattr(existing_response, 'data') and existing_response.data:
                return {'success': False, 'error': 'Plate number already exists'}
        
        # If assigning a driver, validate the driver and enforce max 2
        if 'assigned_driver_id' in data:
            if data['assigned_driver_id']:
                driver_response = supabase.table('users').select('id, role').eq('id', data['assigned_driver_id']).execute()
                if not hasattr(driver_response, 'data') or not driver_response.data:
                    return {'success': False, 'error': 'Driver not found'}
                
                driver_data = driver_response.data[0]
                if driver_data['role'] != 'driver':
                    return {'success': False, 'error': 'User must be a driver'}
                
                assigned_resp = supabase.table('tartanilla_carriages').select('id').eq('assigned_driver_id', data['assigned_driver_id']).neq('id', carriage_id).execute()
                assigned_count = len(assigned_resp.data) if hasattr(assigned_resp, 'data') and assigned_resp.data else 0
                if assigned_count >= 2:
                    return {'success': False, 'error': 'Driver already has the maximum number of tartanilla carriages (2)'}

                # If driver assignment changed and status not provided, set waiting for acceptance
                if data['assigned_driver_id'] != current_data.get('assigned_driver_id') and 'status' not in data:
                    update_data['status'] = 'waiting_driver_acceptance'
        
        # Update in database
        response = supabase.table('tartanilla_carriages').update(update_data).eq('id', carriage_id).execute()
        
        if hasattr(response, 'data') and response.data:
            return {'success': True, 'data': response.data[0]}
        else:
            return {'success': False, 'error': 'Failed to update tartanilla carriage'}
            
    except Exception as e:
        print(f'Error updating carriage: {str(e)}')
        return {'success': False, 'error': str(e)}

def delete_tartanilla_carriage(carriage_id):
    """Delete a tartanilla carriage - standalone function for Django views"""
    try:
        response = supabase.table('tartanilla_carriages').delete().eq('id', carriage_id).execute()
        
        if hasattr(response, 'data') and response.data:
            return {'success': True}
        else:
            return {'success': False, 'error': 'Failed to delete tartanilla carriage'}
            
    except Exception as e:
        print(f'Error deleting carriage: {str(e)}')
        return {'success': False, 'error': str(e)}

def get_tartanilla_carriage_by_id(carriage_id):
    """Get a specific tartanilla carriage by ID - standalone function for Django views"""
    try:
        response = supabase.table('tartanilla_carriages').select('*').eq('id', carriage_id).single().execute()
        carriage = response.data if hasattr(response, 'data') and response.data else None
        
        if not carriage:
            return None
        
        # Get owner info
        if carriage.get('assigned_owner_id'):
            owner_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_owner_id']).execute()
            if hasattr(owner_response, 'data') and owner_response.data:
                carriage['assigned_owner'] = owner_response.data[0]
        
        # Get driver info
        if carriage.get('assigned_driver_id'):
            driver_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_driver_id']).execute()
            if hasattr(driver_response, 'data') and driver_response.data:
                carriage['assigned_driver'] = driver_response.data[0]
        
        return carriage
        
    except Exception as e:
        print(f'Error fetching carriage: {str(e)}')
        return None

def get_available_drivers():
    """Get all drivers with fewer than 2 assigned tartanillas - standalone function for Django views"""
    try:
        # Get all drivers - try multiple approaches (include all drivers)
        drivers = []
        try:
            # Try direct role match with both driver and driver-owner
            drivers_response = supabase.table('users').select('id, name, email, role').in_('role', ['driver', 'driver-owner']).execute()
            if hasattr(drivers_response, 'data') and drivers_response.data:
                drivers.extend(drivers_response.data)
            
            # If no results, try getting all users and filter manually
            if not drivers:
                all_users_response = supabase.table('users').select('id, name, email, role').execute()
                if hasattr(all_users_response, 'data') and all_users_response.data:
                    for user in all_users_response.data:
                        role = user.get('role', '').lower()
                        if role in ['driver', 'driver-owner']:
                            drivers.append(user)
                            
        except Exception as e:
            print(f'Error fetching drivers: {e}')
        
        # Count current assignments per driver
        assigned_response = supabase.table('tartanilla_carriages').select('assigned_driver_id').not_.is_('assigned_driver_id', 'null').execute()
        counts = {}
        if hasattr(assigned_response, 'data') and assigned_response.data:
            for row in assigned_response.data:
                did = row.get('assigned_driver_id')
                if not did:
                    continue
                counts[did] = counts.get(did, 0) + 1

        # Filter drivers with fewer than 2 assignments
        available_drivers = []
        for d in drivers:
            if counts.get(d['id'], 0) < 2:
                available_drivers.append({
                    'id': d['id'],
                    'name': d['name'],
                    'email': d['email']
                })
        
        return available_drivers
        
    except Exception as e:
        print(f'Error fetching available drivers: {str(e)}')
        return []

def get_owners():
    """Get all owners for tartanilla carriage assignment - standalone function for Django views"""
    try:
        response = supabase.table('users').select('id, name, email').in_('role', ['owner', 'driver-owner']).execute()
        owners = response.data if hasattr(response, 'data') else []
        return owners
        
    except Exception as e:
        print(f'Error fetching owners: {str(e)}')
        return []

def get_tartanilla_carriages_by_owner(owner_id):
    """Get tartanilla carriages for a specific owner - standalone function for Django views"""
    try:
        response = supabase.table('tartanilla_carriages').select('*').eq('assigned_owner_id', owner_id).execute()
        carriages = response.data if hasattr(response, 'data') else []
        
        # Get owner and driver information for each carriage
        for carriage in carriages:
            # Get owner info
            if carriage.get('assigned_owner_id'):
                owner_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_owner_id']).execute()
                if hasattr(owner_response, 'data') and owner_response.data:
                    carriage['assigned_owner'] = owner_response.data[0]
            
            # Get driver info
            if carriage.get('assigned_driver_id'):
                driver_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_driver_id']).execute()
                if hasattr(driver_response, 'data') and driver_response.data:
                    carriage['assigned_driver'] = driver_response.data[0]
        
        return carriages
        
    except Exception as e:
        print(f'Error fetching carriages for owner {owner_id}: {str(e)}')
        return []

def get_user_by_id(user_id):
    """Get user information by ID - standalone function for Django views"""
    try:
        response = supabase.table('users').select('id, name, email, role').eq('id', user_id).execute()
        user = response.data[0] if hasattr(response, 'data') and response.data else None
        return user
        
    except Exception as e:
        print(f'Error fetching user {user_id}: {str(e)}')
        return None

def get_user_by_email(email):
    """Get user information by email - standalone function for Django views"""
    try:
        response = supabase.table('users').select('id, name, email, role').eq('email', email).execute()
        user = response.data[0] if hasattr(response, 'data') and response.data else None
        return user
        
    except Exception as e:
        print(f'Error fetching user by email {email}: {str(e)}')
        return None

def get_tartanilla_carriages_by_driver(driver_id):
    """Get tartanilla carriages assigned to a specific driver - standalone function for Django views"""
    try:
        # Retry logic with graceful failure
        carriages = []
        for attempt in range(3):
            try:
                response = supabase.table('tartanilla_carriages').select('*').eq('assigned_driver_id', driver_id).execute()
                carriages = response.data if hasattr(response, 'data') else []
                break
            except Exception as e:
                print(f'Attempt {attempt + 1} failed for driver {driver_id}: {e}')
                if attempt < 2:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                else:
                    print(f'All attempts failed for driver {driver_id}. Returning empty data.')
                    return []
        
        # Get owner and driver information for each carriage
        for carriage in carriages:
            try:
                # Get owner info
                if carriage.get('assigned_owner_id'):
                    owner_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_owner_id']).execute()
                    if hasattr(owner_response, 'data') and owner_response.data:
                        carriage['assigned_owner'] = owner_response.data[0]
                
                # Get driver info
                if carriage.get('assigned_driver_id'):
                    driver_response = supabase.table('users').select('id, name, email, role').eq('id', carriage['assigned_driver_id']).execute()
                    if hasattr(driver_response, 'data') and driver_response.data:
                        carriage['assigned_driver'] = driver_response.data[0]
            except Exception as detail_error:
                print(f'Error fetching details for carriage {carriage.get("id")}: {detail_error}')
                continue
        
        return carriages
        
    except Exception as e:
        print(f'Error fetching carriages for driver {driver_id}: {str(e)}')
        return []
