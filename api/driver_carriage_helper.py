from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase
from datetime import datetime

class DriverCarriageHelperViewSet(viewsets.ViewSet):
    """Helper endpoints for drivers to manage their carriage assignments"""
    permission_classes = [AllowAny]
    
    @action(detail=False, methods=['get'], url_path='pending-assignments/(?P<driver_id>[^/.]+)')
    def get_pending_assignments(self, request, driver_id=None):
        """Get all pending carriage assignments for a driver"""
        try:
            response = supabase.table('tartanilla_carriages').select('*').eq('assigned_driver_id', driver_id).eq('status', 'waiting_driver_acceptance').execute()
            
            pending_carriages = response.data if hasattr(response, 'data') and response.data else []
            
            return Response({
                'success': True,
                'data': pending_carriages,
                'count': len(pending_carriages),
                'message': f'Found {len(pending_carriages)} pending carriage assignments'
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='accept-all-pending/(?P<driver_id>[^/.]+)')
    def accept_all_pending_assignments(self, request, driver_id=None):
        """Accept all pending carriage assignments for a driver"""
        try:
            # Get pending assignments
            response = supabase.table('tartanilla_carriages').select('*').eq('assigned_driver_id', driver_id).eq('status', 'waiting_driver_acceptance').execute()
            
            pending_carriages = response.data if hasattr(response, 'data') and response.data else []
            
            if not pending_carriages:
                return Response({
                    'success': True,
                    'message': 'No pending carriage assignments found',
                    'accepted_count': 0
                })
            
            # Accept each carriage
            accepted_count = 0
            for carriage in pending_carriages:
                try:
                    update_data = {
                        'status': 'driver_assigned',
                        'updated_at': datetime.now().isoformat()
                    }
                    
                    supabase.table('tartanilla_carriages').update(update_data).eq('id', carriage['id']).execute()
                    accepted_count += 1
                    
                except Exception as e:
                    print(f"Failed to accept carriage {carriage['id']}: {e}")
                    continue
            
            return Response({
                'success': True,
                'message': f'Successfully accepted {accepted_count} carriage assignments',
                'accepted_count': accepted_count,
                'total_pending': len(pending_carriages)
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)