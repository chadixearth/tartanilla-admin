"""
SMS utility functions for TarTrack system using Twilio
"""
import logging
import os
from django.conf import settings

logger = logging.getLogger(__name__)

class SMSService:
    """
    SMS service for sending notifications via Twilio
    """
    
    @staticmethod
    def send_approval_sms(phone, role, email, password):
        """
        Send account approval SMS with credentials
        """
        try:
            message = f"TarTrack - {role.title()} Account Approved!\n\nLogin:\nEmail: {email}\nPassword: {password}\n\nDownload TarTrack app and login. Change password after first login."
            
            # Log the SMS content
            logger.warning(f"APPROVAL SMS - To: {phone}")
            print(f"\n=== SMS TO SEND ===")
            print(f"To: {phone}")
            print(f"Message: {message}")
            print(f"==================\n")
            
            # Try to send actual SMS
            sms_result = SMSService._send_twilio_sms(phone, message)
            if sms_result["success"]:
                return sms_result
            else:
                logger.warning(f"SMS sending failed: {sms_result.get('error')}, falling back to console log")
                return {"success": True, "method": "console_log"}
            
        except Exception as e:
            logger.error(f"Error preparing approval SMS: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def send_rejection_sms(phone, role, reason=None):
        """
        Send account rejection SMS
        """
        try:
            message = f"TarTrack - {role.title()} application not approved.\n\nReason: {reason or 'Did not meet requirements'}\n\nYou may reapply in the future."
            
            # Log the SMS content
            logger.warning(f"REJECTION SMS - To: {phone}")
            print(f"\n=== SMS TO SEND ===")
            print(f"To: {phone}")
            print(f"Message: {message}")
            print(f"==================\n")
            
            # Try to send actual SMS
            sms_result = SMSService._send_twilio_sms(phone, message)
            if sms_result["success"]:
                return sms_result
            else:
                logger.warning(f"SMS sending failed: {sms_result.get('error')}, falling back to console log")
                return {"success": True, "method": "console_log"}
            
        except Exception as e:
            logger.error(f"Error preparing rejection SMS: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _format_phone_number(phone):
        """
        Format phone number for Twilio (international format)
        """
        if not phone:
            return phone
            
        # Remove all non-digit characters
        clean_phone = ''.join(filter(str.isdigit, phone))
        
        # Handle Philippine numbers
        if clean_phone.startswith('09') and len(clean_phone) == 11:
            # Convert 09XXXXXXXXX to +639XXXXXXXXX
            return f"+63{clean_phone[1:]}"
        elif clean_phone.startswith('639') and len(clean_phone) == 12:
            # Already in 639 format, just add +
            return f"+{clean_phone}"
        elif clean_phone.startswith('63') and len(clean_phone) == 12:
            # Already in 63 format, just add +
            return f"+{clean_phone}"
        elif phone.startswith('+'):
            # Already has country code
            return phone
        else:
            # Return as-is for other formats
            return phone
    
    @staticmethod
    def _send_twilio_sms(to_phone, message):
        """
        Send SMS via Twilio
        """
        try:
            from twilio.rest import Client
            
            # Format phone number properly
            formatted_phone = SMSService._format_phone_number(to_phone)
            
            # Get Twilio credentials from settings/environment
            account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', os.getenv('TWILIO_ACCOUNT_SID'))
            auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', os.getenv('TWILIO_AUTH_TOKEN'))
            from_phone = getattr(settings, 'TWILIO_PHONE_NUMBER', os.getenv('TWILIO_PHONE_NUMBER'))
            
            # Debug credentials
            print(f"\n=== TWILIO DEBUG ===")
            print(f"Account SID: {account_sid[:10] if account_sid else 'None'}...")
            print(f"Auth Token: {auth_token[:10] if auth_token else 'None'}...")
            print(f"From Phone: {from_phone}")
            print(f"Original Phone: {to_phone}")
            print(f"Formatted Phone: {formatted_phone}")
            
            # Check if trying to send to same number (development issue)
            if formatted_phone.replace('+', '').replace('-', '').replace(' ', '') == from_phone.replace('+', '').replace('-', '').replace(' ', ''):
                print(f"WARNING: Cannot send SMS to same number as sender!")
                print(f"From: {from_phone} | To: {formatted_phone}")
                print(f"Use a different phone number for testing.")
                print(f"==================\n")
                return {"success": False, "error": "Cannot send SMS to same number as sender"}
            
            print(f"==================\n")
            
            if not account_sid or not auth_token or not from_phone:
                logger.warning("Twilio credentials not configured")
                print(f"Missing credentials - SID: {bool(account_sid)}, Token: {bool(auth_token)}, Phone: {bool(from_phone)}")
                return {"success": False, "error": "Twilio not configured"}
            
            # Send SMS
            client = Client(account_sid, auth_token)
            sms_message = client.messages.create(
                body=message,
                from_=from_phone,
                to=formatted_phone
            )
            
            logger.info(f"SMS sent successfully to {formatted_phone}, SID: {sms_message.sid}")
            print(f"SMS SUCCESS: SID {sms_message.sid}")
            return {"success": True, "method": "twilio", "sid": sms_message.sid}
            
        except Exception as e:
            logger.error(f"Twilio SMS failed: {e}")
            print(f"SMS ERROR: {e}")
            return {"success": False, "error": str(e)}