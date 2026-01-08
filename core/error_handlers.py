"""
Comprehensive error handling utilities for API views
"""

import logging
import traceback
from functools import wraps
from rest_framework.response import Response
from rest_framework import status
from tartanilla_admin.supabase import execute_with_retry

logger = logging.getLogger(__name__)

def handle_api_errors(fallback_data=None, log_errors=True):
    """
    Decorator to handle API errors gracefully
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logger.error(f"Error in {func.__name__}: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                
                error_str = str(e).lower()
                
                # Check for connection errors
                connection_errors = [
                    'connection', 'timeout', 'network', 'ssl', 'certificate',
                    'winerror 10054', 'forcibly closed', 'readerror', 'httpx',
                    'supabase', 'postgrest', 'connection pool', 'read timeout'
                ]
                
                if any(err in error_str for err in connection_errors):
                    return Response({
                        'success': False,
                        'error': 'Service temporarily unavailable. Please try again.',
                        'data': fallback_data or [],
                        'retry_suggested': True,
                        'error_code': 'CONNECTION_ERROR'
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                
                # Check for authentication errors
                auth_errors = ['unauthorized', 'forbidden', 'authentication', 'permission']
                if any(err in error_str for err in auth_errors):
                    return Response({
                        'success': False,
                        'error': 'Authentication required or insufficient permissions.',
                        'data': fallback_data or [],
                        'error_code': 'AUTH_ERROR'
                    }, status=status.HTTP_401_UNAUTHORIZED)
                
                # Check for validation errors
                validation_errors = ['validation', 'invalid', 'required', 'missing']
                if any(err in error_str for err in validation_errors):
                    return Response({
                        'success': False,
                        'error': str(e),
                        'data': fallback_data or [],
                        'error_code': 'VALIDATION_ERROR'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Generic server error
                return Response({
                    'success': False,
                    'error': 'An unexpected error occurred. Please try again.',
                    'data': fallback_data or [],
                    'error_code': 'SERVER_ERROR'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return wrapper
    return decorator

def safe_supabase_operation(operation_func, fallback_data=None, max_retries=3):
    """
    Safely execute a Supabase operation with retry logic
    """
    def query_wrapper():
        return operation_func()
    
    try:
        result = execute_with_retry(query_wrapper, max_retries=max_retries)
        
        # Check if result has data attribute
        if hasattr(result, 'data'):
            return result
        else:
            # Create a mock response object
            return type('Response', (), {
                'data': fallback_data or [],
                'error': None
            })()
    
    except Exception as e:
        logger.error(f"Supabase operation failed: {str(e)}")
        return type('Response', (), {
            'data': fallback_data or [],
            'error': str(e)
        })()

def validate_required_fields(data, required_fields):
    """
    Validate that all required fields are present in the data
    """
    missing_fields = []
    for field in required_fields:
        if not data.get(field):
            missing_fields.append(field)
    
    if missing_fields:
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")
    
    return True

def sanitize_response_data(data):
    """
    Sanitize response data to ensure it's JSON serializable
    """
    if data is None:
        return []
    
    if isinstance(data, list):
        return [sanitize_response_data(item) for item in data]
    
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                sanitized[key] = value
            elif isinstance(value, (list, dict)):
                sanitized[key] = sanitize_response_data(value)
            else:
                sanitized[key] = str(value)
        return sanitized
    
    return data

class APIErrorHandler:
    """
    Centralized error handler for API operations
    """
    
    @staticmethod
    def handle_connection_error(error, operation_name="operation"):
        """Handle connection-related errors"""
        logger.warning(f"Connection error in {operation_name}: {error}")
        return {
            'success': False,
            'error': 'Service temporarily unavailable. Please try again.',
            'data': [],
            'retry_suggested': True,
            'error_code': 'CONNECTION_ERROR'
        }
    
    @staticmethod
    def handle_validation_error(error, operation_name="operation"):
        """Handle validation errors"""
        logger.info(f"Validation error in {operation_name}: {error}")
        return {
            'success': False,
            'error': str(error),
            'data': [],
            'error_code': 'VALIDATION_ERROR'
        }
    
    @staticmethod
    def handle_not_found_error(resource_name="Resource"):
        """Handle not found errors"""
        return {
            'success': False,
            'error': f'{resource_name} not found',
            'data': [],
            'error_code': 'NOT_FOUND'
        }
    
    @staticmethod
    def handle_generic_error(error, operation_name="operation"):
        """Handle generic errors"""
        logger.error(f"Error in {operation_name}: {error}")
        return {
            'success': False,
            'error': 'An unexpected error occurred. Please try again.',
            'data': [],
            'error_code': 'SERVER_ERROR'
        }
    
    @staticmethod
    def create_success_response(data, message=None, count=None):
        """Create a standardized success response"""
        response = {
            'success': True,
            'data': sanitize_response_data(data)
        }
        
        if message:
            response['message'] = message
        
        if count is not None:
            response['count'] = count
        elif isinstance(data, list):
            response['count'] = len(data)
        
        return response