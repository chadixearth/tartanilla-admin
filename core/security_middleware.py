"""
Comprehensive Security Middleware for Django Backend
"""

import json
import re
import time
import logging
from collections import defaultdict
from django.http import JsonResponse, HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin
from django.core.cache import cache
from django.conf import settings
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt
from django.utils.html import escape
from django.core.exceptions import ValidationError
import bleach

logger = logging.getLogger(__name__)

class RateLimitMiddleware(MiddlewareMixin):
    """Rate limiting middleware with different limits for different endpoints"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.rate_limits = {
            '/api/auth/': {'requests': 10, 'window': 300},  # 10 requests per 5 minutes
            '/api/booking/': {'requests': 20, 'window': 60},  # 20 requests per minute
            '/api/payment/': {'requests': 5, 'window': 300},  # 5 requests per 5 minutes
            '/api/test/': {'requests': 2, 'window': 10},  # 2 requests per 10 seconds for testing
            'default': {'requests': 100, 'window': 60}  # 100 requests per minute
        }
    
    def __call__(self, request):
        if not self._check_rate_limit(request):
            return JsonResponse({
                'success': False,
                'error': 'Rate limit exceeded. Please try again later.',
                'error_code': 'RATE_LIMIT_EXCEEDED'
            }, status=429)
        
        response = self.get_response(request)
        return response
    
    def _check_rate_limit(self, request):
        client_ip = self._get_client_ip(request)
        path = request.path
        
        # Find matching rate limit
        limit_config = self.rate_limits['default']
        for pattern, config in self.rate_limits.items():
            if pattern != 'default' and path.startswith(pattern):
                limit_config = config
                break
        
        cache_key = f"rate_limit:{client_ip}:{path}"
        current_requests = cache.get(cache_key, 0)
        
        if current_requests >= limit_config['requests']:
            return False
        
        # Use timeout=None to make it persistent for testing
        cache.set(cache_key, current_requests + 1, timeout=limit_config['window'])
        return True
    
    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR', '127.0.0.1')

class InputValidationMiddleware(MiddlewareMixin):
    """Comprehensive input validation and sanitization"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.dangerous_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'on\w+\s*=',
            r'<iframe[^>]*>.*?</iframe>',
            r'eval\s*\(',
            r'document\.',
            r'window\.',
            r'alert\s*\(',
            r'confirm\s*\(',
            r'prompt\s*\(',
        ]
        self.sql_patterns = [
            r'union\s+select',
            r'drop\s+table',
            r'delete\s+from',
            r'insert\s+into',
            r'update\s+.*\s+set',
            r'exec\s*\(',
            r'sp_\w+',
            r'xp_\w+',
        ]
    
    def __call__(self, request):
        if not self._validate_request(request):
            return JsonResponse({
                'success': False,
                'error': 'Invalid input detected',
                'error_code': 'INVALID_INPUT'
            }, status=400)
        
        response = self.get_response(request)
        return self._sanitize_response(response)
    
    def _validate_request(self, request):
        # Validate query parameters
        for key, value in request.GET.items():
            if not self._is_safe_input(value):
                logger.warning(f"Dangerous input in GET parameter {key}: {value}")
                return False
        
        # Validate POST data
        if request.method == 'POST' and hasattr(request, 'body'):
            try:
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                    if not self._validate_json_data(data):
                        return False
                else:
                    for key, value in request.POST.items():
                        if not self._is_safe_input(value):
                            logger.warning(f"Dangerous input in POST parameter {key}: {value}")
                            return False
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        
        return True
    
    def _validate_json_data(self, data):
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and not self._is_safe_input(value):
                    logger.warning(f"Dangerous input in JSON field {key}: {value}")
                    return False
                elif isinstance(value, (dict, list)):
                    if not self._validate_json_data(value):
                        return False
        elif isinstance(data, list):
            for item in data:
                if not self._validate_json_data(item):
                    return False
        elif isinstance(data, str):
            if not self._is_safe_input(data):
                return False
        
        return True
    
    def _is_safe_input(self, value):
        if not isinstance(value, str):
            return True
        
        value_lower = value.lower()
        
        # Check for XSS patterns
        for pattern in self.dangerous_patterns:
            if re.search(pattern, value_lower, re.IGNORECASE):
                return False
        
        # Check for SQL injection patterns
        for pattern in self.sql_patterns:
            if re.search(pattern, value_lower, re.IGNORECASE):
                return False
        
        return True
    
    def _sanitize_response(self, response):
        if hasattr(response, 'content') and response.get('Content-Type', '').startswith('application/json'):
            try:
                data = json.loads(response.content)
                sanitized_data = self._sanitize_json_data(data)
                response.content = json.dumps(sanitized_data).encode('utf-8')
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        
        return response
    
    def _sanitize_json_data(self, data):
        if isinstance(data, dict):
            return {key: self._sanitize_json_data(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_json_data(item) for item in data]
        elif isinstance(data, str):
            return bleach.clean(data, tags=[], attributes={}, strip=True)
        else:
            return data

class CSRFEnhancementMiddleware(MiddlewareMixin):
    """Enhanced CSRF protection for API endpoints"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_paths = [
            '/api/auth/login/',
            '/api/auth/register/',
            '/api/health/',
        ]
    
    def __call__(self, request):
        # Add CSRF token to API responses
        if request.path.startswith('/api/') and request.method == 'GET':
            response = self.get_response(request)
            if hasattr(response, 'content') and response.get('Content-Type', '').startswith('application/json'):
                try:
                    data = json.loads(response.content)
                    if isinstance(data, dict):
                        data['csrf_token'] = get_token(request)
                        response.content = json.dumps(data).encode('utf-8')
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            return response
        
        response = self.get_response(request)
        return response

class SecureHeadersMiddleware(MiddlewareMixin):
    """Add security headers to all responses"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Security headers
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        # Content Security Policy
        if not settings.DEBUG:
            response['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "connect-src 'self' https:; "
                "font-src 'self'; "
                "object-src 'none'; "
                "media-src 'self'; "
                "frame-src 'none';"
            )
        
        return response

class ErrorHandlingMiddleware(MiddlewareMixin):
    """Comprehensive error handling with proper logging"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        try:
            response = self.get_response(request)
            return response
        except Exception as e:
            return self._handle_error(request, e)
    
    def process_exception(self, request, exception):
        return self._handle_error(request, exception)
    
    def _handle_error(self, request, exception):
        error_id = f"error_{int(time.time())}"
        
        # Log the error with context
        logger.error(
            f"Error {error_id}: {str(exception)}",
            extra={
                'request_path': request.path,
                'request_method': request.method,
                'user_id': getattr(request.user, 'id', None) if hasattr(request, 'user') else None,
                'ip_address': self._get_client_ip(request),
                'error_type': type(exception).__name__
            },
            exc_info=True
        )
        
        # Return sanitized error response
        if settings.DEBUG:
            error_message = str(exception)
        else:
            error_message = "An internal error occurred. Please try again later."
        
        return JsonResponse({
            'success': False,
            'error': error_message,
            'error_code': 'INTERNAL_ERROR',
            'error_id': error_id
        }, status=500)
    
    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR', '127.0.0.1')