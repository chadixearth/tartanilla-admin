from django.http import StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from tartanilla_admin.supabase import supabase
import json
import time
import threading
from datetime import datetime

# Store active connections
active_connections = {}

@method_decorator(csrf_exempt, name='dispatch')
class NotificationStreamAPI(APIView):
    """Server-Sent Events endpoint for real-time notifications"""
    
    def get(self, request):
        user_id = request.GET.get('user_id')
        if not user_id:
            return Response({'error': 'user_id required'}, status=400)
        
        def event_stream():
            # Send initial connection message
            yield f"data: {json.dumps({'type': 'connected', 'message': 'Connected to notifications'})}\n\n"
            
            # Store connection
            active_connections[user_id] = True
            
            try:
                while active_connections.get(user_id, False):
                    # Check for new notifications
                    try:
                        result = supabase.table('notification_recipients').select(
                            'id, is_read, created_at, notifications(id, title, message, type, created_at)'
                        ).eq('user_id', user_id).eq('is_read', False).order('created_at', desc=True).limit(5).execute()
                        
                        if result.data:
                            for item in result.data:
                                notif = item['notifications']
                                notification_data = {
                                    'type': 'notification',
                                    'id': item['id'],
                                    'title': notif['title'],
                                    'message': notif['message'],
                                    'notification_type': notif['type'],
                                    'created_at': item['created_at']
                                }
                                yield f"data: {json.dumps(notification_data)}\n\n"
                    except Exception as e:
                        print(f"Error fetching notifications for {user_id}: {e}")
                    
                    # Send heartbeat every 30 seconds
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"
                    time.sleep(30)
                    
            except Exception as e:
                print(f"SSE connection error for {user_id}: {e}")
            finally:
                # Clean up connection
                if user_id in active_connections:
                    del active_connections[user_id]
        
        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['Connection'] = 'keep-alive'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Headers'] = 'Cache-Control'
        return response

@method_decorator(csrf_exempt, name='dispatch')
class PushNotificationAPI(APIView):
    """Push notification to specific users via SSE"""
    
    def post(self, request):
        try:
            data = request.data
            user_ids = data.get('user_ids', [])
            title = data.get('title')
            message = data.get('message')
            notification_type = data.get('type', 'info')
            
            if not all([user_ids, title, message]):
                return Response({
                    "success": False,
                    "error": "Missing required fields"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Create notification in database
            notification_result = supabase.table('notifications').insert({
                'title': title,
                'message': message,
                'type': notification_type,
                'created_at': datetime.now().isoformat()
            }).execute()
            
            if not notification_result.data:
                raise Exception("Failed to create notification")
                
            notification_id = notification_result.data[0]['id']
            
            # Create recipients
            recipients = []
            for user_id in user_ids:
                recipients.append({
                    'notification_id': notification_id,
                    'user_id': user_id,
                    'role': data.get('role', 'tourist'),
                    'delivery_status': 'sent'
                })
            
            supabase.table('notification_recipients').insert(recipients).execute()
            
            # Push to active SSE connections
            notification_data = {
                'type': 'notification',
                'title': title,
                'message': message,
                'notification_type': notification_type,
                'created_at': datetime.now().isoformat()
            }
            
            # This would be handled by the SSE stream checking the database
            
            return Response({
                "success": True,
                "message": "Notification sent successfully",
                "data": notification_result.data[0]
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                "success": False,
                "error": f"Failed to send notification: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)