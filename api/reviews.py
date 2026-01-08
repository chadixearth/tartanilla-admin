from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase
from datetime import datetime
import traceback
import logging

# Prefer the admin client (bypasses RLS for audit_logs) if available
try:
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# JWT helpers if available in your project
try:
    from core.jwt_auth import verify_token, get_token_from_request
except Exception:
    verify_token = None
    get_token_from_request = None

logger = logging.getLogger(__name__)

class ReviewViewSet(viewsets.ViewSet):
    """Manage tour package and driver reviews/ratings."""
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer, BrowsableAPIRenderer]

    TABLE_NAME = 'package_reviews'
    DRIVER_TABLE_NAME = 'driver_reviews'

    # ─────────────────────────────────────────────────────────
    # Actor & Audit helpers
    # ─────────────────────────────────────────────────────────
    def _client(self):
        return supabase_admin or supabase

    def _get_ip(self, request):
        try:
            xff = request.META.get('HTTP_X_FORWARDED_FOR')
            if xff:
                return xff.split(',')[0].strip()
            return request.META.get('REMOTE_ADDR')
        except Exception:
            return None

    def _get_actor(self, request, fallback_user_id=None):
        """
        Returns dict: { user_id, username, role }
        Tries JWT → request.user → fallback_user_id
        """
        actor = {'user_id': None, 'username': None, 'role': None}
        try:
            # JWT path
            if get_token_from_request and verify_token:
                token = get_token_from_request(request)
                if token:
                    claims = verify_token(token) or {}
                    if isinstance(claims, dict):
                        actor['user_id'] = claims.get('sub') or claims.get('user_id') or claims.get('id')
                        actor['username'] = claims.get('username') or claims.get('email')
                        actor['role'] = claims.get('role') or claims.get('user_role')

            # Django user path
            if not actor['user_id']:
                u = getattr(request, 'user', None)
                if getattr(u, 'is_authenticated', False):
                    actor['user_id'] = getattr(u, 'id', None)
                    actor['username'] = getattr(u, 'username', None) or getattr(u, 'email', None)
                    # try to read a simple role field if present
                    try:
                        actor['role'] = getattr(u, 'role', None) or getattr(getattr(u, 'role', None), 'name', None)
                    except Exception:
                        pass

            # Fallback to provided id (e.g., reviewer_id or driver_id)
            if not actor['user_id'] and fallback_user_id:
                actor['user_id'] = fallback_user_id
                try:
                    uresp = supabase.table('users').select('name, email, role').eq('id', fallback_user_id).single().execute()
                    if hasattr(uresp, 'data') and uresp.data:
                        actor['username'] = uresp.data.get('name') or uresp.data.get('email')
                        actor['role'] = uresp.data.get('role')
                except Exception:
                    pass
        except Exception:
            pass
        return actor

    def _audit(self, request, *, action, entity_name, entity_id=None, new_data=None, old_data=None, actor=None):
        """
        Inserts a row into audit_logs. Never blocks the main flow.
        """
        try:
            actor = actor or self._get_actor(request)
            ip = self._get_ip(request)
            device = request.META.get('HTTP_USER_AGENT') if request else None

            payload = {
                'user_id': actor.get('user_id'),
                'username': actor.get('username'),
                'role': actor.get('role'),
                'action': action,
                'entity_name': entity_name,
                'entity_id': str(entity_id) if entity_id is not None else None,
                'old_data': old_data or None,
                'new_data': new_data or None,
                'ip_address': ip,
                'device_info': device,
            }
            self._client().table('audit_logs').insert(payload).execute()
        except Exception as e:
            logger.warning(f"[AUDIT] insert failed: {e}")

    # ─────────────────────────────────────────────────────────
    # Reviews logic
    # ─────────────────────────────────────────────────────────
    def _compute_stats(self, reviews):
        ratings = [r.get('rating', 0) for r in reviews if isinstance(r.get('rating'), (int, float))]
        count = len(ratings)
        avg = round(sum(ratings) / count, 1) if count > 0 else 0.0
        return {
            'average_rating': avg,
            'review_count': count
        }
    
    def _get_reviewer_display_name(self, review):
        """Get display name for reviewer based on anonymous setting"""
        # Always fetch the user's actual name first (bypass RLS)
        display_name = None
        try:
            user_resp = self._client().table('users').select('name, email').eq('id', review.get('reviewer_id')).single().execute()
            if hasattr(user_resp, 'data') and user_resp.data:
                name = user_resp.data.get('name', '').strip()
                email = user_resp.data.get('email', '').strip()
                display_name = name or email
        except Exception:
            pass
        
        # If no user found, return fallback
        if not display_name:
            return 'Customer'
        
        # Apply masking if anonymous
        is_anon = review.get('is_anonymous')
        if is_anon is True or str(is_anon).lower() == 'true':
            if len(display_name) <= 2:
                return display_name
            return display_name[0] + '*' * (len(display_name) - 2) + display_name[-1]
        
        return display_name

    def list(self, request):
        """List reviews, optionally filtered by package_id or booking_id.
        Query params: package_id, booking_id, limit, include_stats=true
        """
        try:
            package_id = request.query_params.get('package_id') if hasattr(request, 'query_params') else request.GET.get('package_id')
            booking_id = request.query_params.get('booking_id') if hasattr(request, 'query_params') else request.GET.get('booking_id')
            include_stats = (request.query_params.get('include_stats') == 'true') if hasattr(request, 'query_params') else (request.GET.get('include_stats') == 'true')
            limit_param = request.query_params.get('limit') if hasattr(request, 'query_params') else request.GET.get('limit')
            reviewer_id = request.query_params.get('reviewer_id') if hasattr(request, 'query_params') else request.GET.get('reviewer_id')

            query = supabase.table(self.TABLE_NAME).select('*').order('created_at', desc=True)
            if package_id:
                query = query.eq('package_id', package_id)
            if booking_id:
                query = query.eq('booking_id', booking_id)
            if reviewer_id:
                query = query.eq('reviewer_id', reviewer_id)
            if limit_param:
                try:
                    query = query.limit(int(limit_param))
                except Exception:
                    pass

            response = query.execute()
            reviews = response.data if hasattr(response, 'data') else []

            # Enrich reviews with package names and reviewer data
            for review in reviews:
                if review.get('package_id'):
                    try:
                        pkg_resp = supabase.table('tourpackages').select('package_name').eq('id', review['package_id']).single().execute()
                        if hasattr(pkg_resp, 'data') and pkg_resp.data:
                            review['package_name'] = pkg_resp.data.get('package_name', '')
                    except Exception:
                        review['package_name'] = ''
                
                # Add raw user data for consistent frontend handling (bypass RLS)
                try:
                    user_resp = self._client().table('users').select('name, email').eq('id', review.get('reviewer_id')).single().execute()
                    if hasattr(user_resp, 'data') and user_resp.data:
                        review['users'] = user_resp.data
                    else:
                        review['users'] = None
                except Exception:
                    review['users'] = None
                
                # Add reviewer name for backward compatibility
                review['reviewer_name'] = self._get_reviewer_display_name(review)

            payload = {
                'success': True,
                'data': reviews,
                'count': len(reviews)
            }
            if include_stats:
                payload['stats'] = self._compute_stats(reviews)

            return Response(payload)
        except Exception as e:
            print(f'Error listing reviews: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Failed to list reviews', 'data': []}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request):
        """Create a PACKAGE review for a completed booking.
        Required fields: package_id, booking_id, customer_id (or reviewer_id), rating (1-5)
        Optional: comment (string)
        Constraints: booking must exist, belong to customer, and be status 'completed'. One review per booking.
        """
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            package_id = data.get('package_id')
            booking_id = data.get('booking_id')
            reviewer_id = data.get('reviewer_id') or data.get('customer_id')
            rating = data.get('rating')
            comment = data.get('comment', '')

            # Validate required
            missing = [f for f in ['package_id', 'booking_id', 'reviewer_id', 'rating'] if not (data.get(f) or (f == 'reviewer_id' and reviewer_id))]
            if missing:
                return Response({'success': False, 'error': f"Missing required fields: {', '.join(missing)}"}, status=status.HTTP_400_BAD_REQUEST)

            # Validate rating
            try:
                rating = int(rating)
                if rating < 1 or rating > 5:
                    return Response({'success': False, 'error': 'Rating must be between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception:
                return Response({'success': False, 'error': 'Rating must be an integer between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)

            # Verify booking exists and belongs to customer, is completed
            booking_resp = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
            booking = booking_resp.data if hasattr(booking_resp, 'data') else None
            if not booking:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            if booking.get('customer_id') != reviewer_id:
                return Response({'success': False, 'error': 'Unauthorized: booking does not belong to this customer'}, status=status.HTTP_403_FORBIDDEN)
            if str(booking.get('package_id')) != str(package_id):
                return Response({'success': False, 'error': 'Booking is for a different package'}, status=status.HTTP_400_BAD_REQUEST)
            if booking.get('status') != 'completed':
                return Response({'success': False, 'error': 'Review allowed only after completion'}, status=status.HTTP_400_BAD_REQUEST)
            # If verification is required, ensure a verification photo exists (defense-in-depth)
            if booking.get('verification_required', True) and not booking.get('verification_photo_url'):
                return Response({'success': False, 'error': 'Verification not found for this completed booking'}, status=status.HTTP_400_BAD_REQUEST)

            # Prevent duplicate review for the same booking
            existing_resp = supabase.table(self.TABLE_NAME).select('id').eq('booking_id', booking_id).execute()
            existing_reviews = existing_resp.data if hasattr(existing_resp, 'data') else []
            if existing_reviews:
                return Response({'success': False, 'error': 'A review for this booking already exists'}, status=status.HTTP_400_BAD_REQUEST)

            # Handle anonymous review option
            is_anonymous = data.get('is_anonymous', False)
            if isinstance(is_anonymous, str):
                is_anonymous = is_anonymous.lower() in ['true', '1', 'yes']

            review_data = {
                'package_id': package_id,
                'booking_id': booking_id,
                'reviewer_id': reviewer_id,
                'rating': rating,
                'comment': comment,
                'created_at': datetime.now().isoformat(),
                'is_published': True,
                'is_anonymous': bool(is_anonymous)
            }

            insert_resp = supabase.table(self.TABLE_NAME).insert(review_data).execute()
            if hasattr(insert_resp, 'data') and insert_resp.data:
                inserted = insert_resp.data[0]
                # Add reviewer_name to response
                inserted['reviewer_name'] = self._get_reviewer_display_name(inserted)
                # AUDIT: package review create
                actor = self._get_actor(request, fallback_user_id=reviewer_id)
                self._audit(
                    request,
                    action='PACKAGE_REVIEW_CREATE',
                    entity_name=self.TABLE_NAME,
                    entity_id=inserted.get('id'),
                    new_data=inserted,
                    actor=actor
                )
                return Response({'success': True, 'data': inserted, 'message': 'Review submitted'}, status=status.HTTP_201_CREATED)
            return Response({'success': False, 'error': 'Failed to submit review'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f'Error creating review: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Failed to submit review'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='tourist')
    def create_tourist_review(self, request):
        """Create a TOURIST review by driver/owner for a completed booking.
        Required fields: tourist_id, booking_id, driver_id, rating (1-5)
        Optional: comment (string)
        """
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            tourist_id = data.get('tourist_id')
            booking_id = data.get('booking_id')
            driver_id = data.get('driver_id')
            rating = data.get('rating')
            comment = data.get('comment', '')

            # Validate required
            missing = [f for f in ['tourist_id', 'booking_id', 'driver_id', 'rating'] if not data.get(f)]
            if missing:
                return Response({'success': False, 'error': f"Missing required fields: {', '.join(missing)}"}, status=status.HTTP_400_BAD_REQUEST)

            # Validate rating
            try:
                rating = int(rating)
                if rating < 1 or rating > 5:
                    return Response({'success': False, 'error': 'Rating must be between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception:
                return Response({'success': False, 'error': 'Rating must be an integer between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)

            # Verify booking
            booking_resp = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
            booking = booking_resp.data if hasattr(booking_resp, 'data') else None
            if not booking:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            if str(booking.get('driver_id')) != str(driver_id):
                return Response({'success': False, 'error': 'Unauthorized: booking not assigned to this driver'}, status=status.HTTP_403_FORBIDDEN)
            if str(booking.get('customer_id')) != str(tourist_id):
                return Response({'success': False, 'error': 'Tourist ID does not match booking customer'}, status=status.HTTP_400_BAD_REQUEST)
            if booking.get('status') != 'completed':
                return Response({'success': False, 'error': 'Review allowed only after completion'}, status=status.HTTP_400_BAD_REQUEST)

            # Prevent duplicate tourist review
            existing_resp = supabase.table('tourist_reviews').select('id').eq('booking_id', booking_id).eq('driver_id', driver_id).execute()
            existing = existing_resp.data if hasattr(existing_resp, 'data') else []
            if existing:
                return Response({'success': False, 'error': 'You already reviewed this tourist for this booking'}, status=status.HTTP_400_BAD_REQUEST)

            review_data = {
                'tourist_id': tourist_id,
                'booking_id': booking_id,
                'driver_id': driver_id,
                'rating': rating,
                'comment': comment,
                'created_at': datetime.now().isoformat(),
                'is_published': True
            }

            insert_resp = supabase.table('tourist_reviews').insert(review_data).execute()
            if hasattr(insert_resp, 'data') and insert_resp.data:
                inserted = insert_resp.data[0]
                # AUDIT: tourist review create (actor is driver)
                actor = self._get_actor(request, fallback_user_id=driver_id)
                self._audit(
                    request,
                    action='TOURIST_REVIEW_CREATE',
                    entity_name='tourist_reviews',
                    entity_id=inserted.get('id'),
                    new_data=inserted,
                    actor=actor
                )
                return Response({'success': True, 'data': inserted, 'message': 'Tourist review submitted'}, status=status.HTTP_201_CREATED)
            return Response({'success': False, 'error': 'Failed to submit tourist review'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f'Error creating tourist review: {str(e)}')
            return Response({'success': False, 'error': 'Failed to submit tourist review'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='driver')
    def create_driver_review(self, request):
        """Create a DRIVER review for a completed booking.
        Required fields: driver_id, booking_id, customer_id (or reviewer_id), rating (1-5)
        Optional: comment (string)
        Constraints: booking must exist, belong to customer, be completed, and have the same driver. One driver review per booking.
        """
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            driver_id = data.get('driver_id')
            booking_id = data.get('booking_id')
            reviewer_id = data.get('reviewer_id') or data.get('customer_id')
            rating = data.get('rating')
            comment = data.get('comment', '')

            # Validate required
            missing = [f for f in ['driver_id', 'booking_id', 'reviewer_id', 'rating'] if not (data.get(f) or (f == 'reviewer_id' and reviewer_id))]
            if missing:
                return Response({'success': False, 'error': f"Missing required fields: {', '.join(missing)}"}, status=status.HTTP_400_BAD_REQUEST)

            # Validate rating
            try:
                rating = int(rating)
                if rating < 1 or rating > 5:
                    return Response({'success': False, 'error': 'Rating must be between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception:
                return Response({'success': False, 'error': 'Rating must be an integer between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)

            # Check if this is a ride hailing booking
            booking_type = data.get('booking_type', 'tour')
            table_name = 'ride_hailing_bookings' if booking_type == 'ride_hailing' else 'bookings'
            
            # Verify booking
            booking_resp = supabase.table(table_name).select('*').eq('id', booking_id).single().execute()
            booking = booking_resp.data if hasattr(booking_resp, 'data') else None
            if not booking:
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            if booking.get('customer_id') != reviewer_id:
                return Response({'success': False, 'error': 'Unauthorized: booking does not belong to this customer'}, status=status.HTTP_403_FORBIDDEN)
            if str(booking.get('driver_id')) != str(driver_id):
                return Response({'success': False, 'error': 'Booking was not assigned to this driver'}, status=status.HTTP_400_BAD_REQUEST)
            if booking.get('status') != 'completed':
                return Response({'success': False, 'error': 'Review allowed only after completion'}, status=status.HTTP_400_BAD_REQUEST)
            # Skip verification check for ride hailing
            if booking_type != 'ride_hailing' and booking.get('verification_required', True) and not booking.get('verification_photo_url'):
                return Response({'success': False, 'error': 'Verification not found for this completed booking'}, status=status.HTTP_400_BAD_REQUEST)

            # Prevent duplicate driver review for the same booking by this reviewer
            existing_resp = (
                supabase
                .table(self.DRIVER_TABLE_NAME)
                .select('id')
                .eq('booking_id', booking_id)
                .eq('reviewer_id', reviewer_id)
                .execute()
            )
            existing = existing_resp.data if hasattr(existing_resp, 'data') else []
            if existing:
                return Response({'success': False, 'error': 'You already reviewed this driver for this booking'}, status=status.HTTP_400_BAD_REQUEST)

            # Handle anonymous review option
            is_anonymous = data.get('is_anonymous', False)
            if isinstance(is_anonymous, str):
                is_anonymous = is_anonymous.lower() in ['true', '1', 'yes']

            review_data = {
                'driver_id': driver_id,
                'booking_id': booking_id,
                'reviewer_id': reviewer_id,
                'rating': rating,
                'comment': comment,
                'created_at': datetime.now().isoformat(),
                'is_published': True,
                'is_anonymous': bool(is_anonymous)
            }

            insert_resp = supabase.table(self.DRIVER_TABLE_NAME).insert(review_data).execute()
            if hasattr(insert_resp, 'data') and insert_resp.data:
                inserted = insert_resp.data[0]
                # Add reviewer_name to response
                inserted['reviewer_name'] = self._get_reviewer_display_name(inserted)
                # AUDIT: driver review create (actor is reviewer/customer)
                actor = self._get_actor(request, fallback_user_id=reviewer_id)
                self._audit(
                    request,
                    action='DRIVER_REVIEW_CREATE',
                    entity_name=self.DRIVER_TABLE_NAME,
                    entity_id=inserted.get('id'),
                    new_data=inserted,
                    actor=actor
                )
                return Response({'success': True, 'data': inserted, 'message': 'Driver review submitted'}, status=status.HTTP_201_CREATED)
            return Response({'success': False, 'error': 'Failed to submit driver review'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f'Error creating driver review: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Failed to submit driver review'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='user/(?P<user_id>[^/.]+)/given')
    def get_user_given_reviews(self, request, user_id=None):
        """Get all reviews given by a user (both package and driver reviews).
        Query params: limit (default 20)
        """
        try:
            limit_param = request.query_params.get('limit') if hasattr(request, 'query_params') else request.GET.get('limit')
            limit_value = 20
            try:
                if limit_param:
                    limit_value = int(limit_param)
            except Exception:
                pass

            all_reviews = []
            
            # Get package reviews
            package_resp = (
                supabase
                .table(self.TABLE_NAME)
                .select('*')
                .eq('reviewer_id', user_id)
                .eq('is_published', True)
                .order('created_at', desc=True)
                .execute()
            )
            package_reviews = package_resp.data if hasattr(package_resp, 'data') else []
            
            for r in package_reviews:
                package_name = ''
                try:
                    pkg_resp = supabase.table('tourpackages').select('package_name').eq('id', r.get('package_id')).single().execute()
                    if hasattr(pkg_resp, 'data') and pkg_resp.data:
                        package_name = pkg_resp.data.get('package_name', '')
                except Exception:
                    pass
                
                # Add reviewer name using helper method
                r['reviewer_name'] = self._get_reviewer_display_name(r)
                
                all_reviews.append({
                    **r,
                    'review_type': 'package',
                    'package_name': package_name
                })
            
            # Get driver reviews
            driver_resp = (
                supabase
                .table(self.DRIVER_TABLE_NAME)
                .select('*')
                .eq('reviewer_id', user_id)
                .eq('is_published', True)
                .order('created_at', desc=True)
                .execute()
            )
            driver_reviews = driver_resp.data if hasattr(driver_resp, 'data') else []
            
            for r in driver_reviews:
                driver_name = ''
                driver_email = ''
                package_name = ''
                
                try:
                    user_resp = supabase.table('users').select('name, email').eq('id', r.get('driver_id')).single().execute()
                    if hasattr(user_resp, 'data') and user_resp.data:
                        driver_name = user_resp.data.get('name', '').strip()
                        driver_email = user_resp.data.get('email', '').strip()
                except Exception:
                    pass
                
                if r.get('booking_id'):
                    try:
                        booking_resp = supabase.table('bookings').select('package_id').eq('id', r['booking_id']).single().execute()
                        if hasattr(booking_resp, 'data') and booking_resp.data and booking_resp.data.get('package_id'):
                            pkg_resp = supabase.table('tourpackages').select('package_name').eq('id', booking_resp.data['package_id']).single().execute()
                            if hasattr(pkg_resp, 'data') and pkg_resp.data:
                                package_name = pkg_resp.data.get('package_name', '')
                    except Exception:
                        pass
                
                # Add reviewer name using helper method
                r['reviewer_name'] = self._get_reviewer_display_name(r)
                
                all_reviews.append({
                    **r,
                    'review_type': 'driver',
                    'driver_name': driver_name or driver_email or 'Driver',
                    'driver_email': driver_email,
                    'package_name': package_name
                })
            
            # Sort by created_at and limit
            all_reviews.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            all_reviews = all_reviews[:limit_value]
            
            return Response({'success': True, 'data': {'reviews': all_reviews}})
        except Exception as e:
            print(f'Error getting user given reviews: {str(e)}')
            return Response({'success': False, 'error': 'Failed to fetch reviews'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='driver/all')
    def list_driver_reviews(self, request):
        """List driver reviews by reviewer_id (reviews given by a user).
        Query params: reviewer_id (required), limit (default 20)
        """
        try:
            reviewer_id = request.query_params.get('reviewer_id') if hasattr(request, 'query_params') else request.GET.get('reviewer_id')
            if not reviewer_id:
                return Response({'success': False, 'error': 'reviewer_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            limit_param = request.query_params.get('limit') if hasattr(request, 'query_params') else request.GET.get('limit')
            limit_value = 20
            try:
                if limit_param:
                    limit_value = int(limit_param)
            except Exception:
                pass

            response = (
                supabase
                .table(self.DRIVER_TABLE_NAME)
                .select('*')
                .eq('reviewer_id', reviewer_id)
                .eq('is_published', True)
                .order('created_at', desc=True)
                .limit(limit_value)
                .execute()
            )
            reviews = response.data if hasattr(response, 'data') else []
            
            # Enrich with driver names and package names
            enriched = []
            for r in reviews:
                driver_name = ''
                driver_email = ''
                package_name = ''
                try:
                    user_resp = supabase.table('users').select('name, email').eq('id', r.get('driver_id')).single().execute()
                    if hasattr(user_resp, 'data') and user_resp.data:
                        driver_name = user_resp.data.get('name', '').strip()
                        driver_email = user_resp.data.get('email', '').strip()
                except Exception:
                    pass
                
                # Get package name from booking
                if r.get('booking_id'):
                    try:
                        booking_resp = supabase.table('bookings').select('package_id').eq('id', r['booking_id']).single().execute()
                        if hasattr(booking_resp, 'data') and booking_resp.data and booking_resp.data.get('package_id'):
                            pkg_resp = supabase.table('tourpackages').select('package_name').eq('id', booking_resp.data['package_id']).single().execute()
                            if hasattr(pkg_resp, 'data') and pkg_resp.data:
                                package_name = pkg_resp.data.get('package_name', '')
                    except Exception:
                        pass
                
                # Add reviewer name using helper method
                r['reviewer_name'] = self._get_reviewer_display_name(r)
                
                enriched.append({
                    **r, 
                    'driver_name': driver_name or driver_email or 'Driver',
                    'driver_email': driver_email,
                    'package_name': package_name
                })
            
            return Response({'success': True, 'data': {'reviews': enriched}})
        except Exception as e:
            print(f'Error listing driver reviews by reviewer: {str(e)}')
            return Response({'success': False, 'error': 'Failed to fetch reviews'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='driver/(?P<driver_id>[^/.]+)')
    def get_driver_reviews(self, request, driver_id=None):
        """Return driver reviews and stats for a driver.
        Query params: limit (default 20), reviewer_id (optional - to get reviews given by a user)
        """
        try:
            limit_param = request.query_params.get('limit') if hasattr(request, 'query_params') else request.GET.get('limit')
            reviewer_id = request.query_params.get('reviewer_id') if hasattr(request, 'query_params') else request.GET.get('reviewer_id')
            limit_value = 20
            try:
                if limit_param:
                    limit_value = int(limit_param)
            except Exception:
                pass

            response = (
                supabase
                .table(self.DRIVER_TABLE_NAME)
                .select('*')
                .eq('driver_id', driver_id)
                .eq('is_published', True)
                .order('created_at', desc=True)
                .limit(limit_value)
                .execute()
            )
            reviews = response.data if hasattr(response, 'data') else []

            # Enrich with driver name, reviewer name, and package name
            enriched = []
            for r in reviews:
                reviewer_name = ''
                reviewer_email = ''
                driver_name = ''
                driver_email = ''
                package_name = ''
                
                # Get reviewer info
                try:
                    user_resp = supabase.table('users').select('name, email').eq('id', r.get('reviewer_id')).single().execute()
                    if hasattr(user_resp, 'data') and user_resp.data:
                        reviewer_name = user_resp.data.get('name', '').strip()
                        reviewer_email = user_resp.data.get('email', '').strip()
                except Exception:
                    pass
                
                # Get driver info
                try:
                    driver_resp = supabase.table('users').select('name, email').eq('id', r.get('driver_id')).single().execute()
                    if hasattr(driver_resp, 'data') and driver_resp.data:
                        driver_name = driver_resp.data.get('name', '').strip()
                        driver_email = driver_resp.data.get('email', '').strip()
                except Exception:
                    pass
                
                # Get package name from booking
                if r.get('booking_id'):
                    try:
                        booking_resp = supabase.table('bookings').select('package_id').eq('id', r['booking_id']).single().execute()
                        if hasattr(booking_resp, 'data') and booking_resp.data and booking_resp.data.get('package_id'):
                            pkg_resp = supabase.table('tourpackages').select('package_name').eq('id', booking_resp.data['package_id']).single().execute()
                            if hasattr(pkg_resp, 'data') and pkg_resp.data:
                                package_name = pkg_resp.data.get('package_name', '')
                    except Exception:
                        pass
                
                # Use helper method for reviewer name
                r['reviewer_name'] = self._get_reviewer_display_name(r)
                
                enriched.append({ 
                    **r, 
                    'reviewer_email': reviewer_email if not r.get('is_anonymous', False) else '',
                    'driver_name': driver_name or driver_email or 'Driver',
                    'driver_email': driver_email,
                    'package_name': package_name
                })

            # Stats
            try:
                all_resp = (
                    supabase
                    .table(self.DRIVER_TABLE_NAME)
                    .select('rating')
                    .eq('driver_id', driver_id)
                    .eq('is_published', True)
                    .execute()
                )
                all_reviews = all_resp.data if hasattr(all_resp, 'data') else []
                stats = self._compute_stats(all_reviews)
            except Exception:
                stats = self._compute_stats(enriched)

            return Response({'success': True, 'data': {'reviews': enriched, **stats}})
        except Exception as e:
            print(f'Error getting driver reviews: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Failed to fetch driver reviews', 'data': {}}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='check-existing/(?P<booking_id>[^/.]+)')
    def check_existing_reviews(self, request, booking_id=None):
        """Check if reviews already exist for a booking by a specific reviewer.
        Query params: reviewer_id (required)
        """
        try:
            reviewer_id = request.query_params.get('reviewer_id') if hasattr(request, 'query_params') else request.GET.get('reviewer_id')
            
            if not reviewer_id:
                return Response({'success': False, 'error': 'reviewer_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Check for package review
            package_review_resp = supabase.table(self.TABLE_NAME).select('id').eq('booking_id', booking_id).eq('reviewer_id', reviewer_id).execute()
            has_package_review = bool(package_review_resp.data if hasattr(package_review_resp, 'data') else [])
            
            # Check for driver review
            driver_review_resp = supabase.table(self.DRIVER_TABLE_NAME).select('id').eq('booking_id', booking_id).eq('reviewer_id', reviewer_id).execute()
            has_driver_review = bool(driver_review_resp.data if hasattr(driver_review_resp, 'data') else [])
            
            return Response({
                'success': True,
                'data': {
                    'booking_id': booking_id,
                    'reviewer_id': reviewer_id,
                    'has_package_review': has_package_review,
                    'has_driver_review': has_driver_review
                }
            })
        except Exception as e:
            print(f'Error checking existing reviews: {str(e)}')
            print(f'Traceback: {traceback.format_exc()}')
            return Response({'success': False, 'error': 'Failed to check existing reviews'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='tourist/(?P<tourist_id>[^/.]+)')
    def get_tourist_reviews(self, request, tourist_id=None):
        """Return tourist reviews and stats for a tourist.
        Query params: limit (default 20)
        """
        try:
            limit_param = request.query_params.get('limit') if hasattr(request, 'query_params') else request.GET.get('limit')
            limit_value = 20
            try:
                if limit_param:
                    limit_value = int(limit_param)
            except Exception:
                pass

            response = supabase.table('tourist_reviews').select('*').eq('tourist_id', tourist_id).eq('is_published', True).order('created_at', desc=True).limit(limit_value).execute()
            reviews = response.data if hasattr(response, 'data') else []

            # Enrich with driver name and package name
            enriched = []
            for r in reviews:
                driver_name = ''
                driver_email = ''
                package_name = ''
                
                # Get driver info
                try:
                    user_resp = supabase.table('users').select('name, email').eq('id', r.get('driver_id')).single().execute()
                    if hasattr(user_resp, 'data') and user_resp.data:
                        driver_name = user_resp.data.get('name', '').strip()
                        driver_email = user_resp.data.get('email', '').strip()
                except Exception:
                    pass
                
                # Get package name from booking
                if r.get('booking_id'):
                    try:
                        booking_resp = supabase.table('bookings').select('package_id').eq('id', r['booking_id']).single().execute()
                        if hasattr(booking_resp, 'data') and booking_resp.data and booking_resp.data.get('package_id'):
                            pkg_resp = supabase.table('tourpackages').select('package_name').eq('id', booking_resp.data['package_id']).single().execute()
                            if hasattr(pkg_resp, 'data') and pkg_resp.data:
                                package_name = pkg_resp.data.get('package_name', '')
                    except Exception:
                        pass
                
                enriched.append({
                    **r, 
                    'driver_name': driver_name or driver_email or 'Driver',
                    'driver_email': driver_email,
                    'package_name': package_name
                })

            # Stats
            try:
                all_resp = supabase.table('tourist_reviews').select('rating').eq('tourist_id', tourist_id).eq('is_published', True).execute()
                all_reviews = all_resp.data if hasattr(all_resp, 'data') else []
                stats = self._compute_stats(all_reviews)
            except Exception:
                stats = self._compute_stats(enriched)

            return Response({'success': True, 'data': {'reviews': enriched, **stats}})
        except Exception as e:
            print(f'Error getting tourist reviews: {str(e)}')
            return Response({'success': False, 'error': 'Failed to fetch tourist reviews', 'data': {}}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='package/(?P<package_id>[^/.]+)')
    def get_package_reviews(self, request, package_id=None):
        """Return reviews and stats for a package.
        Query params: limit (default 20)
        """
        try:
            limit_param = request.query_params.get('limit') if hasattr(request, 'query_params') else request.GET.get('limit')
            limit_value = 20
            try:
                if limit_param:
                    limit_value = int(limit_param)
            except Exception:
                pass

            # Fetch recent published reviews with retry logic
            reviews = []
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = (
                        supabase
                        .table(self.TABLE_NAME)
                        .select('*')
                        .eq('package_id', package_id)
                        .eq('is_published', True)
                        .order('created_at', desc=True)
                        .limit(limit_value)
                        .execute()
                    )
                    reviews = response.data if hasattr(response, 'data') else []
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        print(f'Error getting package reviews: {str(e)}')
                        return Response({'success': True, 'data': {'reviews': [], 'average_rating': 0.0, 'review_count': 0}})
                    import time
                    time.sleep(0.5)

            # Get package name once for all reviews
            package_name = ''
            try:
                pkg_resp = supabase.table('tourpackages').select('package_name').eq('id', package_id).single().execute()
                if hasattr(pkg_resp, 'data') and pkg_resp.data:
                    package_name = pkg_resp.data.get('package_name', '')
            except Exception:
                pass

            # Enrich with reviewer info and package name
            enriched = []
            for r in reviews:
                # Add reviewer name using helper method
                r['reviewer_name'] = self._get_reviewer_display_name(r)
                
                # Handle reviewer email for anonymous reviews
                reviewer_email = ''
                is_anon = r.get('is_anonymous')
                if not (is_anon is True or str(is_anon).lower() == 'true'):
                    try:
                        user_resp = supabase.table('users').select('email').eq('id', r.get('reviewer_id')).single().execute()
                        if hasattr(user_resp, 'data') and user_resp.data:
                            reviewer_email = user_resp.data.get('email', '').strip()
                    except Exception:
                        pass
                
                enriched.append({
                    **r,
                    'reviewer_email': reviewer_email,
                    'package_name': package_name
                })

            # Compute stats across all published reviews for this package
            try:
                all_resp = (
                    supabase
                    .table(self.TABLE_NAME)
                    .select('rating')
                    .eq('package_id', package_id)
                    .eq('is_published', True)
                    .execute()
                )
                all_reviews = all_resp.data if hasattr(all_resp, 'data') else []
                stats = self._compute_stats(all_reviews)
            except Exception:
                stats = self._compute_stats(enriched)

            return Response({'success': True, 'data': {'reviews': enriched, **stats}})
        except Exception as e:
            print(f'Error getting package reviews: {str(e)}')
            return Response({'success': True, 'data': {'reviews': [], 'average_rating': 0.0, 'review_count': 0}})
