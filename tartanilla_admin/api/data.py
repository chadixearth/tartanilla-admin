from tartanilla_admin.supabase import supabase

def get_customers():
    # Fetch users with role 'tourist' from Supabase
    response = supabase.table('users').select('*').eq('role', 'tourist').execute()
    if hasattr(response, 'data'):
        return response.data
    return []

def get_owners():
    # Fetch users with role 'owner' or 'driver-owner' from Supabase
    response = supabase.table('users').select('*').in_('role', ['owner', 'driver-owner']).execute()
    if hasattr(response, 'data'):
        return response.data
    return []