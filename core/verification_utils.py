"""
Verification utility functions for TarTrack system
Supports both SMS and Email verification
"""
import logging
import os
import random
import string
from datetime import datetime, timedelta
from django.conf import settings
from tartanilla_admin.supabase import supabase, supabase_admin

logger = logging.getLogger(__name__)

class VerificationService:
    """
    Verification service for handling SMS and Email OTP verification
    """
    
    @staticmethod
    def generate_otp(length=6):
        """Generate a random OTP code"""
        return ''.join(random.choices(string.digits, k=length))
    
    @staticmethod
    def store_otp(identifier, otp, verification_type='phone', expires_in_minutes=10):
        """
        Store OTP in database with expiration
        identifier: phone number or email
        verification_type: 'phone' or 'email'
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Clean up old OTPs for this identifier
            admin_client.table('verification_codes').delete().eq('identifier', identifier).execute()
            
            # Store new OTP
            expires_at = datetime.now() + timedelta(minutes=expires_in_minutes)
            
            result = admin_client.table('verification_codes').insert({
                'identifier': identifier,
                'code': otp,
                'verification_type': verification_type,
                'expires_at': expires_at.isoformat(),
                'created_at': datetime.now().isoformat(),
                'verified': False
            }).execute()
            
            if hasattr(result, 'data') and result.data:
                logger.info(f"OTP stored for {verification_type}: {identifier}")
                return {'success': True, 'expires_at': expires_at.isoformat()}
            else:
                return {'success': False, 'error': 'Failed to store OTP'}
                
        except Exception as e:
            logger.error(f"Error storing OTP: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def verify_otp(identifier, otp):
        """
        Verify OTP code
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get OTP record
            result = admin_client.table('verification_codes').select('*').eq('identifier', identifier).eq('code', otp).eq('verified', False).execute()
            
            if not hasattr(result, 'data') or not result.data:
                return {'success': False, 'error': 'Invalid or expired verification code'}
            
            otp_record = result.data[0]
            
            # Check expiration
            expires_at = datetime.fromisoformat(otp_record['expires_at'].replace('Z', '+00:00'))
            if datetime.now(expires_at.tzinfo) > expires_at:
                # Clean up expired OTP
                admin_client.table('verification_codes').delete().eq('id', otp_record['id']).execute()
                return {'success': False, 'error': 'Verification code has expired'}
            
            # Mark as verified
            admin_client.table('verification_codes').update({
                'verified': True,
                'verified_at': datetime.now().isoformat()
            }).eq('id', otp_record['id']).execute()
            
            logger.info(f"OTP verified successfully for {otp_record['verification_type']}: {identifier}")
            return {
                'success': True, 
                'verification_type': otp_record['verification_type'],
                'verified_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error verifying OTP: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def send_sms_otp(phone, otp):
        """
        Send OTP via SMS using Twilio
        """
        try:
            from core.sms_utils import SMSService
            
            message = f"TarTrack verification code: {otp}\n\nThis code expires in 10 minutes. Do not share this code with anyone."
            
            # Format phone number
            formatted_phone = SMSService._format_phone_number(phone)
            
            # Send SMS
            sms_result = SMSService._send_twilio_sms(formatted_phone, message)
            
            if sms_result['success']:
                logger.info(f"OTP SMS sent successfully to {formatted_phone}")
                return {'success': True, 'method': 'sms', 'phone': formatted_phone}
            else:
                logger.warning(f"SMS sending failed: {sms_result.get('error')}")
                # Log for manual delivery
                logger.warning(f"MANUAL SMS DELIVERY - Phone: {formatted_phone}, OTP: {otp}")
                print(f"\n=== MANUAL SMS DELIVERY ===")
                print(f"Phone: {formatted_phone}")
                print(f"OTP: {otp}")
                print(f"Message: {message}")
                print(f"===========================\n")
                return {'success': True, 'method': 'manual_sms', 'phone': formatted_phone}
                
        except Exception as e:
            logger.error(f"Error sending SMS OTP: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def send_email_otp(email, otp):
        """
        Send OTP via Email using Gmail SMTP
        """
        try:
            from core.email_smtp import GmailSMTP
            return GmailSMTP.send_verification_email(email, otp)
            
        except Exception as e:
            logger.error(f"Error sending email OTP: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def send_verification_code(identifier, verification_type='phone'):
        """
        Send verification code via SMS or Email
        """
        try:
            # Generate OTP
            otp = VerificationService.generate_otp()
            
            # Store OTP
            store_result = VerificationService.store_otp(identifier, otp, verification_type)
            if not store_result['success']:
                return store_result
            
            # Send OTP
            if verification_type == 'phone':
                send_result = VerificationService.send_sms_otp(identifier, otp)
            elif verification_type == 'email':
                send_result = VerificationService.send_email_otp(identifier, otp)
            else:
                return {'success': False, 'error': 'Invalid verification type'}
            
            if send_result['success']:
                return {
                    'success': True,
                    'message': f'Verification code sent to your {verification_type}',
                    'verification_type': verification_type,
                    'expires_at': store_result['expires_at'],
                    'method': send_result.get('method', verification_type)
                }
            else:
                return send_result
                
        except Exception as e:
            logger.error(f"Error sending verification code: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def cleanup_expired_otps():
        """
        Clean up expired OTP codes (can be run as a scheduled task)
        """
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Delete expired OTPs
            current_time = datetime.now().isoformat()
            result = admin_client.table('verification_codes').delete().lt('expires_at', current_time).execute()
            
            logger.info("Cleaned up expired OTP codes")
            return {'success': True}
            
        except Exception as e:
            logger.error(f"Error cleaning up expired OTPs: {e}")
            return {'success': False, 'error': str(e)}