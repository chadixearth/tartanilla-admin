from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
import traceback

class JsonErrorMiddleware(MiddlewareMixin):
    def process_exception(self, request, exception):
        if request.path.startswith('/api/'):
            return JsonResponse({
                'error': 'Server error',
                'message': str(exception),
                'success': False
            }, status=500)
        return None