from functools import wraps
from django.http import JsonResponse
from core.jwt_auth import verify_token, get_token_from_request
import logging

logger = logging.getLogger(__name__)

def jwt_authenticated(view_func):
    """
    Decorator for views that checks if the user has a valid JWT token.
    If the token is valid, adds the user to the request.
    """
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        token = get_token_from_request(request)
        user = verify_token(token)
        
        if not user:
            return JsonResponse({
                'success': False,
                'error': 'Authentication required'
            }, status=401)
        
        # Add user to request
        request.supabase_user = user
        return view_func(request, *args, **kwargs)
    
    return wrapped_view


def jwt_role_required(allowed_roles):
    """
    Decorator for views that checks if the user has a valid JWT token
    and the required role.
    
    Usage:
    @jwt_role_required(['admin'])
    def admin_view(request):
        # Only admins can access this view
        pass
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            token = get_token_from_request(request)
            user = verify_token(token)
            
            if not user:
                return JsonResponse({
                    'success': False,
                    'error': 'Authentication required'
                }, status=401)
            
            # Check role
            role = user.user_metadata.get('role') if user.user_metadata else None
            
            # Handle special case for driver-owner role
            is_allowed = role in allowed_roles
            if not is_allowed and role == 'driver-owner':
                is_allowed = any(r in ['driver', 'owner'] for r in allowed_roles)
                
            if not is_allowed:
                allowed_str = ', '.join(allowed_roles)
                return JsonResponse({
                    'success': False,
                    'error': f'Access denied. Only {allowed_str} users can access this resource.'
                }, status=403)
            
            # Add user to request
            request.supabase_user = user
            return view_func(request, *args, **kwargs)
        
        return wrapped_view
    
    return decorator