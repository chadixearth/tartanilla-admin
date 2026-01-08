"""
Core app configuration with startup initialization
"""

from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    
    def ready(self):
        """Initialize core components when Django is ready"""
        try:
            # Import and run startup checks
            from .startup import run_startup_checks
            run_startup_checks()
        except Exception as e:
            logger.error(f"Core app initialization failed: {e}")
            # Don't fail the entire application
            pass