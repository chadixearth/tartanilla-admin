from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from tartanilla_admin.supabase import supabase, supabase_admin
from datetime import datetime, timedelta, timezone
import json
import logging

logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class BookingTimeoutAPI(APIView):
    """
    API to handle booking timeouts when no driver accepts within 6 hours
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Check and process bookings that have timed out (no driver acceptance within 6 hours)"""
        try:
            result = self._check_and_timeout_bookings()
            return Response(result)
        except Exception as e:
            logger.error(f"Error in booking timeout check: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _check_and_timeout_bookings(self):
        """Check for bookings that have been pending for more than 6 hours without driver acceptance"""
        try:
            # Calculate 6 hours ago
            six_hours_ago = datetime.now(timezone.utc) - timedelta(hours=6)
            
            # Use admin client to bypass RLS
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Find bookings that are still pending and created more than 6 hours ago
            query = admin_client.table('bookings').select('*').eq('status', 'pending')
            response = query.execute()
            
            bookings_to_timeout = []
            if hasattr(response, 'data') and response.data:
                for booking in response.data:
                    created_at = booking.get('created_at')
                    if created_at:
                        try:
                            created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            if created_time < six_hours_ago:
                                bookings_to_timeout.append(booking)
                        except Exception as e:
                            logger.error(f"Error parsing created_at for booking {booking.get('id')}: {e}")
            
            timed_out_count = 0
            for booking in bookings_to_timeout:
                try:
                    # Update booking status to suggest rebooking
                    update_data = {
                        'status': 'no_driver_available',
                        'timeout_reason': 'No driver accepted within 6 hours',
                        'timed_out_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    
                    admin_client.table('bookings').update(update_data).eq('id', booking['id']).execute()
                    
                    # Notify customer with rebooking options
                    self._notify_customer_timeout(booking)
                    
                    timed_out_count += 1
                    logger.info(f"Timed out booking {booking['id']} - no driver acceptance within 6 hours")
                    
                except Exception as e:
                    logger.error(f"Error timing out booking {booking.get('id')}: {e}")
            
            return {
                'success': True,
                'message': f'Processed {timed_out_count} timed out bookings',
                'timed_out_count': timed_out_count
            }
            
        except Exception as e:
            logger.error(f"Error in timeout check: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _notify_customer_timeout(self, booking):
        """Notify customer that no driver accepted and suggest rebooking"""
        try:
            customer_id = booking.get('customer_id')
            if not customer_id:
                return
            
            package_name = booking.get('package_name', 'tour package')
            booking_date = booking.get('booking_date', 'your selected date')
            
            # Create notification
            notification_data = {
                'title': 'No Driver Available - Rebook Suggested 📅',
                'message': f'Unfortunately, no driver accepted your {package_name} booking for {booking_date}. We suggest rebooking for another date when more drivers are available.',
                'type': 'booking_timeout',
                'created_at': datetime.now().isoformat()
            }
            
            admin_client = supabase_admin if supabase_admin else supabase
            notification = admin_client.table('notifications').insert(notification_data).execute()
            
            if notification.data:
                notification_id = notification.data[0]['id']
                admin_client.table('notification_recipients').insert({
                    'notification_id': notification_id,
                    'user_id': customer_id,
                    'role': 'tourist',
                    'delivery_status': 'sent'
                }).execute()
                
                logger.info(f"Timeout notification sent to customer {customer_id}")
            
        except Exception as e:
            logger.error(f"Failed to notify customer of timeout: {e}")

@method_decorator(csrf_exempt, name='dispatch')
class RebookingAPI(APIView):
    """
    API to handle rebooking for timed out bookings
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Rebook a timed out booking with new date"""
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            booking_id = data.get('booking_id')
            new_date = data.get('new_date')
            new_time = data.get('new_time')
            customer_id = data.get('customer_id')
            
            if not all([booking_id, new_date, customer_id]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: booking_id, new_date, customer_id'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Use admin client to bypass RLS
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get original booking
            booking_response = admin_client.table('bookings').select('*').eq('id', booking_id).execute()
            if not (hasattr(booking_response, 'data') and booking_response.data):
                return Response({
                    'success': False,
                    'error': 'Booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            original_booking = booking_response.data[0]
            
            # Verify customer owns the booking
            if original_booking.get('customer_id') != customer_id:
                return Response({
                    'success': False,
                    'error': 'Unauthorized'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check if booking can be rebooked
            if original_booking.get('status') != 'no_driver_available':
                return Response({
                    'success': False,
                    'error': 'Only timed out bookings can be rebooked'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update booking with new date and reset to pending
            update_data = {
                'booking_date': new_date,
                'pickup_time': new_time or original_booking.get('pickup_time', '09:00:00'),
                'status': 'pending',
                'rebooked_at': datetime.now().isoformat(),
                'rebook_count': (original_booking.get('rebook_count', 0) + 1),
                'updated_at': datetime.now().isoformat(),
                # Clear timeout fields
                'timeout_reason': None,
                'timed_out_at': None
            }
            
            result = admin_client.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            if hasattr(result, 'data') and result.data:
                # Notify drivers of the rebooked booking
                self._notify_drivers_of_rebook(result.data[0])
                
                return Response({
                    'success': True,
                    'data': result.data[0],
                    'message': 'Booking successfully rebooked. Drivers will be notified of your new booking.'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to rebook'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except json.JSONDecodeError:
            return Response({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error rebooking: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _notify_drivers_of_rebook(self, booking):
        """Notify drivers of rebooked booking"""
        try:
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get all drivers
            drivers = admin_client.table('users').select('id, name').in_('role', ['driver', 'driver-owner']).execute()
            if not drivers.data:
                return
            
            driver_ids = [d['id'] for d in drivers.data]
            
            # Create notification
            tourist_name = booking.get('customer_name', 'A tourist')
            package_name = booking.get('package_name', 'Tour Package')
            pax_count = booking.get('number_of_pax', 1)
            pickup_time = booking.get('pickup_time', '09:00')
            booking_date = booking.get('booking_date', 'TBD')
            
            notification_data = {
                'title': 'Rebooked Tour Available! 🔄',
                'message': f'{tourist_name} rebooked {package_name} ({pax_count} pax) for {booking_date} at {pickup_time}. New opportunity to accept!',
                'type': 'booking_rebook',
                'created_at': datetime.now().isoformat()
            }
            
            notification = admin_client.table('notifications').insert(notification_data).execute()
            
            if notification.data:
                notification_id = notification.data[0]['id']
                
                recipients = []
                for driver_id in driver_ids:
                    recipients.append({
                        'notification_id': notification_id,
                        'user_id': driver_id,
                        'role': 'driver',
                        'delivery_status': 'sent'
                    })
                
                if recipients:
                    admin_client.table('notification_recipients').insert(recipients).execute()
                    logger.info(f"Rebook notification sent to {len(recipients)} drivers")
            
        except Exception as e:
            logger.error(f"Failed to notify drivers of rebook: {e}")

@method_decorator(csrf_exempt, name='dispatch')
class CancelTimeoutBookingAPI(APIView):
    """
    API to cancel a timed out booking instead of rebooking
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        """Cancel a timed out booking"""
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else request.data
            
            booking_id = data.get('booking_id')
            customer_id = data.get('customer_id')
            reason = data.get('reason', 'No driver available - customer cancelled')
            
            if not all([booking_id, customer_id]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: booking_id, customer_id'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Use admin client to bypass RLS
            admin_client = supabase_admin if supabase_admin else supabase
            
            # Get booking
            booking_response = admin_client.table('bookings').select('*').eq('id', booking_id).execute()
            if not (hasattr(booking_response, 'data') and booking_response.data):
                return Response({
                    'success': False,
                    'error': 'Booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            booking = booking_response.data[0]
            
            # Verify customer owns the booking
            if booking.get('customer_id') != customer_id:
                return Response({
                    'success': False,
                    'error': 'Unauthorized'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check if booking can be cancelled
            if booking.get('status') not in ['no_driver_available', 'pending']:
                return Response({
                    'success': False,
                    'error': 'Booking cannot be cancelled'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Cancel the booking
            update_data = {
                'status': 'cancelled',
                'cancel_reason': reason,
                'cancelled_by': 'customer',
                'cancelled_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            result = admin_client.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            if hasattr(result, 'data') and result.data:
                return Response({
                    'success': True,
                    'data': result.data[0],
                    'message': 'Booking cancelled successfully. Full refund will be processed if payment was made.'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to cancel booking'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except json.JSONDecodeError:
            return Response({
                'success': False,
                'error': 'Invalid JSON data'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error cancelling timeout booking: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)