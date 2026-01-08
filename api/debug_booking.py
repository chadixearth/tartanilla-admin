from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase

@method_decorator(csrf_exempt, name='dispatch')
class DebugBookingAPI(APIView):
    """
    Debug endpoint to check booking status
    """
    
    def get(self, request, booking_id=None):
        """Get booking details for debugging"""
        try:
            if not booking_id:
                return Response({
                    'success': False,
                    'error': 'booking_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get the booking
            booking_response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            
            if not booking_response.data:
                return Response({
                    'success': False,
                    'error': 'Booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            booking = booking_response.data[0]
            
            return Response({
                'success': True,
                'data': booking,
                'debug_info': {
                    'current_status': booking.get('status'),
                    'payment_status': booking.get('payment_status'),
                    'driver_id': booking.get('driver_id'),
                    'booking_reference': booking.get('booking_reference'),
                    'total_amount': booking.get('total_amount'),
                }
            })
            
        except Exception as e:
            import traceback
            return Response({
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def post(self, request, booking_id=None):
        """Update booking status for testing"""
        try:
            if not booking_id:
                return Response({
                    'success': False,
                    'error': 'booking_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            data = request.data
            update_data = {}
            
            if 'status' in data:
                update_data['status'] = data['status']
            if 'payment_status' in data:
                update_data['payment_status'] = data['payment_status']
            
            if not update_data:
                return Response({
                    'success': False,
                    'error': 'No update data provided'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update booking
            update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            if update_response.data:
                return Response({
                    'success': True,
                    'data': update_response.data[0],
                    'message': 'Booking updated successfully'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to update booking'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            import traceback
            return Response({
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)