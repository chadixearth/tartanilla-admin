"""
Verification API endpoints for phone/email OTP verification
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from core.verification_utils import VerificationService
import json
import logging

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class SendVerificationCodeAPI(APIView):
    """
    API endpoint to send verification code via SMS or Email
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            identifier = data.get('identifier')  # phone number or email
            verification_type = data.get('verification_type', 'phone')  # 'phone' or 'email'
            
            if not identifier:
                return Response({
                    "success": False,
                    "error": "Identifier (phone or email) is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if verification_type not in ['phone', 'email']:
                return Response({
                    "success": False,
                    "error": "Verification type must be 'phone' or 'email'."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Send verification code
            result = VerificationService.send_verification_code(identifier, verification_type)
            
            if result['success']:
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Send verification code API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class VerifyCodeAPI(APIView):
    """
    API endpoint to verify OTP code
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            identifier = data.get('identifier')  # phone number or email
            code = data.get('code')  # OTP code
            
            if not identifier or not code:
                return Response({
                    "success": False,
                    "error": "Identifier and verification code are required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verify code
            result = VerificationService.verify_otp(identifier, code)
            
            if result['success']:
                # If verification successful, we might need to activate the user account
                # For now, just return success
                return Response({
                    "success": True,
                    "message": "Verification successful.",
                    "verification_type": result.get('verification_type'),
                    "verified_at": result.get('verified_at')
                }, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Verify code API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ResendVerificationCodeAPI(APIView):
    """
    API endpoint to resend verification code
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            identifier = data.get('identifier')  # phone number or email
            verification_type = data.get('verification_type', 'phone')  # 'phone' or 'email'
            
            if not identifier:
                return Response({
                    "success": False,
                    "error": "Identifier (phone or email) is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if verification_type not in ['phone', 'email']:
                return Response({
                    "success": False,
                    "error": "Verification type must be 'phone' or 'email'."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Clean up any existing codes for this identifier first
            try:
                from tartanilla_admin.supabase import supabase_admin, supabase
                admin_client = supabase_admin if supabase_admin else supabase
                admin_client.table('verification_codes').delete().eq('identifier', identifier).execute()
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup old verification codes: {cleanup_error}")
            
            # Send new verification code
            result = VerificationService.send_verification_code(identifier, verification_type)
            
            if result['success']:
                return Response({
                    "success": True,
                    "message": f"New verification code sent to your {verification_type}.",
                    "verification_type": verification_type,
                    "expires_at": result.get('expires_at'),
                    "method": result.get('method')
                }, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Resend verification code API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)