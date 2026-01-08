from django.http import HttpResponse
from tartanilla_admin.supabase import supabase
import json

def raw_json(request):
    """Raw JSON endpoint that bypasses all Django processing"""
    try:
        # Get points
        points_response = supabase.table('map_points').select('id,name,latitude,longitude,point_type,icon_color,description').limit(50).execute()
        points = points_response.data if hasattr(points_response, 'data') else []
        
        # Get roads with debug info
        roads_response = supabase.table('road_highlights').select('*').execute()
        roads_raw = roads_response.data if hasattr(roads_response, 'data') else []
        
        # Process roads to ensure proper coordinate format
        roads = []
        for road in roads_raw:
            try:
                # Ensure road_coordinates is properly formatted
                coords = road.get('road_coordinates', [])
                if isinstance(coords, str):
                    coords = json.loads(coords)
                
                # Validate coordinates
                if coords and len(coords) >= 2:
                    road['road_coordinates'] = coords
                    roads.append(road)
                    print(f"Road '{road.get('name', 'unnamed')}' has {len(coords)} coordinates")
                else:
                    print(f"Skipping road '{road.get('name', 'unnamed')}' - invalid coordinates: {coords}")
                    
            except Exception as road_error:
                print(f"Error processing road {road.get('id', 'unknown')}: {road_error}")
                continue
        
        # Debug logging
        print(f"Points found: {len(points)}")
        print(f"Roads found: {len(roads_raw)} raw, {len(roads)} valid")
        if roads:
            print(f"First valid road: {roads[0].get('name', 'unnamed')} with {len(roads[0].get('road_coordinates', []))} coordinates")
        
        data = {
            'success': True,
            'points': points,
            'roads': roads,
            'debug': {
                'points_count': len(points),
                'roads_raw_count': len(roads_raw),
                'roads_valid_count': len(roads),
                'roads_details': [{
                    'id': r.get('id'),
                    'name': r.get('name'),
                    'coord_count': len(r.get('road_coordinates', [])),
                    'color': r.get('stroke_color')
                } for r in roads[:5]]  # First 5 roads for debugging
            }
        }
        
        response = HttpResponse()
        response['Content-Type'] = 'application/json'
        response.content = json.dumps(data).encode('utf-8')
        return response
        
    except Exception as e:
        print(f"Error in raw_json: {e}")
        import traceback
        traceback.print_exc()
        error_data = {'success': False, 'error': str(e)}
        response = HttpResponse()
        response['Content-Type'] = 'application/json'
        response.content = json.dumps(error_data).encode('utf-8')
        return response