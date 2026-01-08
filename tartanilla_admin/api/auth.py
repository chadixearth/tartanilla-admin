from tartanilla_admin.supabase import supabase
from gotrue.errors import AuthApiError, AuthRetryableError

def register_admin_with_auth(email, password):
    try:
        result = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {"role": "admin"}
            }
        })
        # If registration is successful, result.user will not be None
        if result.user:
            return {"success": "Check your email to confirm your registration."}
        else:
            return {"error": "Registration failed. Please try again."}
    except (AuthApiError, AuthRetryableError) as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def login_admin_with_auth(email, password):
    try:
        result = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        user = result.user
        if not user:
            return {"error": "Invalid email or password."}
        # Check if user is confirmed
        if not user.confirmed_at:
            return {"error": "Please confirm your email before logging in."}
        # Check if user is admin
        role = user.user_metadata.get("role") if user.user_metadata else None
        if role != "admin":
            return {"error": "Only admin users can log in here."}
        return {"success": "Login successful.", "user": {"email": user.email, "id": user.id}}
    except (AuthApiError, AuthRetryableError) as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}
