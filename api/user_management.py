from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase, supabase_admin, execute_with_retry
from core.auth_decorators import jwt_authenticated, jwt_role_required
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class UserManagementAPI:
    """
    Core user management functions for admin operations
    """
    
    @staticmethod
    def suspend_user(user_id, suspended_by, reason, duration_days=None):
        """
        Suspend a user account
        
        Args:
            user_id: ID of user to suspend
            suspended_by: ID of admin performing suspension
            reason: Reason for suspension
            duration_days: Number of days to suspend (None for permanent)
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Calculate suspension end date if duration provided
            suspended_until = None
            if duration_days:
                suspended_until = (datetime.now() + timedelta(days=duration_days)).isoformat()
            
            # Update user status
            update_data = {
                'status': 'suspended',
                'suspension_reason': reason,
                'suspended_by': suspended_by,
                'suspended_at': datetime.now().isoformat(),
                'suspended_until': suspended_until
            }
            
            response = admin_client.table('users').update(update_data).eq('id', user_id).execute()
            
            if hasattr(response, 'data') and response.data:
                # Log the suspension action
                UserManagementAPI._log_user_action(
                    user_id, suspended_by, 'suspend', 
                    f"User suspended: {reason}" + (f" for {duration_days} days" if duration_days else " permanently")
                )
                
                return {
                    "success": True,
                    "message": f"User suspended successfully" + (f" for {duration_days} days" if duration_days else " permanently"),
                    "suspended_until": suspended_until
                }
            else:
                return {"success": False, "error": "Failed to suspend user"}
                
        except Exception as e:
            logger.error(f"Error suspending user {user_id}: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def unsuspend_user(user_id, unsuspended_by):
        """
        Remove suspension from a user account
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Update user status
            update_data = {
                'status': 'active',
                'suspension_reason': None,
                'suspended_by': None,
                'suspended_at': None,
                'suspended_until': None,
                'unsuspended_by': unsuspended_by,
                'unsuspended_at': datetime.now().isoformat()
            }
            
            response = admin_client.table('users').update(update_data).eq('id', user_id).execute()
            
            if hasattr(response, 'data') and response.data:
                # Log the unsuspension action
                UserManagementAPI._log_user_action(
                    user_id, unsuspended_by, 'unsuspend', "User suspension removed"
                )
                
                return {
                    "success": True,
                    "message": "User suspension removed successfully"
                }
            else:
                return {"success": False, "error": "Failed to remove suspension"}
                
        except Exception as e:
            logger.error(f"Error removing suspension for user {user_id}: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def get_user_suspension_status(user_id):
        """
        Get detailed suspension status for a user
        """
        try:
            client = supabase_admin if supabase_admin else supabase
            response = client.table('users').select(
                'id, email, name, status, suspended_until, suspension_reason, suspended_at, suspended_by'
            ).eq('id', user_id).execute()
            
            if response.data:
                user = response.data[0]
                is_suspended = user.get('status') == 'suspended'
                
                result = {
                    "success": True,
                    "user_id": user_id,
                    "email": user.get('email'),
                    "name": user.get('name'),
                    "is_suspended": is_suspended,
                    "status": user.get('status'),
                    "suspension_reason": user.get('suspension_reason'),
                    "suspended_at": user.get('suspended_at'),
                    "suspended_by": user.get('suspended_by'),
                    "suspended_until": user.get('suspended_until')
                }
                
                # Calculate remaining days if suspended with end date
                if is_suspended and user.get('suspended_until'):
                    try:
                        suspend_date = datetime.fromisoformat(user.get('suspended_until').replace('Z', '+00:00'))
                        current_date = datetime.now(suspend_date.tzinfo)
                        remaining_days = (suspend_date - current_date).days
                        result["remaining_days"] = max(0, remaining_days)
                        result["is_expired"] = remaining_days <= 0
                    except Exception as date_error:
                        logger.error(f"Error parsing suspension date: {date_error}")
                        result["remaining_days"] = None
                        result["is_expired"] = False
                
                return result
            else:
                return {"success": False, "error": "User not found"}
                
        except Exception as e:
            logger.error(f"Error getting suspension status for user {user_id}: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def list_suspended_users():
        """
        Get list of all suspended users
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            response = admin_client.table('users').select(
                'id, email, name, role, status, suspended_until, suspension_reason, suspended_at, suspended_by'
            ).eq('status', 'suspended').order('suspended_at', desc=True).execute()
            
            if hasattr(response, 'data'):
                users = []
                for user in response.data:
                    user_data = {
                        "id": user.get('id'),
                        "email": user.get('email'),
                        "name": user.get('name'),
                        "role": user.get('role'),
                        "suspension_reason": user.get('suspension_reason'),
                        "suspended_at": user.get('suspended_at'),
                        "suspended_by": user.get('suspended_by'),
                        "suspended_until": user.get('suspended_until'),
                        "is_permanent": user.get('suspended_until') is None
                    }
                    
                    # Calculate remaining days if not permanent
                    if user.get('suspended_until'):
                        try:
                            suspend_date = datetime.fromisoformat(user.get('suspended_until').replace('Z', '+00:00'))
                            current_date = datetime.now(suspend_date.tzinfo)
                            remaining_days = (suspend_date - current_date).days
                            user_data["remaining_days"] = max(0, remaining_days)
                            user_data["is_expired"] = remaining_days <= 0
                        except Exception:
                            user_data["remaining_days"] = None
                            user_data["is_expired"] = False
                    
                    users.append(user_data)
                
                return {"success": True, "users": users}
            else:
                return {"success": True, "users": []}
                
        except Exception as e:
            logger.error(f"Error listing suspended users: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _log_user_action(user_id, performed_by, action, details):
        """
        Log user management actions for audit trail
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            log_data = {
                'user_id': user_id,
                'performed_by': performed_by,
                'action': action,
                'details': details,
                'timestamp': datetime.now().isoformat(),
                'ip_address': None,  # Could be added if needed
                'user_agent': None   # Could be added if needed
            }
            
            admin_client.table('user_management_logs').insert(log_data).execute()
        except Exception as e:
            logger.error(f"Error logging user action: {e}")
            # Don't fail the main operation if logging fails


@method_decorator(csrf_exempt, name='dispatch')
class SuspendUserAPI(APIView):
    """
    API endpoint to suspend a user account
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_id = data.get('user_id')
            suspended_by = data.get('suspended_by')
            reason = data.get('reason')
            duration_days = data.get('duration_days')  # Optional
            
            # Validate required fields
            if not all([user_id, suspended_by, reason]):
                return Response({
                    "success": False,
                    "error": "user_id, suspended_by, and reason are required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate duration_days if provided
            if duration_days is not None:
                try:
                    duration_days = int(duration_days)
                    if duration_days <= 0:
                        return Response({
                            "success": False,
                            "error": "duration_days must be a positive integer."
                        }, status=status.HTTP_400_BAD_REQUEST)
                except (ValueError, TypeError):
                    return Response({
                        "success": False,
                        "error": "duration_days must be a valid number."
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Suspend user
            result = UserManagementAPI.suspend_user(user_id, suspended_by, reason, duration_days)
            
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
            logger.error(f"Suspend user API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class UnsuspendUserAPI(APIView):
    """
    API endpoint to remove suspension from a user account
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_id = data.get('user_id')
            unsuspended_by = data.get('unsuspended_by')
            
            # Validate required fields
            if not all([user_id, unsuspended_by]):
                return Response({
                    "success": False,
                    "error": "user_id and unsuspended_by are required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Remove suspension
            result = UserManagementAPI.unsuspend_user(user_id, unsuspended_by)
            
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
            logger.error(f"Unsuspend user API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class UserSuspensionStatusAPI(APIView):
    """
    API endpoint to get user suspension status
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
            
            result = UserManagementAPI.get_user_suspension_status(user_id)
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Get suspension status API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ListSuspendedUsersAPI(APIView):
    """
    API endpoint to list all suspended users
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            result = UserManagementAPI.list_suspended_users()
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"List suspended users API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)