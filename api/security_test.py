"""
Security testing endpoints
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json

@csrf_exempt
@require_http_methods(["GET"])
def test_rate_limit(request):
    """
    Simple endpoint for testing rate limiting
    """
    return JsonResponse({
        'success': True,
        'message': 'Rate limit test endpoint',
        'timestamp': str(request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR')))
    })

@csrf_exempt
@require_http_methods(["POST"])
def test_input_sanitization(request):
    """
    Test input sanitization
    """
    try:
        data = json.loads(request.body)
        test_input = data.get('test_input', '')
        
        # This will be sanitized by the middleware
        return JsonResponse({
            'success': True,
            'received_input': test_input,
            'message': 'Input processed successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)