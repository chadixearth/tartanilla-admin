from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from tartanilla_admin.supabase import supabase
from .response_fix import create_safe_response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
import json
import logging
import time

logger = logging.getLogger(__name__)

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def get_map_data(request):
    """
    Get all map data including points, road highlights, routes, and zones
    Returns: JSON with comprehensive map data
    """
    try:
        logger.info("Fetching comprehensive map data")
        
        # Get all map points with error handling and timeout
        try:
            points_response = supabase.table('map_points').select('*').limit(100).execute()
            raw_points = points_response.data if hasattr(points_response, 'data') else []
            
            # Clean and validate points data
            points = []
            for point in raw_points:
                try:
                    clean_point = {
                        'id': int(point.get('id', 0)),
                        'name': str(point.get('name', 'Point'))[:100],
                        'description': str(point.get('description', ''))[:500],
                        'latitude': float(point.get('latitude', 0)),
                        'longitude': float(point.get('longitude', 0)),
                        'point_type': str(point.get('point_type', 'pickup')),
                        'icon_color': str(point.get('icon_color', '#FF0000')),
                        'stroke_color': str(point.get('stroke_color', point.get('icon_color', '#FF0000')))
                    }
                    
                    # Validate coordinates
                    if -90 <= clean_point['latitude'] <= 90 and -180 <= clean_point['longitude'] <= 180:
                        # Handle image_url column properly
                        if point.get('image_url'):
                            clean_point['image_urls'] = [str(point['image_url'])]
                        else:
                            clean_point['image_urls'] = []
                        
                        points.append(clean_point)
                except (ValueError, TypeError):
                    continue
            
            logger.info(f"Fetched {len(points)} map points from database")
        except Exception as e:
            logger.warning(f"Error fetching map points: {e}")
            points = []
            # Return early with default data on connection errors
            if 'WinError' in str(e) or 'socket' in str(e).lower():
                logger.error(f"Connection error, returning default data")
                return JsonResponse({
                    'success': True,
                    'data': {
                        'points': [],
                        'roads': [],
                        'routes': [],
                        'zones': [],
                        'config': {
                            'center_latitude': 10.3157,
                            'center_longitude': 123.8854,
                            'zoom_level': 13,
                            'map_style': 'standard'
                        },
                        'ridehailing_routes': [],
                        'total_items': {'points': 0, 'roads': 0, 'routes': 0, 'zones': 0, 'ridehailing_routes': 0}
                    }
                }, json_dumps_params={'separators': (',', ':'), 'ensure_ascii': False})
        
        # Get all road highlights with error handling
        try:
            roads_response = supabase.table('road_highlights').select('*').limit(50).execute()
            raw_roads = roads_response.data if hasattr(roads_response, 'data') else []
            
            # Clean and validate roads data
            roads = []
            for road in raw_roads:
                try:
                    clean_road = {
                        'id': int(road.get('id', 0)),
                        'name': str(road.get('name', 'Road'))[:100],
                        'description': str(road.get('description', ''))[:500],
                        'stroke_color': str(road.get('stroke_color', '#00FF00')),
                        'stroke_width': int(road.get('stroke_width', 3)),
                        'stroke_opacity': float(road.get('stroke_opacity', 0.8)),
                        'highlight_type': str(road.get('highlight_type', 'available'))
                    }
                    
                    # Handle road coordinates safely
                    coords = road.get('road_coordinates', [])
                    if isinstance(coords, str):
                        try:
                            coords = json.loads(coords)
                        except:
                            coords = []
                    
                    # Validate and clean coordinates
                    valid_coords = []
                    if isinstance(coords, list):
                        for coord in coords[:50]:  # Limit to 50 coordinates
                            if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                                try:
                                    lat = float(coord[0])
                                    lng = float(coord[1])
                                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                                        valid_coords.append([lat, lng])
                                except (ValueError, TypeError):
                                    continue
                    
                    clean_road['road_coordinates'] = valid_coords
                    roads.append(clean_road)
                    
                except (ValueError, TypeError):
                    continue
            
            logger.info(f"Fetched {len(roads)} road highlights from database")
        except Exception as e:
            logger.warning(f"Error fetching road highlights: {e}")
            roads = []
        
        # Get ridehailing routes from route_summary table
        ridehailing_routes = []
        try:
            routes_response = supabase.table('route_summary').select('*').execute()
            raw_routes = routes_response.data if hasattr(routes_response, 'data') else []
            
            # Clean ridehailing routes data
            for route in raw_routes:
                try:
                    clean_route = {
                        'id': int(route.get('id', 0)),
                        'name': str(route.get('name', 'Route'))[:100],
                        'pickup_point_id': route.get('pickup_point_id'),
                        'dropoff_point_ids': route.get('dropoff_point_ids', []),
                        'route_type': str(route.get('route_type', 'ridehailing')),
                        'is_active': bool(route.get('is_active', True))
                    }
                    ridehailing_routes.append(clean_route)
                except (ValueError, TypeError):
                    continue
                    
            logger.info(f"Fetched {len(ridehailing_routes)} ridehailing routes from database")
        except Exception as e:
            logger.warning(f"Error fetching ridehailing routes: {e}")
            ridehailing_routes = []
        
        # Add default points if database is empty
        if len(points) == 0:
            logger.info("No points in database, adding default points")
            points = [
                {
                    'id': 1,
                    'name': 'SM City Cebu Terminal',
                    'description': 'Main tartanilla terminal near SM City Cebu',
                    'latitude': 10.3157,
                    'longitude': 123.8854,
                    'point_type': 'pickup',
                    'icon_color': '#28a745',
                    'stroke_color': '#28a745',
                    'image_urls': []
                },
                {
                    'id': 2,
                    'name': 'Ayala Center Cebu Terminal',
                    'description': 'Tartanilla terminal at Ayala Center Cebu',
                    'latitude': 10.3187,
                    'longitude': 123.9064,
                    'point_type': 'pickup',
                    'icon_color': '#28a745',
                    'stroke_color': '#28a745',
                    'image_urls': []
                },
                {
                    'id': 3,
                    'name': 'Plaza Independencia',
                    'description': 'Historic plaza pickup point',
                    'latitude': 10.2934,
                    'longitude': 123.9015,
                    'point_type': 'pickup',
                    'icon_color': '#28a745',
                    'stroke_color': '#28a745',
                    'image_urls': []
                }
            ]
        
        # Set default routes and zones (tables don't exist)
        routes = []
        zones = []
        
        # Use default map configuration
        config = {
            'center_latitude': 10.3157,
            'center_longitude': 123.8854,
            'zoom_level': 13,
            'map_style': 'standard'
        }
        

        
        logger.info(f"Returning map data: {len(points)} points, {len(roads)} roads")
        
        response_data = {
            'success': True,
            'data': {
                'points': points,
                'roads': roads,
                'routes': routes,
                'zones': zones,
                'config': config,
                'ridehailing_routes': ridehailing_routes,
                'total_items': {
                    'points': len(points),
                    'roads': len(roads),
                    'routes': len(routes),
                    'zones': len(zones),
                    'ridehailing_routes': len(ridehailing_routes)
                }
            }
        }
        
        return JsonResponse(response_data, json_dumps_params={'separators': (',', ':'), 'ensure_ascii': False})
        
    except Exception as e:
        logger.error(f"Error in get_map_data: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Failed to fetch map data'
        }, status=500)

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def get_terminals(request):
    """
    Get only terminal/pickup points for map selection
    Query params:
        - type: Filter by specific point type (pickup, station, landmark)
    Returns: JSON with terminal points only
    """
    try:
        logger.info("Fetching terminal points")
        
        # Get query parameters
        point_type = request.GET.get('type', None)
        
        # Build query for database terminals
        query = supabase.table('map_points').select('*')
        
        # Apply filters
        if point_type:
            query = query.eq('point_type', point_type)
        else:
            # Default to pickup points only for tour packages
            query = query.eq('point_type', 'pickup')
        
        # Execute query
        points_response = query.execute()
        db_terminals = points_response.data if hasattr(points_response, 'data') else []
        
        # Add default terminals if not in database
        default_terminals = [
            {
                'id': 'sm_terminal',
                'name': 'SM City Cebu Terminal',
                'description': 'Main tartanilla terminal near SM City Cebu',
                'latitude': 10.3157,
                'longitude': 123.8854,
                'point_type': 'pickup',
                'icon_color': '#28a745',
                'stroke_color': '#28a745'
            },
            {
                'id': 'ayala_terminal',
                'name': 'Ayala Center Cebu Terminal',
                'description': 'Tartanilla terminal at Ayala Center Cebu',
                'latitude': 10.3187,
                'longitude': 123.9064,
                'point_type': 'pickup',
                'icon_color': '#28a745',
                'stroke_color': '#28a745'
            },
            {
                'id': 'plaza_terminal',
                'name': 'Plaza Independencia',
                'description': 'Historic plaza pickup point',
                'latitude': 10.2934,
                'longitude': 123.9015,
                'point_type': 'pickup',
                'icon_color': '#28a745',
                'stroke_color': '#28a745'
            }
        ]
        
        # Merge database terminals with defaults (avoid duplicates)
        terminals = list(db_terminals)
        existing_names = {t.get('name') for t in terminals}
        
        for default_terminal in default_terminals:
            if default_terminal['name'] not in existing_names:
                terminals.append(default_terminal)
        
        logger.info(f"Fetched {len(terminals)} terminal points")
        
        # Group terminals by type for better organization
        grouped_terminals = {}
        for terminal in terminals:
            terminal_type = terminal.get('point_type', 'unknown')
            if terminal_type not in grouped_terminals:
                grouped_terminals[terminal_type] = []
            grouped_terminals[terminal_type].append(terminal)
        
        return JsonResponse({
            'success': True,
            'data': {
                'terminals': terminals,
                'grouped': grouped_terminals,
                'total': len(terminals)
            },
            'message': f'Fetched {len(terminals)} terminal points'
        })
        
    except Exception as e:
        logger.error(f"Error in get_terminals: {e}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to fetch terminals'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@csrf_exempt
@api_view(['POST'])
def add_map_point(request):
    """
    Add a new map point
    Expected JSON: {
        "name": "Point Name",
        "description": "Point Description", 
        "latitude": 10.3157,
        "longitude": 123.8854,
        "point_type": "pickup",
        "icon_color": "#FF0000"
    }
    """
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['name', 'latitude', 'longitude']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }, status=400)
        
        # Validate coordinates
        try:
            latitude = float(data.get('latitude'))
            longitude = float(data.get('longitude'))
            if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                raise ValueError("Invalid coordinate range")
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'error': 'Valid latitude and longitude are required'
            }, status=400)
        
        # Prepare point data
        point_data = {
            'name': data.get('name'),
            'description': data.get('description', ''),
            'latitude': latitude,
            'longitude': longitude,
            'point_type': data.get('point_type', 'pickup'),
            'icon_color': data.get('icon_color', '#FF0000')
        }
        
        # Handle image URL if provided
        if data.get('image_url'):
            point_data['image_url'] = data.get('image_url')
        
        # Insert into database
        response = supabase.table('map_points').insert(point_data).execute()
        
        if hasattr(response, 'data') and response.data:
            return JsonResponse({
                'success': True,
                'data': response.data[0],
                'message': 'Map point added successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to add map point'
            }, status=500)
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@csrf_exempt
@api_view(['POST'])
def add_road_highlight(request):
    """
    Add a new road highlight/route
    Expected JSON: {
        "name": "Route Name",
        "description": "Route Description",
        "coordinates": [{"lat": 10.3157, "lng": 123.8854}, ...] or
        "start_latitude": 10.3157,
        "start_longitude": 123.8854,
        "end_latitude": 10.3257,
        "end_longitude": 123.8954,
        "color": "#007AFF",
        "weight": 4,
        "opacity": 0.7
    }
    """
    try:
        data = json.loads(request.body)
        logger.info(f"Adding road highlight: {data.get('name')}")
        
        # Prepare road data
        road_data = {
            'name': data.get('name', 'Unnamed Road'),
            'description': data.get('description', ''),
            'color': data.get('color', '#007AFF'),
            'weight': data.get('weight', 4),
            'opacity': data.get('opacity', 0.7),
            'created_by': getattr(request, 'user_info', {}).get('user_id', 'system')
        }
        
        # Handle coordinates - support both formats
        if 'coordinates' in data:
            road_data['coordinates'] = data['coordinates']
        elif all(k in data for k in ['start_latitude', 'start_longitude', 'end_latitude', 'end_longitude']):
            road_data['start_latitude'] = float(data['start_latitude'])
            road_data['start_longitude'] = float(data['start_longitude'])
            road_data['end_latitude'] = float(data['end_latitude'])
            road_data['end_longitude'] = float(data['end_longitude'])
        else:
            return JsonResponse({
                'success': False,
                'error': 'Either coordinates array or start/end coordinates are required'
            }, status=400)
        
        # Insert into database
        response = supabase.table('road_highlights').insert(road_data).execute()
        
        if hasattr(response, 'data') and response.data:
            logger.info(f"Road highlight added: {response.data[0].get('id')}")
            return JsonResponse({
                'success': True,
                'data': response.data[0],
                'message': 'Road highlight added successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to add road highlight'
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error adding road highlight: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def get_stops(request):
    """
    Get tour stops/points for tour package creation
    Returns: JSON with stop points only
    """
    try:
        logger.info("Fetching tour stops")
        
        # Get points with type 'stop' or 'landmark' for tour packages
        query = supabase.table('map_points').select('*')
        query = query.in_('point_type', ['stop', 'landmark', 'attraction'])
        
        # Execute query
        points_response = query.execute()
        stops = points_response.data if hasattr(points_response, 'data') else []
        
        logger.info(f"Fetched {len(stops)} tour stops")
        
        return JsonResponse({
            'success': True,
            'data': {
                'stops': stops,
                'total': len(stops)
            },
            'message': f'Fetched {len(stops)} tour stops'
        })
        
    except Exception as e:
        logger.error(f"Error in get_stops: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Failed to fetch stops'
        }, status=500)

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def get_dropoff_points(request):
    """
    Get available drop-off points for a specific pickup point
    Query params:
        - pickup_id: ID of the selected pickup point
        - pickup_name: Name of the selected pickup point
    Returns: JSON with valid drop-off points for the pickup
    """
    try:
        pickup_id = request.GET.get('pickup_id')
        pickup_name = request.GET.get('pickup_name')
        
        logger.info(f"Fetching drop-off points for pickup: {pickup_name or pickup_id}")
        
        dropoff_points = []
        
        # First try to get from route_summary table using pickup_id
        if pickup_id:
            try:
                # Query route_summary table for routes with this pickup point
                routes_response = supabase.table('route_summary').select('dropoff_point_ids').eq('pickup_point_id', pickup_id).execute()
                
                if hasattr(routes_response, 'data') and routes_response.data:
                    # Collect all unique dropoff point IDs
                    dropoff_ids = set()
                    for route in routes_response.data:
                        if route.get('dropoff_point_ids'):
                            dropoff_ids.update(route['dropoff_point_ids'])
                    
                    # Get the actual dropoff points from map_points table
                    if dropoff_ids:
                        points_response = supabase.table('map_points').select('*').in_('id', list(dropoff_ids)).execute()
                        if hasattr(points_response, 'data') and points_response.data:
                            dropoff_points = points_response.data
                            
                logger.info(f"Found {len(dropoff_points)} drop-off points from database for pickup_id: {pickup_id}")
            except Exception as db_error:
                logger.warning(f"Database query failed: {db_error}")
        
        # Fallback to hardcoded data if no database results or pickup_name provided
        if not dropoff_points and pickup_name:
            pickup_dropoff_map = {
                'gg - Pickup': [
                    {'id': 'gg_dropoff_1', 'name': 'Ayala Center Cebu', 'latitude': 10.3187, 'longitude': 123.9064, 'description': 'Shopping mall drop-off'},
                    {'id': 'gg_dropoff_2', 'name': 'IT Park', 'latitude': 10.3280, 'longitude': 123.9070, 'description': 'Business district drop-off'},
                    {'id': 'gg_dropoff_3', 'name': 'Colon Street', 'latitude': 10.2958, 'longitude': 123.9021, 'description': 'Historic street drop-off'},
                    {'id': 'gg_dropoff_4', 'name': 'Capitol Site', 'latitude': 10.3200, 'longitude': 123.8950, 'description': 'Government area drop-off'},
                    {'id': 'gg_dropoff_5', 'name': 'Lahug', 'latitude': 10.3350, 'longitude': 123.9100, 'description': 'Residential area drop-off'}
                ],
                'SM City Cebu Terminal': [
                    {'id': 'sm_dropoff_1', 'name': 'Ayala Center Cebu', 'latitude': 10.3187, 'longitude': 123.9064, 'description': 'Shopping mall drop-off'},
                    {'id': 'sm_dropoff_2', 'name': 'IT Park', 'latitude': 10.3280, 'longitude': 123.9070, 'description': 'Business district drop-off'},
                    {'id': 'sm_dropoff_3', 'name': 'Colon Street', 'latitude': 10.2958, 'longitude': 123.9021, 'description': 'Historic street drop-off'}
                ],
                'Ayala Center Cebu Terminal': [
                    {'id': 'ayala_dropoff_1', 'name': 'SM City Cebu', 'latitude': 10.3157, 'longitude': 123.8854, 'description': 'Shopping mall drop-off'},
                    {'id': 'ayala_dropoff_2', 'name': 'Capitol Site', 'latitude': 10.3200, 'longitude': 123.8950, 'description': 'Government area drop-off'},
                    {'id': 'ayala_dropoff_3', 'name': 'Lahug', 'latitude': 10.3350, 'longitude': 123.9100, 'description': 'Residential area drop-off'}
                ],
                'Plaza Independencia': [
                    {'id': 'plaza_dropoff_1', 'name': 'Magellan\'s Cross', 'latitude': 10.2934, 'longitude': 123.9015, 'description': 'Historic landmark'},
                    {'id': 'plaza_dropoff_2', 'name': 'Basilica del Santo Niño', 'latitude': 10.2945, 'longitude': 123.9017, 'description': 'Religious site'},
                    {'id': 'plaza_dropoff_3', 'name': 'Heritage Monument', 'latitude': 10.2920, 'longitude': 123.9000, 'description': 'Cultural site'},
                    {'id': 'plaza_dropoff_4', 'name': 'Fort San Pedro', 'latitude': 10.2900, 'longitude': 123.9050, 'description': 'Historical fort'}
                ]
            }
            
            dropoff_points = pickup_dropoff_map.get(pickup_name, [])
            logger.info(f"Using fallback data: {len(dropoff_points)} drop-off points for pickup: {pickup_name}")
        
        # If still no dropoff points, provide custom option
        if not dropoff_points:
            dropoff_points = [
                {'id': 'custom', 'name': 'Custom Location', 'latitude': 0, 'longitude': 0, 'description': 'Click on map to select'}
            ]
        
        logger.info(f"Final result: {len(dropoff_points)} drop-off points for pickup: {pickup_name or pickup_id}")
        
        return JsonResponse({
            'success': True,
            'data': {
                'dropoff_points': dropoff_points,
                'pickup_name': pickup_name,
                'pickup_id': pickup_id,
                'total': len(dropoff_points)
            },
            'message': f'Found {len(dropoff_points)} drop-off points'
        })
        
    except Exception as e:
        logger.error(f"Error in get_dropoff_points: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Failed to fetch drop-off points'
        }, status=500)

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def get_routes(request):
    """
    Get tartanilla routes for navigation
    Returns empty routes since table doesn't exist
    """
    return JsonResponse({
        'success': True,
        'data': {
            'routes': [],
            'total': 0
        },
        'message': 'No routes available'
    })

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def get_road_highlights(request):
    """
    Get road highlights for ride hailing pickup/dropoff selection
    Returns: JSON with road highlights and their coordinates
    """
    try:
        logger.info("Fetching road highlights for ride hailing")
        
        # Always return empty data for now to prevent errors
        # The road_highlights table may not exist or have data
        processed_roads = []
        
        try:
            # Try to get road highlights from database
            roads_response = supabase.table('road_highlights').select('*').limit(50).execute()
            roads = roads_response.data if hasattr(roads_response, 'data') else []
            
            # Process roads to ensure coordinates are properly formatted
            for road in roads:
                processed_road = {
                    'id': road.get('id'),
                    'name': road.get('name', 'Unnamed Road'),
                    'description': road.get('description', ''),
                    'color': road.get('color', '#007AFF'),
                    'weight': road.get('weight', 4),
                    'opacity': road.get('opacity', 0.7),
                    'coordinates': []
                }
                
                # Handle different coordinate formats
                if road.get('road_coordinates'):
                    try:
                        coords = json.loads(road['road_coordinates']) if isinstance(road['road_coordinates'], str) else road['road_coordinates']
                        processed_road['coordinates'] = coords
                    except:
                        processed_road['coordinates'] = []
                elif road.get('coordinates'):
                    processed_road['coordinates'] = road['coordinates']
                elif all(k in road for k in ['start_latitude', 'start_longitude', 'end_latitude', 'end_longitude']):
                    processed_road['coordinates'] = [
                        [road['start_latitude'], road['start_longitude']],
                        [road['end_latitude'], road['end_longitude']]
                    ]
                
                processed_roads.append(processed_road)
                
        except Exception as db_error:
            logger.warning(f"Database error (ignoring): {db_error}")
            # Continue with empty roads array
        
        logger.info(f"Returning {len(processed_roads)} road highlights")
        
        return create_safe_response({
            'success': True,
            'data': {
                'roads': processed_roads,
                'total': len(processed_roads)
            },
            'message': f'Fetched {len(processed_roads)} road highlights'
        })
        
    except Exception as e:
        logger.error(f"Error in get_road_highlights: {e}")
        return create_safe_response({
            'success': True,
            'data': {
                'roads': [],
                'total': 0
            },
            'message': 'Road highlights temporarily unavailable'
        })

@csrf_exempt
@api_view(['DELETE'])
def delete_map_point(request, point_id):
    """
    Delete a map point by ID
    """
    try:
        logger.info(f"Deleting map point: {point_id}")
        
        response = supabase.table('map_points').delete().eq('id', point_id).execute()
        
        if hasattr(response, 'data') and response.data:
            logger.info(f"Map point deleted: {point_id}")
            return JsonResponse({
                'success': True,
                'message': 'Map point deleted successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Map point not found'
            }, status=404)
            
    except Exception as e:
        logger.error(f"Error deleting map point: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@csrf_exempt
@api_view(['PUT'])
def update_map_point(request, point_id):
    """
    Update a map point by ID
    """
    try:
        data = json.loads(request.body)
        logger.info(f"Updating map point: {point_id}")
        
        # Prepare update data (only include fields that are provided)
        update_data = {}
        allowed_fields = ['name', 'description', 'latitude', 'longitude', 'point_type', 'icon_color', 'image_url', 'is_active']
        
        for field in allowed_fields:
            if field in data:
                if field in ['latitude', 'longitude']:
                    update_data[field] = float(data[field])
                else:
                    update_data[field] = data[field]
        
        if not update_data:
            return JsonResponse({
                'success': False,
                'error': 'No valid fields to update'
            }, status=400)
        
        # Update in database
        response = supabase.table('map_points').update(update_data).eq('id', point_id).execute()
        
        if hasattr(response, 'data') and response.data:
            logger.info(f"Map point updated: {point_id}")
            return JsonResponse({
                'success': True,
                'data': response.data[0],
                'message': 'Map point updated successfully'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Map point not found'
            }, status=404)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error updating map point: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
