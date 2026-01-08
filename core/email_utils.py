"""
Email utility functions for TarTrack system
For now using console logging, can be extended with actual email service
"""
import logging
import os
from django.conf import settings

logger = logging.getLogger(__name__)

class EmailService:
    """
    Email service for sending notifications
    Currently using console logging - can be extended with actual email providers
    """
    
    @staticmethod
    def send_approval_email(email, role, generated_password=None):
        """
        Send account approval email with credentials using Gmail SMTP
        """
        try:
            from core.email_smtp import GmailSMTP
            return GmailSMTP.send_approval_email(email, role, generated_password)
            
        except Exception as e:
            logger.error(f"Error sending approval email: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def send_rejection_email(email, role, reason=None):
        """
        Send account rejection email
        """
        try:
            subject = f"TarTrack - {role.title()} Application Status"
            message = f"""Dear Applicant,

Thank you for your interest in joining TarTrack as a {role}.

After careful review, we regret to inform you that your application has not been approved at this time.

Reason: {reason or 'Application did not meet current requirements'}

You may reapply in the future if you believe you can address the concerns mentioned above.

Thank you for your understanding.

Best regards,
TarTrack Team"""
            
            # Log the email content for manual delivery
            logger.warning(f"REJECTION EMAIL - To: {email}")
            print(f"\n=== EMAIL TO SEND ===")
            print(f"To: {email}")
            print(f"Subject: {subject}")
            print(f"Message: {message}")
            print(f"====================\n")
            
            # For now, just log the email content
            return {"success": True, "method": "console_log"}
            
        except Exception as e:
            logger.error(f"Error preparing rejection email: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def send_verification_email(email, otp):
        """
        Send email verification OTP
        """
        try:
            subject = "TarTrack - Email Verification Code"
            message = f"""Dear User,

Your TarTrack email verification code is: {otp}

This code expires in 10 minutes. Please do not share this code with anyone.

If you did not request this code, please ignore this email.

Best regards,
TarTrack Team"""
            
            # Log the email content for manual delivery
            logger.warning(f"VERIFICATION EMAIL - To: {email}, OTP: {otp}")
            print(f"\n=== EMAIL VERIFICATION ===")
            print(f"To: {email}")
            print(f"Subject: {subject}")
            print(f"OTP: {otp}")
            print(f"Message: {message}")
            print(f"=========================\n")
            
            return {"success": True, "method": "console_log", "email": email}
            
        except Exception as e:
            logger.error(f"Error sending verification email: {e}")
            return {"success": False, "error": str(e)}