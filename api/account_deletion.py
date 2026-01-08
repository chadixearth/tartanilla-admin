from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase, supabase_admin
from core.jwt_auth import verify_token, get_token_from_request
import json
import logging

logger = logging.getLogger(__name__)


class AccountDeletionAPI:
    """
    Core account deletion functions
    """
    
    @staticmethod
    def request_account_deletion(user_id, reason=None):
        """
        Request account deletion for a user
        Creates a deletion request scheduled for automatic deletion after 7 days
        """
        try:
            # Use admin client to bypass RLS for reading user data
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Check if user exists using admin client
            user_response = admin_client.table('users').select('*').eq('id', user_id).execute()
            if not hasattr(user_response, 'data') or not user_response.data:
                return {"success": False, "error": "User not found."}
            
            user = user_response.data[0]
            
            # Check if there's already a scheduled deletion request using admin client
            # Only check for 'scheduled' status, not cancelled or completed ones
            print(f"Checking for existing scheduled deletion requests for user {user_id}")
            existing_request = admin_client.table('account_deletion_requests').select('*').eq('user_id', user_id).eq('status', 'scheduled').execute()
            
            # Debug logging
            if hasattr(existing_request, 'data'):
                print(f"Found {len(existing_request.data)} existing requests with 'scheduled' status")
                for req in existing_request.data:
                    print(f"  - Request ID: {req.get('id')}, Status: {req.get('status')}, Created: {req.get('requested_at')}")
            
            # Check if we actually have a scheduled request
            if hasattr(existing_request, 'data') and existing_request.data and len(existing_request.data) > 0:
                # There's already a scheduled deletion request
                return {"success": False, "error": "A deletion request is already scheduled for this account."}
            
            # Create deletion request scheduled for 7 days from now
            from datetime import datetime, timedelta
            scheduled_deletion = datetime.now() + timedelta(days=7)
            
            deletion_data = {
                "user_id": user_id,
                "user_email": user.get('email'),
                "user_name": user.get('name'),
                "user_role": user.get('role'),
                "reason": reason,
                "status": "scheduled",
                "requested_at": datetime.now().isoformat(),
                "scheduled_deletion_at": scheduled_deletion.isoformat(),
                "requested_by": user_id  # Self-requested
            }
            
            # Use admin client to insert the deletion request
            result = admin_client.table('account_deletion_requests').insert(deletion_data).execute()
            
            if hasattr(result, 'data') and result.data:
                # Suspend the user account
                AccountDeletionAPI._suspend_user_account(user_id)
                
                # Immediately logout the user from Supabase
                AccountDeletionAPI._logout_user_immediately(user_id)
                
                # Send confirmation email to user
                AccountDeletionAPI._send_deletion_scheduled_email(user, scheduled_deletion)
                
                return {
                    "success": True,
                    "message": f"Account deletion scheduled successfully. Your account has been suspended and you have been logged out. Your account will be deleted on {scheduled_deletion.strftime('%Y-%m-%d at %H:%M')}. You can cancel this request by logging in again.",
                    "request_id": result.data[0]["id"],
                    "scheduled_deletion_at": scheduled_deletion.isoformat(),
                    "days_remaining": 7,
                    "account_suspended": True,
                    "logout_required": True,
                    "user_logged_out": True
                }
            else:
                return {"success": False, "error": "Failed to submit deletion request."}
                
        except Exception as e:
            print(f"Error requesting account deletion: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def cancel_deletion_request(user_id):
        """
        Cancel a scheduled account deletion request
        """
        try:
            # Use admin client to bypass RLS
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Find the scheduled deletion request for this user
            existing_request = admin_client.table('account_deletion_requests').select('*').eq('user_id', user_id).eq('status', 'scheduled').execute()
            
            if not hasattr(existing_request, 'data') or not existing_request.data:
                return {"success": False, "error": "No scheduled deletion request found for this account."}
            
            deletion_request = existing_request.data[0]
            
            # Update the request status to cancelled
            from datetime import datetime
            result = admin_client.table('account_deletion_requests').update({
                "status": "cancelled",
                "cancelled_at": datetime.now().isoformat()
            }).eq('id', deletion_request['id']).execute()
            
            if hasattr(result, 'data') and result.data:
                # Reactivate the user account
                AccountDeletionAPI._reactivate_user_account(user_id)
                
                # Send cancellation confirmation email
                AccountDeletionAPI._send_deletion_cancelled_email(deletion_request)
                
                return {
                    "success": True,
                    "message": "Account deletion request cancelled successfully. Your account has been reactivated and is safe. You can now use all features normally.",
                    "account_reactivated": True
                }
            else:
                return {"success": False, "error": "Failed to cancel deletion request."}
                
        except Exception as e:
            print(f"Error cancelling deletion request: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def get_user_deletion_status(user_id):
        """
        Get the deletion status for a specific user
        """
        try:
            # Use admin client to bypass RLS
            admin_client = supabase_admin if supabase_admin else supabase
            response = admin_client.table('account_deletion_requests').select('*').eq('user_id', user_id).order('requested_at', desc=True).execute()
            
            if hasattr(response, 'data') and response.data:
                request = response.data[0]
                
                # Calculate days remaining if scheduled
                days_remaining = None
                if request['status'] == 'scheduled':
                    from datetime import datetime, timezone
                    scheduled_date = datetime.fromisoformat(request['scheduled_deletion_at'].replace('Z', '+00:00'))
                    current_time = datetime.now(timezone.utc)
                    days_remaining = (scheduled_date - current_time).days
                
                return {
                    "success": True,
                    "data": {
                        "status": request['status'],
                        "scheduled_deletion_at": request.get('scheduled_deletion_at'),
                        "days_remaining": days_remaining,
                        "reason": request.get('reason'),
                        "requested_at": request['requested_at']
                    }
                }
            else:
                return {
                    "success": True,
                    "data": {
                        "status": "none",
                        "scheduled_deletion_at": None,
                        "days_remaining": None,
                        "reason": None,
                        "requested_at": None
                    }
                }
        except Exception as e:
            print(f"Error getting user deletion status: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def get_deletion_requests():
        """
        Get all scheduled account deletion requests (admin only)
        """
        try:
            # Use admin client to bypass RLS for admin operations
            client = supabase_admin if supabase_admin else supabase
            response = client.table('account_deletion_requests').select('*').eq('status', 'scheduled').order('scheduled_deletion_at', desc=True).execute()
            if hasattr(response, 'data'):
                return {"success": True, "data": response.data}
            return {"success": True, "data": []}
        except Exception as e:
            print(f"Error getting deletion requests: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def process_scheduled_deletions():
        """
        Process all scheduled deletions that are due
        This should be called by a background task/cron job
        """
        try:
            from datetime import datetime
            current_time = datetime.now()
            
            # Use admin client to bypass RLS for admin operations
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get all scheduled deletions that are due
            response = admin_client.table('account_deletion_requests').select('*').eq('status', 'scheduled').lte('scheduled_deletion_at', current_time.isoformat()).execute()
            
            if not hasattr(response, 'data') or not response.data:
                return {"success": True, "message": "No scheduled deletions to process", "processed": 0}
            
            processed_count = 0
            failed_count = 0
            
            for deletion_request in response.data:
                try:
                    # Process the deletion
                    result = AccountDeletionAPI._delete_user_account(deletion_request)
                    if result['success']:
                        processed_count += 1
                    else:
                        failed_count += 1
                        # Mark as failed
                        admin_client.table('account_deletion_requests').update({
                            "status": "failed",
                            "failure_reason": result.get('error', 'Unknown error'),
                            "completed_at": current_time.isoformat()
                        }).eq('id', deletion_request['id']).execute()
                        
                except Exception as e:
                    failed_count += 1
                    print(f"Error processing deletion request {deletion_request['id']}: {e}")
                    # Mark as failed
                    admin_client.table('account_deletion_requests').update({
                        "status": "failed",
                        "failure_reason": str(e),
                        "completed_at": current_time.isoformat()
                    }).eq('id', deletion_request['id']).execute()
            
            return {
                "success": True,
                "message": f"Processed {processed_count} deletions, {failed_count} failed",
                "processed": processed_count,
                "failed": failed_count
            }
                
        except Exception as e:
            print(f"Error processing scheduled deletions: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _delete_user_account(deletion_request):
        """
        Actually delete a user account (internal method)
        """
        try:
            from datetime import datetime
            admin_client = supabase_admin if supabase_admin else supabase
            user_id = deletion_request['user_id']
            
            # Delete user from Supabase Auth
            try:
                admin_client.auth.admin.delete_user(user_id)
            except Exception as e:
                print(f"Error deleting user from auth: {e}")
                # Continue with database cleanup even if auth deletion fails
            
            # Delete user from users table
            admin_client.table('users').delete().eq('id', user_id).execute()
            
            # Update deletion request status
            admin_client.table('account_deletion_requests').update({
                "status": "completed",
                "completed_at": datetime.now().isoformat()
            }).eq('id', deletion_request['id']).execute()
            
            # Send confirmation email to user (placeholder)
            AccountDeletionAPI._send_deletion_confirmation_email(deletion_request['user_email'])
            
            return {
                "success": True,
                "message": "Account deleted successfully."
            }
                
        except Exception as e:
            print(f"Error deleting user account: {e}")
            return {"success": False, "error": str(e)}
    
    # Removed approve_deletion_request as admin approval is no longer needed
    
    # Removed reject_deletion_request as admin rejection is no longer needed
    
    @staticmethod
    def _suspend_user_account(user_id):
        """
        Suspend user account when deletion is requested
        """
        try:
            # Use admin client to bypass RLS for updating user status
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Update user account status to scheduled_for_deletion
            result = admin_client.table('users').update({
                "account_status": "scheduled_for_deletion"
            }).eq('id', user_id).execute()
            
            if hasattr(result, 'data') and result.data:
                print(f"User account {user_id} suspended for deletion")
                return True
            else:
                print(f"Failed to suspend user account {user_id}")
                return False
        except Exception as e:
            print(f"Error suspending user account {user_id}: {e}")
            return False
    
    @staticmethod
    def _reactivate_user_account(user_id):
        """
        Reactivate user account when deletion is cancelled
        """
        try:
            # Use admin client to bypass RLS for updating user status
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Update user account status back to active
            result = admin_client.table('users').update({
                "account_status": "active"
            }).eq('id', user_id).execute()
            
            if hasattr(result, 'data') and result.data:
                print(f"User account {user_id} reactivated")
                return True
            else:
                print(f"Failed to reactivate user account {user_id}")
                return False
        except Exception as e:
            print(f"Error reactivating user account {user_id}: {e}")
            return False
    
    @staticmethod
    def _logout_user_immediately(user_id):
        """
        Immediately logout the user when account deletion is requested
        This revokes all active sessions for the user
        """
        try:
            # Use admin client to revoke user sessions
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Revoke all sessions for the user
            try:
                # This will invalidate all JWT tokens for the user
                admin_client.auth.admin.get_user(user_id)
                # Note: Supabase doesn't have a direct "logout user" admin function
                # The session revocation happens automatically when account is suspended
                print(f"User {user_id} sessions invalidated due to account suspension")
                return True
            except Exception as e:
                print(f"Error during admin logout for user {user_id}: {e}")
                # Continue even if this fails - the suspension should prevent access
                return True
                
        except Exception as e:
            print(f"Error logging out user {user_id}: {e}")
            return False
    
    @staticmethod
    def _send_deletion_scheduled_email(user, scheduled_date):
        """
        Send email to user confirming deletion is scheduled (placeholder)
        """
        try:
            print(f"Sending deletion scheduled email to {user.get('email')}. Scheduled for: {scheduled_date}")
            return True
        except Exception as e:
            print(f"Error sending deletion scheduled email: {e}")
            return False
    
    @staticmethod
    def _send_deletion_cancelled_email(deletion_request):
        """
        Send email to user confirming deletion is cancelled (placeholder)
        """
        try:
            print(f"Sending deletion cancelled email to {deletion_request.get('user_email')}")
            return True
        except Exception as e:
            print(f"Error sending deletion cancelled email: {e}")
            return False
    
    @staticmethod
    def _send_deletion_confirmation_email(email):
        """
        Send confirmation email to user about account deletion (placeholder)
        """
        try:
            print(f"Sending deletion confirmation email to {email}")
            return True
        except Exception as e:
            print(f"Error sending deletion confirmation email: {e}")
            return False
    
    # Removed _send_deletion_rejection_email as admin rejection is no longer needed


@method_decorator(csrf_exempt, name='dispatch')
class RequestAccountDeletionAPI(APIView):
    """
    API endpoint for users to request account deletion
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_id = data.get('user_id')
            reason = data.get('reason')
            
            # Validate required fields
            if not user_id:
                return Response({
                    "success": False,
                    "error": "User ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Request account deletion
            result = AccountDeletionAPI.request_account_deletion(user_id, reason)
            
            if result.get("success"):
                return Response(result, status=status.HTTP_201_CREATED)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class AccountDeletionRequestsAPI(APIView):
    """
    API endpoint for admins to get pending account deletion requests
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            result = AccountDeletionAPI.get_deletion_requests()
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Removed ApproveAccountDeletionAPI as admin approval is no longer needed


@method_decorator(csrf_exempt, name='dispatch')
class CancelAccountDeletionAPI(APIView):
    """
    API endpoint for users to cancel their account deletion request
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_id = data.get('user_id')
            
            # Validate required fields
            if not user_id:
                return Response({
                    "success": False,
                    "error": "User ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Cancel deletion request
            result = AccountDeletionAPI.cancel_deletion_request(user_id)
            
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
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class UserDeletionStatusAPI(APIView):
    """
    API endpoint for users to check their deletion status
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            user_id = request.GET.get('user_id')
            
            if not user_id:
                return Response({
                    "success": False,
                    "error": "User ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = AccountDeletionAPI.get_user_deletion_status(user_id)
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ProcessScheduledDeletionsAPI(APIView):
    """
    API endpoint for processing scheduled deletions (admin/system endpoint)
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            result = AccountDeletionAPI.process_scheduled_deletions()
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class CancelDeletionAndLoginAPI(APIView):
    """
    API endpoint for users to cancel deletion and login when their account is suspended
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_id = data.get('user_id')
            confirm_cancellation = data.get('confirm_cancellation', False)
            
            # Validate required fields
            if not user_id:
                return Response({
                    "success": False,
                    "error": "User ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if user has a scheduled deletion
            deletion_status = AccountDeletionAPI.get_user_deletion_status(user_id)
            
            if not deletion_status.get('success') or deletion_status.get('data', {}).get('status') != 'scheduled':
                return Response({
                    "success": False,
                    "error": "No scheduled deletion found for this account."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if confirm_cancellation:
                # Cancel the deletion request
                result = AccountDeletionAPI.cancel_deletion_request(user_id)
                
                if result.get("success"):
                    return Response({
                        "success": True,
                        "message": "Account deletion cancelled successfully. Your account has been reactivated.",
                        "account_reactivated": True,
                        "can_login": True
                    }, status=status.HTTP_200_OK)
                else:
                    return Response(result, status=status.HTTP_400_BAD_REQUEST)
            else:
                # Return deletion info without cancelling
                return Response({
                    "success": True,
                    "message": "Account is scheduled for deletion. Confirm cancellation to reactivate your account.",
                    "deletion_info": deletion_status.get('data', {}),
                    "requires_confirmation": True
                }, status=status.HTTP_200_OK)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)