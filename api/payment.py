from rest_framework import viewsets, status as http_status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from tartanilla_admin.supabase import supabase
from datetime import datetime
import json
import uuid
import traceback
import requests
import hashlib
import hmac
import logging
from decimal import Decimal
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

# Configure logging
logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class PaymentViewSet(viewsets.ViewSet):
    """ViewSet for PayMongo payment processing with mobile optimization"""
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer, BrowsableAPIRenderer]
    
    # PayMongo configuration
    PAYMONGO_SECRET_KEY = getattr(settings, 'PAYMONGO_SECRET_KEY', 'sk_test_your_secret_key_here')
    PAYMONGO_PUBLIC_KEY = getattr(settings, 'PAYMONGO_PUBLIC_KEY', 'pk_test_your_public_key_here')
    PAYMONGO_WEBHOOK_SECRET = getattr(settings, 'PAYMONGO_WEBHOOK_SECRET', 'whsec_your_webhook_secret_here')
    PAYMONGO_BASE_URL = 'https://api.paymongo.com/v1'
    
    def dispatch(self, request, *args, **kwargs):
        """Override dispatch to handle mobile-specific headers"""
        response = super().dispatch(request, *args, **kwargs)
        
        # Add mobile-friendly headers
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, ngrok-skip-browser-warning'
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
        
        return response
    
    def list(self, request):
        """List endpoint to show available payment actions in API root"""
        return Response({
            'message': 'Payment API - PayMongo Integration',
            'available_endpoints': {
                'create_payment': f'{request.build_absolute_uri()}create-payment/',
                'mobile_payment': f'{request.build_absolute_uri()}mobile-payment/',
                'confirm_payment': f'{request.build_absolute_uri()}confirm-payment/',
                'webhook': f'{request.build_absolute_uri()}webhook/',
                'payment_status': f'{request.build_absolute_uri()}status/{{payment_id}}/'
            },
            'supported_payment_methods': ['gcash', 'grab_pay', 'paymaya', 'card'],
            'documentation': 'See MOBILE_PAYMENT_INTEGRATION_GUIDE.md for detailed integration instructions'
        })
    
    def _get_paymongo_headers(self):
        """Get headers for PayMongo API requests with improved error handling"""
        try:
            import base64
            if not self.PAYMONGO_SECRET_KEY or self.PAYMONGO_SECRET_KEY == 'sk_test_your_secret_key_here':
                logger.error("PayMongo secret key not configured")
                raise ValueError("PayMongo secret key not configured. Please check your environment variables.")
                
            auth_string = f"{self.PAYMONGO_SECRET_KEY}:"
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            return {
                'Authorization': f'Basic {encoded_auth}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
        except Exception as e:
            logger.error(f"Error creating PayMongo headers: {str(e)}")
            raise
    
    def _create_payment_intent(self, amount, currency='PHP', description='Tour Package Booking', return_url=None):
        """Create a PayMongo payment intent with mobile optimization"""
        try:
            url = f"{self.PAYMONGO_BASE_URL}/payment_intents"
            
            # Validate amount
            if amount <= 0:
                return {'success': False, 'error': 'Amount must be greater than zero'}
            
            # Convert amount to centavos (PayMongo expects amount in smallest currency unit)
            amount_in_centavos = int(amount * 100)
            
            # Base payload for mobile-optimized payment intent
            payload = {
                "data": {
                    "attributes": {
                        "amount": amount_in_centavos,
                        "payment_method_allowed": [
                            "gcash",
                            "grab_pay",
                            "paymaya",
                            "card"
                        ],
                        "payment_method_options": {
                            "card": {
                                "request_three_d_secure": "any"
                            }
                        },
                        "currency": currency,
                        "description": description,
                        "capture_type": "automatic",
                        "metadata": {
                            "source": "mobile_app",
                            "integration_version": "v1.0"
                        }
                    }
                }
            }
            
            # Add return URL if provided (useful for mobile deep linking)
            if return_url:
                payload["data"]["attributes"]["metadata"]["return_url"] = return_url
            
            # Validate URL to prevent SSRF
            from core.mobile_security import validate_url
            if not validate_url(url):
                logger.error(f"SSRF attempt blocked: {url}")
                return {'success': False, 'error': 'Invalid payment service URL'}
            
            logger.info(f"Creating PayMongo payment intent for amount: {amount} {currency}")
            response = requests.post(url, json=payload, headers=self._get_paymongo_headers(), timeout=30, allow_redirects=False)
            
            if response.status_code == 200:
                logger.info("PayMongo payment intent created successfully")
                return {'success': True, 'data': response.json()}
            else:
                error_msg = f"PayMongo API Error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {'success': False, 'error': error_msg, 'status_code': response.status_code}
                
        except requests.exceptions.Timeout:
            error_msg = "Request to PayMongo timed out. Please try again."
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
        except requests.exceptions.ConnectionError:
            error_msg = "Failed to connect to PayMongo. Please check your internet connection."
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
        except Exception as e:
            error_msg = f"Error creating payment intent: {str(e)}"
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
    
    def _create_paymongo_source(self, amount, payment_method_type, currency='PHP', description='Tour Package Booking'):
        """Create a PayMongo source for mobile payments"""
        try:
            url = f"{self.PAYMONGO_BASE_URL}/sources"
            
            # Validate URL to prevent SSRF
            from core.mobile_security import validate_url
            if not validate_url(url):
                logger.error(f"SSRF attempt blocked: {url}")
                return {'success': False, 'error': 'Invalid payment service URL'}
            
            # Convert amount to centavos
            amount_in_centavos = int(amount * 100)
            
            payload = {
                "data": {
                    "attributes": {
                        "amount": amount_in_centavos,
                        "currency": currency,
                        "type": payment_method_type,
                        "description": description,
                        "redirect": {
                            "success": "tartanilla://payment-success",
                            "failed": "tartanilla://payment-failed"
                        }
                    }
                }
            }
            
            logger.info(f"Creating PayMongo source for {payment_method_type}: {amount} {currency}")
            response = requests.post(url, json=payload, headers=self._get_paymongo_headers(), timeout=30, allow_redirects=False)
            
            if response.status_code == 200:
                logger.info("PayMongo source created successfully")
                return {'success': True, 'data': response.json()}
            else:
                error_msg = f"PayMongo Source API Error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {'success': False, 'error': error_msg, 'status_code': response.status_code}
                
        except requests.exceptions.Timeout:
            error_msg = "Request to PayMongo timed out. Please try again."
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
        except requests.exceptions.ConnectionError:
            error_msg = "Failed to connect to PayMongo. Please check your internet connection."
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
        except Exception as e:
            error_msg = f"Error creating PayMongo source: {str(e)}"
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
    
    def _create_payment_link(self, amount, payment_method_type, currency='PHP', description='Tour Package Booking'):
        """Create a PayMongo Payment Link for mobile payments"""
        try:
            url = f"{self.PAYMONGO_BASE_URL}/links"
            
            # Validate URL to prevent SSRF
            from core.mobile_security import validate_url
            if not validate_url(url):
                logger.error(f"SSRF attempt blocked: {url}")
                return {'success': False, 'error': 'Invalid payment service URL'}
            
            # Convert amount to centavos
            amount_in_centavos = int(amount * 100)
            
            payload = {
                "data": {
                    "attributes": {
                        "amount": amount_in_centavos,
                        "currency": currency,
                        "description": description,
                        "remarks": f"Payment for {description}"
                    }
                }
            }
            
            logger.info(f"Creating PayMongo payment link: {amount} {currency}")
            response = requests.post(url, json=payload, headers=self._get_paymongo_headers(), timeout=30, allow_redirects=False)
            
            if response.status_code == 200:
                logger.info("PayMongo payment link created successfully")
                return {'success': True, 'data': response.json()}
            else:
                error_msg = f"PayMongo Links API Error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {'success': False, 'error': error_msg, 'status_code': response.status_code}
                
        except requests.exceptions.Timeout:
            error_msg = "Request to PayMongo timed out. Please try again."
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
        except requests.exceptions.ConnectionError:
            error_msg = "Failed to connect to PayMongo. Please check your internet connection."
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
        except Exception as e:
            error_msg = f"Error creating PayMongo payment link: {str(e)}"
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
        """Create a payment method for the payment intent"""
        try:
            url = f"{self.PAYMONGO_BASE_URL}/payment_methods"
            
            # Validate URL to prevent SSRF
            from core.mobile_security import validate_url
            if not validate_url(url):
                logger.error(f"SSRF attempt blocked: {url}")
                return {'success': False, 'error': 'Invalid payment service URL'}
            
            payload = {
                "data": {
                    "attributes": {
                        "type": payment_details.get('type', 'gcash'),
                        "details": payment_details.get('details', {})
                    }
                }
            }
            
            response = requests.post(url, json=payload, headers=self._get_paymongo_headers(), timeout=30, allow_redirects=False)
            
            if response.status_code == 200:
                payment_method = response.json()
                # Attach payment method to payment intent
                return self._attach_payment_method(payment_intent_id, payment_method['data']['id'])
            else:
                print(f"PayMongo Payment Method Error: {response.status_code} - {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            print(f"Error creating payment method: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _attach_payment_method(self, payment_intent_id, payment_method_id):
        """Attach payment method to payment intent"""
        try:
            url = f"{self.PAYMONGO_BASE_URL}/payment_intents/{payment_intent_id}/attach"
            
            # Validate URL to prevent SSRF
            from core.mobile_security import validate_url
            if not validate_url(url):
                logger.error(f"SSRF attempt blocked: {url}")
                return {'success': False, 'error': 'Invalid payment service URL'}
            
            payload = {
                "data": {
                    "attributes": {
                        "payment_method": payment_method_id,
                        "client_key": self.PAYMONGO_PUBLIC_KEY
                    }
                }
            }
            
            response = requests.post(url, json=payload, headers=self._get_paymongo_headers(), timeout=30, allow_redirects=False)
            
            if response.status_code == 200:
                return {'success': True, 'data': response.json()}
            else:
                print(f"PayMongo Attach Error: {response.status_code} - {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            print(f"Error attaching payment method: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @action(detail=False, methods=['post'], url_path='create-payment')
    def create_payment(self, request):
        """Create a payment for a booking with mobile optimization"""
        try:
            data = request.data
            logger.info(f"Creating payment with data: {data}")
            
            # Validate required fields
            required_fields = ['booking_id', 'payment_method_type']
            for field in required_fields:
                if not data.get(field):
                    return Response({
                        'success': False,
                        'error': f'Missing required field: {field}',
                        'error_code': 'MISSING_FIELD',
                        'field': field
                    }, status=http_status.HTTP_400_BAD_REQUEST)
            
            booking_id = data['booking_id']
            payment_method_type = data['payment_method_type']  # gcash, grab_pay, paymaya, card
            return_url = data.get('return_url')  # Optional return URL for mobile deep linking
            
            # Validate payment method
            valid_methods = ['gcash', 'grab_pay', 'paymaya', 'card']
            if payment_method_type not in valid_methods:
                return Response({
                    'success': False,
                    'error': f'Invalid payment method. Must be one of: {", ".join(valid_methods)}',
                    'error_code': 'INVALID_PAYMENT_METHOD',
                    'valid_methods': valid_methods
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            # Get booking details
            logger.info(f"Fetching booking details for ID: {booking_id}")
            booking_response = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
            
            if not booking_response.data:
                return Response({
                    'success': False,
                    'error': 'Booking not found',
                    'error_code': 'BOOKING_NOT_FOUND',
                    'booking_id': booking_id
                }, status=http_status.HTTP_404_NOT_FOUND)
            
            booking = booking_response.data
            
            # Check if booking is in correct status for payment
            valid_statuses = ['waiting_for_driver', 'pending']
            if booking['status'] not in valid_statuses:
                return Response({
                    'success': False,
                    'error': f'Cannot process payment for booking with status: {booking["status"]}',
                    'error_code': 'INVALID_BOOKING_STATUS',
                    'current_status': booking['status'],
                    'valid_statuses': valid_statuses
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            # Check if payment already exists for this booking
            existing_payment = supabase.table('payments').select('*').eq('booking_id', booking_id).eq('status', 'pending').execute()
            if existing_payment.data:
                existing = existing_payment.data[0]
                return Response({
                    'success': False,
                    'error': 'A pending payment already exists for this booking',
                    'error_code': 'PAYMENT_ALREADY_EXISTS',
                    'existing_payment_id': existing['id'],
                    'payment_intent_id': existing['payment_intent_id']
                }, status=http_status.HTTP_409_CONFLICT)
            
            # Create payment intent
            amount = Decimal(str(booking['total_amount']))
            description = f"Tour Package Booking - {booking['package_name']} ({booking['booking_reference']})"
            
            logger.info(f"Creating payment intent for amount: {amount}")
            payment_intent_result = self._create_payment_intent(
                amount, 
                description=description, 
                return_url=return_url
            )
            
            if not payment_intent_result['success']:
                return Response({
                    'success': False,
                    'error': 'Failed to create payment intent',
                    'error_code': 'PAYMENT_INTENT_CREATION_FAILED',
                    'details': payment_intent_result.get('error'),
                    'status_code': payment_intent_result.get('status_code')
                }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            payment_intent = payment_intent_result['data']['data']
            
            # Store payment record
            payment_data = {
                'id': str(uuid.uuid4()),
                'booking_id': booking_id,
                'payment_intent_id': payment_intent['id'],
                'amount': float(amount),
                'currency': 'PHP',
                'payment_method_type': payment_method_type,
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            # Insert payment record
            logger.info(f"Storing payment record: {payment_data['id']}")
            payment_response = supabase.table('payments').insert(payment_data).execute()
            
            if not payment_response.data:
                return Response({
                    'success': False,
                    'error': 'Failed to create payment record',
                    'error_code': 'DATABASE_ERROR'
                }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Update booking status to pending (awaiting payment)
            logger.info(f"Updating booking status to pending for booking: {booking_id}")
            supabase.table('bookings').update({
                'status': 'pending',
                'updated_at': datetime.now().isoformat()
            }).eq('id', booking_id).execute()
            
            # Get next action for mobile app handling
            next_action = payment_intent['attributes'].get('next_action')
            client_key = payment_intent['attributes'].get('client_key')
            
            # Prepare mobile-friendly response
            response_data = {
                'success': True,
                'data': {
                    'payment_id': payment_data['id'],
                    'payment_intent_id': payment_intent['id'],
                    'client_key': client_key,
                    'amount': float(amount),
                    'currency': 'PHP',
                    'status': 'pending',
                    'payment_method_type': payment_method_type,
                    'next_action': next_action,
                    'booking_reference': booking['booking_reference'],
                    'booking_id': booking_id,
                    'description': description,
                    'created_at': payment_data['created_at']
                },
                'message': 'Payment intent created successfully. Please proceed with payment.',
                'instructions': {
                    'mobile': 'Use the client_key and payment_intent_id to complete payment in your mobile app',
                    'web': 'Redirect user to the payment URL provided in next_action'
                }
            }
            
            logger.info(f"Payment creation successful for booking: {booking_id}")
            return Response(response_data, status=http_status.HTTP_201_CREATED)
            
        except Exception as e:
            error_msg = f'Error creating payment: {str(e)}'
            logger.error(error_msg)
            traceback.print_exc()
            return Response({
                'success': False,
                'error': error_msg,
                'error_code': 'INTERNAL_ERROR'
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='mobile-payment-with-source')
    def mobile_payment_with_source(self, request):
        """Create a mobile payment with PayMongo Source for checkout URL"""
        try:
            data = request.data
            logger.info(f"Mobile payment with source request: {data}")
            
            # Validate required fields
            required_fields = ['booking_id', 'payment_method']
            missing_fields = [field for field in required_fields if not data.get(field)]
            
            if missing_fields:
                return Response({
                    'success': False,
                    'error': 'Missing required fields',
                    'missing_fields': missing_fields
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            booking_id = data['booking_id']
            payment_method = data['payment_method']
            
            # Get booking details
            logger.info(f"Fetching booking details for ID: {booking_id}")
            booking_response = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
            
            if not booking_response.data:
                return Response({
                    'success': False,
                    'error': 'Booking not found',
                    'error_code': 'BOOKING_NOT_FOUND'
                }, status=http_status.HTTP_404_NOT_FOUND)
            
            booking = booking_response.data
            amount = Decimal(str(booking['total_amount']))
            description = f"Tour Package - {booking['package_name']} ({booking['booking_reference']})"
            
            # Create PayMongo Source for e-wallets
            if payment_method in ['gcash', 'grab_pay', 'paymaya']:
                logger.info(f"Creating PayMongo source for {payment_method}")
                source_result = self._create_payment_source(
                    amount, 
                    payment_method, 
                    description=description
                )
                
                if source_result['success']:
                    source_data = source_result['data']['data']
                    
                    # Store payment record with source info
                    payment_data = {
                        'id': str(uuid.uuid4()),
                        'booking_id': booking_id,
                        'payment_intent_id': source_data['id'],  # Use source ID as reference
                        'amount': float(amount),
                        'currency': 'PHP',
                        'payment_method_type': payment_method,
                        'status': 'pending',
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    
                    # Insert payment record
                    logger.info(f"Storing payment record: {payment_data['id']}")
                    payment_response = supabase.table('payments').insert(payment_data).execute()
                    
                    if payment_response.data:
                        # Return mobile-friendly response with checkout URL
                        return Response({
                            'success': True,
                            'payment_intent_id': source_data['id'],
                            'source_id': source_data['id'],
                            'checkout_url': source_data['attributes']['redirect']['checkout_url'],
                            'amount': float(amount),
                            'currency': 'PHP',
                            'payment_method': payment_method,
                            'booking_reference': booking['booking_reference'],
                            'status': source_data['attributes']['status'],
                            'next_action': {
                                'type': 'redirect',
                                'redirect': {
                                    'url': source_data['attributes']['redirect']['checkout_url']
                                }
                            },
                            'message': f'Payment source created for {payment_method}. Redirect to checkout URL.'
                        }, status=http_status.HTTP_201_CREATED)
                    else:
                        return Response({
                            'success': False,
                            'error': 'Failed to store payment record'
                        }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
                else:
                    return Response({
                        'success': False,
                        'error': 'Failed to create PayMongo source',
                        'details': source_result.get('error')
                    }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                # For other payment methods, fall back to regular mobile payment
                return self.mobile_payment(request)
                
        except Exception as e:
            error_msg = f'Error creating mobile payment with source: {str(e)}'
            logger.error(error_msg)
            traceback.print_exc()
            return Response({
                'success': False,
                'error': error_msg
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='source-status/(?P<source_id>[^/.]+)')
    def get_source_status(self, request, source_id=None):
        """Get PayMongo source status"""
        try:
            logger.info(f"Getting source status for: {source_id}")
            
            url = f"{self.PAYMONGO_BASE_URL}/sources/{source_id}"
            
            # Validate URL to prevent SSRF
            from core.mobile_security import validate_url
            if not validate_url(url):
                logger.error(f"SSRF attempt blocked: {url}")
                return Response({
                    'success': False,
                    'error': 'Invalid payment service URL'
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            response = requests.get(url, headers=self._get_paymongo_headers(), timeout=30, allow_redirects=False)
            
            if response.status_code == 200:
                source_data = response.json()['data']
                status = source_data['attributes']['status']
                
                logger.info(f"Source status: {status}")
                
                return Response({
                    'success': True,
                    'status': status,
                    'data': source_data
                }, status=http_status.HTTP_200_OK)
            else:
                error_msg = f"PayMongo Source Status Error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return Response({
                    'success': False,
                    'error': error_msg
                }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            error_msg = f'Error getting source status: {str(e)}'
            logger.error(error_msg)
            return Response({
                'success': False,
                'error': error_msg
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _create_payment_source(self, amount, payment_method, currency='PHP', description=None):
        """Create a PayMongo source for e-wallet payments"""
        try:
            url = f"{self.PAYMONGO_BASE_URL}/sources"
            
            # Validate URL to prevent SSRF
            from core.mobile_security import validate_url
            if not validate_url(url):
                logger.error(f"SSRF attempt blocked: {url}")
                return {'success': False, 'error': 'Invalid payment service URL'}
            
            # Convert amount to centavos
            amount_in_centavos = int(amount * 100)
            
            payload = {
                "data": {
                    "attributes": {
                        "amount": amount_in_centavos,
                        "currency": currency,
                        "type": payment_method,
                        "redirect": {
                            "success": "https://yourapp.com/payment-success",
                            "failed": "https://yourapp.com/payment-failed"
                        }
                    }
                }
            }
            
            if description:
                payload["data"]["attributes"]["description"] = description
            
            logger.info(f"Creating PayMongo source: {payment_method} for amount: {amount}")
            response = requests.post(url, json=payload, headers=self._get_paymongo_headers(), timeout=30, allow_redirects=False)
            
            if response.status_code == 200:
                logger.info("PayMongo source created successfully")
                return {'success': True, 'data': response.json()}
            else:
                error_msg = f"PayMongo Source API Error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {'success': False, 'error': error_msg}
                
        except requests.exceptions.Timeout:
            error_msg = "Request to PayMongo timed out. Please try again."
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}
        except Exception as e:
            error_msg = f"Error creating PayMongo source: {str(e)}"
            logger.error(error_msg)
            return {'success': False, 'error': error_msg}

    @action(detail=False, methods=['post'], url_path='mobile-payment')
    def mobile_payment(self, request):
        """Create a mobile-optimized payment with simplified response (fallback method)"""
        try:
            data = request.data
            logger.info(f"Mobile payment request: {data}")
            
            # Validate required fields
            required_fields = ['booking_id', 'payment_method']
            missing_fields = [field for field in required_fields if not data.get(field)]
            
            if missing_fields:
                return Response({
                    'success': False,
                    'error': 'Missing required fields',
                    'missing_fields': missing_fields
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            booking_id = data['booking_id']
            payment_method = data['payment_method']
            
            # Call the standard create_payment method
            payment_data = {
                'booking_id': booking_id,
                'payment_method_type': payment_method
            }
            
            # Create a mock request object
            mock_request = type('MockRequest', (), {'data': payment_data})()
            response = self.create_payment(mock_request)
            
            if response.status_code == 201:  # HTTP_201_CREATED
                # For mobile payments, return the payment intent data for client-side processing
                original_data = response.data['data']
                payment_intent_id = original_data['payment_intent_id']
                client_key = original_data['client_key']
                
                next_action = {
                    "type": "client_side_payment",
                    "payment_intent": {
                        "id": payment_intent_id,
                        "client_key": client_key,
                        "payment_method_types": [payment_method]
                    }
                }
                
                return Response({
                    'success': True,
                    'payment_intent_id': payment_intent_id,
                    'client_key': client_key,
                    'amount': original_data['amount'],
                    'currency': original_data['currency'],
                    'payment_method': payment_method,
                    'booking_reference': original_data['booking_reference'],
                    'next_action': next_action,
                    'message': 'Payment ready. Use PayMongo SDK in mobile app to complete payment.',
                    'instructions': {
                        'mobile': 'Use PayMongo React Native SDK with the provided client_key and payment_intent_id',
                        'fallback': 'Implement custom payment method creation flow'
                    }
                }, status=http_status.HTTP_200_OK)
            else:
                return response
                
        except Exception as e:
            logger.error(f'Mobile payment error: {str(e)}')
            return Response({
                'success': False,
                'error': 'Payment creation failed',
                'details': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='confirm-payment')
    def confirm_payment(self, request):
        """Confirm payment after user completes payment process - handles both Payment Intents and Sources"""
        try:
            data = request.data
            logger.info(f"Confirming payment with data: {data}")
            
            if not data.get('payment_intent_id'):
                return Response({
                    'success': False,
                    'error': 'Missing payment_intent_id',
                    'error_code': 'MISSING_PAYMENT_INTENT_ID'
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            payment_reference_id = data['payment_intent_id']
            logger.info(f"Processing payment reference: {payment_reference_id}")
            
            # Determine if this is a Payment Intent (pi_) or Source (src_)
            is_source = payment_reference_id.startswith('src_')
            is_payment_intent = payment_reference_id.startswith('pi_')
            
            if is_source:
                # Handle PayMongo Source (for e-wallets like GCash, Maya, GrabPay)
                logger.info(f"Handling PayMongo Source: {payment_reference_id}")
                url = f"{self.PAYMONGO_BASE_URL}/sources/{payment_reference_id}"
            elif is_payment_intent:
                # Handle PayMongo Payment Intent (for cards)
                logger.info(f"Handling PayMongo Payment Intent: {payment_reference_id}")
                url = f"{self.PAYMONGO_BASE_URL}/payment_intents/{payment_reference_id}"
            else:
                return Response({
                    'success': False,
                    'error': 'Invalid payment reference ID format',
                    'error_code': 'INVALID_PAYMENT_REFERENCE'
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            # Validate URL to prevent SSRF
            from core.mobile_security import validate_url
            if not validate_url(url):
                logger.error(f"SSRF attempt blocked: {url}")
                return Response({
                    'success': False,
                    'error': 'Invalid payment service URL',
                    'error_code': 'INVALID_URL'
                }, status=http_status.HTTP_400_BAD_REQUEST)
            
            # Get payment status from PayMongo
            try:
                response = requests.get(url, headers=self._get_paymongo_headers(), timeout=30, allow_redirects=False)
            except requests.exceptions.Timeout:
                return Response({
                    'success': False,
                    'error': 'Request to PayMongo timed out. Please try again later.',
                    'error_code': 'PAYMONGO_TIMEOUT'
                }, status=http_status.HTTP_408_REQUEST_TIMEOUT)
            except requests.exceptions.ConnectionError:
                return Response({
                    'success': False,
                    'error': 'Failed to connect to PayMongo. Please check your internet connection.',
                    'error_code': 'PAYMONGO_CONNECTION_ERROR'
                }, status=http_status.HTTP_503_SERVICE_UNAVAILABLE)
            
            if response.status_code != 200:
                logger.error(f"PayMongo API error: {response.status_code} - {response.text}")
                return Response({
                    'success': False,
                    'error': 'Failed to retrieve payment status from PayMongo',
                    'error_code': 'PAYMONGO_API_ERROR',
                    'status_code': response.status_code,
                    'details': response.text
                }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            payment_data = response.json()['data']
            payment_status = payment_data['attributes']['status']
            
            logger.info(f"Payment status from PayMongo: {payment_status}")
            
            # Map PayMongo statuses to our system
            if is_source:
                # Source statuses: pending, chargeable, cancelled, expired, paid
                if payment_status in ['chargeable', 'paid']:
                    our_status = 'succeeded'
                elif payment_status in ['cancelled', 'expired']:
                    our_status = 'failed'
                else:
                    our_status = 'processing'
            else:
                # Payment Intent statuses: requires_payment_method, requires_confirmation, requires_action, processing, succeeded, canceled
                our_status = payment_status
            
            # Update payment record
            payment_update = {
                'status': our_status,
                'updated_at': datetime.now().isoformat()
            }
            
            if our_status == 'succeeded':
                payment_update['paid_at'] = datetime.now().isoformat()
            
            payment_response = supabase.table('payments').update(payment_update).eq('payment_intent_id', payment_reference_id).execute()
            
            if not payment_response.data:
                return Response({
                    'success': False,
                    'error': 'Failed to update payment record',
                    'error_code': 'DATABASE_UPDATE_ERROR'
                }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            payment_record = payment_response.data[0]
            booking_id = payment_record['booking_id']
            
            # Update booking status based on payment status
            if our_status == 'succeeded':
                # Payment successful - update payment_status but keep booking status
                # Get current booking to check its status
                booking_response = supabase.table('bookings').select('status').eq('id', booking_id).single().execute()
                current_status = booking_response.data.get('status') if booking_response.data else 'pending'
                
                # Only update status if it's still pending, otherwise keep current status
                if current_status == 'pending':
                    new_status = 'driver_assigned'  # Keep as driver_assigned if driver already accepted
                else:
                    new_status = current_status  # Keep current status (driver_assigned, in_progress, etc.)
                
                booking_update = {
                    'status': new_status,
                    'payment_status': 'paid',
                    'updated_at': datetime.now().isoformat()
                }
                
                message = 'Payment successful! Your booking is confirmed and ready to start.'
                
                # Create earning record for successful payment
                try:
                    self._create_earning_from_booking(booking_id)
                except Exception as e:
                    logger.warning(f"Failed to create earning record: {str(e)}")
                
            elif our_status == 'failed':
                # Payment failed - reset booking status
                booking_update = {
                    'status': 'cancelled',
                    'payment_status': 'failed',
                    'updated_at': datetime.now().isoformat()
                }
                
                message = 'Payment failed. Please try again or use a different payment method.'
                
            else:
                # Payment still processing
                booking_update = {
                    'status': 'pending',
                    'payment_status': 'processing',
                    'updated_at': datetime.now().isoformat()
                }
                
                message = 'Payment is being processed. Please wait for confirmation.'
            
            # Update booking
            logger.info(f"Updating booking {booking_id} with status: {booking_update['status']}")
            supabase.table('bookings').update(booking_update).eq('id', booking_id).execute()
            
            return Response({
                'success': True,
                'data': {
                    'payment_status': our_status,
                    'paymongo_status': payment_status,
                    'payment_type': 'source' if is_source else 'payment_intent',
                    'booking_id': booking_id,
                    'payment_id': payment_record['id'],
                    'amount': payment_record['amount'],
                    'currency': payment_record['currency'],
                    'payment_method': payment_record['payment_method_type'],
                    'paid_at': payment_record.get('paid_at'),
                    'booking_status': booking_update['status']
                },
                'message': message,
                'status_details': {
                    'is_successful': our_status == 'succeeded',
                    'is_failed': our_status == 'failed',
                    'is_processing': our_status not in ['succeeded', 'failed']
                }
            })
            
        except Exception as e:
            error_msg = f'Error confirming payment: {str(e)}'
            logger.error(error_msg)
            traceback.print_exc()
            return Response({
                'success': False,
                'error': error_msg,
                'error_code': 'INTERNAL_ERROR'
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='webhook')
    def webhook(self, request):
        """Handle PayMongo webhooks with mobile notification support"""
        try:
            logger.info("Webhook received from PayMongo")
            
            # Verify webhook signature
            signature = request.META.get('HTTP_PAYMONGO_SIGNATURE')
            payload = request.body
            
            if not self._verify_webhook_signature(payload, signature):
                logger.error("Invalid webhook signature")
                return Response({
                    'success': False,
                    'error': 'Invalid webhook signature'
                }, status=http_status.HTTP_401_UNAUTHORIZED)
            
            # Parse webhook data
            webhook_data = json.loads(payload)
            event_type = webhook_data['data']['attributes']['type']
            event_data = webhook_data['data']['attributes']['data']
            
            logger.info(f"Processing webhook event: {event_type}")
            
            if event_type == 'payment_intent.payment_succeeded':
                result = self._handle_payment_success(event_data)
                # Send mobile notification for successful payment
                self._send_mobile_notification(event_data, 'payment_success')
                return result
            elif event_type == 'payment_intent.payment_failed':
                result = self._handle_payment_failure(event_data)
                # Send mobile notification for failed payment
                self._send_mobile_notification(event_data, 'payment_failed')
                return result
            elif event_type == 'payment_intent.processing':
                # Handle processing status
                result = self._handle_payment_processing(event_data)
                self._send_mobile_notification(event_data, 'payment_processing')
                return result
            
            logger.info(f"Unhandled webhook event type: {event_type}")
            return Response({'success': True, 'message': 'Webhook received but not processed'})
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook payload: {str(e)}")
            return Response({
                'success': False,
                'error': 'Invalid JSON payload'
            }, status=http_status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f'Error processing webhook: {str(e)}')
            traceback.print_exc()
            return Response({
                'success': False,
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _verify_webhook_signature(self, payload, signature):
        """Verify PayMongo webhook signature with improved error handling"""
        try:
            if not signature:
                logger.warning("No signature provided in webhook")
                return False
            
            if not self.PAYMONGO_WEBHOOK_SECRET or self.PAYMONGO_WEBHOOK_SECRET == 'whsec_your_webhook_secret_here':
                logger.warning("PayMongo webhook secret not configured - allowing webhook for development")
                return True  # Allow webhook in development mode
            
            # Extract timestamp and signature from header
            elements = signature.split(',')
            timestamp = None
            signatures = []
            
            for element in elements:
                if '=' not in element:
                    continue
                key, value = element.split('=', 1)
                if key.strip() == 't':
                    timestamp = value.strip()
                elif key.strip() == 'v1':
                    signatures.append(value.strip())
            
            if not timestamp or not signatures:
                logger.warning(f"Invalid signature format: timestamp={timestamp}, signatures={signatures}, original_signature={signature}")
                # For development, allow webhook through
                if not self.PAYMONGO_WEBHOOK_SECRET or self.PAYMONGO_WEBHOOK_SECRET == 'whsec_your_webhook_secret_here':
                    logger.info("Allowing webhook through in development mode")
                    return True
                return False
            
            # Create expected signature
            signed_payload = f"{timestamp}.{payload.decode()}"
            expected_signature = hmac.new(
                self.PAYMONGO_WEBHOOK_SECRET.encode(),
                signed_payload.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            is_valid = any(hmac.compare_digest(expected_signature, sig) for sig in signatures)
            
            if not is_valid:
                logger.warning("Webhook signature verification failed")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {str(e)}")
            return False
    
    def _handle_payment_success(self, payment_data):
        """Handle successful payment webhook with mobile notification"""
        try:
            payment_intent_id = payment_data['id']
            logger.info(f"Processing successful payment webhook for: {payment_intent_id}")
            
            # Update payment record
            payment_update = {
                'status': 'succeeded',
                'paid_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            payment_response = supabase.table('payments').update(payment_update).eq('payment_intent_id', payment_intent_id).execute()
            
            if payment_response.data:
                payment_record = payment_response.data[0]
                booking_id = payment_record['booking_id']
                
                # Get current booking status
                booking_response = supabase.table('bookings').select('status').eq('id', booking_id).single().execute()
                current_status = booking_response.data.get('status') if booking_response.data else 'pending'
                
                # Only update status if it's still pending, otherwise keep current status
                if current_status == 'pending':
                    new_status = 'driver_assigned'  # Keep as driver_assigned if driver already accepted
                else:
                    new_status = current_status  # Keep current status (driver_assigned, in_progress, etc.)
                
                # Update booking status
                supabase.table('bookings').update({
                    'status': new_status,
                    'payment_status': 'paid',
                    'updated_at': datetime.now().isoformat()
                }).eq('id', booking_id).execute()
                
                # Create earning record
                try:
                    self._create_earning_from_booking(booking_id)
                except Exception as e:
                    logger.warning(f"Failed to create earning record: {str(e)}")
                
                logger.info(f"Payment success processed for booking: {booking_id}")
            
            return Response({'success': True, 'message': 'Payment success processed'})
            
        except Exception as e:
            logger.error(f'Error handling payment success: {str(e)}')
            return Response({'success': False, 'error': str(e)})
    
    def _handle_payment_failure(self, payment_data):
        """Handle failed payment webhook"""
        try:
            payment_intent_id = payment_data['id']
            
            # Update payment record
            payment_update = {
                'status': 'failed',
                'updated_at': datetime.now().isoformat()
            }
            
            payment_response = supabase.table('payments').update(payment_update).eq('payment_intent_id', payment_intent_id).execute()
            
            if payment_response.data:
                payment_record = payment_response.data[0]
                booking_id = payment_record['booking_id']
                
                # Update booking status
                supabase.table('bookings').update({
                    'status': 'cancelled',
                    'payment_status': 'failed',
                    'updated_at': datetime.now().isoformat()
                }).eq('id', booking_id).execute()
            
            return Response({'success': True, 'message': 'Payment failure processed'})
            
        except Exception as e:
            print(f'Error handling payment failure: {str(e)}')
            return Response({'success': False, 'error': str(e)})
    
    def _handle_payment_processing(self, payment_data):
        """Handle payment processing webhook"""
        try:
            payment_intent_id = payment_data['id']
            logger.info(f"Processing payment processing webhook for: {payment_intent_id}")
            
            # Update payment record
            payment_update = {
                'status': 'processing',
                'updated_at': datetime.now().isoformat()
            }
            
            payment_response = supabase.table('payments').update(payment_update).eq('payment_intent_id', payment_intent_id).execute()
            
            if payment_response.data:
                payment_record = payment_response.data[0]
                booking_id = payment_record['booking_id']
                
                # Update booking status
                supabase.table('bookings').update({
                    'status': 'pending',
                    'payment_status': 'processing',
                    'updated_at': datetime.now().isoformat()
                }).eq('id', booking_id).execute()
                
                logger.info(f"Payment processing status updated for booking: {booking_id}")
            
            return Response({'success': True, 'message': 'Payment processing status updated'})
            
        except Exception as e:
            logger.error(f'Error handling payment processing: {str(e)}')
            return Response({'success': False, 'error': str(e)})
    
    def _send_mobile_notification(self, payment_data, event_type):
        """Send mobile push notification for payment events"""
        try:
            # This is a placeholder for mobile notification integration
            # You can integrate with Firebase Cloud Messaging (FCM) or similar service
            payment_intent_id = payment_data.get('id')
            
            # Get payment and booking details
            payment_response = supabase.table('payments').select('*, bookings(customer_id, package_name, booking_reference)').eq('payment_intent_id', payment_intent_id).single().execute()
            
            if not payment_response.data:
                logger.warning(f"Payment not found for notification: {payment_intent_id}")
                return
            
            payment = payment_response.data
            customer_id = payment['bookings']['customer_id']
            package_name = payment['bookings']['package_name']
            booking_reference = payment['bookings']['booking_reference']
            
            # Prepare notification data
            notification_data = {
                'customer_id': customer_id,
                'payment_intent_id': payment_intent_id,
                'booking_reference': booking_reference,
                'package_name': package_name,
                'amount': payment['amount'],
                'event_type': event_type,
                'timestamp': datetime.now().isoformat()
            }
            
            # TODO: Implement actual mobile notification sending
            # Example with FCM:
            # fcm_service.send_notification(customer_id, notification_data)
            
            logger.info(f"Mobile notification prepared for {event_type}: {customer_id}")
            
        except Exception as e:
            logger.error(f"Error sending mobile notification: {str(e)}")
    
    def _create_earning_from_booking(self, booking_id):
        """Create earning record from successful booking payment"""
        try:
            # Get booking details
            booking_response = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
            if not booking_response.data:
                logger.error(f"Booking not found for earning creation: {booking_id}")
                return
            
            booking = booking_response.data
            total_amount = Decimal(str(booking['total_amount']))
            
            # Calculate earnings distribution (adjust percentages as needed)
            admin_percentage = Decimal('0.15')  # 15% admin fee
            driver_percentage = Decimal('0.85')  # 85% to driver
            
            admin_earnings = total_amount * admin_percentage
            driver_earnings = total_amount * driver_percentage
            
            # Create earning record
            earning_data = {
                'id': str(uuid.uuid4()),
                'booking_id': booking_id,
                'total_amount': float(total_amount),
                'admin_earnings': float(admin_earnings),
                'driver_earnings': float(driver_earnings),
                'status': 'pending_driver_assignment',
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            supabase.table('earnings').insert(earning_data).execute()
            logger.info(f"Earning record created for booking: {booking_id}")
            
        except Exception as e:
            logger.error(f"Error creating earning record: {str(e)}")
    
    @action(detail=False, methods=['get'], url_path='status/(?P<payment_id>[^/.]+)')
    def payment_status(self, request, payment_id=None):
        """Get payment status"""
        try:
            response = supabase.table('payments').select('*').eq('id', payment_id).single().execute()
            
            if not response.data:
                return Response({
                    'success': False,
                    'error': 'Payment not found'
                }, status=http_status.HTTP_404_NOT_FOUND)
            
            payment = response.data
            
            return Response({
                'success': True,
                'data': payment
            })
            
        except Exception as e:
            print(f'Error fetching payment status: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)