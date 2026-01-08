from django.http import HttpRequest
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
import logging

logger = logging.getLogger(__name__)

# Import supabase client lazily to avoid import errors during Django startup
def get_supabase_client():
    try:
        from tartanilla_admin.supabase import supabase
        return supabase
    except Exception as e:
        logger.error(f"Failed to import Supabase client: {e}")
        return None

# Utility functions for token management
def get_token_from_request(request):
    """
    Extract JWT token from the Authorization header.
    Expected format: "Bearer <token>"
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None
        
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
        
    return parts[1]

def verify_token(token):
    """
    Verify a JWT token with Supabase and return the user if valid.
    Returns None if the token is invalid or expired.
    """
    if not token:
        return None
        
    try:
        # Get Supabase client
        supabase = get_supabase_client()
        if not supabase:
            logger.error("Supabase client not available")
            return None
            
        # Use Supabase's get_user method to verify the token
        # This will throw an exception if the token is invalid
        user = supabase.auth.get_user(token)
        return user.user
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        return None

# Django REST Framework Authentication Class
class SupabaseJWTAuthentication(BaseAuthentication):
    """
    Custom authentication class for Django REST Framework that uses Supabase JWT tokens.
    """
    def authenticate(self, request):
        token = get_token_from_request(request)
        if not token:
            return None  # No token provided, let other auth methods handle it
            
        user = verify_token(token)
        if not user:
            raise AuthenticationFailed('Invalid or expired token')
            
        # Create a simple user object with the necessary attributes
        # This can be expanded based on your needs
        from django.http import HttpRequest
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
import logging

logger = logging.getLogger(__name__)

# Import supabase client lazily to avoid import errors during Django startup
def get_supabase_client():
    try:
        from tartanilla_admin.supabase import supabase
        return supabase
    except Exception as e:
        logger.error(f"Failed to import Supabase client: {e}")
        return None

# Utility functions for token management
def get_token_from_request(request):
    """
    Extract JWT token from the Authorization header or from a cookie.
    Expected format: "Bearer <token>"
    """
    # 1. Try Authorization header
    auth_header = request.headers.get('Authorization')
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            return parts[1]

    # 2. Try cookie
    token = request.COOKIES.get('access_token')
    if token:
        return token

    return None

def verify_token(token):
    """
    Verify a JWT token with Supabase and return the user if valid.
    Returns None if the token is invalid or expired.
    """
    if not token:
        return None
        
    try:
        # Get Supabase client
        supabase = get_supabase_client()
        if not supabase:
            logger.error("Supabase client not available")
            return None
            
        # Use Supabase's get_user method to verify the token
        # This will throw an exception if the token is invalid
        user = supabase.auth.get_user(token)
        return user.user
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        return None

# Django REST Framework Authentication Class
class SupabaseJWTAuthentication(BaseAuthentication):
    """
    Custom authentication class for Django REST Framework that uses Supabase JWT tokens.
    """
    def authenticate(self, request):
        token = get_token_from_request(request)
        if not token:
            return None  # No token provided, let other auth methods handle it
            
        user = verify_token(token)
        if not user:
            raise AuthenticationFailed('Invalid or expired token')
            
        # Create a simple user object with the necessary attributes
        # This can be expanded based on your needs
        auth_user = type('SupabaseUser', (), {
            'is_authenticated': True,
            'id': user.id,
            'pk': user.id,  # Add pk attribute for DRF throttling compatibility
            'email': user.email,
            'user_metadata': user.user_metadata,
            # Add any other attributes you need
        })
        
        return (auth_user, token)

# Django Middleware for JWT Authentication
class SupabaseJWTMiddleware:
    """
    Django middleware that processes JWT tokens from requests.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        # Public endpoints that don't require authentication
        self.public_paths = [
            '/api/map/',
            '/api/auth/login/',
            '/api/auth/register/',
            '/api/debug/',
        ]

    def __call__(self, request):
        # Skip authentication for public endpoints
        if any(request.path.startswith(path) for path in self.public_paths):
            response = self.get_response(request)
            return response
            
        # Extract and verify token
        token = get_token_from_request(request)
        user = verify_token(token)
        
        # If token is valid, add user to request
        if user:
            request.supabase_user = user
        
        # Continue with the request
        response = self.get_response(request)
        return response