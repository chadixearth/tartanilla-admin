from rest_framework.response import Response
from rest_framework import status
from datetime import datetime
from tartanilla_admin.supabase import supabase
import json

def review_goods_services_violation_api(request):
    """Handle goods & services violation review"""
    if request.method != 'POST':
        return Response({'success': False, 'error': 'POST required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
        report_id = data.get('report_id')
        decision = data.get('decision')
        admin_notes = data.get('admin_notes', '')
        suspension_days = int(data.get('suspension_days', 7))
        
        if not report_id or decision not in ['approve', 'reject']:
            return Response({'success': False, 'error': 'Invalid input'}, status=status.HTTP_400_BAD_REQUEST)
        
        report_response = supabase.table('reports').select('*').eq('id', report_id).execute()
        if not report_response.data:
            return Response({'success': False, 'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
        
        report = report_response.data[0]
        
        update_data = {
            'status': 'resolved',
            'decision': decision,
            'admin_notes': f"Decision: {decision.upper()}\n{admin_notes}",
            'updated_at': datetime.now().isoformat()
        }
        
        supabase.table('reports').update(update_data).eq('id', report_id).execute()
        
        message = f'Report marked as {decision}.'
        post_deleted = False
        user_suspended = False
        
        if decision == 'approve':
            try:
                post_id = report.get('related_booking_id')
                user_id = report.get('related_user_id')
                
                if post_id:
                    supabase.table('goods_services_profiles').update({'is_active': False}).eq('id', post_id).execute()
                    post_deleted = True
                
                if user_id:
                    from api.data import suspend_user
                    suspend_user(user_id, suspension_days, 'Goods & Services Violation', 'admin')
                    user_suspended = True
                
                message = f'Violation approved. Post deleted and user suspended for {suspension_days} days.'
            except Exception as e:
                return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({
            'success': True,
            'message': message,
            'post_deleted': post_deleted,
            'user_suspended': user_suspended
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
