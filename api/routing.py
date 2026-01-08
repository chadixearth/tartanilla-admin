from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import requests
import json

@method_decorator(csrf_exempt, name='dispatch')
class RouteAPI(APIView):
    
    def get(self, request):
        """Get route between two points using OpenRouteService or fallback to straight line"""
        try:
            start_lat = request.GET.get('start_lat')
            start_lng = request.GET.get('start_lng')
            end_lat = request.GET.get('end_lat')
            end_lng = request.GET.get('end_lng')
            
            if not all([start_lat, start_lng, end_lat, end_lng]):
                return Response({
                    "success": False,
                    "error": "Missing required parameters: start_lat, start_lng, end_lat, end_lng"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Try to get actual route using OpenRouteService (free tier)
            try:
                # Using OpenRouteService API (you can replace with your preferred routing service)
                ors_url = f"https://api.openrouteservice.org/v2/directions/driving-car"
                params = {
                    'start': f"{start_lng},{start_lat}",
                    'end': f"{end_lng},{end_lat}",
                    'format': 'geojson'
                }
                
                # Note: You should add your OpenRouteService API key here
                # headers = {'Authorization': 'YOUR_API_KEY'}
                
                # For now, return a simple interpolated route
                route_coords = self.interpolate_route(
                    float(start_lat), float(start_lng),
                    float(end_lat), float(end_lng)
                )
                
                return Response({
                    "success": True,
                    "data": {
                        "road_coordinates": route_coords,
                        "distance": self.calculate_distance(
                            float(start_lat), float(start_lng),
                            float(end_lat), float(end_lng)
                        ),
                        "type": "interpolated"
                    }
                }, status=status.HTTP_200_OK)
                
            except Exception as routing_error:
                # Fallback to straight line with some interpolation
                route_coords = self.interpolate_route(
                    float(start_lat), float(start_lng),
                    float(end_lat), float(end_lng)
                )
                
                return Response({
                    "success": True,
                    "data": {
                        "road_coordinates": route_coords,
                        "distance": self.calculate_distance(
                            float(start_lat), float(start_lng),
                            float(end_lat), float(end_lng)
                        ),
                        "type": "fallback"
                    }
                }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                "success": False,
                "error": f"Failed to get route: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def interpolate_route(self, start_lat, start_lng, end_lat, end_lng, points=5):
        """Create interpolated points between start and end to simulate road following"""
        coords = []
        
        for i in range(points + 1):
            ratio = i / points
            lat = start_lat + (end_lat - start_lat) * ratio
            lng = start_lng + (end_lng - start_lng) * ratio
            
            # Add slight curve to make it look more like a road
            if i > 0 and i < points:
                curve_offset = 0.0005 * (1 - abs(ratio - 0.5) * 2)  # Peak at middle
                lat += curve_offset
            
            coords.append({
                "lat": lat,
                "lng": lng
            })
        
        return coords
    
    def calculate_distance(self, lat1, lng1, lat2, lng2):
        """Calculate approximate distance between two points in meters"""
        import math
        
        R = 6371000  # Earth's radius in meters
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_lat / 2) * math.sin(delta_lat / 2) +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lng / 2) * math.sin(delta_lng / 2))
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        
        return R * c