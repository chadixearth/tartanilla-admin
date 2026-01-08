from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase, supabase_admin
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class RoleSwitchAPI:
    """
    Core role switching functions for driver/owner users
    """
    
    @staticmethod
    def switch_role(user_id, new_role):
        """
        Switch user role between driver and owner
        Clears carriage assignments when switching roles
        
        Args:
            user_id: ID of user switching roles
            new_role: New role to switch to (driver, owner, or driver-owner)
        
        Returns:
            dict with success status and updated user data
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get current user info
            user_response = admin_client.table('users').select('*').eq('id', user_id).execute()
            if not user_response.data:
                return {"success": False, "error": "User not found"}
            
            current_user = user_response.data[0]
            current_role = current_user.get('role', '')
            
            # Validate role switch is allowed
            valid_switches = {
                'driver': ['owner', 'driver-owner'],
                'owner': ['driver', 'driver-owner'],
                'driver-owner': ['driver', 'owner']
            }
            
            if current_role not in valid_switches:
                return {"success": False, "error": f"Cannot switch from role: {current_role}"}
            
            if new_role not in valid_switches.get(current_role, []):
                return {"success": False, "error": f"Cannot switch from {current_role} to {new_role}"}
            
            # Update user role
            update_data = {
                'role': new_role,
                'updated_at': datetime.now().isoformat()
            }
            
            response = admin_client.table('users').update(update_data).eq('id', user_id).execute()
            
            if not response.data:
                return {"success": False, "error": "Failed to update role"}
            
            # Clear carriage assignments when switching roles
            # When switching to driver, remove owner assignments
            # When switching to owner, remove driver assignments
            try:
                if new_role == 'driver':
                    # Remove owner-based carriage assignments
                    admin_client.table('tartanilla_carriages').update({
                        'assigned_owner_id': None,
                        'owner_assigned_at': None
                    }).eq('assigned_owner_id', user_id).execute()
                    
                elif new_role == 'owner':
                    # Remove driver-based carriage assignments
                    admin_client.table('tartanilla_carriages').update({
                        'assigned_driver_id': None,
                        'driver_assigned_at': None
                    }).eq('assigned_driver_id', user_id).execute()
                    
                elif new_role == 'driver-owner':
                    # Keep all assignments for driver-owner role
                    pass
                    
            except Exception as carriage_error:
                logger.warning(f"Failed to clear carriage assignments: {carriage_error}")
                # Don't fail the role switch if carriage update fails
            
            # Update Supabase Auth metadata
            try:
                auth_client = supabase_admin if supabase_admin else supabase
                auth_client.auth.admin.update_user_by_id(
                    user_id,
                    {"user_metadata": {"role": new_role}}
                )
            except Exception as auth_error:
                logger.warning(f"Failed to update auth metadata: {auth_error}")
                # Don't fail if auth metadata update fails
            
            logger.info(f"User {user_id} switched role from {current_role} to {new_role}")
            
            return {
                "success": True,
                "message": f"Role switched successfully from {current_role} to {new_role}",
                "previous_role": current_role,
                "new_role": new_role,
                "user": response.data[0]
            }
            
        except Exception as e:
            logger.error(f"Error switching role for user {user_id}: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def get_available_roles(user_id):
        """
        Get list of roles user can switch to
        
        Args:
            user_id: ID of user
        
        Returns:
            dict with available roles
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get current user role
            user_response = admin_client.table('users').select('role').eq('id', user_id).execute()
            if not user_response.data:
                return {"success": False, "error": "User not found"}
            
            current_role = user_response.data[0].get('role', '')
            
            # Define available switches
            available_switches = {
                'driver': ['owner', 'driver-owner'],
                'owner': ['driver', 'driver-owner'],
                'driver-owner': ['driver', 'owner']
            }
            
            available_roles = available_switches.get(current_role, [])
            
            return {
                "success": True,
                "current_role": current_role,
                "available_roles": available_roles
            }
            
        except Exception as e:
            logger.error(f"Error getting available roles for user {user_id}: {e}")
            return {"success": False, "error": str(e)}


@method_decorator(csrf_exempt, name='dispatch')
class SwitchRoleAPI(APIView):
    """
    API endpoint to switch user role
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_id = data.get('user_id')
            new_role = data.get('new_role')
            
            # Validate required fields
            if not user_id or not new_role:
                return Response({
                    "success": False,
                    "error": "user_id and new_role are required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Switch role
            result = RoleSwitchAPI.switch_role(user_id, new_role)
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Switch role API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class GetAvailableRolesAPI(APIView):
    """
    API endpoint to get available roles for user
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            user_id = request.GET.get('user_id')
            
            if not user_id:
                return Response({
                    "success": False,
                    "error": "user_id is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = RoleSwitchAPI.get_available_roles(user_id)
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Get available roles API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
