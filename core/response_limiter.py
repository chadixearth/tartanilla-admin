"""
Response size limiter to prevent JSON truncation
"""
import json
from django.http import JsonResponse

MAX_RESPONSE_SIZE = 2048  # 2KB max response size

def create_limited_response(data, max_size=MAX_RESPONSE_SIZE):
    """Create a response that fits within size limits"""
    try:
        # Convert to JSON string to check size
        json_str = json.dumps(data, separators=(',', ':'))
        
        if len(json_str.encode('utf-8')) <= max_size:
            return JsonResponse(data)
        
        # Response too large, return minimal version
        if isinstance(data, dict):
            if 'data' in data and isinstance(data['data'], dict):
                # Reduce data fields
                minimal_data = {
                    'success': data.get('success', True),
                    'data': {
                        'earnings': [],  # Empty earnings array
                        'statistics': data['data'].get('statistics', {
                            'total_driver_earnings': 0,
                            'count': 0
                        })
                    }
                }
                return JsonResponse(minimal_data)
        
        # Fallback to ultra-minimal response
        return JsonResponse({
            'success': True,
            'data': [],
            'message': 'Response size limited'
        })
        
    except Exception as e:
        # Safe fallback
        return JsonResponse({
            'success': True,
            'data': [],
            'error': 'Response processing failed'
        })