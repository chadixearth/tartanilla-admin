from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase
from datetime import datetime
import json
import uuid as uuid_lib

@method_decorator(csrf_exempt, name='dispatch')
class NotificationAPI(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Create notification in Supabase"""
        try:
            data = request.data
            user_ids = data.get('user_ids', [])
            title = data.get('title')
            message = data.get('message')
            notif_type = data.get('type', 'info')
            role = data.get('role', 'tourist')
            
            if not all([user_ids, title, message]):
                return Response({
                    "success": False,
                    "error": "Missing required fields"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if isinstance(user_ids, str):
                user_ids = [user_ids]
            
            print(f"[NOTIFICATION] Creating: title='{title}', recipients={len(user_ids)}, type='{notif_type}'")
            
            valid_types = ['booking', 'payment', 'tour_ride_update', 'announcement', 'emergency', 'custom_tour_request', 'special_event_request']
            if notif_type not in valid_types:
                notif_type = 'announcement'
            
            notification_result = supabase.table('notifications').insert({
                'title': title,
                'message': message,
                'type': notif_type,
                'is_broadcast': len(user_ids) > 1,
                'audience_roles': [role] if role else ['tourist'],
                'priority': 'normal',
                'created_at': datetime.now().isoformat()
            }).execute()
            
            if not notification_result.data:
                print(f"[NOTIFICATION] Failed to create notification")
                return Response({
                    "success": False,
                    "error": "Failed to create notification"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            notification_id = notification_result.data[0]['id']
            print(f"[NOTIFICATION] Created notification {notification_id}")
            
            recipients = []
            invalid_count = 0
            for user_id in user_ids:
                try:
                    uuid_lib.UUID(str(user_id))
                    recipients.append({
                        'notification_id': notification_id,
                        'user_id': str(user_id),
                        'role': role,
                        'delivery_status': 'sent',
                        'is_read': False
                    })
                except (ValueError, TypeError):
                    print(f"[NOTIFICATION] Skipping invalid UUID: {user_id}")
                    invalid_count += 1
            
            if not recipients:
                print(f"[NOTIFICATION] No valid recipients")
                return Response({
                    "success": False,
                    "error": "No valid recipients"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            recipient_result = supabase.table('notification_recipients').insert(recipients).execute()
            recipients_created = len(recipient_result.data) if recipient_result.data else 0
            
            print(f"[NOTIFICATION] Created {recipients_created} recipients (skipped {invalid_count})")
            
            return Response({
                "success": True,
                "message": "Notification created successfully",
                "data": {
                    'notification_id': notification_id,
                    'title': title,
                    'recipients_created': recipients_created,
                    'invalid_recipients': invalid_count
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"[NOTIFICATION] Error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def get(self, request):
        """Get notifications for user"""
        try:
            user_id = request.GET.get('user_id')
            
            if not user_id:
                return Response({
                    "success": True,
                    "data": [],
                    "message": "User ID required"
                }, status=status.HTTP_200_OK)
            
            try:
                uuid_lib.UUID(str(user_id))
            except ValueError:
                return Response({
                    "success": False,
                    "error": "Invalid user ID format"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            print(f"[NOTIFICATION] Fetching for user: {user_id}")
            
            result = supabase.table('notification_recipients').select(
                'id, is_read, read_at, created_at, user_id, notification_id, notifications!inner(id, title, message, type, created_at)'
            ).eq('user_id', user_id).order('created_at', desc=True).execute()
            
            notifications = []
            if result.data:
                for item in result.data:
                    notif = item.get('notifications')
                    if notif:
                        notifications.append({
                            'id': item['id'],
                            'notification_id': notif['id'],
                            'title': notif['title'],
                            'message': notif['message'],
                            'type': notif['type'],
                            'read': item.get('is_read', False),
                            'created_at': item['created_at'],
                            'read_at': item.get('read_at')
                        })
            
            print(f"[NOTIFICATION] Returning {len(notifications)} notifications")
            
            return Response({
                "success": True,
                "data": notifications
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"[NOTIFICATION] Fetch error: {str(e)}")
            return Response({
                "success": True,
                "data": []
            }, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class MarkReadAPI(APIView):
    permission_classes = [AllowAny]
    
    def put(self, request):
        """Mark notification as read"""
        try:
            data = request.data
            recipient_id = data.get('notification_id')
            
            if not recipient_id:
                return Response({
                    "success": False,
                    "error": "Notification ID required"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = supabase.table('notification_recipients').update({
                'is_read': True,
                'read_at': datetime.now().isoformat(),
                'delivery_status': 'read'
            }).eq('id', recipient_id).execute()
            
            return Response({
                "success": True,
                "message": "Notification marked as read"
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"[NOTIFICATION] Mark read error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class StorePushTokenAPI(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Store push token for user"""
        try:
            data = request.data
            user_id = data.get('user_id')
            push_token = data.get('push_token')
            platform = data.get('platform', 'unknown')
            
            if not all([user_id, push_token]):
                return Response({
                    "success": False,
                    "error": "Missing required fields"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = supabase.table('push_tokens').upsert({
                'user_id': user_id,
                'token': push_token,
                'platform': platform,
                'updated_at': datetime.now().isoformat()
            }).execute()
            
            return Response({
                "success": True,
                "message": "Push token stored successfully"
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            print(f"[NOTIFICATION] Store token error: {str(e)}")
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
