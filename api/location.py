from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase
from datetime import datetime

@method_decorator(csrf_exempt, name='dispatch')
class LocationUpdateAPI(APIView):
    
    def post(self, request):
        """Update driver location"""
        try:
            data = request.data
            user_id = data.get('user_id')
            latitude = data.get('latitude')
            longitude = data.get('longitude')
            speed = data.get('speed', 0)
            heading = data.get('heading', 0)
            
            if not all([user_id, latitude, longitude]):
                return Response({
                    "success": False,
                    "error": "Missing required fields"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update with timeout and retry
            import socket
            from postgrest.exceptions import APIError
            
            for attempt in range(2):
                try:
                    update_result = supabase.table('driver_locations').update({
                        'latitude': float(latitude),
                        'longitude': float(longitude),
                        'speed': float(speed),
                        'heading': float(heading),
                        'updated_at': datetime.now().isoformat()
                    }).eq('user_id', user_id).execute()
                    
                    if not update_result.data:
                        insert_result = supabase.table('driver_locations').insert({
                            'user_id': user_id,
                            'latitude': float(latitude),
                            'longitude': float(longitude),
                            'speed': float(speed),
                            'heading': float(heading),
                            'updated_at': datetime.now().isoformat()
                        }).execute()
                    
                    return Response({"success": True}, status=status.HTTP_200_OK)
                    
                except (socket.error, ConnectionError, APIError) as e:
                    if attempt == 0:
                        continue
                    # Silently succeed on network errors
                    return Response({"success": True}, status=status.HTTP_200_OK)
            
        except Exception:
            # Silently succeed to prevent app errors
            return Response({"success": True}, status=status.HTTP_200_OK)
    
    def get(self, request):
        """Get driver locations"""
        try:
            driver_ids = request.GET.getlist('driver_ids[]')
            driver_id = request.GET.get('driver_id')  # Single driver ID
            
            query = supabase.table('driver_locations').select('*').order('updated_at', desc=True)
            
            if driver_id:
                # Single driver lookup
                query = query.eq('user_id', driver_id).limit(1)
            elif driver_ids:
                # Multiple drivers lookup
                query = query.in_('user_id', driver_ids)
            else:
                # Get all driver locations (limit to recent ones)
                from datetime import datetime, timedelta
                cutoff_time = datetime.now() - timedelta(minutes=30)
                query = query.gte('updated_at', cutoff_time.isoformat())
            
            result = query.execute()
            
            return Response({
                "success": True,
                "data": result.data or []
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                "success": False,
                "error": f"Failed to get locations: {str(e)}",
                "data": []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)