def user_data(request):
    """
    Add user_id and pending reports to all template contexts
    """
    context = {
        'user_id': request.user.id if request.user.is_authenticated else ''
    }
    
    # Add pending reports count for sidebar badge
    try:
        from tartanilla_admin.supabase import supabase
        response = supabase.table('reports').select('id').eq('status', 'pending').execute()
        pending_reports = response.data if hasattr(response, 'data') else []
        context['pending_reports'] = pending_reports
    except:
        context['pending_reports'] = []
    
    return context