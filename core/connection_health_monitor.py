"""
Connection Health Monitor for Supabase
Monitors connection health and provides automatic recovery
"""

import logging
import time
import threading
from datetime import datetime, timedelta
from tartanilla_admin.supabase import supabase, execute_with_retry

logger = logging.getLogger(__name__)

class ConnectionHealthMonitor:
    """Monitor and maintain healthy connections to Supabase"""
    
    def __init__(self):
        self.is_healthy = True
        self.last_health_check = None
        self.consecutive_failures = 0
        self.max_consecutive_failures = 3
        self.health_check_interval = 30  # seconds
        self.monitor_thread = None
        self.stop_monitoring = False
        
    def check_connection_health(self):
        """Perform a lightweight health check"""
        try:
            def health_query():
                return supabase.table('users').select('id').limit(1).execute()
            
            response = execute_with_retry(health_query, max_retries=2)
            
            if hasattr(response, 'data') and response.data is not None:
                self.is_healthy = True
                self.consecutive_failures = 0
                self.last_health_check = datetime.now()
                return True
            else:
                self.consecutive_failures += 1
                if self.consecutive_failures >= self.max_consecutive_failures:
                    self.is_healthy = False
                return False
                
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_consecutive_failures:
                self.is_healthy = False
            return False
    
    def start_monitoring(self):
        """Start background health monitoring"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
            
        self.stop_monitoring = False
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Connection health monitoring started")
    
    def stop_monitoring_service(self):
        """Stop background health monitoring"""
        self.stop_monitoring = True
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("Connection health monitoring stopped")
    
    def _monitor_loop(self):
        """Background monitoring loop"""
        while not self.stop_monitoring:
            try:
                self.check_connection_health()
                time.sleep(self.health_check_interval)
            except Exception as e:
                logger.error(f"Error in health monitoring loop: {e}")
                time.sleep(self.health_check_interval)
    
    def get_health_status(self):
        """Get current health status"""
        return {
            'is_healthy': self.is_healthy,
            'last_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'consecutive_failures': self.consecutive_failures,
            'monitoring_active': self.monitor_thread and self.monitor_thread.is_alive()
        }

# Global health monitor instance
health_monitor = ConnectionHealthMonitor()

def get_connection_health():
    """Get current connection health status"""
    return health_monitor.get_health_status()

def ensure_healthy_connection():
    """Ensure connection is healthy before proceeding"""
    if not health_monitor.is_healthy:
        # Try to recover
        if health_monitor.check_connection_health():
            logger.info("Connection recovered")
        else:
            logger.warning("Connection still unhealthy")
    
    return health_monitor.is_healthy