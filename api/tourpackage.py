from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase, upload_tourpackage_photo
from datetime import datetime
import traceback
import json
import base64
import logging
import copy
from core.api_utils import OptimizedViewSetMixin, APIResponseManager, cached_api_method
from core.cache_utils import CacheManager
from core.database_utils import DatabaseManager, DataProcessor
from core.jwt_auth import get_token_from_request, verify_token

try:
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# Set up logging
logger = logging.getLogger(__name__)

# Audit logging helpers
def _extract_ip(request):
    try:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
    except Exception:
        return None

def _extract_device(request):
    try:
        return request.META.get("HTTP_USER_AGENT")
    except Exception:
        return None

def _fetch_user_profile(user_id=None, email=None):
    """Enrich from public.users (FK target of audit_logs.user_id)."""
    try:
        sb = supabase_admin if supabase_admin else supabase
        q = sb.table("users").select("id,email,username,role")
        if user_id:
            r = q.eq("id", str(user_id)).single().execute()
        elif email:
            r = q.eq("email", email).single().execute()
        else:
            return {}
        return getattr(r, "data", {}) or {}
    except Exception:
        return {}

def _extract_actor(request):
    """
    Resolve actor using the same logic as refunds.py
    """
    uid = uname = role = email = None

    # 1) Admin cookies (from @admin_authenticated decorator)
    try:
        admin_user_id = request.COOKIES.get('admin_user_id')
        admin_email = request.COOKIES.get('admin_email')
        admin_authenticated = request.COOKIES.get('admin_authenticated')
        
        if admin_authenticated == '1' and admin_user_id and admin_email:
            uid = admin_user_id.strip() if admin_user_id else None
            email = admin_email.strip() if admin_email else None
            role = "admin"  # Admin web interface users are always admin
            
            # Try to get user name from database
            db_user = _fetch_user_profile(user_id=uid)
            if db_user:
                uname = db_user.get("username") or db_user.get("name") or email
            else:
                uname = email
    except Exception:
        pass

    # 2) Project helper (JWT)
    if not uid or not uname or not role:
        try:
            if get_token_from_request and verify_token:
                tok = get_token_from_request(request)
                if tok:
                    payload = verify_token(tok) or {}
                    jwt_uid = payload.get("sub") or payload.get("user_id") or payload.get("id") or payload.get("uid")
                    jwt_email = payload.get("email") or (payload.get("user_metadata") or {}).get("email")
                    
                    uid = uid or str(jwt_uid) if jwt_uid else uid
                    email = email or jwt_email
                    
                    if uid:
                        db_user = _fetch_user_profile(user_id=uid)
                        if db_user:
                            uname = uname or db_user.get("username") or db_user.get("name") or email
                            role = role or db_user.get("role")
                        else:
                            um = (payload.get("user_metadata") or {}) or {}
                            uname = uname or um.get("username") or um.get("name") or um.get("full_name") or email
                            role = role or um.get("role")
        except Exception:
            pass

    # 3) Django user fallback
    if not uid or not uname or not role:
        try:
            if getattr(request, "user", None) and getattr(request.user, "is_authenticated", False):
                uid = uid or str(getattr(request.user, "id", None) or getattr(request.user, "pk", None) or "")
                uname = uname or getattr(request.user, "username", None) or getattr(request.user, "email", None)
                email = email or getattr(request.user, "email", None)
                role = role or str(getattr(request.user, "role", None) or "admin")
        except Exception:
            pass

    # 4) Body hints (last resort)
    if not uid or not uname or not role:
        try:
            data = getattr(request, "data", {}) or {}
            actor_block = data.get("actor") or {}
            uid = uid or str(actor_block.get("user_id") or data.get("user_id") or data.get("admin_id") or "") or None
            uname = uname or actor_block.get("username") or data.get("username") or data.get("name")
            email = email or actor_block.get("email") or data.get("email")
            role = role or actor_block.get("role") or data.get("role")
        except Exception:
            pass

    # Final fallbacks
    if not uname:
        uname = email or "System Admin"
    if not role:
        role = "admin"

    return {"user_id": uid, "username": uname, "role": role, "email": email}

def _audit_log(request, action, entity_name, entity_id=None, old_data=None, new_data=None):
    """Insert audit log entry"""
    try:
        admin_client = supabase_admin if supabase_admin else supabase
        actor = _extract_actor(request)
        
        payload = {
            "action": action,
            "entity_name": entity_name,
            "entity_id": str(entity_id) if entity_id else None,
            "username": actor["username"],
            "role": actor["role"],
            "old_data": old_data,
            "new_data": new_data,
            "ip_address": _extract_ip(request),
            "device_info": _extract_device(request),
        }
        
        if actor["user_id"]:
            payload["user_id"] = actor["user_id"]
        
        admin_client.table("audit_logs").insert(payload).execute()
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")

class TourPackageViewSet(OptimizedViewSetMixin, viewsets.ViewSet):
    """ViewSet for tour packages (full CRUD operations)"""
    permission_classes = [AllowAny]  # Allow all operations for development
    renderer_classes = [JSONRenderer, BrowsableAPIRenderer]  # Allow both JSON and browsable API
    
    # Optimization configuration
    TABLE_NAME = 'tourpackages'
    MODULE_NAME = 'tourpackage'
    DATE_FIELDS = ['expiration_date', 'created_at']  # Removed 'updated_at' as it doesn't exist
    JSON_FIELDS = ['available_days', 'photos']
    CACHE_TIMEOUT = 'medium'
    
    def get_permissions(self):
        """Use AllowAny for all operations during development"""
        # Temporarily disable authentication for development
        return [AllowAny()]
        
        # Uncomment this for production with proper authentication
        # if getattr(self, 'action', None) in ['create', 'update', 'partial_update', 'destroy', 'activate', 'deactivate', 'toggle_status']:
        #     return [IsAuthenticated()]
        # return [AllowAny()]

    def list(self, request):
        """Get all tour packages with centralized optimization"""
        logger.info(f"TourPackage list request from user: {getattr(request, 'user', 'Anonymous')}")
        
        try:
            # Get packages directly from database to ensure all fields
            from tartanilla_admin.supabase import supabase
            response = supabase.table('tourpackages').select('*').order('created_at', desc=True).execute()
            
            packages = response.data if hasattr(response, 'data') else []
            
            # Ensure all required fields are present for mobile compatibility
            for package in packages:
                if 'start_time' not in package or not package['start_time']:
                    package['start_time'] = '09:00'
                if 'status' not in package:
                    package['status'] = 'active' if package.get('is_active') else 'inactive'
                
                # Add review aggregation
                package_id = package.get('id')
                if package_id:
                    try:
                        # Get reviews for this package
                        reviews_response = supabase.table('package_reviews').select('rating, comment, reviewer_id, created_at, is_anonymous').eq('package_id', package_id).eq('is_published', True).order('created_at', desc=True).execute()
                        reviews = reviews_response.data if hasattr(reviews_response, 'data') else []
                        
                        # Calculate average rating and count
                        ratings = [r.get('rating', 0) for r in reviews if isinstance(r.get('rating'), (int, float))]
                        reviews_count = len(ratings)
                        average_rating = round(sum(ratings) / reviews_count, 1) if reviews_count > 0 else 0.0
                        
                        # Add reviewer names to reviews
                        for review in reviews:
                            reviewer_name = 'Customer'
                            try:
                                user_resp = supabase.table('users').select('name, email').eq('id', review.get('reviewer_id')).single().execute()
                                if hasattr(user_resp, 'data') and user_resp.data:
                                    name = user_resp.data.get('name', '').strip()
                                    email = user_resp.data.get('email', '').strip()
                                    display_name = name or email
                                    
                                    # Apply masking if anonymous
                                    is_anon = review.get('is_anonymous')
                                    if is_anon is True or str(is_anon).lower() == 'true':
                                        if len(display_name) > 2:
                                            display_name = display_name[0] + '*' * (len(display_name) - 2) + display_name[-1]
                                    reviewer_name = display_name
                            except Exception:
                                pass
                            review['reviewer_name'] = reviewer_name
                        
                        package['average_rating'] = average_rating
                        package['reviews_count'] = reviews_count
                        package['reviews'] = reviews[:5]  # Limit to 5 recent reviews
                        
                    except Exception as e:
                        logger.warning(f"Error fetching reviews for package {package_id}: {e}")
                        package['average_rating'] = 0.0
                        package['reviews_count'] = 0
                        package['reviews'] = []
                else:
                    package['average_rating'] = 0.0
                    package['reviews_count'] = 0
                    package['reviews'] = []
            
            return APIResponseManager.success_response(data=packages)
            
        except Exception as e:
            logger.error(f'Error fetching tour packages: {str(e)}')
            return APIResponseManager.error_response(
                'Failed to fetch tour packages',
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def retrieve(self, request, pk=None):
        """Get a specific tour package with itinerary"""
        logger.info(f"TourPackage retrieve request for pk={pk}")
        
        try:
            response = supabase.table('tourpackages').select('*').eq('id', pk).single().execute()
            
            if not (hasattr(response, 'data') and response.data):
                return APIResponseManager.not_found_response('Tour package')
            
            package = response.data
            
            # Get itinerary
            itinerary_response = supabase.table('tour_itinerary').select('*').eq('package_id', pk).order('step_order').execute()
            package['itinerary'] = itinerary_response.data if hasattr(itinerary_response, 'data') else []
            
            if 'start_time' not in package or not package['start_time']:
                package['start_time'] = '09:00'
            if 'status' not in package:
                package['status'] = 'active' if package.get('is_active') else 'inactive'
            
            # Add review aggregation for single package
            try:
                # Get reviews for this package
                reviews_response = supabase.table('package_reviews').select('rating, comment, reviewer_id, created_at, is_anonymous').eq('package_id', pk).eq('is_published', True).order('created_at', desc=True).execute()
                reviews = reviews_response.data if hasattr(reviews_response, 'data') else []
                
                # Calculate average rating and count
                ratings = [r.get('rating', 0) for r in reviews if isinstance(r.get('rating'), (int, float))]
                reviews_count = len(ratings)
                average_rating = round(sum(ratings) / reviews_count, 1) if reviews_count > 0 else 0.0
                
                # Add reviewer names to reviews
                for review in reviews:
                    reviewer_name = 'Customer'
                    try:
                        user_resp = supabase.table('users').select('name, email').eq('id', review.get('reviewer_id')).single().execute()
                        if hasattr(user_resp, 'data') and user_resp.data:
                            name = user_resp.data.get('name', '').strip()
                            email = user_resp.data.get('email', '').strip()
                            display_name = name or email
                            
                            # Apply masking if anonymous
                            is_anon = review.get('is_anonymous')
                            if is_anon is True or str(is_anon).lower() == 'true':
                                if len(display_name) > 2:
                                    display_name = display_name[0] + '*' * (len(display_name) - 2) + display_name[-1]
                            reviewer_name = display_name
                    except Exception:
                        pass
                    review['reviewer_name'] = reviewer_name
                
                package['average_rating'] = average_rating
                package['reviews_count'] = reviews_count
                package['reviews'] = reviews
                
            except Exception as e:
                logger.warning(f"Error fetching reviews for package {pk}: {e}")
                package['average_rating'] = 0.0
                package['reviews_count'] = 0
                package['reviews'] = []
            
            return APIResponseManager.success_response(data=package)
            
        except Exception as e:
            logger.error(f'Error fetching tour package {pk}: {str(e)}')
            return APIResponseManager.error_response('Failed to fetch tour package', status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request):
        """Create a new tour package"""
        try:
            logger.info(f"TourPackage create request from user: {getattr(request, 'user', 'Anonymous')}")
            
            # Temporarily disable authentication check for development
            # user = getattr(request, 'user', None)
            # if not (user and user.is_authenticated):
            #     logger.warning("Unauthenticated user attempted to create tour package")
            #     return Response({'success': False, 'error': 'Authentication required'}, status=status.HTTP_403_FORBIDDEN)

            # Handle both DRF and Django requests
            if hasattr(request, 'data'):
                # DRF request
                data = request.data
                logger.info(f"DRF request data: {data}")
            else:
                # Django request - try to get data from POST or JSON
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                    logger.info(f"Django JSON request data: {data}")
                else:
                    data = request.POST.dict()
                    logger.info(f"Django POST request data: {data}")
            
            # Validate required fields
            required_fields = ['package_name', 'description', 'price', 'destination']
            for field in required_fields:
                if not data.get(field):
                    logger.warning(f"Missing required field: {field}")
                    return Response({
                        'success': False,
                        'error': f'Missing required field: {field}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate constraints
            if len(data.get('package_name', '')) < 3:
                return Response({'success': False, 'error': 'Package name must be at least 3 characters'}, status=status.HTTP_400_BAD_REQUEST)
            if len(data.get('description', '')) < 10:
                return Response({'success': False, 'error': 'Description must be at least 10 characters'}, status=status.HTTP_400_BAD_REQUEST)
            if float(data.get('price', 0)) < 1:
                return Response({'success': False, 'error': 'Price must be at least 1'}, status=status.HTTP_400_BAD_REQUEST)
            
            max_pax = data.get('max_pax')
            if max_pax:
                max_pax = int(max_pax)
                if max_pax < 1 or max_pax > 4:
                    return Response({'success': False, 'error': 'Max passengers must be between 1 and 4'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate pickup location is from map points
            pickup_location = data.get('pickup_location')
            if pickup_location and pickup_location != 'Plaza Independencia':
                try:
                    # Check if pickup location exists in map_points with type 'pickup'
                    map_points_response = supabase.table('map_points').select('id, name, latitude, longitude').eq('name', pickup_location).eq('point_type', 'pickup').execute()
                    
                    if not (hasattr(map_points_response, 'data') and map_points_response.data):
                        logger.warning(f"Invalid pickup location: {pickup_location}")
                        return Response({
                            'success': False,
                            'error': f'Pickup location "{pickup_location}" must be selected from available map points. Please choose a valid pickup point.'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    # Auto-fill coordinates from map point if not provided
                    map_point = map_points_response.data[0]
                    if not data.get('pickup_lat') or not data.get('pickup_lng'):
                        data['pickup_lat'] = map_point['latitude']
                        data['pickup_lng'] = map_point['longitude']
                        logger.info(f"Auto-filled coordinates for {pickup_location}: {data['pickup_lat']}, {data['pickup_lng']}")
                        
                except Exception as e:
                    logger.error(f"Error validating pickup location: {e}")
                    return Response({
                        'success': False,
                        'error': 'Error validating pickup location. Please try again.'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Process photos if provided - support multiple photos
            photos = []
            if 'photos' in data:
                if isinstance(data['photos'], list):
                    photos_data = data['photos']
                elif isinstance(data['photos'], str):
                    try:
                        photos_data = json.loads(data['photos'])
                    except:
                        photos_data = []
                else:
                    photos_data = []
                
                logger.info(f"Processing {len(photos_data)} photos")
                
                for photo_data in photos_data:
                    if isinstance(photo_data, dict) and photo_data.get('url'):
                        photos.append({
                            'url': photo_data['url'],
                            'storage_path': photo_data.get('storage_path', ''),
                            'filename': photo_data.get('filename', ''),
                            'caption': photo_data.get('caption', ''),
                            'uploaded_at': photo_data.get('uploaded_at', datetime.now().isoformat())
                        })
                    elif isinstance(photo_data, str):  # Single photo URL
                        photos.append({
                            'url': photo_data,
                            'storage_path': '',
                            'filename': '',
                            'caption': '',
                            'uploaded_at': datetime.now().isoformat()
                        })
            
            # Process available days from checkboxes
            available_days = []
            if 'available_days_data' in data and data['available_days_data']:
                try:
                    if isinstance(data['available_days_data'], str):
                        available_days = json.loads(data['available_days_data'])
                    elif isinstance(data['available_days_data'], list):
                        available_days = data['available_days_data']
                except (json.JSONDecodeError, TypeError):
                    available_days = []
            
            # Process expiration date - handle "no expiration" case
            expiration_date = None
            if data.get('no_expiry') or data.get('no_expiration'):
                # If no_expiry is checked, set expiration_date to None
                expiration_date = None
            elif 'expiration_date_data' in data and data['expiration_date_data']:
                try:
                    expiration_date_str = data['expiration_date_data']
                    if expiration_date_str and expiration_date_str.lower() not in ['no expiration', 'none', '']:
                        expiration_date = datetime.fromisoformat(expiration_date_str.replace('Z', '+00:00')).date()
                        expiration_date = expiration_date.isoformat()
                except (ValueError, TypeError):
                    expiration_date = None
            elif 'expiration_date' in data and data['expiration_date']:
                try:
                    expiration_date_str = data['expiration_date']
                    if expiration_date_str and expiration_date_str.lower() not in ['no expiration', 'none', '']:
                        expiration_date = datetime.fromisoformat(expiration_date_str.replace('Z', '+00:00')).date()
                        expiration_date = expiration_date.isoformat()
                except (ValueError, TypeError):
                    expiration_date = None
            
            # Get creator info - check if admin or driver
            creator_id = None
            creator_role = data.get('creator_role', 'admin')  # Default to admin
            
            # If driver is creating, get driver_id from request
            if creator_role == 'driver':
                creator_id = data.get('driver_id') or data.get('creator_id')
            
            # Process itinerary data (step-by-step with time stamps)
            itinerary_data = []
            stops_lat = []
            stops_lng = []
            
            if data.get('itinerary'):
                try:
                    itinerary = data.get('itinerary', '[]')
                    if isinstance(itinerary, str):
                        itinerary_data = json.loads(itinerary) if itinerary.strip() else []
                    elif isinstance(itinerary, list):
                        itinerary_data = itinerary
                    
                    # Extract coordinates for backward compatibility
                    for step in itinerary_data:
                        if isinstance(step, dict) and step.get('location_type') == 'stop':
                            try:
                                lat = float(step.get('latitude', 0))
                                lng = float(step.get('longitude', 0))
                                if -90 <= lat <= 90 and -180 <= lng <= 180:
                                    stops_lat.append(lat)
                                    stops_lng.append(lng)
                            except (ValueError, TypeError):
                                continue
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    logger.warning(f"Error parsing itinerary: {e}")
                    itinerary_data = []

            # Prepare package data
            package_data = {
                'package_name': data.get('package_name'),
                'description': data.get('description'),
                'price': data.get('price', 0),
                'price_type': data.get('price_type', 'per_person'),
                'pickup_location': data.get('pickup_location', 'Plaza Independencia'),
                'destination': data.get('destination'),
                'pickup_lat': data.get('pickup_lat'),
                'pickup_lng': data.get('pickup_lng'),
                'dropoff_lat': data.get('dropoff_lat'),
                'dropoff_lng': data.get('dropoff_lng'),
                'route': data.get('route'),
                'duration_hours': int(data.get('duration_hours', 0)),
                'duration_minutes': int(data.get('duration_minutes', 0)),
                'start_time': data.get('pickup_time', '09:00'),  # Map pickup_time to start_time column
                'stops_lat': stops_lat,
                'stops_lng': stops_lng,
                'available_days': available_days,
                'expiration_date': expiration_date,
                'max_pax': data.get('max_pax'),
                'photos': [{'url': photo['url']} if isinstance(photo, dict) and 'url' in photo else {'url': photo} if isinstance(photo, str) else photo for photo in photos] if photos else [],
                'driver_id': creator_id,  # Set driver_id if created by driver, null if admin
                'is_active': True,
                'status': 'active',  # Mobile expects status field
                'created_at': datetime.now().isoformat()
            }
            
            # Remove None values
            package_data = {k: v for k, v in package_data.items() if v is not None}
            
            logger.info(f"Creating tour package with data: {package_data}")
            
            # Create package
            result = self.optimized_create(request, package_data)
            
            # Save itinerary if package created successfully
            if result.status_code == 201 and itinerary_data:
                try:
                    response_data = result.data if hasattr(result, 'data') else {}
                    if isinstance(response_data, dict) and 'data' in response_data:
                        package_id = response_data['data'].get('id')
                    else:
                        package_id = response_data.get('id')
                    
                    if package_id:
                        logger.info(f"Saving {len(itinerary_data)} itinerary steps for package {package_id}")
                        for step in itinerary_data:
                            itinerary_record = {
                                'package_id': package_id,
                                'step_order': int(step.get('step_order', 0)),
                                'location_name': step.get('location_name', ''),
                                'location_type': step.get('location_type', 'stop'),
                                'latitude': float(step.get('latitude', 0)),
                                'longitude': float(step.get('longitude', 0)),
                                'duration_hours': int(step.get('duration_hours', 0)),
                                'duration_minutes': int(step.get('duration_minutes', 0)),
                                'description': step.get('description', ''),
                                'activities': step.get('activities', [])
                            }
                            logger.info(f"Inserting itinerary step: {itinerary_record}")
                            supabase.table('tour_itinerary').insert(itinerary_record).execute()
                        logger.info(f"Successfully saved {len(itinerary_data)} itinerary steps")
                    else:
                        logger.error(f"No package_id found in result: {response_data}")
                except Exception as e:
                    logger.error(f"Error saving itinerary: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Add audit log
            if result.status_code == 201:
                _audit_log(request, "TOUR_PACKAGE_CREATE", "tourpackages",
                    entity_id=result.data.get('id') if hasattr(result, 'data') else None,
                    new_data=package_data)
            
            return result
            
        except Exception as e:
            logger.error(f'Error creating package: {str(e)}')
            logger.error(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, pk=None):
        """Update an existing tour package"""
        try:
            logger.info(f"TourPackage update request for pk={pk} from user: {getattr(request, 'user', 'Anonymous')}")
            
            # Check if package was created by driver - admin can only view, not edit
            package_check = supabase.table('tourpackages').select('driver_id').eq('id', pk).single().execute()
            if hasattr(package_check, 'data') and package_check.data:
                driver_id = package_check.data.get('driver_id')
                if driver_id:  # Package created by driver
                    return Response({
                        'success': False, 
                        'error': 'Cannot edit driver-created packages. Admin can only view driver packages.'
                    }, status=status.HTTP_403_FORBIDDEN)
            
            # Temporarily disable authentication check for development
            # user = getattr(request, 'user', None)
            # if not (user and user.is_authenticated):
            #     logger.warning("Unauthenticated user attempted to update tour package")
            #     return Response({'success': False, 'error': 'Authentication required'}, status=status.HTTP_403_FORBIDDEN)

            # Handle both DRF and Django requests
            if hasattr(request, 'data'):
                # DRF request
                data = request.data
                logger.info(f"DRF update request data: {data}")
            else:
                # Django request - try to get data from POST or JSON
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                    logger.info(f"Django JSON update request data: {data}")
                else:
                    data = request.POST.dict()
                    logger.info(f"Django POST update request data: {data}")
            
            # Handle simple status toggle
            if 'is_active' in data and len(data) == 1:
                update_data = {
                    'is_active': data['is_active']
                    # Removed 'updated_at' as it doesn't exist in the Supabase table
                }
                logger.info(f"Simple status toggle to: {data['is_active']}")
            else:
                # Validate required fields for full update
                required_fields = ['package_name', 'description', 'price', 'destination']
                for field in required_fields:
                    if not data.get(field):
                        logger.warning(f"Missing required field for update: {field}")
                        return Response({
                            'success': False,
                            'error': f'Missing required field: {field}'
                        }, status=status.HTTP_400_BAD_REQUEST)
                
                # Validate pickup location is from map points
                pickup_location = data.get('pickup_location')
                if pickup_location and pickup_location != 'Plaza Independencia':
                    try:
                        # Check if pickup location exists in map_points with type 'pickup'
                        map_points_response = supabase.table('map_points').select('id, name, latitude, longitude').eq('name', pickup_location).eq('point_type', 'pickup').execute()
                        
                        if not (hasattr(map_points_response, 'data') and map_points_response.data):
                            logger.warning(f"Invalid pickup location for update: {pickup_location}")
                            return Response({
                                'success': False,
                                'error': f'Pickup location "{pickup_location}" must be selected from available map points. Please choose a valid pickup point.'
                            }, status=status.HTTP_400_BAD_REQUEST)
                        
                        # Auto-fill coordinates from map point if not provided
                        map_point = map_points_response.data[0]
                        if not data.get('pickup_lat') or not data.get('pickup_lng'):
                            data['pickup_lat'] = map_point['latitude']
                            data['pickup_lng'] = map_point['longitude']
                            logger.info(f"Auto-filled coordinates for update {pickup_location}: {data['pickup_lat']}, {data['pickup_lng']}")
                            
                    except Exception as e:
                        logger.error(f"Error validating pickup location for update: {e}")
                        return Response({
                            'success': False,
                            'error': 'Error validating pickup location. Please try again.'
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
                # Process photos if provided
                photos = []
                if 'photos' in data:
                    if data['photos']:  # Has photos
                        photos_data = data['photos'] if isinstance(data['photos'], list) else []
                        logger.info(f"Processing {len(photos_data)} photos for update")
                        
                        for photo_data in photos_data:
                            if isinstance(photo_data, dict) and photo_data.get('url'):
                                photos.append({
                                    'url': photo_data['url'],
                                    'storage_path': photo_data.get('storage_path', ''),
                                    'filename': photo_data.get('filename', ''),
                                    'caption': photo_data.get('caption', ''),
                                    'uploaded_at': photo_data.get('uploaded_at', datetime.now().isoformat())
                                })
                    else:  # Empty photos array - user removed all photos
                        photos = []
                        logger.info("Removing all photos from tour package")
                elif data.get('photos') == '[]' or data.get('photos') == []:  # Handle empty photos explicitly
                    photos = []
                    logger.info("Explicitly removing all photos from tour package")
                
                # Process available days from checkboxes
                available_days = []
                if 'available_days_data' in data and data['available_days_data']:
                    try:
                        if isinstance(data['available_days_data'], str):
                            available_days = json.loads(data['available_days_data'])
                        elif isinstance(data['available_days_data'], list):
                            available_days = data['available_days_data']
                    except (json.JSONDecodeError, TypeError):
                        available_days = []
                
                # Process expiration date
                expiration_date = None
                if data.get('no_expiry'):
                    # If no_expiry is checked, set expiration_date to None
                    expiration_date = None
                elif 'expiration_date_data' in data and data['expiration_date_data']:
                    try:
                        expiration_date_str = data['expiration_date_data']
                        if expiration_date_str:
                            expiration_date = datetime.fromisoformat(expiration_date_str.replace('Z', '+00:00')).date()
                            expiration_date = expiration_date.isoformat()
                    except (ValueError, TypeError):
                        expiration_date = None
                
                # Process stops data for update
                stops_data = []
                stops_lat = []
                stops_lng = []
                if data.get('selected_stops'):
                    try:
                        selected_stops = data.get('selected_stops', '[]')
                        # Handle if it's already a list
                        if isinstance(selected_stops, list):
                            stops_data = selected_stops
                        elif isinstance(selected_stops, str):
                            # Clean the string before parsing
                            cleaned_str = selected_stops.strip()
                            if cleaned_str and cleaned_str != '[]':
                                stops_data = json.loads(cleaned_str)
                            else:
                                stops_data = []
                        else:
                            stops_data = []
                        
                        # Extract coordinates safely
                        for stop in stops_data:
                            if isinstance(stop, dict):
                                try:
                                    lat = float(stop.get('latitude', 0))
                                    lng = float(stop.get('longitude', 0))
                                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                                        stops_lat.append(lat)
                                        stops_lng.append(lng)
                                except (ValueError, TypeError):
                                    continue
                                    
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        logger.warning(f"Error parsing selected_stops for update: {e} - Data: {data.get('selected_stops', '')[:200]}")
                        stops_data = []
                        stops_lat = []
                        stops_lng = []

                # Prepare update data (don't update driver_id on edit)
                update_data = {
                    'package_name': data.get('package_name'),
                    'description': data.get('description'),
                    'price': data.get('price', 0),
                    'pickup_location': data.get('pickup_location', 'Plaza Independencia'),
                    'destination': data.get('destination'),
                    'pickup_lat': data.get('pickup_lat'),
                    'pickup_lng': data.get('pickup_lng'),
                    'dropoff_lat': data.get('dropoff_lat'),
                    'dropoff_lng': data.get('dropoff_lng'),
                    'route': data.get('route'),
                    'duration_hours': int(data.get('duration_hours', 0)),
                    'duration_minutes': int(data.get('duration_minutes', 0)),
                    'start_time': data.get('pickup_time', '09:00'),  # Map pickup_time to start_time column
                    'stops_lat': stops_lat,
                    'stops_lng': stops_lng,
                    'available_days': available_days,
                    'expiration_date': expiration_date,
                    'max_pax': data.get('max_pax')
                }
                
                # Always include photos in update if photos field is present
                if 'photos' in data:
                    update_data['photos'] = [{'url': photo['url']} if isinstance(photo, dict) and 'url' in photo else {'url': photo} if isinstance(photo, str) else photo for photo in photos] if photos else []
                
                # Remove None values
                update_data = {k: v for k, v in update_data.items() if v is not None}
            
            logger.info(f"Updating tour package {pk} with data: {update_data}")
            
            # Get old data for audit log
            old_response = supabase.table('tourpackages').select('*').eq('id', pk).single().execute()
            old_data = old_response.data if hasattr(old_response, 'data') else None
            
            # Direct database update to avoid response processing issues
            updated_record = DatabaseManager.update_record('tourpackages', pk, update_data)
            
            if not updated_record:
                return APIResponseManager.error_response(
                    'Tour package not found or update failed',
                    status.HTTP_404_NOT_FOUND
                )
            
            # Update itinerary if provided
            if data.get('itinerary'):
                try:
                    itinerary = data.get('itinerary', '[]')
                    if isinstance(itinerary, str):
                        itinerary_data = json.loads(itinerary) if itinerary.strip() else []
                    elif isinstance(itinerary, list):
                        itinerary_data = itinerary
                    else:
                        itinerary_data = []
                    
                    if itinerary_data:
                        logger.info(f"Updating itinerary for package {pk} with {len(itinerary_data)} steps")
                        # Delete existing itinerary
                        supabase.table('tour_itinerary').delete().eq('package_id', pk).execute()
                        
                        # Insert new itinerary
                        for step in itinerary_data:
                            itinerary_record = {
                                'package_id': pk,
                                'step_order': int(step.get('step_order', 0)),
                                'location_name': step.get('location_name', ''),
                                'location_type': step.get('location_type', 'stop'),
                                'latitude': float(step.get('latitude', 0)),
                                'longitude': float(step.get('longitude', 0)),
                                'duration_hours': int(step.get('duration_hours', 0)),
                                'duration_minutes': int(step.get('duration_minutes', 0)),
                                'description': step.get('description', ''),
                                'activities': step.get('activities', [])
                            }
                            supabase.table('tour_itinerary').insert(itinerary_record).execute()
                        logger.info(f"Successfully updated itinerary with {len(itinerary_data)} steps")
                except Exception as e:
                    logger.error(f"Error updating itinerary: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Add audit log for successful update
            _audit_log(
                request,
                "TOUR_PACKAGE_UPDATE",
                "tourpackages",
                entity_id=pk,
                old_data=old_data,
                new_data=update_data
            )
            
            return APIResponseManager.success_response(
                data=updated_record,
                message='Tour package updated successfully'
            )
            
        except Exception as e:
            logger.error(f'Error updating package: {str(e)}')
            logger.error(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, pk=None):
        """Delete a tour package"""
        try:
            logger.info(f"TourPackage delete request for pk={pk} from user: {getattr(request, 'user', 'Anonymous')}")
            
            # Check if package was created by driver - admin cannot delete driver packages
            package_check = supabase.table('tourpackages').select('driver_id').eq('id', pk).single().execute()
            if hasattr(package_check, 'data') and package_check.data:
                driver_id = package_check.data.get('driver_id')
                if driver_id:  # Package created by driver
                    return Response({
                        'success': False, 
                        'error': 'Cannot delete driver-created packages. Only drivers can manage their own packages.'
                    }, status=status.HTTP_403_FORBIDDEN)
            
            # Temporarily disable authentication check for development
            # user = getattr(request, 'user', None)
            # if not (user and user.is_authenticated):
            #     logger.warning("Unauthenticated user attempted to delete tour package")
            #     return Response({'success': False, 'error': 'Authentication required'}, status=status.HTTP_403_FORBIDDEN)

            # Get old data for audit log
            old_response = supabase.table('tourpackages').select('*').eq('id', pk).single().execute()
            old_data = old_response.data if hasattr(old_response, 'data') else None
            
            # Direct database delete to ensure proper response
            deleted = DatabaseManager.delete_record('tourpackages', pk)
            
            if deleted:
                # Add audit log for successful deletion
                _audit_log(
                    request,
                    "TOUR_PACKAGE_DELETE",
                    "tourpackages",
                    entity_id=pk,
                    old_data=old_data
                )
                
                return APIResponseManager.success_response(
                    message='Tour package deleted successfully'
                )
            else:
                return APIResponseManager.not_found_response('Tour package')
            
        except Exception as e:
            logger.error(f'Error deleting package: {str(e)}')
            logger.error(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[AllowAny])  # Changed to AllowAny
    def activate(self, request, pk=None):
        """Activate a tour package"""
        try:
            # Get user from request
            user = getattr(request, 'user', None)
            
            # Check for JWT token in request
            token = get_token_from_request(request)
            supabase_user = verify_token(token) if token else None
            
            # Use supabase_user if available, otherwise use request.user
            effective_user = supabase_user or user
            user_display = getattr(effective_user, 'email', str(effective_user)) if effective_user else 'Anonymous'
            
            logger.info(f"TourPackage activate request for pk={pk} from user: {user_display}")
            
            # Temporarily disable authentication check for development
            # if not (effective_user and getattr(effective_user, 'is_authenticated', False)):
            #     logger.warning("Unauthenticated user attempted to activate tour package")
            #     return Response({'success': False, 'error': 'Authentication required'}, status=status.HTTP_403_FORBIDDEN)

            # Check if package was created by driver and verify ownership
            package_check = supabase.table('tourpackages').select('driver_id').eq('id', pk).single().execute()
            if hasattr(package_check, 'data') and package_check.data:
                package_driver_id = package_check.data.get('driver_id')
                if package_driver_id:  # Package created by driver
                    # Get current user's driver_id from request data
                    current_driver_id = request.data.get('driver_id') if hasattr(request, 'data') else None
                    if not current_driver_id and hasattr(request, 'POST'):
                        current_driver_id = request.POST.get('driver_id')
                    
                    # Only allow the package creator to activate their own package
                    if package_driver_id != current_driver_id:
                        return Response({
                            'success': False, 
                            'error': 'Cannot modify driver-created packages. Only drivers can manage their own packages.'
                        }, status=status.HTTP_403_FORBIDDEN)
            
            # Update package to active
            update_data = {
                'is_active': True,
                'status': 'active'
            }
            
            logger.info(f"Activating tour package {pk}")
            
            # Get old data for audit log
            old_response = supabase.table('tourpackages').select('*').eq('id', pk).single().execute()
            old_data = old_response.data if hasattr(old_response, 'data') else None
            
            # Direct database update to ensure proper response
            updated_record = DatabaseManager.update_record('tourpackages', pk, update_data)
            
            if updated_record:
                # Add audit log for successful activation
                _audit_log(
                    request,
                    "TOUR_PACKAGE_ACTIVATE",
                    "tourpackages",
                    entity_id=pk,
                    old_data=old_data,
                    new_data=update_data
                )
                
                return APIResponseManager.success_response(
                    data=updated_record,
                    message='Tour package activated successfully'
                )
            else:
                return APIResponseManager.error_response(
                    'Failed to activate package',
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
        except Exception as e:
            logger.error(f'Error activating package: {str(e)}')
            logger.error(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[AllowAny])  # Changed to AllowAny
    def deactivate(self, request, pk=None):
        """Deactivate a tour package"""
        try:
            # Get user from request
            user = getattr(request, 'user', None)
            
            # Check for JWT token in request
            token = get_token_from_request(request)
            supabase_user = verify_token(token) if token else None
            
            # Use supabase_user if available, otherwise use request.user
            effective_user = supabase_user or user
            user_display = getattr(effective_user, 'email', str(effective_user)) if effective_user else 'Anonymous'
            
            logger.info(f"TourPackage deactivate request for pk={pk} from user: {user_display}")
            
            # Check if package was created by driver and verify ownership
            package_check = supabase.table('tourpackages').select('driver_id').eq('id', pk).single().execute()
            if hasattr(package_check, 'data') and package_check.data:
                package_driver_id = package_check.data.get('driver_id')
                if package_driver_id:  # Package created by driver
                    # Get current user's driver_id from request data
                    current_driver_id = request.data.get('driver_id') if hasattr(request, 'data') else None
                    if not current_driver_id and hasattr(request, 'POST'):
                        current_driver_id = request.POST.get('driver_id')
                    
                    # Only allow the package creator to deactivate their own package
                    if package_driver_id != current_driver_id:
                        return Response({
                            'success': False, 
                            'error': 'Cannot modify driver-created packages. Only drivers can manage their own packages.'
                        }, status=status.HTTP_403_FORBIDDEN)
            
            # Update package to inactive
            update_data = {
                'is_active': False,
                'status': 'inactive'
            }
            
            logger.info(f"Deactivating tour package {pk}")
            
            # Get old data for audit log
            old_response = supabase.table('tourpackages').select('*').eq('id', pk).single().execute()
            old_data = old_response.data if hasattr(old_response, 'data') else None
            
            # Direct database update to ensure proper response
            updated_record = DatabaseManager.update_record('tourpackages', pk, update_data)
            
            if updated_record:
                # Add audit log for successful deactivation
                _audit_log(
                    request,
                    "TOUR_PACKAGE_DEACTIVATE",
                    "tourpackages",
                    entity_id=pk,
                    old_data=old_data,
                    new_data=update_data
                )
                
                return APIResponseManager.success_response(
                    data=updated_record,
                    message='Tour package deactivated successfully'
                )
            else:
                return APIResponseManager.error_response(
                    'Failed to deactivate package',
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
        except Exception as e:
            logger.error(f'Error deactivating package: {str(e)}')
            logger.error(f'Traceback: {traceback.format_exc()}')
            error_msg = str(e).replace('"', '').replace("'", '')
            return Response({
                'success': False,
                'error': error_msg
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[AllowAny])  # Changed to AllowAny
    def toggle_status(self, request, pk=None):
        """Toggle tour package active status with restrictions"""
        try:
            # Get user from request
            user = getattr(request, 'user', None)
            
            # Check for JWT token in request
            token = get_token_from_request(request)
            supabase_user = verify_token(token) if token else None
            
            # Use supabase_user if available, otherwise use request.user
            effective_user = supabase_user or user
            user_display = getattr(effective_user, 'email', str(effective_user)) if effective_user else 'Anonymous'
            
            logger.info(f"TourPackage toggle status request for pk={pk} from user: {user_display}")

            # Get current package status and check ownership
            current_response = supabase.table('tourpackages').select('is_active, driver_id').eq('id', pk).single().execute()
            
            if not (hasattr(current_response, 'data') and current_response.data):
                logger.warning(f"Tour package {pk} not found for status toggle")
                return Response({
                    'success': False,
                    'error': 'Tour package not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Check if package was created by driver and verify ownership
            package_driver_id = current_response.data.get('driver_id')
            if package_driver_id:  # Package created by driver
                # Get current user's driver_id from request data
                current_driver_id = request.data.get('driver_id') if hasattr(request, 'data') else None
                if not current_driver_id and hasattr(request, 'POST'):
                    current_driver_id = request.POST.get('driver_id')
                
                # Only allow the package creator to toggle their own package
                if package_driver_id != current_driver_id:
                    return Response({
                        'success': False, 
                        'error': 'Cannot modify driver-created packages. Only drivers can manage their own packages.'
                    }, status=status.HTTP_403_FORBIDDEN)
            
            current_status = current_response.data.get('is_active', False)
            new_status = not current_status
            
            # If activating, check if driver already has an active package
            if new_status and package_driver_id:
                active_packages = supabase.table('tourpackages').select('id, package_name').eq('driver_id', package_driver_id).eq('is_active', True).neq('id', pk).execute()
                
                if hasattr(active_packages, 'data') and active_packages.data:
                    active_package = active_packages.data[0]
                    return Response({
                        'success': False,
                        'error': f'You already have an active package: "{active_package["package_name"]}". Deactivate it first before activating another.',
                        'active_package': active_package
                    }, status=status.HTTP_409_CONFLICT)
            
            # If deactivating, check for unfinished bookings
            if not new_status:
                unfinished_statuses = ['pending', 'driver_assigned', 'in_progress']
                bookings_response = supabase.table('bookings').select('id, status, customer_name, booking_date').eq('package_id', pk).in_('status', unfinished_statuses).execute()
                
                if hasattr(bookings_response, 'data') and bookings_response.data:
                    unfinished_count = len(bookings_response.data)
                    return Response({
                        'success': False,
                        'error': f'Cannot deactivate package with {unfinished_count} unfinished booking(s). Complete or cancel existing bookings first.',
                        'unfinished_bookings': bookings_response.data
                    }, status=status.HTTP_409_CONFLICT)
            
            logger.info(f"Toggling tour package {pk} status from {current_status} to {new_status}")
            
            # Update package status and status field
            update_data = {
                'is_active': new_status,
                'status': 'active' if new_status else 'inactive'
            }
            
            logger.info(f"Update data for toggle: {update_data}")
            
            # Direct database update to ensure proper response
            logger.info(f"Attempting to update package {pk} with data: {update_data}")
            updated_record = DatabaseManager.update_record('tourpackages', pk, update_data)
            
            if updated_record:
                logger.info(f"Successfully updated package {pk}. New record: {updated_record}")
                # Add audit log for successful status toggle
                _audit_log(
                    request,
                    "TOUR_PACKAGE_STATUS_TOGGLE",
                    "tourpackages",
                    entity_id=pk,
                    old_data={'is_active': current_status},
                    new_data=update_data
                )
                
                action_text = 'activated' if new_status else 'deactivated'
                response = APIResponseManager.success_response(
                    data=updated_record,
                    message=f'Tour package {action_text} successfully'
                )
                logger.info(f"Returning success response: {response.data}")
                return response
            else:
                logger.error(f"Failed to update package {pk} in database")
                return APIResponseManager.error_response(
                    'Failed to update package status',
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
        except Exception as e:
            logger.error(f'Error toggling package status: {str(e)}')
            logger.error(f'Traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def driver_update(self, request, pk=None):
        """Allow driver to update their own tour package if no unfinished bookings exist"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            driver_id = data.get('driver_id')
            
            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'driver_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if package exists and belongs to driver
            package_response = supabase.table('tourpackages').select('*').eq('id', pk).eq('driver_id', driver_id).single().execute()
            
            if not (hasattr(package_response, 'data') and package_response.data):
                return Response({
                    'success': False,
                    'error': 'Tour package not found or you do not have permission to edit it'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Check for unfinished bookings
            unfinished_statuses = ['pending', 'driver_assigned', 'in_progress']
            bookings_response = supabase.table('bookings').select('id, status, customer_name, booking_date').eq('package_id', pk).in_('status', unfinished_statuses).execute()
            
            if hasattr(bookings_response, 'data') and bookings_response.data:
                unfinished_count = len(bookings_response.data)
                return Response({
                    'success': False,
                    'error': f'Cannot edit package with {unfinished_count} unfinished booking(s). Complete or cancel existing bookings first.',
                    'unfinished_bookings': bookings_response.data
                }, status=status.HTTP_409_CONFLICT)
            
            # Proceed with update using existing update logic
            old_data = package_response.data
            
            # Prepare update data
            update_data = {
                'package_name': data.get('package_name'),
                'description': data.get('description'),
                'price': data.get('price'),
                'destination': data.get('destination'),
                'pickup_location': data.get('pickup_location'),
                'duration_hours': data.get('duration_hours'),
                'duration_minutes': data.get('duration_minutes'),
                'max_pax': data.get('max_pax'),
                'available_days': data.get('available_days', []),
                'expiration_date': data.get('expiration_date')
            }
            
            # Remove None values
            update_data = {k: v for k, v in update_data.items() if v is not None}
            
            # Update the package
            updated_response = supabase.table('tourpackages').update(update_data).eq('id', pk).execute()
            
            if hasattr(updated_response, 'data') and updated_response.data:
                # Audit log
                _audit_log(
                    request,
                    "DRIVER_TOUR_PACKAGE_UPDATE",
                    "tourpackages",
                    entity_id=pk,
                    old_data=old_data,
                    new_data=update_data
                )
                
                return Response({
                    'success': True,
                    'data': updated_response.data[0],
                    'message': 'Tour package updated successfully'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to update tour package'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f'Error in driver_update: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def driver_packages(self, request):
        """Get tour packages created by a specific driver"""
        try:
            driver_id = request.query_params.get('driver_id')
            
            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'driver_id parameter is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get packages created by driver
            response = supabase.table('tourpackages').select('*').eq('driver_id', driver_id).order('created_at', desc=True).execute()
            
            packages = response.data if hasattr(response, 'data') else []
            
            # For each package, check if it has unfinished bookings
            for package in packages:
                unfinished_statuses = ['pending', 'driver_assigned', 'in_progress']
                bookings_response = supabase.table('bookings').select('id, status').eq('package_id', package['id']).in_('status', unfinished_statuses).execute()
                
                unfinished_count = len(bookings_response.data) if hasattr(bookings_response, 'data') and bookings_response.data else 0
                package['can_edit'] = unfinished_count == 0
                package['unfinished_bookings_count'] = unfinished_count
            
            return Response({
                'success': True,
                'data': packages,
                'count': len(packages)
            })
            
        except Exception as e:
            logger.error(f'Error fetching driver packages: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def get_pickup_points(self, request):
        """Get available pickup points from map for tour package creation"""
        try:
            logger.info("Fetching available pickup points for tour packages")
            
            # Get map points with type 'pickup' only
            response = supabase.table('map_points').select('id, name, latitude, longitude, point_type, description, image_url, image_urls').eq('point_type', 'pickup').order('name').execute()
            
            pickup_points = response.data if hasattr(response, 'data') else []
            
            logger.info(f"Found {len(pickup_points)} available pickup points")
            
            return Response({
                'success': True,
                'data': pickup_points,
                'message': f'Found {len(pickup_points)} available pickup points'
            })
            
        except Exception as e:
            logger.error(f'Error fetching pickup points: {str(e)}')
            return Response({
                'success': False,
                'error': 'Failed to fetch pickup points',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def get_dropoff_points(self, request):
        """Get available dropoff points from map for tour package creation"""
        try:
            logger.info("Fetching available dropoff points for tour packages")
            
            # Get map points with type 'dropoff' only
            response = supabase.table('map_points').select('id, name, latitude, longitude, point_type, description, image_url, image_urls').eq('point_type', 'dropoff').order('name').execute()
            
            dropoff_points = response.data if hasattr(response, 'data') else []
            
            logger.info(f"Found {len(dropoff_points)} available dropoff points")
            
            return Response({
                'success': True,
                'data': dropoff_points,
                'message': f'Found {len(dropoff_points)} available dropoff points'
            })
            
        except Exception as e:
            logger.error(f'Error fetching dropoff points: {str(e)}')
            return Response({
                'success': False,
                'error': 'Failed to fetch dropoff points',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['get'])
    def get_itinerary(self, request, pk=None):
        """Get tour package itinerary with images from map_points"""
        try:
            response = supabase.table('tour_itinerary').select('*').eq('package_id', pk).order('step_order').execute()
            itinerary = response.data if hasattr(response, 'data') else []
            
            # Enrich with images from map_points
            for step in itinerary:
                try:
                    map_point = supabase.table('map_points').select('image_url, image_urls').eq('name', step['location_name']).single().execute()
                    if hasattr(map_point, 'data') and map_point.data:
                        step['image_url'] = map_point.data.get('image_url')
                        step['image_urls'] = map_point.data.get('image_urls', [])
                except:
                    step['image_url'] = None
                    step['image_urls'] = []
            
            return Response({
                'success': True,
                'data': itinerary,
                'message': f'Found {len(itinerary)} itinerary steps'
            })
        except Exception as e:
            logger.error(f'Error fetching itinerary: {str(e)}')
            return Response({
                'success': False,
                'error': 'Failed to fetch itinerary',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def get_stops(self, request):
        """Get available stops/tourist spots for tour package creation"""
        try:
            logger.info("Fetching available stops for tour packages")
            
            response = supabase.table('map_points').select('id, name, latitude, longitude, point_type, description, icon_color, image_url, image_urls').order('name').execute()
            
            stops = response.data if hasattr(response, 'data') else []
            stops = [s for s in stops if s.get('point_type', '').lower() not in ['pickup', 'dropoff']]
            
            # Filter to show only unassociated points (not linked to roads or highlights)
            show_unassociated = request.query_params.get('unassociated', 'false').lower() == 'true'
            
            if show_unassociated:
                # Get all point IDs that are associated with roads or highlights
                try:
                    road_points = supabase.table('road_points').select('point_id').execute()
                    highlight_points = supabase.table('highlight_points').select('point_id').execute()
                    
                    associated_ids = set()
                    if hasattr(road_points, 'data') and road_points.data:
                        associated_ids.update(p.get('point_id') for p in road_points.data if p.get('point_id'))
                    if hasattr(highlight_points, 'data') and highlight_points.data:
                        associated_ids.update(p.get('point_id') for p in highlight_points.data if p.get('point_id'))
                    
                    # Filter stops to only include unassociated ones
                    stops = [s for s in stops if s.get('id') not in associated_ids]
                    logger.info(f"Filtered to {len(stops)} unassociated stops")
                except Exception as e:
                    logger.warning(f"Error filtering unassociated points: {e}")
            
            logger.info(f"Found {len(stops)} available stops")
            
            return Response({
                'success': True,
                'data': stops,
                'message': f'Found {len(stops)} available stops'
            })
            
        except Exception as e:
            logger.error(f'Error fetching stops: {str(e)}')
            return Response({
                'success': False,
                'error': 'Failed to fetch stops',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)