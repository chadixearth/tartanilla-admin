"""
Admin Approval System for Driver and Owner Verification
Handles the complete workflow: Application -> Admin Review -> Approval/Rejection -> Credential Delivery
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase, supabase_admin
from core.sms_utils import SMSService
from core.email_utils import EmailService
from .authentication import AuthenticationAPI
import json
import logging
import secrets
import string
from datetime import datetime

logger = logging.getLogger(__name__)

class AdminApprovalAPI:
    """
    Core admin approval functions for driver and owner verification
    """
    
    @staticmethod
    def get_pending_applications():
        """
        Get all pending driver and owner applications for admin review
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get pending registrations with enhanced data
            response = admin_client.table('pending_registrations').select('''
                id, email, role, status, created_at, phone, username,
                first_name, last_name, address, additional_data, preferred_notification
            ''').eq('status', 'pending').order('created_at', desc=True).execute()
            
            if hasattr(response, 'data') and response.data:
                # Enhance data for admin display
                enhanced_data = []
                for app in response.data:
                    additional = app.get('additional_data') or {}
                    enhanced_app = {
                        **app,
                        'full_name': f"{app.get('first_name', '')} {app.get('last_name', '')}".strip(),
                        'application_type': app.get('role', '').title(),
                        'contact_info': {
                            'email': app.get('email'),
                            'phone': app.get('phone') or additional.get('phone')
                        },
                        'preferred_notification': app.get('preferred_notification') or additional.get('preferred_notification') or 'both',
                        'documents': additional.get('documents', {}),
                        'experience': additional.get('experience'),
                        'owns_tartanilla': additional.get('owns_tartanilla'),
                        'drives_own_tartanilla': additional.get('drives_own_tartanilla'),
                        'owned_count': additional.get('owned_count'),
                        'license_number': additional.get('license_number'),
                        'vehicle_details': additional.get('vehicle_details')
                    }
                    enhanced_data.append(enhanced_app)
                
                return {"success": True, "applications": enhanced_data, "count": len(enhanced_data)}
            
            return {"success": True, "applications": [], "count": 0}
            
        except Exception as e:
            logger.error(f"Error getting pending applications: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def approve_application(application_id, admin_id, admin_name, send_credentials_via=None):
        """
        Approve driver/owner application and send credentials
        send_credentials_via: "email", "sms", "both", or None (use user preference)
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get the pending application
            app_response = admin_client.table('pending_registrations').select('*').eq('id', application_id).execute()
            
            if not hasattr(app_response, 'data') or not app_response.data:
                return {"success": False, "error": "Application not found"}
            
            application = app_response.data[0]
            
            if application['status'] != 'pending':
                return {"success": False, "error": "Application is not in pending status"}
            
            # Use user's preferred method if not overridden by admin
            if send_credentials_via is None:
                additional_data = application.get('additional_data') or {}
                send_credentials_via = application.get('preferred_notification') or additional_data.get('preferred_notification') or 'both'
            
            # Generate secure password
            password = AdminApprovalAPI._generate_secure_password()
            
            # Determine final role (handle driver-owner combinations)
            final_role = AdminApprovalAPI._determine_final_role(application)
            
            # Create user account with Supabase Auth
            user_metadata = {
                "role": final_role,
                "approved_by": admin_name,
                "approved_at": datetime.now().isoformat()
            }
            
            # Add additional data to metadata
            if application.get('additional_data'):
                user_metadata.update(application['additional_data'])
            
            # Create user account
            auth_result = admin_client.auth.admin.create_user({
                "email": application['email'],
                "password": password,
                "user_metadata": user_metadata,
                "email_confirm": True  # Auto-confirm for approved users
            })
            
            if not auth_result.user:
                return {"success": False, "error": "Failed to create user account"}
            
            # Update pending registration status
            admin_client.table('pending_registrations').update({
                "status": "approved",
                "approved_by": admin_name,
                "approved_at": datetime.now().isoformat(),
                "user_id": auth_result.user.id
            }).eq('id', application_id).execute()
            
            # Send credentials via requested method
            notification_results = AdminApprovalAPI._send_approval_credentials(
                application, final_role, password, send_credentials_via
            )
            
            return {
                "success": True,
                "message": f"{final_role.title()} application approved successfully",
                "user_id": auth_result.user.id,
                "credentials_sent": notification_results,
                "final_role": final_role,
                "notification_method": send_credentials_via
            }
            
        except Exception as e:
            logger.error(f"Error approving application: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def reject_application(application_id, admin_id, admin_name, reason, send_notification_via=None):
        """
        Reject driver/owner application with reason
        send_notification_via: "email", "sms", "both", or None (use user preference)
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get the pending application
            app_response = admin_client.table('pending_registrations').select('*').eq('id', application_id).execute()
            
            if not hasattr(app_response, 'data') or not app_response.data:
                return {"success": False, "error": "Application not found"}
            
            application = app_response.data[0]
            
            if application['status'] != 'pending':
                return {"success": False, "error": "Application is not in pending status"}
            
            # Use user's preferred method if not overridden by admin
            if send_notification_via is None:
                additional_data = application.get('additional_data') or {}
                send_notification_via = application.get('preferred_notification') or additional_data.get('preferred_notification') or 'both'
            
            # Update pending registration status
            admin_client.table('pending_registrations').update({
                "status": "rejected",
                "rejected_by": admin_name,
                "rejected_at": datetime.now().isoformat(),
                "rejection_reason": reason
            }).eq('id', application_id).execute()
            
            # Send rejection notification
            notification_results = AdminApprovalAPI._send_rejection_notification(
                application, reason, send_notification_via
            )
            
            return {
                "success": True,
                "message": f"{application['role'].title()} application rejected",
                "notification_sent": notification_results,
                "notification_method": send_notification_via
            }
            
        except Exception as e:
            logger.error(f"Error rejecting application: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _generate_secure_password(length=12):
        """Generate a secure random password"""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        
        # Ensure password has required character types
        while not (any(c.islower() for c in password) and 
                   any(c.isupper() for c in password) and 
                   any(c.isdigit() for c in password) and 
                   any(c in "!@#$%^&*" for c in password)):
            password = ''.join(secrets.choice(alphabet) for _ in range(length))
        
        return password
    
    @staticmethod
    def _determine_final_role(application):
        """Determine final role based on application data"""
        base_role = application['role']
        additional_data = application.get('additional_data') or {}
        
        def _is_truthy(value):
            return str(value).lower() in {"1", "true", "yes", "y"}
        
        # Check for combined roles
        owns_count = additional_data.get('owned_count')
        try:
            owns_count_num = int(owns_count) if owns_count is not None and str(owns_count).strip() != '' else 0
        except (TypeError, ValueError):
            owns_count_num = 0
        
        also_owns = _is_truthy(additional_data.get('owns_tartanilla')) or owns_count_num > 0
        also_drives = _is_truthy(additional_data.get('drives_own_tartanilla')) or _is_truthy(additional_data.get('also_drives'))
        
        if (base_role == 'driver' and also_owns) or (base_role == 'owner' and also_drives):
            return 'driver-owner'
        
        return base_role
    
    @staticmethod
    def _send_approval_credentials(application, role, password, method="both"):
        """Send approval credentials via email and/or SMS"""
        results = {"email": None, "sms": None}
        
        email = application['email']
        phone = application.get('phone') or (application.get('additional_data') or {}).get('phone')
        
        # Auto-adjust method if no phone provided
        if method == "both" and not phone:
            method = "email"
            logger.info(f"No phone number provided for {email}, sending via email only")
        elif method == "sms" and not phone:
            method = "email"
            logger.warning(f"SMS requested but no phone number for {email}, falling back to email")
        
        # Send email notification
        if method in ["email", "both"]:
            try:
                email_result = EmailService.send_approval_email(email, role, password)
                results["email"] = email_result
                logger.info(f"Approval email result for {email}: {email_result}")
            except Exception as e:
                logger.error(f"Failed to send approval email to {email}: {e}")
                results["email"] = {"success": False, "error": str(e)}
        
        # Send SMS notification
        if method in ["sms", "both"] and phone:
            try:
                sms_result = SMSService.send_approval_sms(phone, role, email, password)
                results["sms"] = sms_result
                logger.info(f"Approval SMS result for {phone}: {sms_result}")
            except Exception as e:
                logger.error(f"Failed to send approval SMS to {phone}: {e}")
                results["sms"] = {"success": False, "error": str(e)}
        
        return results
    
    @staticmethod
    def _send_rejection_notification(application, reason, method="both"):
        """Send rejection notification via email and/or SMS"""
        results = {"email": None, "sms": None}
        
        email = application['email']
        phone = application.get('phone') or (application.get('additional_data') or {}).get('phone')
        role = application['role']
        
        # Auto-adjust method if no phone provided
        if method == "both" and not phone:
            method = "email"
            logger.info(f"No phone number provided for {email}, sending rejection via email only")
        elif method == "sms" and not phone:
            method = "email"
            logger.warning(f"SMS requested but no phone number for {email}, falling back to email")
        
        # Send email notification
        if method in ["email", "both"]:
            try:
                email_result = EmailService.send_rejection_email(email, role, reason)
                results["email"] = email_result
                logger.info(f"Rejection email result for {email}: {email_result}")
            except Exception as e:
                logger.error(f"Failed to send rejection email to {email}: {e}")
                results["email"] = {"success": False, "error": str(e)}
        
        # Send SMS notification
        if method in ["sms", "both"] and phone:
            try:
                sms_result = SMSService.send_rejection_sms(phone, role, reason)
                results["sms"] = sms_result
                logger.info(f"Rejection SMS result for {phone}: {sms_result}")
            except Exception as e:
                logger.error(f"Failed to send rejection SMS to {phone}: {e}")
                results["sms"] = {"success": False, "error": str(e)}
        
        return results


@method_decorator(csrf_exempt, name='dispatch')
class PendingApplicationsAPI(APIView):
    """Get all pending driver and owner applications"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            result = AdminApprovalAPI.get_pending_applications()
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f"PendingApplicationsAPI error: {e}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ApproveApplicationAPI(APIView):
    """Approve a driver or owner application"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            application_id = data.get('application_id')
            admin_id = data.get('admin_id')
            admin_name = data.get('admin_name', 'Admin')
            send_via = data.get('send_credentials_via')  # email, sms, both, or None (use user preference)
            
            if not application_id:
                return Response({
                    "success": False,
                    "error": "Application ID is required"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = AdminApprovalAPI.approve_application(
                application_id, admin_id, admin_name, send_via
            )
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data"
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"ApproveApplicationAPI error: {e}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class RejectApplicationAPI(APIView):
    """Reject a driver or owner application"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            application_id = data.get('application_id')
            admin_id = data.get('admin_id')
            admin_name = data.get('admin_name', 'Admin')
            reason = data.get('reason', 'Application did not meet requirements')
            send_via = data.get('send_notification_via')  # email, sms, both, or None (use user preference)
            
            if not application_id:
                return Response({
                    "success": False,
                    "error": "Application ID is required"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = AdminApprovalAPI.reject_application(
                application_id, admin_id, admin_name, reason, send_via
            )
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data"
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"RejectApplicationAPI error: {e}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ResendCredentialsAPI(APIView):
    """Resend credentials to approved users"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_email = data.get('email')
            send_via = data.get('send_via', 'both')  # email, sms, or both
            new_password = data.get('generate_new_password', False)
            
            if not user_email:
                return Response({
                    "success": False,
                    "error": "Email is required"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get user info
            admin_client = supabase_admin if supabase_admin else supabase
            user_response = admin_client.table('users').select('*').eq('email', user_email).execute()
            
            if not hasattr(user_response, 'data') or not user_response.data:
                return Response({
                    "success": False,
                    "error": "User not found"
                }, status=status.HTTP_404_NOT_FOUND)
            
            user = user_response.data[0]
            
            # Generate new password if requested
            password = None
            if new_password:
                password = AdminApprovalAPI._generate_secure_password()
                
                # Update password in Supabase Auth
                admin_client.auth.admin.update_user_by_id(
                    user['id'],
                    {"password": password}
                )
            
            # Create mock application object for notification
            mock_application = {
                'email': user['email'],
                'phone': user.get('phone'),
                'role': user.get('role', 'user'),
                'additional_data': {}
            }
            
            # Send credentials
            if password:
                results = AdminApprovalAPI._send_approval_credentials(
                    mock_application, user.get('role', 'user'), password, send_via
                )
                message = "New credentials sent successfully"
            else:
                # Just send login reminder without password
                results = {"email": {"success": True, "method": "reminder"}}
                message = "Login reminder sent successfully"
            
            return Response({
                "success": True,
                "message": message,
                "credentials_sent": results,
                "new_password_generated": bool(password)
            }, status=status.HTTP_200_OK)
            
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data"
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"ResendCredentialsAPI error: {e}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)