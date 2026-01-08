from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.http import JsonResponse
import json

class TestRegistrationAPI(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        return JsonResponse({
            "success": True,
            "message": "Test registration endpoint working",
            "received_data": request.data
        })
    
    def get(self, request):
        return JsonResponse({
            "success": True,
            "message": "Test endpoint is working"
        })