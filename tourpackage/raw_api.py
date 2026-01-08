from django.http import HttpResponse
import json

def raw_toggle_status(request, package_id):
    """Raw endpoint that bypasses all Django middleware"""
    try:
        from tartanilla_admin.supabase import supabase
        
        # Get current status
        response = supabase.table('tourpackages').select('is_active').eq('id', package_id).single().execute()
        if not (hasattr(response, 'data') and response.data):
            data = {'success': False, 'error': 'Package not found'}
        else:
            current_status = response.data.get('is_active', False)
            new_status = not current_status
            
            # Update status
            update_response = supabase.table('tourpackages').update({'is_active': new_status}).eq('id', package_id).execute()
            
            if hasattr(update_response, 'data') and update_response.data:
                data = {'success': True, 'message': 'Status updated successfully'}
            else:
                data = {'success': False, 'error': 'Update failed'}
        
        response = HttpResponse()
        response['Content-Type'] = 'application/json'
        response.content = json.dumps(data).encode('utf-8')
        return response
        
    except Exception as e:
        error_data = {'success': False, 'error': 'Server error'}
        response = HttpResponse()
        response['Content-Type'] = 'application/json'
        response.content = json.dumps(error_data).encode('utf-8')
        return response