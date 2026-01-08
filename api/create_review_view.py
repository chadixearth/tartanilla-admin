from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from tartanilla_admin.supabase import supabase
from datetime import datetime

@api_view(['POST'])
def create_review(request):
    """Create review with proper is_anonymous handling"""
    try:
        data = request.data
        
        # Extract is_anonymous from request
        is_anonymous = data.get('is_anonymous', False)
        
        # Ensure it's a proper boolean
        if isinstance(is_anonymous, str):
            is_anonymous = is_anonymous.lower() in ['true', '1', 'yes']
        
        # Create review data
        review_data = {
            'package_id': data.get('package_id'),
            'booking_id': data.get('booking_id'),
            'reviewer_id': data.get('reviewer_id'),
            'rating': int(data.get('rating')),
            'comment': data.get('comment', ''),
            'is_anonymous': bool(is_anonymous),
            'created_at': datetime.now().isoformat(),
            'is_published': True
        }
        
        # Insert into database
        result = supabase.table('package_reviews').insert(review_data).execute()
        
        return Response({
            'success': True,
            'data': result.data[0] if result.data else None,
            'message': 'Review created successfully'
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)