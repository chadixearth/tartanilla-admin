import time
import threading
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

class TimeoutMiddleware(MiddlewareMixin):
    """Middleware to handle request timeouts and prevent hanging connections"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        super().__init__(get_response)
    
    def process_request(self, request):
        # Set request start time
        request._start_time = time.time()
        return None
    
    def process_response(self, request, response):
        # Add timeout headers to prevent client hanging
        response['Connection'] = 'close'
        response['Keep-Alive'] = 'timeout=5, max=1'
        
        # Log slow requests
        if hasattr(request, '_start_time'):
            duration = time.time() - request._start_time
            if duration > 10:  # Log requests taking more than 10 seconds
                print(f"Slow request: {request.path} took {duration:.2f}s")
        
        return response
    
    def process_exception(self, request, exception):
        # Handle all exceptions with proper JSON response
        if request.path.startswith('/api/'):
            return JsonResponse({
                'error': 'Server error',
                'message': str(exception)[:200],
                'success': False
            }, status=500)
        return None