# api/breakeven_notifications.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase
from datetime import datetime, timedelta
import json
import os

class BreakevenNotificationService:
    """Service to handle breakeven-related notifications for drivers"""
    
    @staticmethod
    async def check_and_notify_breakeven_status(driver_id, current_data, previous_data=None):
        """
        Check breakeven status and send notifications if needed
        
        Args:
            driver_id: Driver UUID
            current_data: Current breakeven data from API
            previous_data: Previous breakeven data (optional)
        """
        try:
            if not current_data or not current_data.get('success'):
                return {'success': False, 'error': 'Invalid current data'}
            
            data = current_data.get('data', {})
            expenses = float(data.get('expenses', 0))
            revenue = float(data.get('revenue_period', 0))
            profit = revenue - expenses
            rides_done = int(data.get('total_bookings', 0))
            rides_needed = int(data.get('bookings_needed', 0))
            
            # Skip if no expenses set (no meaningful breakeven calculation)
            if expenses <= 0:
                return {'success': True, 'message': 'No expenses set, skipping notification'}
            
            notifications_sent = []
            
            # Check for breakeven achievement
            if profit >= 0 and (not previous_data or previous_data.get('profit', -1) < 0):
                notification = await BreakevenNotificationService._send_breakeven_achieved_notification(
                    driver_id, expenses, revenue, rides_done, rides_needed
                )
                if notification.get('success'):
                    notifications_sent.append('breakeven_achieved')
            
            # Check for profit milestone
            if profit > 0 and (not previous_data or previous_data.get('profit', 0) <= 0):
                notification = await BreakevenNotificationService._send_profit_achieved_notification(
                    driver_id, profit, revenue, expenses
                )
                if notification.get('success'):
                    notifications_sent.append('profit_achieved')
            
            # Check for significant profit milestones (every ₱500)
            if profit > 0:
                current_milestone = int(profit // 500) * 500
                previous_profit = previous_data.get('profit', 0) if previous_data else 0
                previous_milestone = int(previous_profit // 500) * 500 if previous_profit > 0 else 0
                
                if current_milestone > previous_milestone and current_milestone >= 500:
                    notification = await BreakevenNotificationService._send_profit_milestone_notification(
                        driver_id, current_milestone, profit
                    )
                    if notification.get('success'):
                        notifications_sent.append(f'profit_milestone_{current_milestone}')
            
            # Check for deficit warning (if deficit is significant)
            if profit < 0:
                deficit = abs(profit)
                if deficit >= 200 and rides_done > 0:  # Only warn if they've done some rides
                    notification = await BreakevenNotificationService._send_deficit_warning_notification(
                        driver_id, deficit, rides_needed - rides_done, expenses
                    )
                    if notification.get('success'):
                        notifications_sent.append('deficit_warning')
            
            return {
                'success': True,
                'notifications_sent': notifications_sent,
                'current_status': {
                    'profit': profit,
                    'breakeven_hit': profit >= 0,
                    'profitable': profit > 0
                }
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    async def _send_breakeven_achieved_notification(driver_id, expenses, revenue, rides_done, rides_needed):
        """Send notification when driver reaches breakeven"""
        try:
            title = "🎯 Breakeven Achieved!"
            message = f"Great job! You've reached your breakeven point with ₱{revenue:,.2f} revenue covering ₱{expenses:,.2f} expenses. You completed {rides_done} out of {rides_needed} needed rides."
            
            return await BreakevenNotificationService._create_notification(
                driver_id, title, message, 'breakeven'
            )
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    async def _send_profit_achieved_notification(driver_id, profit, revenue, expenses):
        """Send notification when driver starts making profit"""
        try:
            title = "💰 You're Now Profitable!"
            message = f"Excellent! You're now earning profit of ₱{profit:,.2f}. Your revenue (₱{revenue:,.2f}) exceeds your expenses (₱{expenses:,.2f}). Keep up the great work!"
            
            return await BreakevenNotificationService._create_notification(
                driver_id, title, message, 'profit'
            )
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    async def _send_profit_milestone_notification(driver_id, milestone, actual_profit):
        """Send notification for profit milestones"""
        try:
            title = f"🏆 ₱{milestone:,} Profit Milestone!"
            message = f"Amazing achievement! You've reached ₱{milestone:,} in profit (actual: ₱{actual_profit:,.2f}). Your hard work is paying off!"
            
            return await BreakevenNotificationService._create_notification(
                driver_id, title, message, 'milestone'
            )
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    async def _send_deficit_warning_notification(driver_id, deficit, rides_remaining, expenses):
        """Send notification when driver has significant deficit"""
        try:
            title = "📊 Breakeven Update"
            message = f"You're ₱{deficit:,.2f} away from breakeven. Complete about {rides_remaining} more rides to cover your ₱{expenses:,.2f} expenses. You're making progress!"
            
            return await BreakevenNotificationService._create_notification(
                driver_id, title, message, 'update'
            )
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    async def _create_notification(driver_id, title, message, notification_type):
        """Create notification in database"""
        try:
            # Create notification
            notification_result = supabase.table('notifications').insert({
                'title': title,
                'message': message,
                'type': 'booking',  # Use 'booking' as it's allowed in the schema
                'created_at': datetime.now().isoformat()
            }).execute()
            
            if not notification_result.data:
                raise Exception("Failed to create notification")
                
            notification_id = notification_result.data[0]['id']
            
            # Create recipient
            recipient_result = supabase.table('notification_recipients').insert({
                'notification_id': notification_id,
                'user_id': driver_id,
                'role': 'driver',
                'delivery_status': 'sent',
                'created_at': datetime.now().isoformat()
            }).execute()
            
            return {
                'success': True,
                'notification_id': notification_id,
                'type': notification_type
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

@method_decorator(csrf_exempt, name='dispatch')
class BreakevenNotificationAPI(APIView):
    """API endpoint for breakeven notifications"""
    
    def post(self, request):
        """Manually trigger breakeven notification check"""
        try:
            data = request.data
            driver_id = data.get('driver_id')
            current_data = data.get('current_data')
            previous_data = data.get('previous_data')
            
            if not driver_id or not current_data:
                return Response({
                    'success': False,
                    'error': 'driver_id and current_data are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check and send notifications
            result = BreakevenNotificationService.check_and_notify_breakeven_status(
                driver_id, current_data, previous_data
            )
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def get(self, request):
        """Get breakeven notification settings for driver"""
        try:
            driver_id = request.GET.get('driver_id')
            
            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'driver_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get recent breakeven notifications for this driver
            try:
                result = supabase.table('notification_recipients').select(
                    'id, created_at, is_read, notifications(id, title, message, type, created_at)'
                ).eq('user_id', driver_id).eq('role', 'driver').order('created_at', desc=True).limit(10).execute()
                
                notifications = []
                for item in result.data or []:
                    notif = item.get('notifications')
                    if notif and ('breakeven' in notif['title'].lower() or 'profit' in notif['title'].lower()):
                        notifications.append({
                            'id': item['id'],
                            'title': notif['title'],
                            'message': notif['message'],
                            'type': notif['type'],
                            'read': item['is_read'],
                            'created_at': item['created_at']
                        })
                
                return Response({
                    'success': True,
                    'data': {
                        'recent_notifications': notifications,
                        'notification_count': len(notifications)
                    }
                }, status=status.HTTP_200_OK)
                
            except Exception as db_error:
                return Response({
                    'success': True,
                    'data': {
                        'recent_notifications': [],
                        'notification_count': 0
                    }
                }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)