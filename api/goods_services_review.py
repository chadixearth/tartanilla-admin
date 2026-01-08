from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import action
from datetime import datetime
from tartanilla_admin.supabase import supabase, supabase_admin

def review_goods_services_violation(request, report_id):
    """Admin reviews goods & services violation and decides to approve or reject"""
    try:
        data = request.data if hasattr(request, 'data') else request.POST
        admin_decision = data.get('decision')
        admin_notes = data.get('admin_notes', '')
        suspension_days = int(data.get('suspension_days', 7))
        
        if admin_decision not in ['approve', 'reject']:
            return Response({'success': False, 'error': 'Decision must be approve or reject'}, status=status.HTTP_400_BAD_REQUEST)
        
        report_response = supabase.table('reports').select('*').eq('id', report_id).execute()
        if not report_response.data:
            return Response({'success': False, 'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
        
        report = report_response.data[0]
        if report.get('report_type') != 'Goods_Services_Violation':
            return Response({'success': False, 'error': 'Invalid report type'}, status=status.HTTP_400_BAD_REQUEST)
        
        client = supabase_admin if supabase_admin else supabase
        decision_note = f"Admin Decision: {admin_decision.upper()}\nReview Date: {datetime.now().isoformat()}\n{admin_notes}"
        update_data = {
            'status': 'resolved',
            'admin_notes': decision_note,
            'decision': admin_decision
        }
        
        client.table('reports').update(update_data).eq('id', report_id).execute()
        
        post_deleted = False
        user_suspended = False
        message = f'Report marked as {admin_decision}.'
        
        if admin_decision == 'approve':
            try:
                post_id = report.get('related_booking_id')
                user_id = report.get('related_user_id')
                
                if post_id:
                    client.table('goods_services_profiles').update({'is_active': False}).eq('id', post_id).execute()
                    post_deleted = True
                
                if user_id:
                    from api.data import suspend_user
                    suspension = suspend_user(user_id, suspension_days, 'Goods & Services Violation - Post removed', 'admin')
                    user_suspended = suspension.get('success', False) if suspension else False
                
                message = f'Violation approved. Post deleted and user suspended for {suspension_days} days.'
            except Exception as e:
                return Response({'success': False, 'error': f'Failed to process approval: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            message = 'Report rejected. No action taken.'
        
        return Response({
            'success': True,
            'message': message,
            'post_deleted': post_deleted,
            'user_suspended': user_suspended,
            'admin_decision': admin_decision
        })
    except Exception as e:
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
