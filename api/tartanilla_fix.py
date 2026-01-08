# Quick fix for tartanilla.py create method
# Replace lines 155-167 in the create method with this:

# OLD CODE (lines 155-167):
# Validate that the owner exists and has the correct role
# owner_response = supabase.table('users').select('id, role').eq('id', data['assigned_owner_id']).execute()
# if not hasattr(owner_response, 'data') or not owner_response.data:
#     return Response({
#         'success': False,
#         'error': 'Owner not found'
#     }, status=status.HTTP_400_BAD_REQUEST)
# 
# owner_data = owner_response.data[0]
# if owner_data['role'] not in ['owner', 'driver-owner']:
#     return Response({
#         'success': False,
#         'error': 'User must be an owner to create tartanilla carriages'
#     }, status=status.HTTP_400_BAD_REQUEST)

# NEW CODE:
owner_id = data['assigned_owner_id']
owner_response = supabase.table('users').select('id, role').eq('id', owner_id).execute()

if hasattr(owner_response, 'data') and owner_response.data:
    owner_data = owner_response.data[0]
    if owner_data['role'] not in ['owner', 'driver-owner']:
        return Response({
            'success': False,
            'error': 'User must be an owner to create tartanilla carriages'
        }, status=status.HTTP_400_BAD_REQUEST)
