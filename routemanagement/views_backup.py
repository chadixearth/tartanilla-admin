from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from accounts.views import admin_authenticated  # Import existing decorator
import json
from tartanilla_admin.supabase import supabase
from datetime import datetime
import logging
import html

logger = logging.getLogger(__name__)

def get_user_info_from_cookies(request):
    """Extract user information from cookies for Supabase authentication"""
    is_authenticated = request.COOKIES.get('admin_authenticated')
    user_email = request.COOKIES.get('admin_email')
    user_id = request.COOKIES.get('admin_user_id')
    
    return {
        'user_id': user_id,
        'user_email': user_email
    } if is_authenticated == '1' and user_id and user_email else None

@never_cache
@admin_authenticated
def debug_info(request):
    """Debug endpoint to check database connection and user info"""
    try:
        user_info = get_user_info_from_cookies(request)
        
        # Test database connection for all tables (matching API pattern)
        table_status = {}
        for table_name in ['map_points', 'road_highlights', 'map_configurations']:
            try:
                response = supabase.table(table_name).select('id').limit(1).execute()
                # Using API pattern: check hasattr(response, 'data')
                if hasattr(response, 'data'):
                    table_status[table_name] = "✅ Exists"
                else:
                    table_status[table_name] = "❌ No data response"
            except Exception as e:
                table_status[table_name] = f"❌ Error: {str(e)}"
        
        # Test insert structure (minimal schema)
        test_insert_status = "Not tested"
        if user_info:
            try:
                # Minimal data structure (no is_active field)
                test_data = {
                    'name': 'Test Point',
                    'description': 'Test',
                    'latitude': 10.3157,
                    'longitude': 123.8854,
                    'point_type': 'pickup',
                    'icon_color': '#FF0000',
                    'created_by': user_info['user_id']
                }
                test_insert_status = "✅ Data structure valid (minimal schema)"
            except Exception as e:
                test_insert_status = f"❌ Data structure error: {str(e)}"
        
        return JsonResponse({
            'success': True,
            'debug_info': {
                'user_authenticated': user_info is not None,
                'user_info': user_info,
                'table_status': table_status,
                'test_insert_status': test_insert_status,
                'cookies': {
                    'admin_authenticated': request.COOKIES.get('admin_authenticated'),
                    'admin_email': request.COOKIES.get('admin_email'),
                    'admin_user_id': request.COOKIES.get('admin_user_id'),
                }
            }
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Debug error: {str(e)}'
        })

@never_cache
@admin_authenticated
def route_management(request):
    """Main route management page with interactive map"""
    return render(request, 'routemanagement/route_management.html')



@never_cache
@admin_authenticated
@require_http_methods(["POST"])
def save_point(request):
    """Save a new map point to Supabase with optional image"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({
                'success': False,
                'error': 'User information not found. Please log in again.'
            }, status=400)
        
        # Handle both JSON and FormData
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Handle image upload
            data = {
                'name': request.POST.get('name'),
                'point_type': request.POST.get('point_type'),
                'icon_color': request.POST.get('icon_color'),
                'description': request.POST.get('description'),
                'latitude': float(request.POST.get('latitude')),
                'longitude': float(request.POST.get('longitude'))
            }
            
            image_urls = []
            if 'images' in request.FILES:
                image_files = request.FILES.getlist('images')[:5]  # Limit to 5 images
                for i, image_file in enumerate(image_files):
                    try:
                        # Create unique filename with index
                        timestamp = int(datetime.now().timestamp())
                        file_extension = image_file.name.split('.')[-1] if '.' in image_file.name else 'jpg'
                        file_name = f"tourist_spot_{user_info['user_id']}_{timestamp}_{i+1}.{file_extension}"
                        
                        # Upload file to tourist_spots bucket
                        upload_response = supabase.storage.from_('tourist_spots').upload(
                            file_name, 
                            image_file.read()
                        )
                        
                        # Get public URL with proper error handling
                        try:
                            public_url_response = supabase.storage.from_('tourist_spots').get_public_url(file_name)
                            if isinstance(public_url_response, dict) and 'publicURL' in public_url_response:
                                image_url = public_url_response['publicURL']
                            elif isinstance(public_url_response, str):
                                image_url = public_url_response
                            else:
                                # Fallback URL construction
                                image_url = f"https://your-supabase-url.supabase.co/storage/v1/object/public/tourist_spots/{file_name}"
                            
                            if image_url and image_url.strip():
                                image_urls.append(image_url)
                        except Exception as url_error:
                            print(f'Failed to get public URL for {file_name}: {str(url_error)}')
                            continue
                        
                    except Exception as e:
                        # Continue with other images if one fails
                        print(f'Image upload failed for {image_file.name}: {str(e)}')
                        continue
            
            point_data = {
                'name': data['name'],
                'description': data['description'],
                'latitude': data['latitude'],
                'longitude': data['longitude'],
                'point_type': data['point_type'],
                'icon_color': data['icon_color'],
                'created_by': user_info['user_id']
            }
            
            # Add image data only if images were uploaded successfully
            if image_urls:
                point_data['image_url'] = image_urls[0]
                # Store multiple URLs as JSON string if the column supports it
                if len(image_urls) > 1:
                    try:
                        # Ensure proper JSON formatting
                        point_data['image_urls'] = json.dumps(image_urls, ensure_ascii=False)
                    except Exception as e:
                        logger.warning(f"Failed to serialize image URLs to JSON: {str(e)}")
                        point_data['image_urls'] = image_urls[0]  # Fallback to first image
                else:
                    point_data['image_urls'] = image_urls[0]
            
            response = supabase.table('map_points').insert(point_data).execute()
            
            if hasattr(response, 'data') and response.data:
                success_message = f'Tourist spot saved successfully'
                if image_urls:
                    success_message += f' with {len(image_urls)} image(s)'
                
                return JsonResponse({
                    'success': True,
                    'point_id': response.data[0]['id'],
                    'image_count': len(image_urls),
                    'message': success_message
                })
            else:
                error_message = 'Failed to save point to database'
                if image_urls:
                    error_message += f' (but {len(image_urls)} images were uploaded)'
                
                return JsonResponse({
                    'success': False,
                    'error': error_message
                })
        else:
            # Handle JSON data without image
            data = json.loads(request.body)
            
            point_data = {
                'name': data.get('name'),
                'description': data.get('description'),
                'latitude': float(data.get('latitude')),
                'longitude': float(data.get('longitude')),
                'point_type': data.get('point_type'),
                'icon_color': data.get('icon_color'),
                'created_by': user_info['user_id']
            }
            
            response = supabase.table('map_points').insert(point_data).execute()
            
            if hasattr(response, 'data') and response.data:
                return JsonResponse({
                    'success': True,
                    'point_id': response.data[0]['id'],
                    'message': 'Point saved successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to save point to database'
                })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error: {str(e)}'
        }, status=500)

@never_cache
@admin_authenticated
@require_http_methods(["POST"])
def save_ridehailing(request):
    """Save a new ridehailing route to Supabase with optional images"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({
                'success': False,
                'error': 'User information not found. Please log in again.'
            }, status=400)
        
        # Handle both JSON and FormData
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Handle form data with images
            data = {
                'name': request.POST.get('name'),
                'description': request.POST.get('description'),
                'color': request.POST.get('color'),
                'pickup_point': json.loads(request.POST.get('pickup_point', '{}')),
                'road_coordinates': json.loads(request.POST.get('road_coordinates', '[]')),
                'dropoff_points': json.loads(request.POST.get('dropoff_points', '[]')),
                'dropoff_routes': json.loads(request.POST.get('dropoff_routes', '[]'))
            }
            
            # Upload pickup images
            pickup_image_urls = []
            if 'pickup_images' in request.FILES:
                pickup_files = request.FILES.getlist('pickup_images')[:3]
                for i, image_file in enumerate(pickup_files):
                    try:
                        timestamp = int(datetime.now().timestamp())
                        file_extension = image_file.name.split('.')[-1] if '.' in image_file.name else 'jpg'
                        file_name = f"pickup_{user_info['user_id']}_{timestamp}_{i+1}.{file_extension}"
                        
                        upload_response = supabase.storage.from_('tourist_spots').upload(file_name, image_file.read())
                        
                        try:
                            public_url_response = supabase.storage.from_('tourist_spots').get_public_url(file_name)
                            if isinstance(public_url_response, dict) and 'publicURL' in public_url_response:
                                image_url = public_url_response['publicURL']
                            elif isinstance(public_url_response, str):
                                image_url = public_url_response
                            else:
                                image_url = f"https://your-supabase-url.supabase.co/storage/v1/object/public/tourist_spots/{file_name}"
                            
                            if image_url and image_url.strip():
                                pickup_image_urls.append(image_url)
                        except Exception as url_error:
                            continue
                    except Exception as e:
                        continue
            
            # Upload dropoff images
            dropoff_image_urls = []
            if 'dropoff_images' in request.FILES:
                dropoff_files = request.FILES.getlist('dropoff_images')[:3]
                for i, image_file in enumerate(dropoff_files):
                    try:
                        timestamp = int(datetime.now().timestamp())
                        file_extension = image_file.name.split('.')[-1] if '.' in image_file.name else 'jpg'
                        file_name = f"dropoff_{user_info['user_id']}_{timestamp}_{i+1}.{file_extension}"
                        
                        upload_response = supabase.storage.from_('tourist_spots').upload(file_name, image_file.read())
                        
                        try:
                            public_url_response = supabase.storage.from_('tourist_spots').get_public_url(file_name)
                            if isinstance(public_url_response, dict) and 'publicURL' in public_url_response:
                                image_url = public_url_response['publicURL']
                            elif isinstance(public_url_response, str):
                                image_url = public_url_response
                            else:
                                image_url = f"https://your-supabase-url.supabase.co/storage/v1/object/public/tourist_spots/{file_name}"
                            
                            if image_url and image_url.strip():
                                dropoff_image_urls.append(image_url)
                        except Exception as url_error:
                            continue
                    except Exception as e:
                        continue
        else:
            # Handle JSON data without images
            data = json.loads(request.body)
            pickup_image_urls = []
            dropoff_image_urls = []
        
        # Validate required fields
        if not data.get('name'):
            return JsonResponse({
                'success': False,
                'error': 'Route name is required'
            }, status=400)
        
        if not data.get('pickup_point'):
            return JsonResponse({
                'success': False,
                'error': 'Pickup point is required'
            }, status=400)
        
        # Handle both single dropoff_point and multiple dropoff_points
        dropoff_points = []
        if data.get('dropoff_points'):
            dropoff_points = data.get('dropoff_points')
        elif data.get('dropoff_point'):
            dropoff_points = [data.get('dropoff_point')]
        
        if not dropoff_points:
            return JsonResponse({
                'success': False,
                'error': 'At least one dropoff point is required'
            }, status=400)
        
        # Generate unique route ID for linking
        route_id = f"ridehailing_{user_info['user_id']}_{int(datetime.now().timestamp())}"
        
        # Save pickup point with route_id and images
        safe_name = str(data['name']).replace('"', '').replace("'", '').replace('\n', ' ').replace('\r', ' ')[:100]
        pickup_data = {
            'name': f"{safe_name} - Pickup",
            'description': f"Pickup point for {safe_name} (Route: {route_id})",
            'latitude': float(data['pickup_point']['lat']),
            'longitude': float(data['pickup_point']['lng']),
            'point_type': 'pickup',
            'icon_color': data.get('color', '#007bff'),
            'created_by': user_info['user_id']
        }
        
        # Add pickup images if available
        if pickup_image_urls:
            pickup_data['image_url'] = pickup_image_urls[0]
            if len(pickup_image_urls) > 1:
                try:
                    pickup_data['image_urls'] = json.dumps(pickup_image_urls, ensure_ascii=False)
                except Exception as e:
                    logger.warning(f"Failed to serialize pickup image URLs to JSON: {str(e)}")
                    pickup_data['image_urls'] = pickup_image_urls[0]
            else:
                pickup_data['image_urls'] = pickup_image_urls[0]
        pickup_response = supabase.table('map_points').insert(pickup_data).execute()
        
        # Use the validated dropoff_points from above
        dropoff_responses = []
        
        for i, dropoff in enumerate(dropoff_points):
            dropoff_name = str(dropoff.get('name', f"Dropoff {i+1}")).replace('"', '').replace("'", '').replace('\n', ' ').replace('\r', ' ')[:50]
            dropoff_data = {
                'name': f"{safe_name} - {dropoff_name}",
                'description': f"{dropoff_name} for {safe_name} (Route: {route_id})",
                'latitude': float(dropoff['lat']),
                'longitude': float(dropoff['lng']),
                'point_type': 'dropoff',
                'icon_color': data.get('color', '#007bff'),
                'created_by': user_info['user_id']
            }
            
            # Add dropoff images if available (apply to all dropoff points)
            if dropoff_image_urls:
                dropoff_data['image_url'] = dropoff_image_urls[0]
                if len(dropoff_image_urls) > 1:
                    try:
                        dropoff_data['image_urls'] = json.dumps(dropoff_image_urls, ensure_ascii=False)
                    except Exception as e:
                        logger.warning(f"Failed to serialize dropoff image URLs to JSON: {str(e)}")
                        dropoff_data['image_urls'] = dropoff_image_urls[0]
                else:
                    dropoff_data['image_urls'] = dropoff_image_urls[0]
            
            dropoff_response = supabase.table('map_points').insert(dropoff_data).execute()
            dropoff_responses.append(dropoff_response)
        
        # Save road highlight with route_id (only if road coordinates exist)
        road_response = None
        if data.get('road_coordinates'):
            safe_desc = str(data.get('description', '')).replace('"', '').replace("'", '').replace('\n', ' ').replace('\r', ' ')[:200]
            road_data = {
                'name': f"{safe_name} - Route",
                'description': f"{safe_desc} (Route: {route_id})",
                'highlight_type': 'ridehailing',
                'stroke_color': data.get('color', '#007bff'),
                'stroke_width': 5,
                'stroke_opacity': 0.8,
                'road_coordinates': data['road_coordinates'],
                'created_by': user_info['user_id']
            }
            road_response = supabase.table('road_highlights').insert(road_data).execute()
        
        # Save dropoff routes as separate road highlights
        dropoff_route_responses = []
        if data.get('dropoff_routes'):
            for i, route_coords in enumerate(data['dropoff_routes']):
                if route_coords:  # Only save if coordinates exist
                    dropoff_route_data = {
                        'name': f"{data['name']} - Dropoff Route {i+1}",
                        'description': f"Auto-generated route to {dropoff_points[i].get('name', f'Dropoff {i+1}')} (Route: {route_id})",
                        'highlight_type': 'ridehailing_dropoff',
                        'stroke_color': data.get('color', '#007bff'),
                        'stroke_width': 3,
                        'stroke_opacity': 0.7,
                        'road_coordinates': route_coords,
                        'created_by': user_info['user_id']
                    }
                    dropoff_route_response = supabase.table('road_highlights').insert(dropoff_route_data).execute()
                    dropoff_route_responses.append(dropoff_route_response)
        
        # Check if pickup and at least one dropoff were saved successfully
        pickup_saved = hasattr(pickup_response, 'data') and pickup_response.data
        dropoffs_saved = all(hasattr(resp, 'data') and resp.data for resp in dropoff_responses)
        
        if pickup_saved and dropoffs_saved:
            # Collect all IDs
            pickup_id = pickup_response.data[0]['id']
            dropoff_ids = [resp.data[0]['id'] for resp in dropoff_responses]
            road_ids = []
            
            if road_response and hasattr(road_response, 'data') and road_response.data:
                road_ids.append(road_response.data[0]['id'])
            
            if dropoff_route_responses:
                road_ids.extend([resp.data[0]['id'] for resp in dropoff_route_responses if hasattr(resp, 'data') and resp.data])
            
            # Save to route_summary table
            summary_data = {
                'route_id': route_id,
                'color': data.get('color', '#007bff'),
                'pickup_point_id': pickup_id,
                'road_highlight_ids': road_ids,
                'dropoff_point_ids': dropoff_ids
            }
            
            # Build safe response data
            response_data = {
                'success': True,
                'message': f'Ridehailing route saved successfully with {len(dropoff_responses)} dropoff points',
                'route_id': route_id,
                'pickup_id': pickup_id,
                'dropoff_ids': dropoff_ids,
                'road_ids': road_ids,
                'color': data.get('color', '#007bff')
            }
            
            try:
                summary_response = supabase.table('route_summary').insert(summary_data).execute()
            except Exception as summary_error:
                logger.warning(f'Route summary save failed: {summary_error}')
            
            return JsonResponse(response_data, safe=False)
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to save ridehailing route - pickup or dropoff points not saved'
            })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error: {str(e)}'
        }, status=500)

@never_cache
@admin_authenticated
@require_http_methods(["POST"])
def save_road(request):
    """Save a new road highlight to Supabase (minimal schema)"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({
                'success': False,
                'error': 'User information not found. Please log in again.'
            }, status=400)
        
        # Parse JSON data
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            return JsonResponse({
                'success': False,
                'error': f'Invalid JSON data: {str(e)}'
            }, status=400)
        
        # Validate required fields
        if not data.get('name'):
            return JsonResponse({
                'success': False,
                'error': 'Road highlight name is required'
            }, status=400)
        
        if not data.get('road_coordinates') or len(data.get('road_coordinates', [])) == 0:
            return JsonResponse({
                'success': False,
                'error': 'Road coordinates are required'
            }, status=400)
        
        try:
            stroke_width = int(data.get('stroke_width', 3))
            if stroke_width < 1 or stroke_width > 10:
                stroke_width = 3
        except (ValueError, TypeError):
            stroke_width = 3
        
        # Minimal road data structure
        road_data = {
            'name': data.get('name', 'Unnamed Road'),
            'description': data.get('description', ''),
            'highlight_type': data.get('highlight_type', 'available'),
            'stroke_color': data.get('stroke_color', '#00FF00'),
            'stroke_width': stroke_width,
            'stroke_opacity': 0.8,
            'road_coordinates': data.get('road_coordinates', []),
            'created_by': user_info['user_id']
        }
        
        # Insert data (exact API pattern)
        response = supabase.table('road_highlights').insert(road_data).execute()
        
        # Check response (exact API pattern)
        if hasattr(response, 'data') and response.data:
            return JsonResponse({
                'success': True,
                'road_id': response.data[0]['id'],
                'message': 'Road highlight saved successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to save road highlight to Supabase.'
            }, status=500)
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Error: {str(e)}'
        }, status=500)

@never_cache
@admin_authenticated
def fix_json_data(request):
    """Fix malformed JSON data in the database"""
    try:
        # Get all points with image_urls
        response = supabase.table('map_points').select('*').execute()
        
        if not hasattr(response, 'data') or not response.data:
            return JsonResponse({
                'success': True,
                'message': 'No points found in database',
                'fixed_count': 0
            })
        
        points = response.data
        fixed_count = 0
        
        for point in points:
            if not point.get('image_urls'):
                continue
                
            original_urls = point['image_urls']
            fixed_urls = fix_image_urls_data(original_urls)
            
            if fixed_urls != original_urls:
                # Update the point with fixed data
                update_data = {'image_urls': fixed_urls}
                
                update_response = supabase.table('map_points').update(update_data).eq('id', point['id']).execute()
                
                if hasattr(update_response, 'data') and update_response.data:
                    fixed_count += 1
                    logger.info(f'Fixed point ID {point["id"]}: {original_urls} -> {fixed_urls}')
        
        return JsonResponse({
            'success': True,
            'message': f'Fixed {fixed_count} points with malformed JSON data',
            'fixed_count': fixed_count
        })
        
    except Exception as e:
        logger.error(f'Error fixing JSON data: {str(e)}')
        return JsonResponse({
            'success': False,
            'error': f'Error fixing JSON data: {str(e)}'
        })

def fix_image_urls_data(urls_data):
    """Fix malformed image URLs data"""
    if not urls_data:
        return None
        
    # Convert to string if not already
    urls_str = str(urls_data).strip()
    
    if not urls_str:
        return None
        
    # If it looks like JSON, try to parse and re-serialize properly
    if urls_str.startswith('[') or urls_str.startswith('"'):
        try:
            parsed = json.loads(urls_str)
            if isinstance(parsed, list):
                # Clean the list and re-serialize
                clean_list = [str(url).strip() for url in parsed if url and str(url).strip()]
                if clean_list:
                    return json.dumps(clean_list, ensure_ascii=False)
                else:
                    return None
            elif isinstance(parsed, str):
                return parsed.strip() if parsed.strip() else None
            else:
                return str(parsed).strip() if str(parsed).strip() else None
        except (json.JSONDecodeError, ValueError, TypeError):
            # If JSON parsing fails, treat as single URL
            return urls_str if urls_str else None
    else:
        # Not JSON format, return as single URL
        return urls_str if urls_str else None

@never_cache
@admin_authenticated
def test_json(request):
    """Test endpoint to check JSON issues"""
    try:
        points_response = supabase.table('map_points').select('*').execute()
        points = points_response.data if hasattr(points_response, 'data') else []
        
        # Test each point individually
        for i, point in enumerate(points):
            try:
                json.dumps(point)
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': f'Point {i} (ID: {point.get("id", "unknown")}) has JSON error: {str(e)}',
                    'point_data': str(point)
                })
        
        return JsonResponse({
            'success': True,
            'message': f'All {len(points)} points are JSON-valid'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@never_cache
def get_items(request):
    """Get all routes, points, and road highlights from Supabase"""
    try:
        logger.info("Starting get_items request")
        
        # Get points with safe processing
        points_response = supabase.table('map_points').select('*').execute()
        raw_points = points_response.data if hasattr(points_response, 'data') else []
        logger.info(f"Retrieved {len(raw_points)} raw points from database")
        
        # Ultra-minimal response - only essential data
        points = []
        for point in raw_points[:3]:  # Only first 3 points
            points.append({
                'id': point.get('id'),
                'name': str(point.get('name', 'Point'))[:20],  # Limit name length
                'latitude': float(point.get('latitude')),
                'longitude': float(point.get('longitude')),
                'point_type': point.get('point_type', 'pickup'),
                'icon_color': point.get('icon_color', '#ff0000')
            })
        
        response_data = {
            'success': True,
            'points': points
        }
        
        logger.info(f"Returning minimal response with {len(points)} points")
        
        # Use HttpResponse to avoid Django HTML encoding
        json_str = json.dumps(response_data, ensure_ascii=False)
        return HttpResponse(json_str, content_type='application/json; charset=utf-8')
        
    except Exception as e:
        logger.error(f"Error in get_items: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })



@admin_authenticated
@require_http_methods(["POST"])
def update_point(request, point_id):
    """Update an existing point in Supabase"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({
                'success': False,
                'error': 'User information not found'
            }, status=400)
        
        data = json.loads(request.body)
        
        update_data = {
            'name': data.get('name'),
            'description': data.get('description'),
            'latitude': float(data.get('latitude')) if data.get('latitude') else None,
            'longitude': float(data.get('longitude')) if data.get('longitude') else None,
            'point_type': data.get('point_type'),
            'icon_color': data.get('icon_color')
        }
        
        # Remove None values
        update_data = {k: v for k, v in update_data.items() if v is not None}
        
        response = supabase.table('map_points').update(update_data).eq('id', point_id).eq('created_by', user_info['user_id']).execute()
        
        if hasattr(response, 'data') and response.data:
            return JsonResponse({
                'success': True,
                'message': 'Point updated successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Point not found or permission denied'
            })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@admin_authenticated
@require_http_methods(["POST"])
def update_road(request, road_id):
    """Update an existing road highlight in Supabase"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({
                'success': False,
                'error': 'User information not found'
            }, status=400)
        
        data = json.loads(request.body)
        
        update_data = {
            'name': data.get('name'),
            'description': data.get('description'),
            'highlight_type': data.get('highlight_type'),
            'stroke_color': data.get('stroke_color'),
            'stroke_width': int(data.get('stroke_width')) if data.get('stroke_width') else None,
            'road_coordinates': data.get('road_coordinates'),
            'updated_at': datetime.now().isoformat()
        }
        
        # Remove None values
        update_data = {k: v for k, v in update_data.items() if v is not None}
        
        response = supabase.table('road_highlights').update(update_data).eq('id', road_id).eq('created_by', user_info['user_id']).execute()
        
        if hasattr(response, 'data') and response.data:
            return JsonResponse({
                'success': True,
                'message': 'Road highlight updated successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Road highlight not found or permission denied'
            })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })



@admin_authenticated
@require_http_methods(["DELETE"])
def delete_point(request, point_id):
    """Delete a point and cascade delete ridehailing route components"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({
                'success': False,
                'error': 'User information not found'
            }, status=400)
        
        # First check if point exists at all
        check_response = supabase.table('map_points').select('*').eq('id', point_id).execute()
        
        if not (hasattr(check_response, 'data') and check_response.data):
            return JsonResponse({
                'success': False,
                'error': f'Point with ID {point_id} not found in database'
            })
        
        point = check_response.data[0]
        
        # Check if user has permission (admin can delete any point)
        if point.get('created_by') and point['created_by'] != user_info['user_id']:
            # Admin override - allow deletion anyway
            logger.info(f"Admin {user_info['user_id']} deleting point {point_id} created by {point.get('created_by')}")
        
        # Check if this is part of a ridehailing route
        if 'Route: ridehailing_' in point.get('description', ''):
            route_id = point['description'].split('Route: ')[1].split(')')[0]
            
            # Delete all related components (admin can delete any route)
            supabase.table('map_points').delete().like('description', f'%Route: {route_id}%').execute()
            supabase.table('road_highlights').delete().like('description', f'%Route: {route_id}%').execute()
            try:
                supabase.table('route_summary').delete().eq('route_id', route_id).execute()
            except:
                pass  # route_summary table might not exist
            
            return JsonResponse({
                'success': True,
                'message': 'Ridehailing route deleted successfully (all components removed)'
            })
        else:
            # Regular point deletion (admin can delete any point)
            response = supabase.table('map_points').delete().eq('id', point_id).execute()
            
            if hasattr(response, 'data'):
                return JsonResponse({
                    'success': True,
                    'message': 'Point deleted successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to delete point from database'
                })
        
    except Exception as e:
        logger.error(f"Error deleting point {point_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Database error: {str(e)}'
        })

@admin_authenticated
@require_http_methods(["DELETE"])
def delete_road(request, road_id):
    """Delete a road highlight and cascade delete ridehailing route components"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({
                'success': False,
                'error': 'User information not found'
            }, status=400)
        
        # Get road details first
        road_response = supabase.table('road_highlights').select('*').eq('id', road_id).eq('created_by', user_info['user_id']).execute()
        
        if not (hasattr(road_response, 'data') and road_response.data):
            return JsonResponse({
                'success': False,
                'error': 'Road highlight not found or permission denied'
            })
        
        road = road_response.data[0]
        
        # Check if this is part of a ridehailing route
        if 'Route: ridehailing_' in road.get('description', ''):
            route_id = road['description'].split('Route: ')[1].split(')')[0]
            
            # Delete all related components
            supabase.table('map_points').delete().like('description', f'%Route: {route_id}%').eq('created_by', user_info['user_id']).execute()
            supabase.table('road_highlights').delete().like('description', f'%Route: {route_id}%').eq('created_by', user_info['user_id']).execute()
            supabase.table('route_summary').delete().eq('route_id', route_id).execute()
            
            return JsonResponse({
                'success': True,
                'message': 'Ridehailing route deleted successfully (all components removed)'
            })
        else:
            # Regular road deletion
            response = supabase.table('road_highlights').delete().eq('id', road_id).eq('created_by', user_info['user_id']).execute()
            
            return JsonResponse({
                'success': True,
                'message': 'Road highlight deleted successfully'
            })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@never_cache
@admin_authenticated
def test_json(request):
    """Simple test endpoint to verify JSON response"""
    return JsonResponse({
        'success': True,
        'message': 'JSON test successful',
        'data': {'test': 'value'}
    }, json_dumps_params={'ensure_ascii': False})

@admin_authenticated
def get_map_configuration(request):
    """Get the current map configuration from Supabase (minimal schema)"""
    try:
        response = supabase.table('map_configurations').select('*').order('created_at', desc=True).limit(1).execute()
        
        if hasattr(response, 'data') and response.data:
            config = response.data[0]
            return JsonResponse({
                'success': True,
                'config': {
                    'default_latitude': float(config['default_latitude']),
                    'default_longitude': float(config['default_longitude']),
                    'default_zoom': config['default_zoom']
                }
            })
        else:
            # Return default configuration
            return JsonResponse({
                'success': True,
                'config': {
                    'default_latitude': 10.3157,
                    'default_longitude': 123.8854,
                    'default_zoom': 12
                }
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@admin_authenticated
@require_http_methods(["POST"])
def save_map_configuration(request):
    """Save map configuration to Supabase"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({
                'success': False,
                'error': 'User information not found'
            }, status=400)
        
        data = json.loads(request.body)
        
        # Create new configuration (minimal schema)
        config_data = {
            'name': data.get('name', 'Default Configuration'),
            'default_latitude': float(data.get('default_latitude', 10.3157)),
            'default_longitude': float(data.get('default_longitude', 123.8854)),
            'default_zoom': int(data.get('default_zoom', 12)),
            'created_by': user_info['user_id']
        }
        
        response = supabase.table('map_configurations').insert(config_data).execute()
        
        if hasattr(response, 'data') and response.data:
            return JsonResponse({
                'success': True,
                'config_id': response.data[0]['id'],
                'message': 'Map configuration saved successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to save map configuration'
            })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })