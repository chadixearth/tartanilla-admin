"""
Startup script to initialize connection health monitoring
"""

import logging
from core.connection_health_monitor import health_monitor

logger = logging.getLogger(__name__)

def initialize_health_monitoring():
    """Initialize and start connection health monitoring"""
    try:
        health_monitor.start_monitoring()
        logger.info("Connection health monitoring initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize health monitoring: {e}")
        return False

def shutdown_health_monitoring():
    """Shutdown connection health monitoring"""
    try:
        health_monitor.stop_monitoring_service()
        logger.info("Connection health monitoring shutdown successfully")
    except Exception as e:
        logger.error(f"Error shutting down health monitoring: {e}")

# Auto-initialize when imported
if __name__ != "__main__":
    initialize_health_monitoring()