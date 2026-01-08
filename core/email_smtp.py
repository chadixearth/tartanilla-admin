"""
Gmail SMTP configuration for TarTrack email verification
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.conf import settings

logger = logging.getLogger(__name__)

class GmailSMTP:
    """Gmail SMTP service for sending emails"""
    
    # Gmail SMTP configuration
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    EMAIL = "richard.legaspi.1880@gmail.com"  # Replace with your Gmail
    APP_PASSWORD = "jhzc koat qxvw trej"  # Your app password
    
    @staticmethod
    def send_verification_email(to_email, verification_code):
        """Send verification code via Gmail SMTP"""
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = GmailSMTP.EMAIL
            msg['To'] = to_email
            msg['Subject'] = "TarTrack - Email Verification Code"
            
            body = f"""
Dear User,

Your TarTrack verification code is: {verification_code}

This code expires in 10 minutes. Please enter this code in the app to verify your email.

If you did not request this code, please ignore this email.

Best regards,
TarTrack Team
"""
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Connect to Gmail SMTP server
            server = smtplib.SMTP(GmailSMTP.SMTP_SERVER, GmailSMTP.SMTP_PORT)
            server.starttls()  # Enable encryption
            server.login(GmailSMTP.EMAIL, GmailSMTP.APP_PASSWORD)
            
            # Send email
            text = msg.as_string()
            server.sendmail(GmailSMTP.EMAIL, to_email, text)
            server.quit()
            
            logger.info(f"Verification email sent successfully to {to_email}")
            return {"success": True, "method": "gmail_smtp"}
            
        except Exception as e:
            logger.error(f"Failed to send verification email: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def send_approval_email(to_email, role, password=None):
        """Send approval notification via Gmail SMTP"""
        try:
            msg = MIMEMultipart()
            msg['From'] = GmailSMTP.EMAIL
            msg['To'] = to_email
            msg['Subject'] = f"TarTrack - {role.title()} Account Approved"
            
            if password:
                body = f"""
Dear {role.title()},

Congratulations! Your {role} application has been approved.

Your login credentials:
Email: {to_email}
Password: {password}

IMPORTANT: Please log in and change your password immediately for security.

Download the TarTrack mobile app and log in with these credentials.

Welcome to TarTrack!

Best regards,
TarTrack Team
"""
            else:
                body = f"""
Dear {role.title()},

Congratulations! Your {role} application has been approved.

You can now log in to the TarTrack mobile app using the credentials you provided during registration.

Welcome to TarTrack!

Best regards,
TarTrack Team
"""
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(GmailSMTP.SMTP_SERVER, GmailSMTP.SMTP_PORT)
            server.starttls()
            server.login(GmailSMTP.EMAIL, GmailSMTP.APP_PASSWORD)
            
            text = msg.as_string()
            server.sendmail(GmailSMTP.EMAIL, to_email, text)
            server.quit()
            
            logger.info(f"Approval email sent successfully to {to_email}")
            return {"success": True, "method": "gmail_smtp"}
            
        except Exception as e:
            logger.error(f"Failed to send approval email: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def send_password_reset_email(to_email, reset_code):
        """Send password reset code via Gmail SMTP"""
        try:
            msg = MIMEMultipart()
            msg['From'] = GmailSMTP.EMAIL
            msg['To'] = to_email
            msg['Subject'] = "TarTrack - Password Reset Code"
            
            body = f"""
Dear User,

You have requested to reset your TarTrack password.

Your password reset code is: {reset_code}

This code expires in 10 minutes. Please enter this code in the app to reset your password.

If you did not request this password reset, please ignore this email and your password will remain unchanged.

Best regards,
TarTrack Team
"""
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(GmailSMTP.SMTP_SERVER, GmailSMTP.SMTP_PORT)
            server.starttls()
            server.login(GmailSMTP.EMAIL, GmailSMTP.APP_PASSWORD)
            
            text = msg.as_string()
            server.sendmail(GmailSMTP.EMAIL, to_email, text)
            server.quit()
            
            logger.info(f"Password reset email sent successfully to {to_email}")
            return {"success": True, "method": "gmail_smtp"}
            
        except Exception as e:
            logger.error(f"Failed to send password reset email: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def send_email(to_email, subject, body):
        """Generic email sending method via Gmail SMTP"""
        try:
            msg = MIMEMultipart()
            msg['From'] = GmailSMTP.EMAIL
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(GmailSMTP.SMTP_SERVER, GmailSMTP.SMTP_PORT)
            server.starttls()
            server.login(GmailSMTP.EMAIL, GmailSMTP.APP_PASSWORD)
            
            text = msg.as_string()
            server.sendmail(GmailSMTP.EMAIL, to_email, text)
            server.quit()
            
            logger.info(f"Email sent successfully to {to_email}")
            return {"success": True, "method": "gmail_smtp"}
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return {"success": False, "error": str(e)}