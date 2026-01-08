"""
Middleware for handling connection errors and providing graceful degradation
"""

import logging
import json
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

class ConnectionErrorMiddleware(MiddlewareMixin):
    """Middleware to catch and handle connection errors gracefully"""
    
    def process_exception(self, request, exception):
        """Handle exceptions that bubble up from views"""
        error_str = str(exception).lower()
        
        # Check if it's a connection-related error
        connection_errors = [
            'connection', 'timeout', 'network', 'ssl', 'certificate',
            'winerror 10054', 'forcibly closed', 'readerror', 'httpx',
            'supabase', 'postgrest', 'connection pool'
        ]
        
        if any(err in error_str for err in connection_errors):
            logger.warning(f"Connection error caught by middleware: {exception}")
            
            # Return a user-friendly error response
            return JsonResponse({
                'success': False,
                'error': 'Service temporarily unavailable. Please try again in a moment.',
                'data': [],
                'retry_suggested': True,
                'error_code': 'CONNECTION_ERROR'
            }, status=503)
        
        # Let other exceptions bubble up normally
        return None
    
    def process_response(self, request, response):
        """Process the response to add connection health headers"""
        if hasattr(response, 'status_code') and response.status_code >= 500:
            # Add retry headers for server errors
            response['Retry-After'] = '5'
            response['X-Connection-Status'] = 'unstable'
        
        return response

class APIResponseMiddleware(MiddlewareMixin):
    """Middleware to standardize API responses"""
    
    def process_response(self, request, response):
        """Minimal response processing to prevent truncation issues"""
        # Temporarily disable complex response processing to prevent truncation
        if request.path.startswith('/api/') and hasattr(response, 'content'):
            # Just ensure proper content type
            if response.get('Content-Type', '').startswith('text/html'):
                response['Content-Type'] = 'application/json'
        
        return response