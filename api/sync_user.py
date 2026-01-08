from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase
import json

@method_decorator(csrf_exempt, name='dispatch')
class SyncUserAPI(APIView):
    
    def post(self, request):
        """Sync user from auth to users table"""
        try:
            data = request.data
            user_id = data.get('id')
            email = data.get('email')
            name = data.get('name', email.split('@')[0] if email else 'User')
            role = data.get('role', 'tourist')
            
            if not user_id or not email:
                return Response({
                    "success": False,
                    "error": "User ID and email required"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if user exists
            existing = supabase.table('users').select('id').eq('id', user_id).execute()
            
            if existing.data:
                return Response({
                    "success": True,
                    "message": "User already exists"
                }, status=status.HTTP_200_OK)
            
            # Create user
            result = supabase.table('users').insert({
                'id': user_id,
                'email': email,
                'name': name,
                'role': role,
                'status': 'active'
            }).execute()
            
            return Response({
                "success": True,
                "message": "User synced successfully"
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)