"""
Device Verification System
Sends email verification code when user logs in from a new device
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase, supabase_admin
from datetime import datetime, timedelta
import json
import logging
import secrets
import hashlib

logger = logging.getLogger(__name__)


class DeviceVerificationAPI:
    """
    Handle device verification for new device logins
    """
    
    @staticmethod
    def get_device_fingerprint(request):
        """
        Generate a device fingerprint from request metadata
        """
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        ip_address = request.META.get('REMOTE_ADDR', '')
        
        # Create a hash of device info
        device_string = f"{user_agent}|{ip_address}"
        device_hash = hashlib.sha256(device_string.encode()).hexdigest()
        
        return device_hash
    
    @staticmethod
    def is_trusted_device(user_id, device_fingerprint):
        """
        Check if device is already trusted for this user
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            result = admin_client.table('trusted_devices').select('*').eq(
                'user_id', user_id
            ).eq('device_fingerprint', device_fingerprint).eq('is_active', True).execute()
            
            return bool(result.data)
        except Exception as e:
            logger.error(f"Error checking trusted device: {e}")
            return False
    
    @staticmethod
    def generate_verification_code():
        """
        Generate a 6-digit verification code
        """
        return str(secrets.randbelow(900000) + 100000)
    
    @staticmethod
    def send_device_verification_email(email, code, device_info):
        """
        Send device verification code via email
        """
        try:
            from core.email_smtp import GmailSMTP
            
            subject = "TarTrack - New Device Login Verification"
            body = f"""
Hello,

We detected a login to your TarTrack account from a new device.

Verification Code: {code}

Device Information:
{device_info}

If this was you, please enter the code to verify this device.
If this wasn't you, please change your password immediately.

This code will expire in 10 minutes.

Best regards,
TarTrack Security Team
"""
            
            result = GmailSMTP.send_email(email, subject, body)
            return result
        except Exception as e:
            logger.error(f"Error sending device verification email: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def create_verification_request(user_id, email, device_fingerprint, device_info):
        """
        Create a device verification request
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Generate verification code
            code = DeviceVerificationAPI.generate_verification_code()
            
            # Store verification request
            verification_data = {
                'user_id': user_id,
                'device_fingerprint': device_fingerprint,
                'verification_code': code,
                'device_info': device_info,
                'created_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(minutes=10)).isoformat(),
                'is_verified': False
            }
            
            admin_client.table('device_verification_requests').insert(verification_data).execute()
            
            # Send email
            email_result = DeviceVerificationAPI.send_device_verification_email(
                email, code, device_info
            )
            
            return {
                'success': True,
                'message': 'Verification code sent to your email',
                'email_sent': email_result.get('success', False)
            }
        except Exception as e:
            logger.error(f"Error creating verification request: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def verify_device_code(user_id, device_fingerprint, code):
        """
        Verify the device verification code
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get the latest verification request for this user and device
            result = admin_client.table('device_verification_requests').select('*').eq(
                'user_id', user_id
            ).eq('device_fingerprint', device_fingerprint).eq(
                'is_verified', False
            ).order('created_at', desc=True).limit(1).execute()
            
            if not result.data:
                return {'success': False, 'error': 'No verification request found'}
            
            verification = result.data[0]
            
            # Check if code matches
            if verification['verification_code'] != code:
                return {'success': False, 'error': 'Invalid verification code'}
            
            # Check if expired
            expires_at = datetime.fromisoformat(verification['expires_at'].replace('Z', '+00:00'))
            if datetime.now(expires_at.tzinfo) > expires_at:
                return {'success': False, 'error': 'Verification code has expired'}
            
            # Mark as verified
            admin_client.table('device_verification_requests').update({
                'is_verified': True,
                'verified_at': datetime.now().isoformat()
            }).eq('id', verification['id']).execute()
            
            # Add device to trusted devices
            trusted_device_data = {
                'user_id': user_id,
                'device_fingerprint': device_fingerprint,
                'device_info': verification['device_info'],
                'first_seen': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat(),
                'is_active': True
            }
            
            admin_client.table('trusted_devices').insert(trusted_device_data).execute()
            
            return {
                'success': True,
                'message': 'Device verified successfully'
            }
        except Exception as e:
            logger.error(f"Error verifying device code: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def update_device_last_seen(user_id, device_fingerprint):
        """
        Update last seen timestamp for trusted device
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            admin_client.table('trusted_devices').update({
                'last_seen': datetime.now().isoformat()
            }).eq('user_id', user_id).eq('device_fingerprint', device_fingerprint).execute()
        except Exception as e:
            logger.error(f"Error updating device last seen: {e}")


@method_decorator(csrf_exempt, name='dispatch')
class CheckDeviceAPI(APIView):
    """
    Check if device needs verification
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_id = data.get('user_id')
            email = data.get('email')
            
            if not user_id or not email:
                return Response({
                    'success': False,
                    'error': 'User ID and email are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get device fingerprint
            device_fingerprint = DeviceVerificationAPI.get_device_fingerprint(request)
            
            # Check if device is trusted
            is_trusted = DeviceVerificationAPI.is_trusted_device(user_id, device_fingerprint)
            
            if is_trusted:
                # Update last seen
                DeviceVerificationAPI.update_device_last_seen(user_id, device_fingerprint)
                
                return Response({
                    'success': True,
                    'requires_verification': False,
                    'message': 'Device is trusted'
                }, status=status.HTTP_200_OK)
            else:
                # Create verification request
                user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
                device_info = f"User Agent: {user_agent}"
                
                result = DeviceVerificationAPI.create_verification_request(
                    user_id, email, device_fingerprint, device_info
                )
                
                if result['success']:
                    return Response({
                        'success': True,
                        'requires_verification': True,
                        'message': result['message'],
                        'device_fingerprint': device_fingerprint
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        'success': False,
                        'error': result['error']
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        except Exception as e:
            logger.error(f"Check device error: {e}")
            return Response({
                'success': False,
                'error': 'Failed to check device'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class VerifyDeviceCodeAPI(APIView):
    """
    Verify device verification code
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            user_id = data.get('user_id')
            device_fingerprint = data.get('device_fingerprint')
            code = data.get('code')
            
            if not user_id or not device_fingerprint or not code:
                return Response({
                    'success': False,
                    'error': 'User ID, device fingerprint, and code are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = DeviceVerificationAPI.verify_device_code(user_id, device_fingerprint, code)
            
            if result['success']:
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
        
        except Exception as e:
            logger.error(f"Verify device code error: {e}")
            return Response({
                'success': False,
                'error': 'Failed to verify device code'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
