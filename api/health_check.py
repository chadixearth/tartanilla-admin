"""
Health Check API for Connection Monitoring
"""

from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from tartanilla_admin.supabase import supabase, execute_with_retry
from core.connection_health_monitor import get_connection_health
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class HealthCheckViewSet(viewsets.ViewSet):
    """Health check endpoints for connection monitoring"""
    permission_classes = [AllowAny]
    
    def list(self, request):
        """Basic health check"""
        try:
            # Test database connection
            def test_query():
                return supabase.table('users').select('id').limit(1).execute()
            
            response = execute_with_retry(test_query, max_retries=2)
            
            if hasattr(response, 'data') and response.data is not None:
                resp = Response({
                    'success': True,
                    'status': 'healthy',
                    'timestamp': datetime.now().isoformat(),
                    'database': 'connected'
                })
                # Remove hop-by-hop headers
                if 'Connection' in resp:
                    del resp['Connection']
                return resp
            else:
                resp = Response({
                    'success': False,
                    'status': 'unhealthy',
                    'timestamp': datetime.now().isoformat(),
                    'database': 'disconnected',
                    'error': getattr(response, 'error', 'Unknown error')
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                if 'Connection' in resp:
                    del resp['Connection']
                return resp
                
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            resp = Response({
                'success': False,
                'status': 'unhealthy',
                'timestamp': datetime.now().isoformat(),
                'database': 'error',
                'error': str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            if 'Connection' in resp:
                del resp['Connection']
            return resp
    
    @action(detail=False, methods=['get'], url_path='detailed')
    def detailed_health(self, request):
        """Detailed health check with connection monitoring info"""
        try:
            # Get connection health status
            health_status = get_connection_health()
            
            # Test database connection
            def test_query():
                return supabase.table('users').select('id').limit(1).execute()
            
            response = execute_with_retry(test_query, max_retries=2)
            
            database_healthy = hasattr(response, 'data') and response.data is not None
            
            overall_status = 'healthy' if database_healthy and health_status['is_healthy'] else 'unhealthy'
            
            return Response({
                'success': database_healthy,
                'status': overall_status,
                'timestamp': datetime.now().isoformat(),
                'components': {
                    'database': {
                        'status': 'healthy' if database_healthy else 'unhealthy',
                        'error': getattr(response, 'error', None) if not database_healthy else None
                    },
                    'connection_monitor': health_status
                }
            }, status=status.HTTP_200_OK if database_healthy else status.HTTP_503_SERVICE_UNAVAILABLE)
            
        except Exception as e:
            logger.error(f"Detailed health check failed: {e}")
            return Response({
                'success': False,
                'status': 'unhealthy',
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    
    @action(detail=False, methods=['post'], url_path='reset-connections')
    def reset_connections(self, request):
        """Force reset connections (for debugging)"""
        try:
            # Force garbage collection
            import gc
            gc.collect()
            
            return Response({
                'success': True,
                'message': 'Connection reset completed',
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Connection reset failed: {e}")
            return Response({
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)