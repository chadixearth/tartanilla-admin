from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from tartanilla_admin.supabase import supabase
try:
    from tartanilla_admin.supabase import supabase_admin
except:
    supabase_admin = None
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class GoodsServicesReportViewSet(viewsets.ViewSet):
    """Handle reports for goods & services posts"""
    permission_classes = [AllowAny]
    
    def create(self, request):
        """Create a report for a goods/services post"""
        try:
            data = request.data
            required = ['post_id', 'reporter_id', 'reporter_type', 'reason']
            
            for field in required:
                if not data.get(field):
                    return Response({
                        'success': False,
                        'error': f'Missing required field: {field}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get post details
            post_resp = supabase.table('goods_services_profiles').select('*').eq('id', data['post_id']).execute()
            if not post_resp.data:
                return Response({
                    'success': False,
                    'error': 'Post not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            post = post_resp.data[0]
            
            # Create report
            report_data = {
                'report_type': 'goods_services_violation',
                'title': f'Goods & Services Post Report - {data["reason"]}',
                'related_booking_id': data['post_id'],
                'description': f"""Goods & Services Post Report

Reason: {data['reason']}
Details: {data.get('details', 'No additional details provided')}

Post Information:
- Post ID: {data['post_id']}
- Author ID: {post.get('author_id')}
- Author Role: {post.get('author_role')}
- Description: {post.get('description', 'N/A')[:200]}

Reporter Information:
- Reporter ID: {data['reporter_id']}
- Reporter Type: {data['reporter_type']}
""",
                'reporter_id': data['reporter_id'],
                'reporter_type': data['reporter_type'],
                'related_user_id': post.get('author_id'),
                'status': 'pending',
                'priority': 'high' if data['reason'] in ['inappropriate_content', 'fraud', 'harassment'] else 'medium',
                'metadata': {
                    'post_id': data['post_id'],
                    'reason': data['reason'],
                    'details': data.get('details', '')
                }
            }
            
            response = supabase.table('reports').insert(report_data).execute()
            
            if response.data:
                # Notify admins
                self._notify_admins(response.data[0])
                
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': 'Report submitted successfully. Admin will review it shortly.'
                }, status=status.HTTP_201_CREATED)
            
            return Response({
                'success': False,
                'error': 'Failed to create report'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.error(f"Error creating goods/services report: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='handle_goods_services_violation')
    def handle_violation(self, request):
        """Admin handles a goods/services violation report"""
        try:
            data = request.data
            report_id = data.get('report_id')
            action = data.get('action')  # 'dismiss', 'warn', 'remove_post', 'suspend_user'
            admin_notes = data.get('admin_notes', '')
            suspension_days = data.get('suspension_days', 7)
            post_id = data.get('post_id')
            user_id = data.get('user_id')
            
            if action not in ['dismiss', 'warn', 'remove_post', 'suspend_user']:
                return Response({
                    'success': False,
                    'error': 'Invalid action'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get report
            report_resp = supabase.table('reports').select('*').eq('id', report_id).execute()
            if not report_resp.data:
                return Response({
                    'success': False,
                    'error': 'Report not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            report = report_resp.data[0]
            
            result_message = ''
            actions_taken = []
            
            # Execute action
            if action == 'dismiss':
                result_message = 'Report dismissed. No violations found.'
                actions_taken.append('Report dismissed')
                
                # Resolve all reports for this post
                supabase.table('reports').update({
                    'status': 'resolved',
                    'admin_notes': f'No violation found. {admin_notes}',
                    'resolved_at': datetime.now().isoformat()
                }).eq('related_booking_id', post_id).eq('status', 'pending').execute()
                
            elif action == 'warn':
                result_message = 'Warning sent to user.'
                actions_taken.append('User warned')
                if user_id:
                    self._notify_user(user_id, 'Warning: Community Guidelines', 
                        f'Your goods & services post has been flagged. Please review our community guidelines. Admin note: {admin_notes}')
                
            elif action == 'remove_post':
                # Delete the post
                supabase.table('goods_services_profiles').delete().eq('id', post_id).execute()
                
                result_message = 'Post deleted for violating community guidelines.'
                actions_taken.append('Post deleted')
                
                # Resolve all reports for this post
                supabase.table('reports').update({
                    'status': 'resolved',
                    'admin_notes': f'Post removed. {admin_notes}',
                    'resolved_at': datetime.now().isoformat()
                }).eq('related_booking_id', post_id).eq('status', 'pending').execute()
                
                # Notify post author
                if user_id:
                    self._notify_user(user_id, 'Post Removed', 
                        f'Your goods & services post has been removed for violating community guidelines. Reason: {admin_notes}')
                
            elif action == 'suspend_user':
                # Delete post
                supabase.table('goods_services_profiles').delete().eq('id', post_id).execute()
                actions_taken.append('Post deleted')
                
                # Suspend user
                from datetime import timedelta
                suspension_until = (datetime.now() + timedelta(days=int(suspension_days))).isoformat()
                
                # Suspend user
                try:
                    supabase.table('users').update({
                        'status': 'suspended',
                        'updated_at': datetime.now().isoformat()
                    }).eq('id', user_id).execute()
                    
                    actions_taken.append(f'User suspended for {suspension_days} days')
                    result_message = f'Post deleted and user suspended for {suspension_days} days.'
                    
                    # Resolve all reports for this post
                    supabase.table('reports').update({
                        'status': 'resolved',
                        'admin_notes': f'User suspended for {suspension_days} days. Post deleted. {admin_notes}',
                        'resolved_at': datetime.now().isoformat()
                    }).eq('related_booking_id', post_id).eq('status', 'pending').execute()
                    
                    # Notify user
                    self._notify_user(user_id, 'Account Suspended',
                        f'Your account has been suspended for {suspension_days} days due to violations in your goods & services post. Reason: {admin_notes}')
                        
                except Exception as e:
                    logger.error(f"Failed to suspend user: {e}")
                    result_message = f'Post deleted but failed to suspend user: {str(e)}'
            
            # Update report status
            update_data = {
                'status': 'resolved',
                'admin_notes': f"{admin_notes}\n\nAction: {action}\nActions taken: {', '.join(actions_taken)}",
                'resolved_at': datetime.now().isoformat(),
                'decision': action
            }
            
            supabase.table('reports').update(update_data).eq('id', report_id).execute()
            
            # Log audit
            try:
                audit_data = {
                    'action': 'GOODS_SERVICES_VIOLATION_HANDLED',
                    'entity_name': 'goods_services_report',
                    'entity_id': str(report_id),
                    'old_data': report,
                    'new_data': {
                        'action': action,
                        'actions_taken': actions_taken,
                        'post_id': post_id,
                        'user_id': user_id
                    }
                }
                supabase.table('audit_logs').insert(audit_data).execute()
            except Exception as e:
                logger.warning(f"Audit log failed: {e}")
            
            return Response({
                'success': True,
                'message': result_message,
                'action': action,
                'actions_taken': actions_taken
            })
            
        except Exception as e:
            logger.error(f"Error reviewing report: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _notify_admins(self, report):
        """Notify admins of new report"""
        try:
            admin_resp = supabase.table('users').select('id').eq('role', 'admin').execute()
            admin_ids = [a['id'] for a in admin_resp.data] if admin_resp.data else []
            
            if admin_ids:
                notif_data = {
                    'title': 'New Goods & Services Report',
                    'message': f'{report["title"]} - Priority: {report["priority"].upper()}',
                    'type': 'report',
                    'created_at': datetime.now().isoformat()
                }
                
                notif = supabase.table('notifications').insert(notif_data).execute()
                if notif.data:
                    recipients = [{
                        'notification_id': notif.data[0]['id'],
                        'user_id': aid,
                        'role': 'admin',
                        'delivery_status': 'sent'
                    } for aid in admin_ids]
                    supabase.table('notification_recipients').insert(recipients).execute()
        except Exception as e:
            logger.warning(f"Failed to notify admins: {e}")
    
    def _notify_user(self, user_id, title, message):
        """Notify user"""
        try:
            notif_data = {
                'title': title,
                'message': message,
                'type': 'system',
                'created_at': datetime.now().isoformat()
            }
            
            notif = supabase.table('notifications').insert(notif_data).execute()
            if notif.data:
                recipient = {
                    'notification_id': notif.data[0]['id'],
                    'user_id': user_id,
                    'delivery_status': 'sent'
                }
                supabase.table('notification_recipients').insert(recipient).execute()
        except Exception as e:
            logger.warning(f"Failed to notify user: {e}")
