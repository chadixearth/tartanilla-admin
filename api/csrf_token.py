"""
CSRF Token API endpoint for mobile apps
"""

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from core.validators import InputValidator
import json
import logging

logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["GET"])
def get_csrf_token(request):
    """
    Get CSRF token for mobile app forms
    """
    try:
        token = get_token(request)
        
        return JsonResponse({
            'success': True,
            'csrf_token': token,
            'message': 'CSRF token generated successfully'
        })
        
    except Exception as e:
        logger.error(f"Error generating CSRF token: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to generate CSRF token'
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def validate_input(request):
    """
    Validate input data using server-side validation
    """
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        validated_data = InputValidator.validate_json_data(
            data, 
            required_fields=['field_name', 'field_value', 'validation_type']
        )
        
        field_name = validated_data['field_name']
        field_value = validated_data['field_value']
        validation_type = validated_data['validation_type']
        
        # Perform validation based on type
        if validation_type == 'email':
            result = InputValidator.validate_email_field(field_value)
        elif validation_type == 'phone':
            result = InputValidator.validate_phone(field_value)
        elif validation_type == 'string':
            options = validated_data.get('options', {})
            result = InputValidator.validate_string(
                field_value, 
                field_name,
                min_length=options.get('min_length', 1),
                max_length=options.get('max_length', 255),
                pattern=options.get('pattern'),
                required=options.get('required', True)
            )
            # Return sanitized result to show XSS prevention working
            return JsonResponse({
                'success': True,
                'original_value': field_value,
                'validated_value': result,
                'is_valid': True,
                'sanitized': result != field_value
            })
        elif validation_type == 'coordinates':
            coords = json.loads(field_value) if isinstance(field_value, str) else field_value
            result = InputValidator.validate_coordinates(coords.get('lat'), coords.get('lng'))
        elif validation_type == 'price':
            options = validated_data.get('options', {})
            result = InputValidator.validate_price(
                field_value,
                min_value=options.get('min_value', 0),
                max_value=options.get('max_value', 100000)
            )
        else:
            return JsonResponse({
                'success': False,
                'error': f'Unknown validation type: {validation_type}'
            }, status=400)
        
        return JsonResponse({
            'success': True,
            'validated_value': str(result) if result is not None else None,
            'is_valid': True
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'is_valid': False
        }, status=400)