"""
Middleware to fix JSON response truncation issues
"""

import json
import logging
from django.http import JsonResponse, HttpResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

class JsonResponseFixMiddleware(MiddlewareMixin):
    """
    Middleware to ensure JSON responses are properly formatted and not truncated
    """
    
    def process_response(self, request, response):
        """
        Fix JSON response truncation issues
        """
        try:
            # Only process JSON responses
            content_type = response.get('Content-Type', '')
            if 'application/json' in content_type:
                
                # Get response content
                if hasattr(response, 'content'):
                    content = response.content
                    
                    # Try to parse as JSON to validate
                    try:
                        if content:
                            json_data = json.loads(content.decode('utf-8'))
                            
                            # Re-serialize to ensure proper formatting
                            fixed_content = json.dumps(json_data, ensure_ascii=False, separators=(',', ':'))
                            
                            # Create new response with fixed content
                            new_response = HttpResponse(
                                fixed_content,
                                content_type='application/json',
                                status=response.status_code
                            )
                            
                            # Copy headers
                            for header, value in response.items():
                                new_response[header] = value
                            
                            # Set correct content length
                            new_response['Content-Length'] = str(len(fixed_content))
                            
                            return new_response
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"JSON decode error in response: {e}")
                        # Return original response if JSON is invalid
                        pass
        
        except Exception as e:
            logger.error(f"Error in JsonResponseFixMiddleware: {e}")
        
        return response