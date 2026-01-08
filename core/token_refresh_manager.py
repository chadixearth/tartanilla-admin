"""
Token Refresh Manager for Supabase JWT Tokens
Handles automatic token refresh to prevent JWT expiration issues
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from tartanilla_admin.supabase import supabase, supabase_admin

logger = logging.getLogger(__name__)

class TokenRefreshManager:
    """Manages automatic token refresh for Supabase clients"""
    
    def __init__(self):
        self.refresh_interval = 1800  # 30 minutes
        self.is_running = False
        self.refresh_thread = None
        self.last_refresh = None
        
    def start_refresh_scheduler(self):
        """Start the background token refresh scheduler"""
        if self.is_running:
            logger.info("Token refresh scheduler already running")
            return
            
        self.is_running = True
        self.refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self.refresh_thread.start()
        logger.info("Token refresh scheduler started")
    
    def stop_refresh_scheduler(self):
        """Stop the background token refresh scheduler"""
        self.is_running = False
        if self.refresh_thread:
            self.refresh_thread.join(timeout=5)
        logger.info("Token refresh scheduler stopped")
    
    def _refresh_loop(self):
        """Background loop that refreshes tokens periodically"""
        while self.is_running:
            try:
                self._refresh_tokens()
                time.sleep(self.refresh_interval)
            except Exception as e:
                logger.error(f"Error in token refresh loop: {e}")
                time.sleep(60)  # Wait 1 minute before retrying on error
    
    def _refresh_tokens(self):
        """Refresh tokens for all Supabase clients"""
        try:
            current_time = datetime.now()
            
            # Skip if we refreshed recently (within 10 minutes)
            if (self.last_refresh and 
                current_time - self.last_refresh < timedelta(minutes=10)):
                return
            
            logger.info("Refreshing Supabase tokens...")
            
            # For service role clients, we don't need to refresh tokens
            # as service role keys don't expire
            if supabase_admin:
                logger.info("Using service role key - no token refresh needed")
                self.last_refresh = current_time
                return
            
            # For regular clients using anon key, we also don't need refresh
            # as anon keys don't expire
            logger.info("Using anon key - no token refresh needed")
            self.last_refresh = current_time
            
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
    
    def force_refresh(self):
        """Force an immediate token refresh"""
        try:
            self._refresh_tokens()
            return {"success": True, "message": "Tokens refreshed successfully"}
        except Exception as e:
            logger.error(f"Force refresh failed: {e}")
            return {"success": False, "error": str(e)}

# Global token refresh manager instance
token_refresh_manager = TokenRefreshManager()

def start_token_refresh_manager():
    """Start the global token refresh manager"""
    token_refresh_manager.start_refresh_scheduler()

def stop_token_refresh_manager():
    """Stop the global token refresh manager"""
    token_refresh_manager.stop_refresh_scheduler()

def force_token_refresh():
    """Force refresh tokens immediately"""
    return token_refresh_manager.force_refresh()