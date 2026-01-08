from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase
from datetime import datetime

class TestEligibilityViewSet(viewsets.ViewSet):
    """Test endpoints for carriage eligibility system"""
    permission_classes = [AllowAny]
    
    @action(detail=False, methods=['post'], url_path='set-eligibility/(?P<carriage_id>[^/.]+)')
    def set_carriage_eligibility(self, request, carriage_id=None):
        """Test endpoint to set carriage eligibility"""
        try:
            data = request.data if hasattr(request, 'data') else request.POST.dict()
            eligibility = data.get('eligibility', 'eligible')
            
            if eligibility not in ['eligible', 'suspended']:
                return Response({
                    'success': False,
                    'error': 'Invalid eligibility. Must be "eligible" or "suspended"'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update carriage eligibility
            update_data = {
                'eligibility': eligibility,
                'updated_at': datetime.now().isoformat()
            }
            
            response = supabase.table('tartanilla_carriages').update(update_data).eq('id', carriage_id).execute()
            
            if hasattr(response, 'data') and response.data:
                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': f'Carriage eligibility set to {eligibility}'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to update carriage eligibility'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='check-driver-eligibility/(?P<driver_id>[^/.]+)')
    def check_driver_eligibility(self, request, driver_id=None):
        """Test endpoint to check if driver has eligible carriages"""
        try:
            # Get driver's assigned carriages
            carriage_response = supabase.table('tartanilla_carriages').select('id, plate_number, eligibility, status').eq('assigned_driver_id', driver_id).execute()
            
            carriages = carriage_response.data if hasattr(carriage_response, 'data') and carriage_response.data else []
            
            if not carriages:
                return Response({
                    'success': True,
                    'can_accept_bookings': False,
                    'reason': 'No carriages assigned',
                    'carriages': []
                })
            
            # Check for eligible carriages
            eligible_carriages = [c for c in carriages if c.get('eligibility') == 'eligible']
            
            return Response({
                'success': True,
                'can_accept_bookings': len(eligible_carriages) > 0,
                'reason': 'Has eligible carriages' if eligible_carriages else 'No eligible carriages',
                'carriages': carriages,
                'eligible_carriages': eligible_carriages,
                'total_carriages': len(carriages),
                'eligible_count': len(eligible_carriages)
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def list_all_carriages_with_eligibility(self, request):
        """List all carriages with their eligibility status"""
        try:
            response = supabase.table('tartanilla_carriages').select('id, plate_number, eligibility, status, assigned_driver_id').execute()
            carriages = response.data if hasattr(response, 'data') and response.data else []
            
            # Group by eligibility
            eligible = [c for c in carriages if c.get('eligibility') == 'eligible']
            suspended = [c for c in carriages if c.get('eligibility') == 'suspended']
            
            return Response({
                'success': True,
                'data': {
                    'all_carriages': carriages,
                    'eligible_carriages': eligible,
                    'suspended_carriages': suspended,
                    'summary': {
                        'total': len(carriages),
                        'eligible': len(eligible),
                        'suspended': len(suspended)
                    }
                }
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)