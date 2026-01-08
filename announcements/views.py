from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from tartanilla_admin.supabase import supabase, supabase_admin, execute_with_retry
from datetime import datetime
import json

def admin_authenticated(view_func):
    """Decorator to check admin authentication"""
    from functools import wraps
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.COOKIES.get('admin_authenticated') != '1':
            return redirect('/accounts/login/')
        
        # Get user info from cookies
        user_id = request.COOKIES.get('admin_user_id')
        user_email = request.COOKIES.get('admin_email')
        
        # Set user information on request object
        request.user = type('AdminUser', (), {
            'is_authenticated': True,
            'is_active': True,
            'id': user_id,
            'pk': user_id,
            'email': user_email,
            '__str__': lambda self: self.email
        })
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@admin_authenticated
def announcements_page(request):
    """Render the announcements management page"""
    return render(request, 'announcements/announcements.html', {'user': request.COOKIES.get('admin_email')})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def send_announcement(request):
    """Send announcement to all users"""
    try:
        data = json.loads(request.body)
        announcement_type = data.get('type', 'general')
        message = data.get('message', '')
        target_roles = data.get('roles', ['tourist', 'driver', 'owner'])
        
        if not message:
            return JsonResponse({'success': False, 'error': 'Message is required'})
        
        if not target_roles:
            return JsonResponse({'success': False, 'error': 'At least one user role must be selected'})
        
        print(f"Sending announcement to roles: {target_roles}")
        
        # Map frontend roles to database roles
        db_roles = []
        for role in target_roles:
            if role == 'owner':
                db_roles.extend(['owner', 'driver-owner'])
            else:
                db_roles.append(role)
        
        print(f"Database roles to query: {db_roles}")
        
        # Get users with specified roles
        client = supabase_admin if supabase_admin else supabase
        def query():
            return client.table('users').select('id,role,email').in_('role', db_roles).execute()
        
        users = execute_with_retry(query)
        
        print(f"Query returned {len(users.data or [])} users")
        
        if not hasattr(users, 'data') or not users.data:
            return JsonResponse({'success': False, 'error': f'No users found with roles: {db_roles}'})
        
        user_data = [(user['id'], user['role']) for user in users.data]
        print(f"User data: {[(user['email'], user['role']) for user in users.data][:5]}...")
        
        # Create notification using same client
        def create_notification():
            return client.table('notifications').insert({
                'title': f'{announcement_type.title()} Announcement',
                'message': message,
                'type': 'announcement',
                'created_at': datetime.now().isoformat()
            }).execute()
        
        notification = execute_with_retry(create_notification)
        
        if notification.data:
            notification_id = notification.data[0]['id']
            
            # Create recipients with actual user roles
            recipients = []
            for user_id, role in user_data:
                # Map roles correctly for notification recipients
                recipient_role = role
                if role == 'driver-owner':
                    recipient_role = 'owner'  # Map driver-owner to owner for notifications
                elif role == 'tourist':
                    recipient_role = 'tourist'
                elif role == 'driver':
                    recipient_role = 'driver'
                
                recipients.append({
                    'notification_id': notification_id,
                    'user_id': user_id,
                    'role': recipient_role,
                    'delivery_status': 'sent'
                })
            
            print(f"Creating {len(recipients)} notification recipients for announcement")
            
            def create_recipients():
                return client.table('notification_recipients').insert(recipients).execute()
            
            execute_with_retry(create_recipients)
            
            # Log to audit trail
            try:
                admin_email = request.COOKIES.get('admin_email', 'Unknown Admin')
                admin_id = request.COOKIES.get('admin_user_id', 'Unknown')
                
                audit_data = {
                    'user_id': admin_id,
                    'username': admin_email,
                    'role': 'admin',
                    'action': 'ANNOUNCEMENT_SENT',
                    'entity_name': 'ANNOUNCEMENT',
                    'entity_id': str(notification_id),
                    'new_data': {
                        'type': announcement_type,
                        'message': message[:100] + '...' if len(message) > 100 else message,
                        'recipients_count': len(user_data),
                        'timestamp': datetime.now().isoformat()
                    },
                    'ip_address': request.META.get('REMOTE_ADDR', 'Unknown')
                }
                
                client.table('audit_logs').insert(audit_data).execute()
            except Exception as e:
                print(f"Failed to log announcement: {e}")
            
            return JsonResponse({
                'success': True,
                'message': f'Announcement sent to {len(user_data)} users'
            })
        
        return JsonResponse({'success': False, 'error': 'Failed to create notification'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})