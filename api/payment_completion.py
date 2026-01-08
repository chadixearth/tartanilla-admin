from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase
from datetime import datetime
import json

@method_decorator(csrf_exempt, name='dispatch')
class PaymentCompletionAPI(APIView):
    """
    API endpoint to handle payment completion and update booking status
    """
    
    def get(self, request):
        """Test endpoint to verify API is working"""
        return Response({
            'success': True,
            'message': 'Payment completion API is working',
            'endpoint': '/api/payment/complete/',
            'methods': ['GET', 'POST']
        })
    
    def post(self, request):
        """Update booking status after successful payment"""
        try:
            print(f'[PaymentCompletion] Received request: {request.method} {request.path}')
            print(f'[PaymentCompletion] Request body: {request.body}')
            
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            print(f'[PaymentCompletion] Parsed data: {data}')
            
            booking_id = data.get('booking_id')
            payment_status = data.get('payment_status')  # 'paid' or 'failed'
            payment_reference = data.get('payment_reference')
            
            print(f'[PaymentCompletion] Processing: booking_id={booking_id}, payment_status={payment_status}')
            
            if not booking_id or not payment_status:
                return Response({
                    'success': False,
                    'error': 'Missing booking_id or payment_status'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get the booking
            print(f'[PaymentCompletion] Fetching booking: {booking_id}')
            booking_response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            print(f'[PaymentCompletion] Booking response: {booking_response}')
            
            if not booking_response.data:
                return Response({
                    'success': False,
                    'error': 'Booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            booking = booking_response.data[0]
            
            # Update booking based on payment status
            if payment_status == 'paid':
                # Payment successful - update payment_status to paid (keep status as driver_assigned)
                update_data = {
                    'payment_status': 'paid',
                    'payment_method': data.get('payment_method', 'gcash'),
                    'payment_reference': payment_reference,
                    'paid_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                # Update booking
                update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
                
                if update_response.data:
                    updated_booking = update_response.data[0]
                    
                    # Notify the assigned driver that payment is complete
                    try:
                        if updated_booking.get('driver_id'):
                            notification_data = {
                                'title': 'Payment Received! Ready to Start Trip ✅💰',
                                'message': f'Excellent! Payment has been received for booking {updated_booking.get("booking_reference", "N/A")} - {updated_booking.get("package_name", "Tour Package")}. The trip is now ready to start on the scheduled date. Check your ongoing bookings to begin the trip.',
                                'type': 'booking',
                                'created_at': datetime.now().isoformat()
                            }
                            
                            notification = supabase.table('notifications').insert(notification_data).execute()
                            
                            if notification.data:
                                notification_id = notification.data[0]['id']
                                supabase.table('notification_recipients').insert({
                                    'notification_id': notification_id,
                                    'user_id': updated_booking['driver_id'],
                                    'role': 'driver',
                                    'delivery_status': 'sent'
                                }).execute()
                    except Exception as e:
                        print(f"Failed to notify driver of payment: {e}")
                    
                    # Notify the customer that payment is confirmed
                    try:
                        if updated_booking.get('customer_id'):
                            notification_data = {
                                'title': 'Payment Confirmed! ✅',
                                'message': f'Your payment for {updated_booking.get("package_name", "Tour Package")} has been confirmed. Your booking is now confirmed and your driver is ready. See you on {updated_booking.get("booking_date", "the scheduled date")}!',
                                'type': 'booking',
                                'created_at': datetime.now().isoformat()
                            }
                            
                            notification = supabase.table('notifications').insert(notification_data).execute()
                            
                            if notification.data:
                                notification_id = notification.data[0]['id']
                                supabase.table('notification_recipients').insert({
                                    'notification_id': notification_id,
                                    'user_id': updated_booking['customer_id'],
                                    'role': 'tourist',
                                    'delivery_status': 'sent'
                                }).execute()
                    except Exception as e:
                        print(f"Failed to notify customer of payment confirmation: {e}")
                    
                    return Response({
                        'success': True,
                        'data': updated_booking,
                        'message': 'Payment completed successfully. Driver can now start the trip on the scheduled date.'
                    })
                else:
                    return Response({
                        'success': False,
                        'error': 'Failed to update booking status'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
            else:
                # Payment failed - keep as pending or mark as failed
                update_data = {
                    'payment_status': 'failed',
                    'payment_reference': payment_reference,
                    'updated_at': datetime.now().isoformat()
                }
                
                update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
                
                return Response({
                    'success': True,
                    'data': update_response.data[0] if update_response.data else booking,
                    'message': 'Payment failed. Please try again.'
                })
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f'[PaymentCompletion] Error processing payment completion: {str(e)}')
            print(f'[PaymentCompletion] Full traceback: {error_details}')
            return Response({
                'success': False,
                'error': str(e),
                'debug_info': error_details if hasattr(request, 'user') and getattr(request.user, 'is_staff', False) else None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
