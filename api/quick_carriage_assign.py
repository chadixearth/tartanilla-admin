from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase
from datetime import datetime
import uuid

class QuickCarriageAssignViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]
    
    @action(detail=False, methods=['post'], url_path='assign-to-driver')
    def assign_carriage_to_driver(self, request):
        """Quick assign a carriage to driver for testing"""
        try:
            driver_id = request.data.get('driver_id')
            
            if not driver_id:
                return Response({'error': 'driver_id required'}, status=400)
            
            # Create a test carriage for this driver
            carriage_data = {
                'id': str(uuid.uuid4()),
                'plate_number': f'TEST-{driver_id[:8]}',
                'assigned_driver_id': driver_id,
                'assigned_owner_id': driver_id,  # Use driver as owner for simplicity
                'status': 'driver_assigned',
                'capacity': 4,
                'eligibility': 'eligible',
                'created_at': datetime.now().isoformat()
            }
            
            response = supabase.table('tartanilla_carriages').insert(carriage_data).execute()
            
            return Response({
                'success': True,
                'message': f'Carriage assigned to driver {driver_id}',
                'carriage': response.data[0] if response.data else carriage_data
            })
            
        except Exception as e:
            return Response({'error': str(e)}, status=500)