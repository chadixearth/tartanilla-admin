from django.shortcuts import render
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from accounts.views import admin_authenticated
import json
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
def get_items(request):
    """Get map items - simplified version"""
    try:
        # Get points
        points_response = supabase.table('map_points').select('id,name,latitude,longitude,point_type,icon_color').limit(10).execute()
        points = points_response.data if hasattr(points_response, 'data') else []
        
        # Clean points data
        clean_points = []
        for point in points:
            clean_points.append({
                'id': point.get('id'),
                'name': str(point.get('name', 'Point'))[:30],
                'latitude': float(point.get('latitude', 0)),
                'longitude': float(point.get('longitude', 0)),
                'point_type': point.get('point_type', 'pickup'),
                'icon_color': point.get('icon_color', '#ff0000')
            })
        
        # Get roads - minimal data
        roads_response = supabase.table('road_highlights').select('id,name,stroke_color,road_coordinates').limit(5).execute()
        roads = roads_response.data if hasattr(roads_response, 'data') else []
        
        clean_roads = []
        for road in roads:
            coords = road.get('road_coordinates', [])
            if len(coords) > 20:
                coords = coords[::5]  # Take every 5th coordinate
            
            clean_roads.append({
                'id': road.get('id'),
                'name': str(road.get('name', 'Road'))[:20],
                'stroke_color': road.get('stroke_color', '#00FF00'),
                'stroke_width': 3,
                'road_coordinates': coords[:20]  # Max 20 coordinates
            })
        
        response_data = {
            'success': True,
            'points': clean_points,
            'roads': clean_roads
        }
        
        return HttpResponse(
            json.dumps(response_data, ensure_ascii=False),
            content_type='application/json'
        )
        
    except Exception as e:
        return HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            content_type='application/json'
        )

@never_cache
@csrf_exempt
@require_http_methods(["POST"])
def save_point(request):
    """Save a point - simplified version"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return HttpResponse(
                json.dumps({'success': False, 'error': 'Not authenticated'}),
                content_type='application/json'
            )
        
        data = json.loads(request.body)
        
        point_data = {
            'name': str(data.get('name', 'Point'))[:50],
            'description': str(data.get('description', ''))[:200],
            'latitude': float(data.get('latitude')),
            'longitude': float(data.get('longitude')),
            'point_type': data.get('point_type', 'pickup'),
            'icon_color': data.get('icon_color', '#FF0000'),
            'created_by': user_info['user_id']
        }
        
        response = supabase.table('map_points').insert(point_data).execute()
        
        if hasattr(response, 'data') and response.data:
            return HttpResponse(
                json.dumps({'success': True, 'message': 'Point saved successfully'}),
                content_type='application/json'
            )
        else:
            return HttpResponse(
                json.dumps({'success': False, 'error': 'Failed to save point'}),
                content_type='application/json'
            )
            
    except Exception as e:
        return HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            content_type='application/json'
        )

@never_cache
@csrf_exempt
@require_http_methods(["POST"])
def save_road(request):
    """Save a road - simplified version"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return HttpResponse(
                json.dumps({'success': False, 'error': 'Not authenticated'}),
                content_type='application/json'
            )
        
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
            return HttpResponse(
                json.dumps({'success': True, 'message': 'Road saved successfully'}),
                content_type='application/json'
            )
        else:
            return HttpResponse(
                json.dumps({'success': False, 'error': 'Failed to save road'}),
                content_type='application/json'
            )
            
    except Exception as e:
        return HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            content_type='application/json'
        )

@never_cache
@csrf_exempt
@require_http_methods(["POST"])
def save_ridehailing(request):
    """Save ridehailing route - simplified version"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return HttpResponse(
                json.dumps({'success': False, 'error': 'Not authenticated'}),
                content_type='application/json'
            )
        
        data = json.loads(request.body)
        
        # Validate required fields
        if not data.get('name') or not data.get('pickup_point') or not data.get('dropoff_points'):
            return HttpResponse(
                json.dumps({'success': False, 'error': 'Missing required fields'}),
                content_type='application/json'
            )
        
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
        
        # Save road if provided
        if data.get('road_coordinates'):
            coords = data['road_coordinates']
            if len(coords) > 50:
                coords = coords[::2]  # Reduce coordinates
                
            road_data = {
                'name': f"{data['name']} - Route",
                'description': f"Route for {data['name']}",
                'highlight_type': 'ridehailing',
                'stroke_color': data.get('color', '#007bff'),
                'stroke_width': 5,
                'stroke_opacity': 0.8,
                'road_coordinates': coords[:50],
                'created_by': user_info['user_id']
            }
            supabase.table('road_highlights').insert(road_data).execute()
        
        return HttpResponse(
            json.dumps({'success': True, 'message': 'Ridehailing route saved successfully'}),
            content_type='application/json'
        )
        
    except Exception as e:
        return HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            content_type='application/json'
        )

@never_cache
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_point(request, point_id):
    """Delete a point"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return HttpResponse(
                json.dumps({'success': False, 'error': 'Not authenticated'}),
                content_type='application/json'
            )
        
        response = supabase.table('map_points').delete().eq('id', point_id).execute()
        
        return HttpResponse(
            json.dumps({'success': True, 'message': 'Point deleted successfully'}),
            content_type='application/json'
        )
        
    except Exception as e:
        return HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            content_type='application/json'
        )

@never_cache
@csrf_exempt
@require_http_methods(["DELETE"])
def delete_road(request, road_id):
    """Delete a road"""
    try:
        user_info = get_user_info_from_cookies(request)
        if not user_info:
            return HttpResponse(
                json.dumps({'success': False, 'error': 'Not authenticated'}),
                content_type='application/json'
            )
        
        response = supabase.table('road_highlights').delete().eq('id', road_id).execute()
        
        return HttpResponse(
            json.dumps({'success': True, 'message': 'Road deleted successfully'}),
            content_type='application/json'
        )
        
    except Exception as e:
        return HttpResponse(
            json.dumps({'success': False, 'error': str(e)}),
            content_type='application/json'
        )