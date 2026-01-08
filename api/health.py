from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
import time

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    Simple health check endpoint for mobile app connectivity testing
    """
    response = JsonResponse({
        'status': 'healthy',
        'timestamp': int(time.time()),
        'server': 'Django Tartanilla Admin',
        'message': 'Server is running normally'
    })
    response['Connection'] = 'close'
    return response

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def ping(request):
    """
    Ultra-fast ping endpoint for connection testing
    """
    response = JsonResponse({'pong': True})
    response['Connection'] = 'close'
    return response

@csrf_exempt
def quick_health(request):
    """
    Fastest possible health check - no DRF overhead
    """
    response = JsonResponse({'ok': 1})
    response['Connection'] = 'close'
    response['Cache-Control'] = 'no-cache'
    return response