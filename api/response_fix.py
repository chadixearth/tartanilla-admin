from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
import json

def create_safe_response(data, status=200):
    """Create a DRF response with safe headers"""
    response = Response(data, status=status)
    response['Cache-Control'] = 'no-cache'
    return response