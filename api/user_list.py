from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase, supabase_admin
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class UserListAPI(APIView):
    """
    API endpoint to get list of users by role and status
    """
    
    def get(self, request):
        try:
            role = request.GET.get('role')
            status_filter = request.GET.get('status', 'Active')
            
            # Build query - use admin client to bypass RLS
            client = supabase_admin if supabase_admin else supabase
            query = client.table('users').select('id, email, name, role, status, profile_photo_url')
            
            if role:
                if role == 'driver':
                    # Include both 'driver' and 'driver-owner' for driver requests
                    query = query.in_('role', ['driver', 'driver-owner'])
                elif role == 'owner':
                    # Include both 'owner' and 'driver-owner' for owner requests
                    query = query.in_('role', ['owner', 'driver-owner'])
                else:
                    query = query.eq('role', role)
            
            if status_filter and status_filter.lower() != 'all':
                # Handle case-insensitive status filtering
                if status_filter.lower() == 'active':
                    query = query.eq('status', 'active')
                else:
                    query = query.eq('status', status_filter)
            
            result = query.execute()
            
            # If no results and looking for drivers, try manual filtering
            if (not hasattr(result, 'data') or not result.data) and role == 'driver':
                logger.info("No drivers found with direct query, trying manual filtering...")
                all_users_query = client.table('users').select('id, email, name, role, status, profile_photo_url')
                if status_filter and status_filter.lower() != 'all':
                    all_users_query = all_users_query.eq('status', status_filter)
                
                all_result = all_users_query.execute()
                if hasattr(all_result, 'data') and all_result.data:
                    filtered_users = []
                    for user in all_result.data:
                        user_role = user.get('role', '').lower()
                        if user_role in ['driver', 'driver-owner']:
                            filtered_users.append(user)
                    
                    logger.info(f"Manual filtering found {len(filtered_users)} drivers out of {len(all_result.data)} total users")
                    result.data = filtered_users
            
            if hasattr(result, 'data'):
                return Response({
                    "success": True,
                    "data": result.data,
                    "users": result.data,  # Alternative key for compatibility
                    "count": len(result.data),
                    "query_params": {
                        "role": role,
                        "status_filter": status_filter
                    }
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    "success": True,
                    "data": [],
                    "users": [],
                    "count": 0
                }, status=status.HTTP_200_OK)
                
        except Exception as e:
            logger.error(f"Error fetching users: {e}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class CreateTestUsersAPI(APIView):
    """
    API endpoint to create test users for development
    """
    
    def post(self, request):
        try:
            # Use admin client to bypass RLS
            client = supabase_admin if supabase_admin else supabase
            
            test_users = [
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
                },
                {
                    'id': str(uuid.uuid4()),
                    'name': 'Rosa Martinez',
                    'email': 'rosa.owner@test.com',
                    'role': 'owner',
                    'status': 'active',
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
            ]
            
            created_users = []
            for user_data in test_users:
                # Check if user already exists
                existing = client.table('users').select('id').eq('email', user_data['email']).execute()
                if hasattr(existing, 'data') and existing.data:
                    logger.info(f"User {user_data['email']} already exists, skipping...")
                    continue
                
                # Create the user
                response = client.table('users').insert(user_data).execute()
                if hasattr(response, 'data') and response.data:
                    created_users.append(response.data[0])
                    logger.info(f"Created user: {user_data['name']} ({user_data['role']})")
            
            return Response({
                "success": True,
                "message": f"Created {len(created_users)} test users",
                "data": created_users
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating test users: {e}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class DebugUsersAPI(APIView):
    """
    API endpoint to debug user data and roles
    """
    
    def get(self, request):
        try:
            # Use admin client to bypass RLS
            client = supabase_admin if supabase_admin else supabase
            
            # Get all users
            result = client.table('users').select('id, email, name, role, status, profile_photo_url, created_at').execute()
            
            if hasattr(result, 'data'):
                users = result.data
                
                # Analyze role distribution
                role_counts = {}
                for user in users:
                    role = user.get('role', 'no_role')
                    role_counts[role] = role_counts.get(role, 0) + 1
                
                # Find drivers specifically
                drivers = [u for u in users if u.get('role', '').lower() in ['driver', 'driver-owner']]
                owners = [u for u in users if u.get('role', '').lower() in ['owner', 'driver-owner']]
                
                return Response({
                    "success": True,
                    "total_users": len(users),
                    "role_distribution": role_counts,
                    "drivers": {
                        "count": len(drivers),
                        "users": drivers
                    },
                    "owners": {
                        "count": len(owners),
                        "users": owners
                    },
                    "all_users": users
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    "success": False,
                    "error": "No data returned from database"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Error debugging users: {e}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)