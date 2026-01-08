from tartanilla_admin.supabase import supabase, supabase_admin, execute_with_retry
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

def get_customers():
    """Fetch users with role 'tourist' from Supabase with retry logic"""
    try:
        client = supabase_admin if supabase_admin else supabase
        def query():
            return client.table('users').select('*').eq('role', 'tourist').execute()
        
        response = execute_with_retry(query)
        if hasattr(response, 'data'):
            # Normalize field names for template compatibility
            customers = []
            for user in response.data:
                customer = dict(user)
                # Split name field into first_name and last_name for template compatibility
                if 'name' in customer and customer['name']:
                    name_parts = customer['name'].split(' ', 1)
                    customer['first_name'] = name_parts[0] if name_parts else ''
                    customer['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
                else:
                    customer['first_name'] = ''
                    customer['last_name'] = ''
                # Add missing fields with defaults
                customer.setdefault('phone', '')
                customer.setdefault('address', '')
                customer.setdefault('date_of_birth', '')
                # Map profile photo URL to profile_photo for template compatibility
                if customer.get('profile_photo_url'):
                    customer['profile_photo'] = {'url': customer['profile_photo_url']}
                else:
                    customer['profile_photo'] = None
                customers.append(customer)
            return customers
        return []
    except Exception as e:
        logger.error(f"Error fetching customers: {e}")
        return []

def get_owners():
    """Fetch users with role 'owner' (including driver-owner) from Supabase with retry logic"""
    try:
        client = supabase_admin if supabase_admin else supabase
        def query():
            return client.table('users').select('*').in_('role', ['owner', 'driver-owner']).execute()
        
        response = execute_with_retry(query)
        if hasattr(response, 'data'):
            # Normalize field names for template compatibility
            owners = []
            for user in response.data:
                owner = dict(user)
                # Split name field into first_name and last_name for template compatibility
                if 'name' in owner and owner['name']:
                    name_parts = owner['name'].split(' ', 1)
                    owner['first_name'] = name_parts[0] if name_parts else ''
                    owner['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
                else:
                    owner['first_name'] = ''
                    owner['last_name'] = ''
                # Add missing fields with defaults for template compatibility
                owner.setdefault('phone', '')
                owner.setdefault('address', '')
                owner.setdefault('date_of_birth', '')
                # Map profile photo URL to profile_photo for template compatibility
                if owner.get('profile_photo_url'):
                    owner['profile_photo'] = {'url': owner['profile_photo_url']}
                else:
                    owner['profile_photo'] = None
                # Map field names for owners template
                owner['firstname'] = owner['first_name']
                owner['lastname'] = owner['last_name']
                owner['dob'] = owner['date_of_birth']
                owners.append(owner)
            return owners
        return []
    except Exception as e:
        logger.error(f"Error fetching owners: {e}")
        return []

def get_drivers():
    """Fetch users with role 'driver' (including driver-owner) from Supabase with retry logic"""
    try:
        client = supabase_admin if supabase_admin else supabase
        def query():
            return client.table('users').select('*').in_('role', ['driver', 'driver-owner']).execute()
        
        response = execute_with_retry(query)
        if hasattr(response, 'data'):
            # Normalize field names for template compatibility
            drivers = []
            for user in response.data:
                driver = dict(user)
                # Split name field into first_name and last_name for template compatibility
                if 'name' in driver and driver['name']:
                    name_parts = driver['name'].split(' ', 1)
                    driver['first_name'] = name_parts[0] if name_parts else ''
                    driver['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
                else:
                    driver['first_name'] = ''
                    driver['last_name'] = ''
                # Add missing fields with defaults
                driver.setdefault('phone', '')
                driver.setdefault('address', '')
                driver.setdefault('date_of_birth', '')
                # Map profile photo URL to profile_photo for template compatibility
                if driver.get('profile_photo_url'):
                    driver['profile_photo'] = {'url': driver['profile_photo_url']}
                else:
                    driver['profile_photo'] = None
                drivers.append(driver)
            return drivers
        return []
    except Exception as e:
        logger.error(f"Error fetching drivers: {e}")
        return []

def suspend_user(user_id, duration_days, reason, suspended_by):
    """
    Suspend a user for a specified duration with retry logic
    """
    try:
        client = supabase_admin if supabase_admin else supabase
        # Calculate suspension end date
        suspended_until = datetime.now() + timedelta(days=duration_days)
        
        def query():
            return client.table('users').update({
                'status': 'Suspended',
                'suspended_until': suspended_until.isoformat(),
                'suspension_reason': reason,
                'suspended_by': suspended_by,
                'suspended_at': datetime.now().isoformat()
            }).eq('id', user_id).execute()
        
        response = execute_with_retry(query)
        
        if hasattr(response, 'data') and response.data:
            return {'success': True, 'message': 'User suspended successfully'}
        else:
            return {'success': False, 'error': 'Failed to suspend user'}
    except Exception as e:
        logger.error(f"Error suspending user {user_id}: {e}")
        return {'success': False, 'error': str(e)}

def unsuspend_user(user_id, unsuspended_by):
    """
    Remove suspension from a user with retry logic
    """
    try:
        client = supabase_admin if supabase_admin else supabase
        def query():
            return client.table('users').update({
                'status': 'Active',
                'suspended_until': None,
                'suspension_reason': None,
                'suspended_by': None,
                'suspended_at': None
            }).eq('id', user_id).execute()
        
        response = execute_with_retry(query)
        
        if hasattr(response, 'data') and response.data:
            return {'success': True, 'message': 'User unsuspended successfully'}
        else:
            return {'success': False, 'error': 'Failed to unsuspend user'}
    except Exception as e:
        logger.error(f"Error unsuspending user {user_id}: {e}")
        return {'success': False, 'error': str(e)}

def check_and_update_expired_suspensions():
    """
    Check for expired suspensions and automatically unsuspend users with retry logic
    """
    try:
        client = supabase_admin if supabase_admin else supabase
        current_time = datetime.now().isoformat()
        
        def query():
            return client.table('users').update({
                'status': 'Active',
                'suspended_until': None,
                'suspension_reason': None,
                'suspended_by': None,
                'suspended_at': None
            }).eq('status', 'Suspended').lt('suspended_until', current_time).execute()
        
        response = execute_with_retry(query)
        
        return {'success': True, 'updated_count': len(response.data) if hasattr(response, 'data') else 0}
    except Exception as e:
        logger.error(f"Error checking expired suspensions: {e}")
        return {'success': False, 'error': str(e)}

#To get tartanillas by owner
# def get_tartanillas_by_owner():
#     response = supabase.table('tartanillas').select('*').eq('owner_id',owner_id).execute()
#     if hasattr(response, 'data'):
#         return response.data
#     return []