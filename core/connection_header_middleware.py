class RemoveConnectionHeaderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Remove Connection header from request
        if 'HTTP_CONNECTION' in request.META:
            del request.META['HTTP_CONNECTION']
        
        response = self.get_response(request)
        
        # Remove Connection header from response
        if 'Connection' in response:
            del response['Connection']
        
        return response