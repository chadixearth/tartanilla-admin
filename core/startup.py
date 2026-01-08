"""
Startup initialization for connection management and error handling
"""

import logging
import os
from django.conf import settings
from tartanilla_admin.supabase import check_connection_health

logger = logging.getLogger(__name__)

def initialize_connection_management():
    """Initialize connection management and health monitoring"""
    try:
        logger.info("Initializing connection management...")
        
        # Test initial connection
        is_healthy = check_connection_health()
        if is_healthy:
            logger.info("✅ Supabase connection established successfully")
        else:
            logger.warning("⚠️ Supabase connection test failed - will retry on demand")
        
        # Set up connection monitoring
        logger.info("Connection management initialized")
        
    except Exception as e:
        logger.error(f"Failed to initialize connection management: {e}")

def setup_logging():
    """Configure enhanced logging for connection monitoring"""
    # Add connection-specific logger
    connection_logger = logging.getLogger('connection_manager')
    connection_logger.setLevel(logging.INFO)
    
    # Add handler if not already present
    if not connection_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '[%(asctime)s] %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        connection_logger.addHandler(handler)
    
    logger.info("Enhanced logging configured")

def run_startup_checks():
    """Run all startup checks and initialization"""
    logger.info("🚀 Starting Tartanilla Admin API...")
    
    setup_logging()
    initialize_connection_management()
    
    # Initialize token refresh manager
    try:
        from core.token_refresh_manager import start_token_refresh_manager
        start_token_refresh_manager()
        logger.info("✅ Token refresh manager started")
    except Exception as e:
        logger.warning(f"Failed to start token refresh manager: {e}")
    
    logger.info("✅ Startup checks completed")

# Auto-run on import (when Django starts)
if __name__ != '__main__':
    try:
        run_startup_checks()
    except Exception as e:
        logger.error(f"Startup initialization failed: {e}")
        # Don't fail the entire application startup
        pass