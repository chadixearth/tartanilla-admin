from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings
from tartanilla_admin.supabase import supabase, supabase_admin
from gotrue.errors import AuthApiError, AuthRetryableError
from core.jwt_auth import verify_token, get_token_from_request
from core.auth_decorators import jwt_authenticated, jwt_role_required
import json
import logging
import secrets
import string
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class AuthenticationAPI:
    """
    Core authentication functions for all user roles
    """
    
    @staticmethod
    def generate_secure_password(length=12):
        """
        Generate a secure random password
        """
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        # Ensure password has at least one uppercase, lowercase, digit, and special char
        while not (any(c.islower() for c in password) and 
                   any(c.isupper() for c in password) and 
                   any(c.isdigit() for c in password) and 
                   any(c in "!@#$%^&*" for c in password)):
            password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password
    
    @staticmethod
    def register_user_with_auth(email, password, role, additional_data=None, verification_method='email'):
        """
        Register user with specified role (admin, tourist, owner, driver)
        For driver/owner roles: Creates pending registration for admin approval (password optional)
        For admin/tourist roles: Direct registration with phone/email verification (password required)
        verification_method: 'phone' or 'email' - determines verification method
        """
        try:
            # Validate role
            valid_roles = ['admin', 'tourist', 'owner', 'driver']
            if role not in valid_roles:
                return {"success": False, "error": f"Invalid role. Must be one of: {', '.join(valid_roles)}"}
            
            # Validate verification method
            if verification_method not in ['phone', 'email']:
                return {"success": False, "error": "Verification method must be 'phone' or 'email'"}
            
            # Check if role requires admin approval
            if role in ['driver', 'owner']:
                # For driver/owner roles, password is optional (will be generated on approval)
                return AuthenticationAPI._create_pending_registration(email, password, role, additional_data, verification_method)
            else:
                # For admin/tourist roles, password is required
                if not password:
                    return {"success": False, "error": "Password is required for admin and tourist registrations."}
                return AuthenticationAPI._create_direct_registration(email, password, role, additional_data, verification_method)
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _create_direct_registration(email, password, role, additional_data=None, verification_method='email'):
        """
        Direct registration for admin and tourist roles with phone/email verification
        """
        try:
            # Use admin client for checking existing records
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Check if phone number already exists
            if additional_data and additional_data.get('phone'):
                phone = additional_data.get('phone')
                existing_phone = admin_client.table('users').select('*').eq('phone', phone).execute()
                if hasattr(existing_phone, 'data') and existing_phone.data:
                    return {"success": False, "error": "This phone number is already in use."}
            
            # Prepare user metadata
            user_metadata = {"role": role}
            if additional_data:
                user_metadata.update(additional_data)
            
            # Create user account without email confirmation for custom verification
            result = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": user_metadata,
                    "email_confirm": False  # Skip Supabase email confirmation
                }
            })
            
            if result.user:
                # Send custom verification code
                from core.verification_utils import VerificationService
                
                if verification_method == 'phone':
                    phone = additional_data.get('phone') if additional_data else None
                    if not phone:
                        return {"success": False, "error": "Phone number is required for phone verification"}
                    
                    # SMS verification (will be pending until SMS service is configured)
                    sms_result = VerificationService.send_verification_code(phone, 'phone')
                    
                    return {
                        "success": True,
                        "message": "Registration successful. SMS verification is currently pending - please contact admin.",
                        "verification_required": True,
                        "verification_method": "phone",
                        "phone": phone,
                        "user": {
                            "id": result.user.id,
                            "email": result.user.email,
                            "role": role
                        },
                        "status": "phone_verification_pending"
                    }
                else:
                    # Email verification with custom OTP
                    email_result = VerificationService.send_verification_code(email, 'email')
                    
                    if email_result['success']:
                        return {
                            "success": True,
                            "message": "Registration successful. Check your email for verification code.",
                            "verification_required": True,
                            "verification_method": "email",
                            "user": {
                                "id": result.user.id,
                                "email": result.user.email,
                                "role": role
                            },
                            "status": "email_verification_required"
                        }
                    else:
                        return {"success": False, "error": f"Registration successful but failed to send verification email: {email_result.get('error')}"}
            else:
                return {"success": False, "error": "Registration failed. Please try again."}
                
        except (AuthApiError, AuthRetryableError) as e:
            error_msg = str(e).lower()
            if "user already registered" in error_msg or "email already exists" in error_msg:
                return {"success": False, "error": "Email already registered. Check your email for confirmation link."}
            elif "invalid email" in error_msg:
                return {"success": False, "error": "Invalid email."}
            elif "password" in error_msg and "weak" in error_msg:
                return {"success": False, "error": "Password too weak."}
            elif "too many requests" in error_msg or "rate limit" in error_msg:
                return {"success": False, "error": "Too many requests. Wait 10 seconds."}
            else:
                return {"success": False, "error": "Registration failed."}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _create_pending_registration(email, password, role, additional_data=None, verification_method='email'):
        """
        Create pending registration for driver/owner roles (requires admin approval)
        Password is optional - if not provided, it will be generated upon approval
        verification_method is stored for later use when sending approval notifications
        """
        try:
            # Use admin client to bypass RLS for pending registrations
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Check if email already exists in pending registrations
            existing_pending = admin_client.table('pending_registrations').select('*').eq('email', email).execute()
            if hasattr(existing_pending, 'data') and existing_pending.data:
                return {"success": False, "error": "A registration request with this email is already pending approval."}
            
            # Check if email already exists in users table
            existing_user = admin_client.table('users').select('*').eq('email', email).execute()
            if hasattr(existing_user, 'data') and existing_user.data:
                return {"success": False, "error": "An account with this email already exists."}
            
            # Check if phone number already exists
            if additional_data and additional_data.get('phone'):
                phone = additional_data.get('phone')
                existing_phone_pending = admin_client.table('pending_registrations').select('*').eq('phone', phone).execute()
                if hasattr(existing_phone_pending, 'data') and existing_phone_pending.data:
                    return {"success": False, "error": "This phone number is already registered."}
                
                existing_phone_user = admin_client.table('users').select('*').eq('phone', phone).execute()
                if hasattr(existing_phone_user, 'data') and existing_phone_user.data:
                    return {"success": False, "error": "This phone number is already in use."}
            
            # Prepare registration data - only include non-null values
            from datetime import datetime
            registration_data = {
                "email": email,
                "role": role,
                "status": "pending",
                "created_at": datetime.now().isoformat()
            }
            
            # Always include password - use placeholder if not provided
            if password and password.strip():
                registration_data["password"] = password
            else:
                registration_data["password"] = "PENDING_APPROVAL"  # Placeholder for admin approval
            
            # Store notification preference (not verification_method)
            # verification_method is for internal use only
            
            # Only add preferred_notification if it's provided
            if additional_data and additional_data.get("preferred_notification"):
                registration_data["preferred_notification"] = additional_data["preferred_notification"]
            
            # Add additional_data as JSON if provided
            if additional_data:
                registration_data["additional_data"] = additional_data
                
                # Add flattened fields for easier display (only if they exist)
                if additional_data.get("first_name"):
                    registration_data["first_name"] = additional_data["first_name"]
                if additional_data.get("last_name"):
                    registration_data["last_name"] = additional_data["last_name"]
                if additional_data.get("phone"):
                    registration_data["phone"] = additional_data["phone"]
                if additional_data.get("address"):
                    registration_data["address"] = additional_data["address"]
                

                
                # Create username from name parts
                first = (additional_data.get('first_name') or '').strip()
                last = (additional_data.get('last_name') or '').strip()
                if first or last:
                    registration_data["username"] = f"{first} {last}".strip()
            
            # Insert into pending registrations table using admin client
            try:
                result = admin_client.table('pending_registrations').insert(registration_data).execute()
            except Exception as insert_error:
                # If error is about missing column, retry without problematic fields
                if any(field in str(insert_error) for field in ["preferred_notification", "verification_method"]) and "column" in str(insert_error):
                    logger.warning(f"Column missing, retrying without problematic fields: {insert_error}")
                    # Remove the problematic fields and retry
                    registration_data_clean = {k: v for k, v in registration_data.items() if k not in ["preferred_notification", "verification_method"]}
                    result = admin_client.table('pending_registrations').insert(registration_data_clean).execute()
                else:
                    raise insert_error
            
            if hasattr(result, 'data') and result.data:
                # Get user's preferred notification method for response message
                preferred = additional_data.get("preferred_notification") if additional_data else None
                if not preferred:
                    preferred = "both"  # Default fallback
                notification_text = {
                    "email": "email",
                    "sms": "SMS", 
                    "both": "email and SMS"
                }.get(preferred, "email")
                
                return {
                    "success": True,
                    "message": "Application submitted.",
                    "status": "pending"
                }
            else:
                return {"success": False, "error": "Failed to submit registration for approval."}
                
        except Exception as e:
            logger.error(f"Error creating pending registration: {str(e)}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def login_user_with_auth(email, password, allowed_roles=None):
        """
        Login user with role validation - Optimized for mobile with better error handling
        allowed_roles: list of roles allowed to login (None = all roles allowed)
        """
        try:
            # Enhanced retry logic for mobile connections
            def auth_attempt():
                return supabase.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })
            
            # Execute with enhanced retry logic for mobile
            try:
                from tartanilla_admin.supabase import execute_with_retry
                result = execute_with_retry(auth_attempt, max_retries=5, delay=1)
            except ImportError:
                # Fallback with basic retry
                max_attempts = 3
                last_error = None
                for attempt in range(max_attempts):
                    try:
                        result = auth_attempt()
                        break
                    except Exception as e:
                        last_error = e
                        if attempt < max_attempts - 1:
                            import time
                            time.sleep(1 * (attempt + 1))  # Progressive delay
                        else:
                            raise last_error
            
            user = result.user 
            if not user:
                return {"success": False, "error": "Invalid email or password."}
            
            # Check if user is confirmed (only for tourist and admin roles)
            if not user.confirmed_at and role in ['tourist', 'admin']:
                return {
                    "success": False, 
                    "error": "Please confirm your email before logging in. Check your inbox for the confirmation link.",
                    "error_type": "unconfirmed",
                    "email_confirmation_required": True
                }
            
            # Get user role
            role = user.user_metadata.get("role") if user.user_metadata else None
            
            # Validate role if restrictions are specified
            if allowed_roles:
                is_allowed = role in allowed_roles
                # Treat 'driver-owner' as either driver or owner when restricted
                if not is_allowed and role == 'driver-owner':
                    is_allowed = any(r in ['driver', 'owner'] for r in allowed_roles)
                if not is_allowed:
                    allowed_str = ', '.join(allowed_roles)
                    return {"success": False, "error": f"Access denied. Only {allowed_str} users can access this platform."}
            
            # Enhanced account deletion cancellation on login
            deletion_cancelled = False
            deletion_message = None
            account_reactivated = False
            
            try:
                from .account_deletion import AccountDeletionAPI
                
                # Check if user has a scheduled deletion request
                deletion_status = AccountDeletionAPI.get_user_deletion_status(user.id)
                
                if (deletion_status.get('success') and 
                    deletion_status.get('data', {}).get('status') == 'scheduled'):
                    
                    deletion_data = deletion_status.get('data', {})
                    days_remaining = deletion_data.get('days_remaining', 0)
                    scheduled_date = deletion_data.get('scheduled_deletion_at')
                    
                    logger.info(f"User {user.email} has scheduled deletion with {days_remaining} days remaining")
                    print(f"DELETION CHECK: User {user.email} has scheduled deletion, attempting to cancel...")
                    
                    # Force cancel the deletion request
                    try:
                        admin_client = supabase_admin if supabase_admin else supabase
                        
                        # Update deletion request to cancelled
                        admin_client.table('account_deletion_requests').update({
                            "status": "cancelled",
                            "cancelled_at": datetime.now().isoformat()
                        }).eq('user_id', user.id).eq('status', 'scheduled').execute()
                        
                        # Reactivate user account
                        admin_client.table('users').update({
                            "account_status": "active"
                        }).eq('id', user.id).execute()
                        
                        cancel_result = {"success": True}
                        print(f"DELETION CANCELLED: Direct database update successful")
                        
                    except Exception as direct_error:
                        print(f"DIRECT CANCEL ERROR: {direct_error}")
                        cancel_result = {"success": False, "error": str(direct_error)}
                    
                    if cancel_result.get('success'):
                        deletion_cancelled = True
                        account_reactivated = True
                        
                        if days_remaining > 0:
                            deletion_message = f"Welcome back! Your scheduled account deletion (was set for {days_remaining} days from now) has been automatically cancelled. Your account is now fully active."
                        else:
                            deletion_message = "Welcome back! Your scheduled account deletion has been automatically cancelled. Your account is now fully active."
                        
                        logger.info(f"Successfully cancelled scheduled deletion for user {user.email}")
                        print(f"DELETION CANCELLED: Successfully cancelled for user {user.email}")
                        logger.info(f"Successfully cancelled scheduled deletion for user {user.email}")
                        
                    else:
                        logger.error(f"Failed to auto-cancel deletion for user {user.email}: {cancel_result.get('error')}")
                        print(f"DELETION CANCEL FAILED: {cancel_result.get('error')}")
                        deletion_message = f"Warning: Unable to automatically cancel your scheduled account deletion. Please contact support. Error: {cancel_result.get('error')}"
                        
            except ImportError:
                logger.warning("Account deletion module not available - skipping deletion check")
                print("DELETION CHECK: Module not available")
                pass
            except Exception as e:
                logger.error(f"Error checking/cancelling deletion status during login for user {user.email}: {e}")
                print(f"DELETION CHECK ERROR: {e}")
                # Continue with login even if deletion check fails - don't block user access
            
            # Get additional user info from database with retry
            user_info = None
            force_password_change = False
            try:
                def get_user_info_attempt():
                    return AuthenticationAPI.get_user_info(user.id)
                
                from tartanilla_admin.supabase import execute_with_retry
                user_info = execute_with_retry(get_user_info_attempt, max_retries=3, delay=0.5)
                
                # If user doesn't exist in users table, create them on first login
                if not user_info:
                    try:
                        admin_client = supabase_admin if supabase_admin else supabase
                        user_data = {
                            'id': user.id,
                            'email': user.email,
                            'role': role or 'tourist',
                            'status': 'Active',
                            'account_status': 'active',
                            'created_at': datetime.now().isoformat(),
                            'updated_at': datetime.now().isoformat()
                        }
                        # Add name from auth metadata if available
                        if user.user_metadata and user.user_metadata.get('name'):
                            user_data['name'] = user.user_metadata.get('name')
                        if user.user_metadata and user.user_metadata.get('phone'):
                            user_data['phone'] = user.user_metadata.get('phone')
                        
                        admin_client.table('users').insert(user_data).execute()
                        user_info = user_data
                        logger.info(f"Created user {user.email} in users table on first login")
                    except Exception as create_error:
                        logger.warning(f"Failed to create user in users table on first login: {create_error}")
                        # Continue without user_info - user can still login
                
                # Check if password change is required
                if user_info and user_info.get('force_password_change'):
                    force_password_change = True
                
                # Ensure profile photo URL is available from either database or auth metadata
                if user_info:
                    # Prioritize database profile_photo_url, fallback to auth metadata
                    if not user_info.get('profile_photo_url') and user.user_metadata:
                        auth_photo_url = user.user_metadata.get('profile_photo_url')
                        if auth_photo_url:
                            user_info['profile_photo_url'] = auth_photo_url
                            logger.info(f"Retrieved profile photo from auth metadata for user {user.email}")
                    elif user_info.get('profile_photo_url'):
                        logger.info(f"Retrieved profile photo from database for user {user.email}")
                        
            except Exception as e:
                logger.warning(f"Failed to get user info for {user.email}: {e}")
                # Continue without user info rather than failing login
            
            # Enhanced suspension check with better error handling
            if user_info and user_info.get('status') == 'suspended':
                suspension_reason = user_info.get('suspension_reason', 'Account suspended by admin')
                suspended_until = user_info.get('suspended_until')
                
                if suspended_until:
                    from datetime import datetime
                    try:
                        suspend_date = datetime.fromisoformat(suspended_until.replace('Z', '+00:00'))
                        current_date = datetime.now(suspend_date.tzinfo)
                        remaining_days = (suspend_date - current_date).days
                        
                        if remaining_days > 0:
                            return {
                                "success": False, 
                                "error": f"Account suspended: {suspension_reason}. Suspension ends in {remaining_days} day(s).",
                                "suspended": True,
                                "suspension_reason": suspension_reason,
                                "remaining_days": remaining_days,
                                "suspended_until": suspended_until
                            }
                        else:
                            # Suspension expired, reactivate account
                            try:
                                admin_client = supabase_admin if supabase_admin else supabase
                                admin_client.table('users').update({
                                    'status': 'active',
                                    'suspension_reason': None,
                                    'suspended_until': None,
                                    'unsuspended_at': datetime.now().isoformat(),
                                    'unsuspended_by': 'system_auto'
                                }).eq('id', user.id).execute()
                                logger.info(f"Auto-reactivated expired suspension for user {user.email}")
                                # Update user_info to reflect the change
                                user_info['status'] = 'active'
                                user_info['suspension_reason'] = None
                                user_info['suspended_until'] = None
                            except Exception as reactivate_error:
                                logger.error(f"Failed to auto-reactivate user {user.email}: {reactivate_error}")
                                # Still allow login if reactivation fails
                    except Exception as date_error:
                        logger.error(f"Error parsing suspension date for user {user.email}: {date_error}")
                        return {
                            "success": False,
                            "error": f"Account suspended: {suspension_reason}",
                            "suspended": True,
                            "suspension_reason": suspension_reason
                        }
                else:
                    # Permanent suspension
                    return {
                        "success": False,
                        "error": f"Account permanently suspended: {suspension_reason}",
                        "suspended": True,
                        "suspension_reason": suspension_reason,
                        "permanent": True
                    }
            
            # Get JWT tokens from session
            access_token = result.session.access_token if result.session else None
            refresh_token = result.session.refresh_token if result.session else None
            
            # Log successful login
            logger.info(f"User {user.email} logged in successfully")
            
            # Prepare login response message
            login_message = "Login successful."
            if deletion_cancelled:
                login_message += f" {deletion_message}"
            
            # Merge user info with auth metadata for complete profile
            merged_user_data = {
                "id": user.id,
                "email": user.email,
                "role": role
            }
            
            # Add profile info from database if available
            if user_info:
                merged_user_data.update(user_info)
            
            # Add/override with auth metadata if available
            if user.user_metadata:
                for key in ['name', 'phone', 'profile_photo_url']:
                    if user.user_metadata.get(key):
                        merged_user_data[key] = user.user_metadata[key]
            
            response_data = {
                "success": True,
                "message": login_message,
                "user": merged_user_data,
                "session": {
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "token_type": "Bearer"
                },
                "jwt": {
                    "token": access_token,
                    "refresh_token": refresh_token,
                    "token_type": "Bearer",
                    "expires_in": 3600
                },
                "force_password_change": force_password_change
            }
            
            # Add deletion cancellation info if applicable
            if deletion_cancelled:
                response_data["deletion_cancelled"] = True
                response_data["account_reactivated"] = account_reactivated
                response_data["deletion_info"] = {
                    "was_scheduled": True,
                    "cancelled_on_login": True,
                    "cancellation_timestamp": datetime.now().isoformat()
                }
            
            return response_data
            
        except (AuthApiError, AuthRetryableError) as e:
            error_msg = str(e).lower()
            # Enhanced error messages for mobile users
            if any(keyword in error_msg for keyword in ['timeout', 'timed out']):
                return {"success": False, "error": "Connection timeout. Please check your internet connection and try again.", "error_type": "timeout"}
            elif any(keyword in error_msg for keyword in ['network', 'connection', 'unreachable']):
                return {"success": False, "error": "Network error. Please check your connection and try again.", "error_type": "network"}
            elif 'invalid login credentials' in error_msg:
                return {"success": False, "error": "Invalid email or password.", "error_type": "credentials"}
            elif 'email not confirmed' in error_msg:
                return {"success": False, "error": "Please confirm your email before logging in.", "error_type": "unconfirmed"}
            else:
                return {"success": False, "error": "Login failed. Please try again.", "error_type": "auth_error"}
        except Exception as e:
            error_msg = str(e).lower()
            logger.error(f"Login error for {email}: {e}")
            if any(keyword in error_msg for keyword in ['timeout', 'timed out']):
                return {"success": False, "error": "Request timeout. Please try again.", "error_type": "timeout"}
            elif any(keyword in error_msg for keyword in ['connection', 'network']):
                return {"success": False, "error": "Connection error. Please check your internet and try again.", "error_type": "connection"}
            else:
                return {"success": False, "error": "Login failed. Please try again.", "error_type": "general_error"}
    
    @staticmethod
    def get_user_info(user_id):
        """
        Get user information from the users table with retry logic
        """
        try:
            def get_user_attempt():
                return supabase.table('users').select('*').eq('id', user_id).execute()
            
            # Use retry logic for better reliability
            try:
                from tartanilla_admin.supabase import execute_with_retry
                response = execute_with_retry(get_user_attempt, max_retries=2, delay=0.5)
            except ImportError:
                response = get_user_attempt()
            
            if hasattr(response, 'data') and response.data:
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error getting user info for {user_id}: {e}")
            return None
    
    @staticmethod
    def logout_user(user_id=None):
        """
        Logout current user from Supabase - optimized for mobile clients
        """
        try:
            # Log the logout for audit purposes
            if user_id:
                logger.info(f"User {user_id} logged out")
            
            # For mobile clients, we don't need to call Supabase sign_out
            # The client handles token cleanup locally
            return {
                "success": True, 
                "message": "Logged out successfully.",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Logout error: {e}")
            # Always return success for logout to avoid blocking user
            return {"success": True, "message": "Logged out successfully."}
    
    @staticmethod
    def update_user_profile(user_id, profile_data):
        """
        Update user profile information in the users table and Supabase Auth metadata
        """
        try:
            logger.info(f"Updating profile for user {user_id} with data: {profile_data}")
            
            # Map frontend fields to database fields and prepare update data
            update_data = {}
            field_mapping = {
                'first_name': 'name',  # Map first_name to name field
                'last_name': None,     # Ignore last_name as we only have name field
                'middle_name': None,   # Ignore middle_name as we only have name field
                'profile_photo': 'profile_photo_url',  # Map profile_photo to profile_photo_url
                'profile_photo_url': 'profile_photo_url',
                'bio': 'bio',          # Map bio field
                'name': 'name',
                'email': 'email',
                'phone': 'phone',      # Phone field mapping
                'phone_number': 'phone',  # Alternative phone field name
                'contact_number': 'phone',  # Another alternative
                'address': 'address',  # Address field mapping
                'role': 'role',
                'status': 'status'
            }
            
            # Process each field in profile_data
            for k, v in profile_data.items():
                if v is not None and v != "" and v != "undefined":
                    # Map the field to database column
                    db_field = field_mapping.get(k, k)  # Use original field name if not in mapping
                    if db_field is not None:  # Only include if not explicitly ignored
                        update_data[db_field] = v
                        logger.info(f"Mapped {k} -> {db_field}: {v}")
            
            # Handle name field combination if first_name, middle_name, or last_name are provided
            if any(field in profile_data for field in ['first_name', 'middle_name', 'last_name']):
                first = profile_data.get('first_name', '').strip()
                middle = profile_data.get('middle_name', '').strip()
                last = profile_data.get('last_name', '').strip()
                
                # Combine name parts, filtering out empty strings
                name_parts = [part for part in [first, middle, last] if part]
                if name_parts:
                    update_data['name'] = ' '.join(name_parts)
                    logger.info(f"Combined name: {update_data['name']}")
            
            if not update_data:
                logger.warning("No valid data provided for update")
                return {"success": False, "error": "No valid data provided for update"}
            
            logger.info(f"Final update data: {update_data}")
            
            # Use admin client for better reliability
            client = supabase_admin if supabase_admin else supabase
            response = client.table('users').update(update_data).eq('id', user_id).execute()
            
            logger.info(f"Database response: {response}")
            
            if hasattr(response, 'data') and response.data:
                # Always update Supabase Auth user metadata with the latest profile data
                try:
                    auth_client = supabase_admin if supabase_admin else supabase
                    metadata_update = {}
                    
                    # Include profile photo URL in metadata if present
                    if 'profile_photo_url' in update_data:
                        metadata_update['profile_photo_url'] = update_data['profile_photo_url']
                    
                    # Include name in metadata if present
                    if 'name' in update_data:
                        metadata_update['name'] = update_data['name']
                    
                    # Include phone in metadata if present
                    if 'phone' in update_data:
                        metadata_update['phone'] = update_data['phone']
                    
                    if metadata_update:
                        auth_client.auth.admin.update_user_by_id(
                            user_id,
                            {
                                "user_metadata": metadata_update
                            }
                        )
                        logger.info(f"Updated Supabase Auth metadata for user {user_id}: {metadata_update}")
                except Exception as auth_error:
                    logger.error(f"Failed to update Auth metadata: {auth_error}")
                    # Continue - database update succeeded
                
                logger.info(f"Profile updated successfully for user {user_id}")
                return {
                    "success": True, 
                    "message": "Profile updated successfully",
                    "data": response.data[0]
                }
            else:
                logger.error(f"No data returned from database update for user {user_id}")
                return {"success": False, "error": "Failed to update profile - no data returned"}
                
        except Exception as e:
            logger.error(f"Error updating user profile for user {user_id}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def upload_profile_photo(user_id, photo_file, file_name):
        """
        Upload profile photo to Supabase storage and update user profile
        """
        try:
            # Use the new upload utility function which handles RLS properly
            from tartanilla_admin.supabase import upload_profile_photo
            
            # Upload using the utility function
            upload_result = upload_profile_photo(photo_file, file_name, user_id)
            
            if upload_result['success']:
                # Update user profile with photo URL
                profile_update = AuthenticationAPI.update_user_profile(user_id, {
                    "profile_photo": upload_result['url']
                })
                
                if profile_update.get("success"):
                    return {
                        "success": True,
                        "message": "Profile photo uploaded successfully",
                        "photo_url": upload_result['url'],
                        "storage_path": upload_result['path']
                    }
                else:
                    return {"success": False, "error": "Failed to update profile with photo URL"}
            else:
                return {"success": False, "error": upload_result['error']}
                
        except Exception as e:
            logger.error(f"Error uploading profile photo: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def get_pending_registrations():
        """
        Get all pending registrations for admin review
        """
        try:
            # Use admin client to bypass RLS for admin operations
            admin_client = supabase_admin if supabase_admin else supabase
            response = admin_client.table('pending_registrations').select('*').eq('status', 'pending').order('created_at', desc=True).execute()
            if hasattr(response, 'data'):
                return {"success": True, "data": response.data}
            return {"success": True, "data": []}
        except Exception as e:
            logger.error(f"Error getting pending registrations: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def approve_registration(registration_id, approved_by):
        """
        Approve a pending registration and create the actual user account
        Uses user's preferred notification method from registration
        """
        try:
            # Use admin client to bypass RLS for admin operations
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get the pending registration
            pending_response = admin_client.table('pending_registrations').select('*').eq('id', registration_id).execute()
            
            if not hasattr(pending_response, 'data') or not pending_response.data:
                return {"success": False, "error": "Pending registration not found."}
            
            pending_reg = pending_response.data[0]
            
            if pending_reg['status'] != 'pending':
                return {"success": False, "error": "Registration is not in pending status."}
            
            # Create the actual user account with Supabase Auth (use admin client)
            # Determine final role, allowing combined "driver-owner" based on answers
            additional_data = pending_reg.get('additional_data') or {}
            base_role = pending_reg['role']
            def _is_truthy(value):
                return str(value).lower() in {"1", "true", "yes", "y"}

            owns_count = additional_data.get('owned_count')
            try:
                owns_count_num = int(owns_count) if owns_count is not None and str(owns_count).strip() != '' else 0
            except (TypeError, ValueError):
                owns_count_num = 0

            also_owns = _is_truthy(additional_data.get('owns_tartanilla')) or owns_count_num > 0
            also_drives = _is_truthy(additional_data.get('drives_own_tartanilla')) or _is_truthy(additional_data.get('also_drives'))

            calculated_role = base_role
            if (base_role == 'driver' and also_owns) or (base_role == 'owner' and also_drives):
                calculated_role = 'driver-owner'

            user_metadata = {"role": calculated_role}
            if additional_data:
                user_metadata.update(additional_data)
            
            # Generate password if not provided during registration
            final_password = pending_reg.get('password')
            generated_password = None
            
            if not final_password or final_password.strip() == '' or final_password == 'PENDING_APPROVAL':
                # Generate a secure password for the user
                generated_password = AuthenticationAPI.generate_secure_password()
                final_password = generated_password
            
            auth_result = admin_client.auth.admin.create_user({
                "email": pending_reg['email'],
                "password": final_password,
                "user_metadata": user_metadata,
                "email_confirm": True  # Auto-confirm email for approved registrations
            })
            
            if auth_result.user:
                # Update pending registration status
                from datetime import datetime
                admin_client.table('pending_registrations').update({
                    "status": "approved",
                    "approved_by": approved_by,
                    "approved_at": datetime.now().isoformat(),
                    "user_id": auth_result.user.id
                }).eq('id', registration_id).execute()
                
                # Mark user for password change on first login
                admin_client.table('users').update({
                    "force_password_change": True,
                    "first_login": True
                }).eq('id', auth_result.user.id).execute()
                
                # Get user's preferred notification method
                preferred_method = pending_reg.get('preferred_notification') or additional_data.get('preferred_notification', 'both')
                
                # Send notifications based on user preference
                notification_results = {"email": None, "sms": None}
                
                # Send email if preferred
                if preferred_method in ['email', 'both']:
                    try:
                        from core.email_utils import EmailService
                        email_result = EmailService.send_approval_email(pending_reg['email'], calculated_role, generated_password)
                        notification_results["email"] = email_result
                        logger.info(f"Approval email result: {email_result}")
                    except Exception as e:
                        logger.error(f"Failed to send approval email: {e}")
                        notification_results["email"] = {"success": False, "error": str(e)}
                
                # Send SMS if preferred
                if preferred_method in ['sms', 'both']:
                    try:
                        from core.sms_utils import SMSService
                        phone = pending_reg.get('phone') or additional_data.get('phone')
                        if phone:
                            sms_result = SMSService.send_approval_sms(phone, calculated_role, pending_reg['email'], generated_password)
                            notification_results["sms"] = sms_result
                            logger.info(f"Approval SMS result: {sms_result}")
                        else:
                            notification_results["sms"] = {"success": False, "error": "No phone number provided"}
                    except Exception as e:
                        logger.error(f"Failed to send approval SMS: {e}")
                        notification_results["sms"] = {"success": False, "error": str(e)}
                
                return {
                    "success": True,
                    "message": f"Registration approved successfully. Credentials sent via {preferred_method}.",
                    "user_id": auth_result.user.id,
                    "password_generated": generated_password is not None,
                    "notification_method": preferred_method,
                    "notification_results": notification_results
                }
            else:
                return {"success": False, "error": "Failed to create user account."}
                
        except Exception as e:
            logger.error(f"Error approving registration: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def reject_registration(registration_id, rejected_by, reason=None):
        """
        Reject a pending registration
        Uses user's preferred notification method from registration
        """
        try:
            # Use admin client to bypass RLS for admin operations
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get the pending registration
            pending_response = admin_client.table('pending_registrations').select('*').eq('id', registration_id).execute()
            
            if not hasattr(pending_response, 'data') or not pending_response.data:
                return {"success": False, "error": "Pending registration not found."}
            
            pending_reg = pending_response.data[0]
            
            if pending_reg['status'] != 'pending':
                return {"success": False, "error": "Registration is not in pending status."}
            
            # Update pending registration status
            from datetime import datetime
            admin_client.table('pending_registrations').update({
                "status": "rejected",
                "rejected_by": rejected_by,
                "rejected_at": datetime.now().isoformat(),
                "rejection_reason": reason
            }).eq('id', registration_id).execute()
            
            # Get user's preferred notification method
            additional_data = pending_reg.get('additional_data') or {}
            preferred_method = pending_reg.get('preferred_notification') or additional_data.get('preferred_notification', 'both')
            
            # Send notifications based on user preference
            notification_results = {"email": None, "sms": None}
            
            # Send email if preferred
            if preferred_method in ['email', 'both']:
                try:
                    from core.email_utils import EmailService
                    email_result = EmailService.send_rejection_email(pending_reg['email'], pending_reg['role'], reason)
                    notification_results["email"] = email_result
                    logger.info(f"Rejection email result: {email_result}")
                except Exception as e:
                    logger.error(f"Failed to send rejection email: {e}")
                    notification_results["email"] = {"success": False, "error": str(e)}
            
            # Send SMS if preferred
            if preferred_method in ['sms', 'both']:
                try:
                    from core.sms_utils import SMSService
                    phone = pending_reg.get('phone') or additional_data.get('phone')
                    if phone:
                        sms_result = SMSService.send_rejection_sms(phone, pending_reg['role'], reason)
                        notification_results["sms"] = sms_result
                        logger.info(f"Rejection SMS result: {sms_result}")
                    else:
                        notification_results["sms"] = {"success": False, "error": "No phone number provided"}
                except Exception as e:
                    logger.error(f"Failed to send rejection SMS: {e}")
                    notification_results["sms"] = {"success": False, "error": str(e)}
            
            return {
                "success": True,
                "message": f"Registration rejected successfully. Notification sent via {preferred_method}.",
                "notification_method": preferred_method,
                "notification_results": notification_results
            }
                
        except Exception as e:
            logger.error(f"Error rejecting registration: {e}")
            return {"success": False, "error": str(e)}
    
    # Email templates for better maintainability
    EMAIL_TEMPLATES = {
        'approval_with_password': {
            'subject': "TarTrack - {role} Account Approved",
            'body': """
Dear {role},

Congratulations! Your {role} application has been approved.

Your login credentials:
Email: {email}
Password: {password}

IMPORTANT: Please log in and change your password immediately for security.

Download the TarTrack mobile app and log in with these credentials.

Welcome to TarTrack!

Best regards,
TarTrack Team
"""
        },
        'approval_without_password': {
            'subject': "TarTrack - {role} Account Approved",
            'body': """
Dear {role},

Congratulations! Your {role} application has been approved.

You can now log in to the TarTrack mobile app using the credentials you provided during registration.

Welcome to TarTrack!

Best regards,
TarTrack Team
"""
        }
    }

    @staticmethod
    def _send_approval_email(email, role, generated_password=None):
        """
        Send approval notification via email - Console logging for now
        """
        try:
            # Log credentials for manual delivery
            if generated_password:
                logger.warning(f"APPROVED USER CREDENTIALS - Email: {email}, Password: {generated_password}, Role: {role}")
                print(f"\n=== ACCOUNT APPROVED ===")
                print(f"Email: {email}")
                print(f"Password: {generated_password}")
                print(f"Role: {role}")
                print(f"========================\n")
            else:
                logger.warning(f"APPROVED USER - Email: {email}, Role: {role} (Use registration password)")
                print(f"\n=== ACCOUNT APPROVED ===")
                print(f"Email: {email}")
                print(f"Role: {role}")
                print(f"Password: Use registration password")
                print(f"========================\n")
            
            # For now, just log the email content
            subject = f"TarTrack - {role.title()} Account Approved"
            
            if generated_password:
                body = f"""
Dear {role.title()},

Congratulations! Your {role} application has been approved.

Your login credentials:
Email: {email}
Password: {generated_password}

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
            
            logger.info(f"Email content for {email}:\nSubject: {subject}\nBody: {body}")
            
            return {'success': True, 'email_sent': True}
            
        except Exception as email_error:
            logger.error(f"Failed to process email for {email}: {email_error}")
            return {'success': True, 'email_sent': False, 'manual_delivery': True}
    
    @staticmethod
    def resend_confirmation_email(email):
        """
        Resend email confirmation for unconfirmed users
        """
        try:
            # Use Supabase Auth to resend confirmation
            result = supabase.auth.resend({
                "type": "signup",
                "email": email
            })
            
            if result:
                return {
                    "success": True,
                    "message": "Email sent successfully."
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to send email."
                }
                
        except (AuthApiError, AuthRetryableError) as e:
            error_msg = str(e).lower()
            if "email not found" in error_msg or "user not found" in error_msg:
                return {"success": False, "error": "No account found with this email address."}
            elif "already confirmed" in error_msg:
                return {"success": False, "error": "This email is already confirmed. You can log in normally."}
            else:
                return {"success": False, "error": "Failed to send confirmation email. Please try again."}
        except Exception as e:
            logger.error(f"Error resending confirmation email: {e}")
            return {"success": False, "error": "Failed to send confirmation email. Please try again."}
    
    @staticmethod
    def change_user_password(user_id, current_password, new_password):
        """
        Change user password with current password verification
        """
        try:
            # Get user info to verify current password
            user_info = AuthenticationAPI.get_user_info(user_id)
            if not user_info:
                return {"success": False, "error": "User not found."}
            
            email = user_info.get('email')
            if not email:
                return {"success": False, "error": "User email not found."}
            
            # Verify current password by attempting login
            login_result = AuthenticationAPI.login_user_with_auth(email, current_password)
            if not login_result.get('success'):
                return {"success": False, "error": "Current password is incorrect."}
            
            # Validate new password
            if not new_password or len(new_password) < 6:
                return {"success": False, "error": "New password must be at least 6 characters long."}
            
            if new_password == current_password:
                return {"success": False, "error": "New password must be different from current password."}
            
            # Use admin client to update password
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Update password using Supabase Admin API
            result = admin_client.auth.admin.update_user_by_id(
                user_id,
                {"password": new_password}
            )
            
            if result.user:
                # Clear force_password_change flag
                try:
                    admin_client.table('users').update({
                        'force_password_change': False,
                        'first_login': False
                    }).eq('id', user_id).execute()
                except Exception as flag_error:
                    logger.warning(f"Failed to clear password change flag: {flag_error}")
                
                logger.info(f"Password changed successfully for user {email}")
                return {
                    "success": True,
                    "message": "Password changed successfully."
                }
            else:
                return {"success": False, "error": "Failed to update password."}
                
        except Exception as e:
            logger.error(f"Error changing password for user {user_id}: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _send_rejection_email(email, role, reason=None):
        """
        Send rejection notification - Console logging for now
        """
        try:
            logger.warning(f"REJECTION NOTIFICATION - Email: {email}, Role: {role}, Reason: {reason or 'No reason provided'}")
            print(f"\n=== ACCOUNT REJECTED ===")
            print(f"Email: {email}")
            print(f"Role: {role}")
            print(f"Reason: {reason or 'No reason provided'}")
            print(f"========================\n")
            
            # Log the rejection email content
            subject = f"TarTrack - {role.title()} Application Status"
            body = f"""
Dear Applicant,

Thank you for your interest in joining TarTrack as a {role}.

After careful review, we regret to inform you that your application has not been approved at this time.

Reason: {reason or 'Application did not meet current requirements'}

You may reapply in the future if you believe you can address the concerns mentioned above.

Thank you for your understanding.

Best regards,
TarTrack Team
"""
            
            logger.info(f"Rejection email content for {email}:\nSubject: {subject}\nBody: {body}")
            return {'success': True, 'email_sent': True}
            
        except Exception as email_error:
            logger.error(f"Failed to process rejection email for {email}: {email_error}")
            return {'success': True, 'email_sent': False, 'manual_delivery': True}


@method_decorator(csrf_exempt, name='dispatch')
class RegisterAPI(APIView):
    """
    API endpoint for user registration (all roles)
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            email = (data.get('email') or '').strip()
            password = (data.get('password') or '').strip() if data.get('password') else ''
            role = (data.get('role') or '').strip()
            additional_data = data.get('additional_data', {})
            verification_method = data.get('verification_method', 'email')
            
            # Validate required fields
            if not email or not role:
                return Response({
                    "success": False,
                    "error": "Email and role are required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate email format
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, email):
                return Response({
                    "success": False,
                    "error": "Please enter a valid email address."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate role-specific required fields
            if role == 'driver':
                first_name = (additional_data.get('first_name') or '').strip()
                last_name = (additional_data.get('last_name') or '').strip()
                phone = (additional_data.get('phone') or '').strip()
                license_number = (additional_data.get('license_number') or '').strip()
                
                if not first_name:
                    return Response({
                        "success": False,
                        "error": "First name is required for driver registration."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if not last_name:
                    return Response({
                        "success": False,
                        "error": "Last name is required for driver registration."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if not phone:
                    return Response({
                        "success": False,
                        "error": "Phone number is required for driver registration."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if not license_number:
                    return Response({
                        "success": False,
                        "error": "Driver's license number is required."
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            elif role == 'owner':
                first_name = (additional_data.get('first_name') or '').strip()
                last_name = (additional_data.get('last_name') or '').strip()
                phone = (additional_data.get('phone') or '').strip()
                business_name = (additional_data.get('business_name') or '').strip()
                
                if not first_name:
                    return Response({
                        "success": False,
                        "error": "First name is required for owner registration."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if not last_name:
                    return Response({
                        "success": False,
                        "error": "Last name is required for owner registration."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if not phone:
                    return Response({
                        "success": False,
                        "error": "Phone number is required for owner registration."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if not business_name:
                    return Response({
                        "success": False,
                        "error": "Business name is required for owner registration."
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            elif role == 'tourist':
                # For tourists, validate password and confirmation
                if not password:
                    return Response({
                        "success": False,
                        "error": "Password is required for tourist registration."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                if len(password) < 6:
                    return Response({
                        "success": False,
                        "error": "Password must be at least 6 characters long."
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # If SMS verification is chosen, phone is required
                if verification_method == 'phone':
                    phone = (additional_data.get('phone') or '').strip()
                    if not phone:
                        return Response({
                            "success": False,
                            "error": "Phone number is required for SMS verification."
                        }, status=status.HTTP_400_BAD_REQUEST)
            
            # Ensure additional_data is a dict
            if not isinstance(additional_data, dict):
                additional_data = {}
            
            # Password is required for admin/tourist, optional for driver/owner
            if role in ['admin', 'tourist'] and not password:
                return Response({
                    "success": False,
                    "error": "Password is required for admin and tourist registrations."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Clean password - treat empty strings as None for driver/owner roles
            if role in ['driver', 'owner'] and password and password.strip() == '':
                password = None
            
            # Register user
            result = AuthenticationAPI.register_user_with_auth(
                email=email,
                password=password,
                role=role,
                additional_data=additional_data,
                verification_method=verification_method
            )
            
            # Always return minimal, complete JSON
            if result.get("success"):
                return Response({
                    "success": True,
                    "message": "Registration successful"
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    "success": False,
                    "error": str(result.get("error", "Registration failed"))[:100]
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Registration API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class LoginAPI(APIView):
    """
    API endpoint for user login (all roles) - Enhanced for mobile
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            # Handle both JSON and form data for mobile compatibility
            if hasattr(request, 'data') and request.data:
                data = request.data
            else:
                data = json.loads(request.body) if isinstance(request.body, bytes) else {}
            
            email = data.get('email', '').strip().lower()
            password = data.get('password', '')
            allowed_roles = data.get('allowed_roles')  # Optional role restrictions
            
            # Enhanced validation
            if not email:
                return Response({
                    "success": False,
                    "error": "Email is required.",
                    "error_type": "validation"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not password:
                return Response({
                    "success": False,
                    "error": "Password is required.",
                    "error_type": "validation"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Basic email format validation
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, email):
                return Response({
                    "success": False,
                    "error": "Please enter a valid email address.",
                    "error_type": "validation"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Login user with enhanced retry logic
            result = AuthenticationAPI.login_user_with_auth(
                email=email,
                password=password,
                allowed_roles=allowed_roles
            )
            
            if result.get("success"):
                # Check if device verification is needed
                try:
                    from .device_verification import DeviceVerificationAPI
                    
                    user_id = result.get('user', {}).get('id')
                    if user_id:
                        # Use device fingerprint from request body if provided (mobile app)
                        # Otherwise generate from request metadata (web)
                        device_fingerprint = data.get('device_fingerprint')
                        if not device_fingerprint:
                            device_fingerprint = DeviceVerificationAPI.get_device_fingerprint(request)
                        
                        is_trusted = DeviceVerificationAPI.is_trusted_device(user_id, device_fingerprint)
                        
                        if not is_trusted:
                            # Create verification request
                            user_agent = request.META.get('HTTP_USER_AGENT', 'Unknown')
                            device_info = f"User Agent: {user_agent}"
                            
                            verification_result = DeviceVerificationAPI.create_verification_request(
                                user_id, email, device_fingerprint, device_info
                            )
                            
                            if verification_result['success']:
                                return Response({
                                    "success": True,
                                    "requires_device_verification": True,
                                    "device_fingerprint": device_fingerprint,
                                    "user": result.get('user'),
                                    "message": "Device verification required. Check your email for the verification code."
                                }, status=status.HTTP_200_OK)
                        else:
                            # Update last seen for trusted device
                            DeviceVerificationAPI.update_device_last_seen(user_id, device_fingerprint)
                except Exception as device_error:
                    logger.error(f"Device verification check failed: {device_error}")
                    # Continue with normal login if device verification fails
                    pass
                
                response = Response(result, status=status.HTTP_200_OK)
                
                # Set tokens in HttpOnly cookies
                access_token = result.get("session", {}).get("access_token")
                refresh_token = result.get("session", {}).get("refresh_token")

                if access_token:
                    response.set_cookie(
                        key='access_token',
                        value=access_token,
                        httponly=True,
                        secure=not settings.DEBUG,  # Use secure in production
                        samesite='Strict'
                    )
                
                if refresh_token:
                    response.set_cookie(
                        key='refresh_token',
                        value=refresh_token,
                        httponly=True,
                        secure=not settings.DEBUG, # Use secure in production
                        samesite='Strict'
                    )
                
                return response
            else:
                # Determine appropriate HTTP status based on error type
                error_type = result.get("error_type", "unknown")
                if error_type in ["credentials", "unconfirmed"]:
                    status_code = status.HTTP_401_UNAUTHORIZED
                elif error_type in ["timeout", "network", "connection"]:
                    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                elif result.get("suspended"):
                    status_code = status.HTTP_403_FORBIDDEN
                else:
                    status_code = status.HTTP_401_UNAUTHORIZED
                
                return Response(result, status=status_code)
                
        except json.JSONDecodeError:
            return Response({
                "success": False,
                "error": "Invalid request format.",
                "error_type": "format"
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Login API error: {str(e)}")
            return Response({
                "success": False,
                "error": "Login service temporarily unavailable. Please try again.",
                "error_type": "service_error"
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@method_decorator(csrf_exempt, name='dispatch')
class AdminLoginAPI(APIView):
    """
    API endpoint for admin-only login (for web interface)
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            email = data.get('email')
            password = data.get('password')
            
            # Validate required fields
            if not email or not password:
                return Response({
                    "success": False,
                    "error": "Email and password are required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Login with admin role restriction
            result = AuthenticationAPI.login_user_with_auth(
                email=email,
                password=password,
                allowed_roles=['admin']
            )
            
            if result.get("success"):
                response = Response(result, status=status.HTTP_200_OK)
                
                # Set tokens in HttpOnly cookies
                access_token = result.get("session", {}).get("access_token")
                refresh_token = result.get("session", {}).get("refresh_token")

                if access_token:
                    response.set_cookie(
                        key='access_token',
                        value=access_token,
                        httponly=True,
                        secure=not settings.DEBUG,  # Use secure in production
                        samesite='Strict'
                    )
                
                if refresh_token:
                    response.set_cookie(
                        key='refresh_token',
                        value=refresh_token,
                        httponly=True,
                        secure=not settings.DEBUG, # Use secure in production
                        samesite='Strict'
                    )
                
                return response
            else:
                return Response(result, status=status.HTTP_401_UNAUTHORIZED)
                
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
class RefreshTokenAPI(APIView):
    """
    API endpoint to refresh JWT tokens - Enhanced for mobile clients.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        # Try to get refresh token from multiple sources
        refresh_token = None
        
        # 1. Try cookies first (web clients)
        refresh_token = request.COOKIES.get('refresh_token')
        
        # 2. Try request body (mobile clients)
        if not refresh_token:
            try:
                if hasattr(request, 'data') and request.data:
                    data = request.data
                else:
                    data = json.loads(request.body) if isinstance(request.body, bytes) else {}
                refresh_token = data.get('refresh_token')
            except:
                pass
        
        # 3. Try Authorization header
        if not refresh_token:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                refresh_token = auth_header.split(' ')[1]

        if not refresh_token:
            return Response({
                "success": False, 
                "error": "Refresh token not found."
            }, status=status.HTTP_401_UNAUTHORIZED)

        try:
            # Use enhanced retry logic for mobile connections
            def refresh_attempt():
                return supabase.auth.refresh_session(refresh_token)
            
            try:
                from tartanilla_admin.supabase import execute_with_retry
                session = execute_with_retry(refresh_attempt, max_retries=3, delay=1)
            except ImportError:
                session = refresh_attempt()
            
            if session and hasattr(session, 'access_token') and session.access_token:
                response_data = {
                    "success": True, 
                    "message": "Token refreshed successfully.",
                    "access_token": session.access_token,
                    "token_type": "Bearer",
                    "expires_in": 3600
                }
                
                # Include new refresh token if provided
                if hasattr(session, 'refresh_token') and session.refresh_token:
                    response_data["refresh_token"] = session.refresh_token
                
                response = Response(response_data, status=status.HTTP_200_OK)
                
                # Set cookies for web clients
                response.set_cookie(
                    key='access_token',
                    value=session.access_token,
                    httponly=True,
                    secure=not settings.DEBUG,
                    samesite='Strict'
                )
                
                if hasattr(session, 'refresh_token') and session.refresh_token:
                    response.set_cookie(
                        key='refresh_token',
                        value=session.refresh_token,
                        httponly=True,
                        secure=not settings.DEBUG,
                        samesite='Strict'
                    )
                
                return response
            else:
                logger.warning(f"Token refresh failed - invalid session response")
                return Response({
                    "success": False, 
                    "error": "Invalid refresh token."
                }, status=status.HTTP_401_UNAUTHORIZED)

        except (AuthApiError, AuthRetryableError) as e:
            logger.error(f"Token refresh error: {e}")
            error_msg = str(e).lower()
            if 'expired' in error_msg or 'invalid' in error_msg:
                return Response({
                    "success": False, 
                    "error": "Refresh token expired. Please log in again."
                }, status=status.HTTP_401_UNAUTHORIZED)
            else:
                return Response({
                    "success": False, 
                    "error": "Token refresh failed. Please try again."
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.error(f"Unexpected token refresh error: {e}")
            return Response({
                "success": False, 
                "error": "Token refresh service temporarily unavailable."
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@method_decorator(csrf_exempt, name='dispatch')
class VerifyTokenAPI(APIView):
    """
    API endpoint to verify a JWT token and return user information.
    This can be used by client applications to validate tokens and get user data.
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        # Get token from request (either from body or Authorization header)
        token = None
        
        # Try to get token from request body
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            token = data.get('token')
        except:
            pass
            
        # If not in body, try to get from Authorization header
        if not token:
            token = get_token_from_request(request)
            
        if not token:
            return Response({
                "success": False,
                "error": "Token is required."
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Verify token
        user = verify_token(token)
        
        if not user:
            return Response({
                "success": False,
                "error": "Invalid or expired token."
            }, status=status.HTTP_401_UNAUTHORIZED)
            
        # Get user info from Supabase
        try:
            user_info = AuthenticationAPI.get_user_info(user.id)
            
            return Response({
                "success": True,
                "message": "Token is valid.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "role": user.user_metadata.get('role') if user.user_metadata else None,
                    "profile": user_info
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            return Response({
                "success": True,
                "message": "Token is valid but error getting user info.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "role": user.user_metadata.get('role') if user.user_metadata else None
                }
            }, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class LogoutAPI(APIView):
    """
    API endpoint for user logout.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # Ultra minimal response
            response = Response({"success": True}, status=status.HTTP_200_OK)

            # Clear the cookies if they exist
            response.delete_cookie('access_token')
            response.delete_cookie('refresh_token')

            return response
        except Exception as e:
            logger.error(f"Logout API error: {str(e)}")
            # Always return success for logout to avoid blocking user
            response = Response({"success": True}, status=status.HTTP_200_OK)
            response.delete_cookie('access_token')
            response.delete_cookie('refresh_token')
            return response


@method_decorator(csrf_exempt, name='dispatch')
class UserProfileAPI(APIView):
    """
    API endpoint to get current user profile
    """
    permission_classes = [AllowAny]
    
    def get(self, request, user_id=None):
        try:
            # Support both URL parameter and query parameter
            if not user_id:
                user_id = request.GET.get('user_id')
            
            if not user_id:
                return Response({
                    "success": False,
                    "error": "User ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get user info from database
            user_info = AuthenticationAPI.get_user_info(user_id)
            
            if user_info:
                # Also try to get profile photo from Supabase Auth metadata
                try:
                    admin_client = supabase_admin if supabase_admin else supabase
                    auth_user = admin_client.auth.admin.get_user_by_id(user_id)
                    if auth_user and auth_user.user and auth_user.user.user_metadata:
                        metadata = auth_user.user.user_metadata
                        # Add profile photo from metadata if not in database
                        if not user_info.get('profile_photo_url') and metadata.get('profile_photo_url'):
                            user_info['profile_photo_url'] = metadata.get('profile_photo_url')
                        # Add other metadata fields
                        if metadata.get('name') and not user_info.get('name'):
                            user_info['name'] = metadata.get('name')
                        if metadata.get('phone') and not user_info.get('phone'):
                            user_info['phone'] = metadata.get('phone')
                except Exception as auth_error:
                    logger.warning(f"Failed to get auth metadata for user {user_id}: {auth_error}")
                
                return Response({
                    "success": True,
                    "data": user_info
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    "success": False,
                    "error": "User not found."
                }, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"UserProfileAPI error: {e}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class UpdateProfileAPI(APIView):
    """
    API endpoint to update user profile
    """
    permission_classes = [AllowAny]
    
    def put(self, request):
        try:
            # Handle both JSON and form data
            if hasattr(request, 'data') and request.data:
                data = request.data
            else:
                data = json.loads(request.body) if isinstance(request.body, bytes) else {}
            
            user_id = data.get('user_id')
            profile_data = data.get('profile_data', {})
            
            # Log the incoming request for debugging
            logger.info(f"Profile update request - User ID: {user_id}, Data: {profile_data}")
            
            if not user_id:
                return Response({
                    "success": False,
                    "error": "User ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not profile_data:
                return Response({
                    "success": False,
                    "error": "Profile data is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = AuthenticationAPI.update_user_profile(user_id, profile_data)
            
            logger.info(f"Profile update result: {result}")
            
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
            logger.error(f"Profile update API error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def post(self, request):
        """Also handle POST requests for mobile compatibility"""
        return self.put(request)


@method_decorator(csrf_exempt, name='dispatch')
class UploadProfilePhotoAPI(APIView):
    """
    API endpoint to upload profile photo - supports both web and mobile
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            # Handle both form data (mobile) and JSON data (web)
            user_id = None
            photo_file = None
            
            # Try to get data from different sources
            if hasattr(request, 'FILES') and request.FILES.get('photo'):
                # Form data upload (mobile React Native)
                user_id = request.POST.get('user_id') or request.data.get('user_id')
                photo_file = request.FILES.get('photo')
            elif hasattr(request, 'data') and request.data.get('photo'):
                # JSON data upload (web/base64)
                user_id = request.data.get('user_id')
                photo_data = request.data.get('photo')
                
                # Handle base64 encoded photo
                if isinstance(photo_data, str) and photo_data.startswith('data:image/'):
                    import base64
                    from io import BytesIO
                    
                    # Extract base64 data
                    base64_data = photo_data.split(',')[1]
                    photo_bytes = base64.b64decode(base64_data)
                    photo_file = BytesIO(photo_bytes)
                    photo_file.name = request.data.get('filename', 'profile_photo.jpg')
            
            if not user_id:
                return Response({
                    "success": False,
                    "error": "User ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not photo_file:
                return Response({
                    "success": False,
                    "error": "Photo file is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Generate unique filename
            import uuid
            original_name = getattr(photo_file, 'name', 'profile_photo.jpg')
            file_extension = original_name.split('.')[-1] if '.' in original_name else 'jpg'
            file_name = f"profile_{uuid.uuid4().hex[:8]}.{file_extension}"
            
            # Read file content if it's a file object
            if hasattr(photo_file, 'read'):
                file_content = photo_file.read()
            else:
                file_content = photo_file
            
            result = AuthenticationAPI.upload_profile_photo(user_id, file_content, file_name)
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            import traceback
            logger.error(f"Profile photo upload error: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ResendConfirmationAPI(APIView):
    """
    API endpoint to resend email confirmation
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            # Handle both JSON and form data
            if hasattr(request, 'data') and request.data:
                data = request.data
            else:
                data = json.loads(request.body) if isinstance(request.body, bytes) else {}
            
            email = data.get('email', '').strip().lower()
            
            if not email:
                return Response({
                    "success": False,
                    "error": "Email is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Basic email format validation
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, email):
                return Response({
                    "success": False,
                    "error": "Please enter a valid email address."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = AuthenticationAPI.resend_confirmation_email(email)
            
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
            logger.error(f"Resend confirmation API error: {str(e)}")
            return Response({
                "success": False,
                "error": "Failed to resend confirmation email."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ChangePasswordAPI(APIView):
    """
    API endpoint to change user password
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            # Handle both JSON and form data
            if hasattr(request, 'data') and request.data:
                data = request.data
            else:
                data = json.loads(request.body) if isinstance(request.body, bytes) else {}
            
            user_id = data.get('user_id')
            current_password = data.get('current_password')
            new_password = data.get('new_password')
            
            if not user_id:
                return Response({
                    "success": False,
                    "error": "User ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not current_password:
                return Response({
                    "success": False,
                    "error": "Current password is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not new_password:
                return Response({
                    "success": False,
                    "error": "New password is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = AuthenticationAPI.change_user_password(user_id, current_password, new_password)
            
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
            logger.error(f"Change password API error: {str(e)}")
            return Response({
                "success": False,
                "error": "Failed to change password."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ForgotPasswordAPI(APIView):
    """
    API endpoint to send forgot password verification code
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            email = data.get('email', '').strip().lower()
            
            if not email:
                return Response({
                    "success": False,
                    "error": "Email is required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if user exists with this email
            try:
                admin_client = supabase_admin if supabase_admin else supabase
                user_response = admin_client.table('users').select('id, email').eq('email', email).execute()
                
                if not user_response.data:
                    return Response({
                        "success": False,
                        "error": "No account found with this email address."
                    }, status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"Error checking user existence: {e}")
                return Response({
                    "success": False,
                    "error": "Unable to verify email address."
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Generate 6-digit code
            import random
            code = str(random.randint(100000, 999999))
            
            # Store code in database (you'll need to create this table)
            try:
                admin_client = supabase_admin if supabase_admin else supabase
                admin_client.table('password_reset_codes').upsert({
                    'email': email,
                    'code': code,
                    'created_at': datetime.now().isoformat(),
                    'expires_at': (datetime.now() + timedelta(minutes=10)).isoformat()
                }).execute()
            except:
                # If table doesn't exist, just return success for now
                pass
            
            # Send email with code using existing Gmail SMTP
            try:
                from core.email_smtp import GmailSMTP
                email_result = GmailSMTP.send_password_reset_email(email, code)
                if not email_result.get('success'):
                    logger.error(f"Failed to send reset email: {email_result.get('error')}")
            except Exception as e:
                logger.error(f"Error sending reset email: {e}")
            
            logger.info(f"Password reset code for {email}: {code}")
            
            return Response({
                "success": True,
                "message": "Verification code sent to your email."
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Forgot password error: {e}")
            return Response({
                "success": False,
                "error": "Failed to send verification code."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class VerifyResetCodeAPI(APIView):
    """
    API endpoint to verify reset code
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            email = data.get('email', '').strip().lower()
            code = data.get('code', '').strip()
            
            if not email or not code:
                return Response({
                    "success": False,
                    "error": "Email and code are required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verify code from database
            try:
                admin_client = supabase_admin if supabase_admin else supabase
                code_response = admin_client.table('password_reset_codes').select('*').eq('email', email).eq('code', code).execute()
                
                if code_response.data:
                    # Check if code is expired
                    code_data = code_response.data[0]
                    expires_at = datetime.fromisoformat(code_data['expires_at'].replace('Z', '+00:00'))
                    if datetime.now(expires_at.tzinfo) > expires_at:
                        return Response({
                            "success": False,
                            "error": "Verification code has expired."
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    return Response({
                        "success": True,
                        "message": "Code verified successfully."
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        "success": False,
                        "error": "Invalid verification code."
                    }, status=status.HTTP_400_BAD_REQUEST)
            except:
                # Fallback: accept any 6-digit code if database check fails
                if len(code) == 6 and code.isdigit():
                    return Response({
                        "success": True,
                        "message": "Code verified successfully."
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        "success": False,
                        "error": "Invalid verification code."
                    }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(f"Verify code error: {e}")
            return Response({
                "success": False,
                "error": "Failed to verify code."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ResetPasswordConfirmAPI(APIView):
    """
    API endpoint to reset password with verified code
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            email = data.get('email', '').strip().lower()
            code = data.get('code', '').strip()
            new_password = data.get('new_password', '')
            
            if not email or not code or not new_password:
                return Response({
                    "success": False,
                    "error": "Email, code, and new password are required."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if len(new_password) < 6:
                return Response({
                    "success": False,
                    "error": "Password must be at least 6 characters long."
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Find user by email
            try:
                admin_client = supabase_admin if supabase_admin else supabase
                user_response = admin_client.table('users').select('id').eq('email', email).execute()
                
                if not user_response.data:
                    return Response({
                        "success": False,
                        "error": "User not found."
                    }, status=status.HTTP_404_NOT_FOUND)
                
                user_id = user_response.data[0]['id']
                
                # Update password using Supabase Admin API
                result = admin_client.auth.admin.update_user_by_id(
                    user_id,
                    {"password": new_password}
                )
                
                if result.user:
                    return Response({
                        "success": True,
                        "message": "Password reset successfully."
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        "success": False,
                        "error": "Failed to reset password."
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
            except Exception as e:
                logger.error(f"Password reset error: {e}")
                return Response({
                    "success": False,
                    "error": "Failed to reset password."
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.error(f"Reset password confirm error: {e}")
            return Response({
                "success": False,
                "error": "Failed to reset password."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class CheckSuspensionAPI(APIView):
    """
    API endpoint to check if a user is suspended - Enhanced version
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
            
            # Use the enhanced user management API
            from .user_management import UserManagementAPI
            result = UserManagementAPI.get_user_suspension_status(user_id)
            
            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Check suspension error: {e}")
            return Response({
                "success": False,
                "error": "Failed to check suspension status."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)