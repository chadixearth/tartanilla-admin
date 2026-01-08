from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from accounts.views import admin_authenticated
import json
import uuid
from tartanilla_admin.supabase import supabase
from datetime import datetime

def get_user_info_from_cookies(request):
    """Extract user information from cookies"""
    is_authenticated = request.COOKIES.get('admin_authenticated')
    user_email = request.COOKIES.get('admin_email')
    user_id = request.COOKIES.get('admin_user_id')
    
    return {
        'user_id': user_id,
        'user_email': user_email
    } if is_authenticated == '1' and user_id and user_email else None

@never_cache
@admin_authenticated
def route_management(request):
    """Main route management page"""
    return render(request, 'routemanagement/route_management.html')

@never_cache
@csrf_exempt
def get_items(request):
    """Get map items - simplified version"""
    try:
        # Get points with stroke_color
        points_response = supabase.table('map_points').select('id,name,latitude,longitude,point_type,icon_color,description').execute()
        points = points_response.data if hasattr(points_response, 'data') else []
        
        # Add stroke_color to points
        for point in points:
            point['stroke_color'] = point.get('icon_color', '#FF0000')
        
        # Get roads
        roads_response = supabase.table('road_highlights').select('id,name,stroke_color,stroke_width,stroke_opacity,road_coordinates,highlight_type').execute()
        roads = roads_response.data if hasattr(roads_response, 'data') else []
        
        return JsonResponse({
            'success': True,
            'points': points,
            'roads': roads
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
@csrf_exempt
@require_http_methods(["POST"])
def save_point(request):
    """Save a point - handles both JSON and FormData with images"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Not authenticated'})
        
        # Handle both JSON and FormData
        if request.content_type and 'multipart/form-data' in request.content_type:
            # FormData with potential images
            data = {
                'name': request.POST.get('name'),
                'description': request.POST.get('description', ''),
                'latitude': request.POST.get('latitude'),
                'longitude': request.POST.get('longitude'),
                'point_type': request.POST.get('point_type', 'pickup'),
                'icon_color': request.POST.get('icon_color', '#FF0000')
            }
            images = request.FILES.getlist('images')
        else:
            # Regular JSON
            data = json.loads(request.body)
            images = []
        
        # Validate required fields
        if not data.get('name') or not data.get('latitude') or not data.get('longitude'):
            return JsonResponse({'success': False, 'error': 'Missing required fields: name, latitude, longitude'})
        
        point_data = {
            'name': str(data.get('name', 'Point'))[:50],
            'description': str(data.get('description', ''))[:200],
            'latitude': float(data.get('latitude')),
            'longitude': float(data.get('longitude')),
            'point_type': data.get('point_type', 'pickup'),
            'icon_color': data.get('icon_color', '#FF0000'),
            'created_by': user_info['user_id']
        }
        
        # Handle image upload if present
        if images:
            try:
                # Upload first image to Supabase storage
                image = images[0]  # Take first image for now
                import uuid
                import base64
                
                # Generate unique filename
                file_extension = image.name.split('.')[-1] if '.' in image.name else 'jpg'
                unique_filename = f"{user_info['user_id']}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}.{file_extension}"
                
                # Read image content
                image_content = image.read()
                
                # Upload to Supabase storage
                upload_response = supabase.storage.from_("stoppoints_photos").upload(
                    path=unique_filename,
                    file=image_content,
                    file_options={"content-type": f"image/{file_extension}"}
                )
                
                if not (hasattr(upload_response, 'error') and upload_response.error):
                    # Get public URL
                    public_url_response = supabase.storage.from_("stoppoints_photos").get_public_url(unique_filename)
                    
                    if isinstance(public_url_response, str):
                        point_data['image_url'] = public_url_response
                    elif hasattr(public_url_response, 'get'):
                        point_data['image_url'] = public_url_response.get('publicURL', '')
                        
            except Exception as img_error:
                print(f"Image upload error: {img_error}")
                # Continue without image if upload fails
        
        # Insert point into database
        response = supabase.table('map_points').insert(point_data).execute()
        
        if hasattr(response, 'data') and response.data:
            return JsonResponse({
                'success': True, 
                'message': 'Point saved successfully',
                'data': response.data[0],
                'image_uploaded': 'image_url' in point_data
            })
        else:
            return JsonResponse({'success': False, 'error': 'Failed to save point to database'})
            
    except json.JSONDecodeError as e:
        return JsonResponse({'success': False, 'error': f'Invalid JSON data: {str(e)}'})
    except ValueError as e:
        return JsonResponse({'success': False, 'error': f'Invalid data format: {str(e)}'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'})

@never_cache
@csrf_exempt
@require_http_methods(["POST"])
def save_road(request):
    """Save a road - simplified version"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Not authenticated'})
        
        data = json.loads(request.body)
        
        # Limit coordinates to prevent issues
        coords = data.get('road_coordinates', [])
        if len(coords) > 50:
            coords = coords[::2]  # Take every other coordinate
        
        road_data = {
            'name': str(data.get('name', 'Road'))[:50],
            'description': str(data.get('description', ''))[:200],
            'highlight_type': data.get('highlight_type', 'available'),
            'stroke_color': data.get('stroke_color', '#00FF00'),
            'stroke_width': int(data.get('stroke_width', 3)),
            'stroke_opacity': 0.8,
            'road_coordinates': coords[:50],  # Max 50 coordinates
            'created_by': user_info['user_id']
        }
        
        response = supabase.table('road_highlights').insert(road_data).execute()
        
        if hasattr(response, 'data') and response.data:
            return JsonResponse({'success': True, 'message': 'Road saved successfully'})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to save road'})
            
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
@csrf_exempt
@require_http_methods(["POST"])
def save_ridehailing(request):
    """Save ridehailing route - simplified version"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Not authenticated'})
        
        # Handle both JSON and FormData
        if request.content_type and 'multipart/form-data' in request.content_type:
            # FormData with files
            data = {
                'name': request.POST.get('name'),
                'description': request.POST.get('description', ''),
                'color': request.POST.get('color', '#007bff'),
                'pickup_point': json.loads(request.POST.get('pickup_point', '{}')),
                'road_coordinates': json.loads(request.POST.get('road_coordinates', '[]')),
                'dropoff_points': json.loads(request.POST.get('dropoff_points', '[]')),
                'dropoff_routes': json.loads(request.POST.get('dropoff_routes', '[]'))
            }
        else:
            # Regular JSON
            data = json.loads(request.body)
        
        # Validate required fields
        if not data.get('name') or not data.get('pickup_point') or not data.get('dropoff_points'):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        route_id = f"ridehailing_{user_info['user_id']}_{int(datetime.now().timestamp())}"
        
        # Save pickup point
        pickup_data = {
            'name': f"{data['name']} - Pickup",
            'description': f"Pickup for {data['name']}",
            'latitude': float(data['pickup_point']['lat']),
            'longitude': float(data['pickup_point']['lng']),
            'point_type': 'pickup',
            'icon_color': data.get('color', '#007bff'),
            'created_by': user_info['user_id']
        }
        pickup_response = supabase.table('map_points').insert(pickup_data).execute()
        
        # Save dropoff points
        dropoff_responses = []
        for i, dropoff in enumerate(data['dropoff_points']):
            dropoff_data = {
                'name': f"{data['name']} - {dropoff.get('name', f'Dropoff {i+1}')}",
                'description': f"Dropoff for {data['name']}",
                'latitude': float(dropoff['lat']),
                'longitude': float(dropoff['lng']),
                'point_type': 'dropoff',
                'icon_color': data.get('color', '#007bff'),
                'created_by': user_info['user_id']
            }
            dropoff_response = supabase.table('map_points').insert(dropoff_data).execute()
            dropoff_responses.append(dropoff_response)
        
        # Create road highlights for each dropoff using OSRM routing
        pickup = data['pickup_point']
        road_responses = []
        
        for i, dropoff in enumerate(data['dropoff_points']):
            # Get route from OSRM with retry
            import requests
            road_coords = None
            
            for attempt in range(3):  # Try 3 times
                try:
                    url = f"https://router.project-osrm.org/route/v1/driving/{pickup['lng']},{pickup['lat']};{dropoff['lng']},{dropoff['lat']}?overview=full&geometries=geojson"
                    response = requests.get(url, timeout=15)  # Increased timeout
                    
                    if response.status_code == 200:
                        route_data = response.json()
                        if route_data.get('routes') and route_data['routes'][0].get('geometry'):
                            osrm_coords = route_data['routes'][0]['geometry']['coordinates']
                            road_coords = [{'lat': coord[1], 'lng': coord[0]} for coord in osrm_coords]
                            print(f"OSRM route to dropoff {i+1}: {len(road_coords)} points (attempt {attempt+1})")
                            break
                    else:
                        print(f"OSRM API returned {response.status_code} on attempt {attempt+1}")
                        
                except Exception as e:
                    print(f"OSRM attempt {attempt+1} failed: {e}")
                    if attempt < 2:  # Don't sleep on last attempt
                        import time
                        time.sleep(1)  # Wait 1 second before retry
            
            # Use OSRM result or fallback
            if not road_coords:
                print(f"All OSRM attempts failed for dropoff {i+1}, using straight line")
                road_coords = [
                    {'lat': float(pickup['lat']), 'lng': float(pickup['lng'])},
                    {'lat': float(dropoff['lat']), 'lng': float(dropoff['lng'])}
                ]
            
            # Create road highlight for this dropoff
            road_data = {
                'name': f"{data['name']} - Route to {dropoff.get('name', f'Dropoff {i+1}')}",
                'description': f"Ridehailing route from pickup to {dropoff.get('name', f'dropoff {i+1}')}",
                'highlight_type': 'ridehailing',
                'stroke_color': data.get('color', '#007bff'),
                'stroke_width': 5,
                'stroke_opacity': 0.8,
                'road_coordinates': road_coords,
                'created_by': user_info['user_id']
            }
            
            road_response = supabase.table('road_highlights').insert(road_data).execute()
            road_responses.append(road_response)
            print(f"Saved road to dropoff {i+1}: {bool(road_response.data)}")
        
        roads_saved = sum(1 for r in road_responses if r.data)
        
        # Save route summary to bundle all components
        if pickup_response.data and roads_saved > 0:
            pickup_id = pickup_response.data[0]['id']
            road_ids = [r.data[0]['id'] for r in road_responses if r.data]
            dropoff_ids = [r.data[0]['id'] for r in dropoff_responses if r.data]
            
            summary_data = {
                'route_id': route_id,
                'color': data.get('color', '#007bff'),
                'pickup_point_id': pickup_id,
                'road_highlight_ids': road_ids,
                'dropoff_point_ids': dropoff_ids
            }
            
            summary_response = supabase.table('route_summary').insert(summary_data).execute()
            print(f"Route summary saved: {bool(summary_response.data)}")
        
        return JsonResponse({
            'success': True, 
            'message': 'Ridehailing route saved successfully',
            'pickup_saved': bool(pickup_response.data if hasattr(pickup_response, 'data') else False),
            'dropoffs_saved': len(dropoff_responses),
            'roads_saved': roads_saved,
            'route_id': route_id,
            'summary_saved': bool(summary_response.data if 'summary_response' in locals() else False)
        })
        
    except json.JSONDecodeError as e:
        return JsonResponse({'success': False, 'error': f'Invalid JSON data: {str(e)}'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_point(request, point_id):
    """Delete a point"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Not authenticated'})
        
        response = supabase.table('map_points').delete().eq('id', point_id).execute()
        
        return JsonResponse({'success': True, 'message': 'Point deleted successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_road(request, road_id):
    """Delete a road"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Not authenticated'})
        
        response = supabase.table('road_highlights').delete().eq('id', road_id).execute()
        
        return JsonResponse({'success': True, 'message': 'Road deleted successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
def debug_info(request):
    """Debug endpoint"""
    try:
        # Simple test without authentication
        return JsonResponse({
            'success': True, 
            'message': 'Debug endpoint working',
            'authenticated': bool(request.COOKIES.get('admin_authenticated') == '1'),
            'user_id': request.COOKIES.get('admin_user_id', 'None')
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@never_cache
def fix_json_data(request):
    """Fix JSON data endpoint"""
    return JsonResponse({'success': True, 'message': 'JSON data fixed'})

@never_cache
def test_json(request):
    """Test JSON endpoint"""
    test_data = {
        'success': True,
        'message': 'JSON test successful',
        'points': [
            {
                'id': 1,
                'name': 'Test Point',
                'latitude': 14.5995,
                'longitude': 120.9842,
                'point_type': 'pickup',
                'icon_color': '#ff0000'
            }
        ],
        'roads': [
            {
                'id': 1,
                'name': 'Test Road',
                'stroke_color': '#00FF00',
                'stroke_width': 3,
                'road_coordinates': [[14.5995, 120.9842], [14.6000, 120.9850]]
            }
        ]
    }
    return JsonResponse(test_data)

@never_cache
def get_points_by_type(request):
    """Get map points filtered by type"""
    try:
        point_type = request.GET.get('type', 'all')
        
        if point_type == 'all':
            points_response = supabase.table('map_points').select('*').execute()
        else:
            points_response = supabase.table('map_points').select('*').eq('point_type', point_type).execute()
        
        points = points_response.data if hasattr(points_response, 'data') else []
        
        return JsonResponse({
            'success': True,
            'data': {
                'points': points,
                'type_filter': point_type,
                'count': len(points)
            },
            'message': f'Found {len(points)} points of type "{point_type}"'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@never_cache
def test_roads(request):
    """Test roads endpoint to check database content"""
    try:
        # Get all roads from database
        roads_response = supabase.table('road_highlights').select('*').execute()
        roads = roads_response.data if hasattr(roads_response, 'data') else []
        
        # Process each road for debugging
        road_info = []
        for road in roads:
            coords = road.get('road_coordinates', [])
            coord_type = type(coords).__name__
            coord_count = len(coords) if isinstance(coords, (list, tuple)) else 0
            
            road_info.append({
                'id': road.get('id'),
                'name': road.get('name'),
                'color': road.get('stroke_color'),
                'coord_type': coord_type,
                'coord_count': coord_count,
                'coord_sample': coords[:2] if isinstance(coords, list) and len(coords) > 0 else None,
                'created_by': road.get('created_by')
            })
        
        return JsonResponse({
            'success': True,
            'total_roads': len(roads),
            'roads': road_info,
            'message': f'Found {len(roads)} roads in database'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Error checking roads'
        })

@never_cache
@csrf_exempt
@require_http_methods(["PUT"])
def update_point(request, point_id):
    """Update a point"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Not authenticated'})
        
        data = json.loads(request.body)
        update_data = {
            'name': str(data.get('name', 'Point'))[:50],
            'description': str(data.get('description', ''))[:200],
            'latitude': float(data.get('latitude')),
            'longitude': float(data.get('longitude')),
            'point_type': data.get('point_type', 'pickup'),
            'icon_color': data.get('icon_color', '#FF0000')
        }
        
        response = supabase.table('map_points').update(update_data).eq('id', point_id).execute()
        
        return JsonResponse({'success': True, 'message': 'Point updated successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
@csrf_exempt
@require_http_methods(["PUT"])
def update_road(request, road_id):
    """Update a road"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Not authenticated'})
        
        data = json.loads(request.body)
        coords = data.get('road_coordinates', [])
        if len(coords) > 50:
            coords = coords[::2]
        
        update_data = {
            'name': str(data.get('name', 'Road'))[:50],
            'description': str(data.get('description', ''))[:200],
            'highlight_type': data.get('highlight_type', 'available'),
            'stroke_color': data.get('stroke_color', '#00FF00'),
            'stroke_width': int(data.get('stroke_width', 3)),
            'road_coordinates': coords[:50]
        }
        
        response = supabase.table('road_highlights').update(update_data).eq('id', road_id).execute()
        
        return JsonResponse({'success': True, 'message': 'Road updated successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
def get_map_configuration(request):
    """Get map configuration"""
    try:
        response = supabase.table('map_configuration').select('*').limit(1).execute()
        config = response.data[0] if response.data else {}
        
        return JsonResponse({'success': True, 'config': config})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
@csrf_exempt
@require_http_methods(["POST"])
def save_map_configuration(request):
    """Save map configuration"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return JsonResponse({'success': False, 'error': 'Not authenticated'})
        
        data = json.loads(request.body)
        config_data = {
            'center_lat': float(data.get('center_lat', 14.5995)),
            'center_lng': float(data.get('center_lng', 120.9842)),
            'zoom_level': int(data.get('zoom_level', 13)),
            'updated_by': user_info['user_id']
        }
        
        existing = supabase.table('map_configuration').select('id').limit(1).execute()
        
        if existing.data:
            response = supabase.table('map_configuration').update(config_data).eq('id', existing.data[0]['id']).execute()
        else:
            response = supabase.table('map_configuration').insert(config_data).execute()
        
        return JsonResponse({'success': True, 'message': 'Configuration saved successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})