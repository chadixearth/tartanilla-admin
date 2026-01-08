class ResponseFixMiddleware:
    """
    Middleware to fix response truncation issues
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Fix API responses
        if request.path.startswith('/api/'):
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            
            # Ensure response is complete
            if hasattr(response, 'content') and response.content:
                try:
                    content = response.content.decode('utf-8')
                    # Check if JSON is complete
                    if content.strip().startswith('{') and not content.strip().endswith('}'):
                        # Fix incomplete JSON
                        import json
                        try:
                            json.loads(content)
                        except json.JSONDecodeError:
                            # Add missing closing brace
                            content += '}'
                            response.content = content.encode('utf-8')
                except (UnicodeDecodeError, AttributeError):
                    pass
        
        return response