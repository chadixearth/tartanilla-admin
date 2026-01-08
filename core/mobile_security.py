"""
Mobile-Safe Security Middleware and Decorators
Provides security without breaking mobile API functionality
"""
from django.http import JsonResponse
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from functools import wraps
import re
import logging

logger = logging.getLogger(__name__)

class MobileSafeSecurityMiddleware:
    """
    Security middleware that applies different rules for API vs Web requests
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Add security headers for all responses
        response = self.get_response(request)
        
        # Only add web security headers for non-API requests
        if not request.path.startswith('/api/'):
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-Frame-Options'] = 'DENY'
            response['X-XSS-Protection'] = '1; mode=block'
        
        return response

def mobile_safe_csrf(view_func):
    """
    Decorator that exempts mobile API calls from CSRF but keeps web protection
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Check if this is a mobile API request
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        is_mobile_app = any(agent in user_agent for agent in [
            'expo', 'react-native', 'okhttp', 'mobile-app'
        ]) or request.path.startswith('/api/')
        
        if is_mobile_app:
            # Exempt from CSRF for mobile
            return csrf_exempt(view_func)(request, *args, **kwargs)
        else:
            # Apply CSRF for web requests
            return view_func(request, *args, **kwargs)
    
    return wrapper

def sanitize_input(data):
    """
    Sanitize user input to prevent XSS
    """
    if isinstance(data, str):
        return escape(data)
    elif isinstance(data, dict):
        return {k: sanitize_input(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_input(item) for item in data]
    return data

def validate_url(url):
    """
    Validate URLs to prevent SSRF attacks
    """
    if not url or not isinstance(url, str):
        return False
    
    # Strict whitelist of allowed domains
    allowed_domains = [
        'api.paymongo.com',
        'hooks.paymongo.com'
    ]
    
    # Block private IP ranges and localhost
    blocked_patterns = [
        r'localhost',
        r'127\.\d+\.\d+\.\d+',
        r'10\.\d+\.\d+\.\d+',
        r'172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+',
        r'192\.168\.\d+\.\d+',
        r'169\.254\.\d+\.\d+',
        r'0\.0\.0\.0',
        r'\[::\]',
        r'\[::1\]'
    ]
    
    # Check for blocked patterns
    for pattern in blocked_patterns:
        if re.search(pattern, url, re.IGNORECASE):
            logger.warning(f"Blocked URL with private IP/localhost: {url}")
            return False
    
    # Extract domain from URL
    domain_match = re.search(r'https?://([^/:]+)', url)
    if not domain_match:
        return False
    
    domain = domain_match.group(1).lower()
    
    # Only allow exact domain matches
    is_allowed = domain in allowed_domains or any(domain.endswith('.' + d) for d in allowed_domains)
    
    if not is_allowed:
        logger.warning(f"Blocked URL with unauthorized domain: {url}")
    
    return is_allowed

def secure_api_response(func):
    """
    Decorator to add security to API responses
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            
            # If it's a Django Response, add security headers
            if hasattr(result, 'status_code'):
                result['X-Content-Type-Options'] = 'nosniff'
                
            return result
        except Exception as e:
            logger.error(f"API Error: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': 'An error occurred processing your request'
            }, status=500)
    
    return wrapper