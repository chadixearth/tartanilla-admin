"""
Enhanced Connection Management for Windows Socket Errors
Specifically handles WinError 10054 and HTTP/2 connection issues
"""

import logging
import time
import gc
import threading
from functools import wraps
from typing import Any, Callable, Optional
from tartanilla_admin.supabase import supabase
import httpx
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class EnhancedConnectionManager:
    """Enhanced connection manager for Windows socket errors and HTTP/2 issues"""
    
    def __init__(self):
        self.connection_errors = 0
        self.last_error_time = 0
        self.max_errors_per_minute = 5
        self.circuit_breaker_timeout = 60  # seconds
        self.is_circuit_open = False
        self.last_circuit_open_time = 0
        self.connection_pool = None
        self.lock = threading.Lock()
        
    def is_windows_socket_error(self, error) -> bool:
        """Check if error is a Windows socket error"""
        error_str = str(error).lower()
        windows_socket_errors = [
            'winerror 10054',
            'winerror 10035', 
            'winerror 10060',
            'existing connection was forcibly closed',
            'connection aborted',
            'connection reset',
            'readerror',
            'httpx.readerror',
            'httpcore.readerror',
            'stream_id',
            'http2',
            'connectionterminated'
        ]
        return any(err in error_str for err in windows_socket_errors)
    
    def reset_connection_pool(self):
        """Force reset of connection pool"""
        try:
            # Force garbage collection
            gc.collect()
            
            # Reset any cached connections in supabase client
            if hasattr(supabase, '_client') and hasattr(supabase._client, '_client'):
                client = supabase._client._client
                if hasattr(client, 'close'):
                    try:
                        client.close()
                    except:
                        pass
            
            logger.info("Connection pool reset completed")
        except Exception as e:
            logger.warning(f"Error resetting connection pool: {e}")
    
    def should_circuit_break(self) -> bool:
        """Check if circuit breaker should be activated"""
        with self.lock:
            current_time = time.time()
            
            # Reset circuit breaker if timeout has passed
            if self.is_circuit_open and (current_time - self.last_circuit_open_time) > self.circuit_breaker_timeout:
                self.is_circuit_open = False
                self.connection_errors = 0
                logger.info("Circuit breaker reset - attempting normal operation")
            
            # Reset error count if more than a minute has passed
            if current_time - self.last_error_time > 60:
                self.connection_errors = 0
            
            # Open circuit if too many errors
            if self.connection_errors >= self.max_errors_per_minute and not self.is_circuit_open:
                self.is_circuit_open = True
                self.last_circuit_open_time = current_time
                logger.warning("Circuit breaker activated due to connection errors")
                self.reset_connection_pool()
            
            return self.is_circuit_open
    
    def record_error(self, error):
        """Record a connection error"""
        with self.lock:
            if self.is_windows_socket_error(error):
                self.connection_errors += 1
                self.last_error_time = time.time()
                logger.warning(f"Windows socket error recorded: {error}")
    
    def record_success(self):
        """Record successful operation"""
        with self.lock:
            if self.connection_errors > 0:
                self.connection_errors = max(0, self.connection_errors - 1)
    
    def safe_execute_with_fallback(self, query_func: Callable, fallback_data: Any = None, max_retries: int = 3) -> Any:
        """Execute query with enhanced retry logic for Windows socket errors"""
        
        if self.should_circuit_break():
            logger.warning("Circuit breaker is open - returning fallback data")
            return type('Response', (), {'data': fallback_data or [], 'error': 'Circuit breaker active'})()
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                result = query_func()
                
                # Record success
                self.record_success()
                
                # Ensure result has data attribute
                if not hasattr(result, 'data'):
                    result = type('Response', (), {'data': result or fallback_data or []})()
                
                return result
                
            except Exception as e:
                last_error = e
                self.record_error(e)
                
                if self.is_windows_socket_error(e):
                    # Progressive backoff for socket errors
                    delay = min(2 ** attempt, 8)  # Max 8 seconds
                    logger.warning(f"Windows socket error on attempt {attempt + 1}/{max_retries}, retrying in {delay}s: {e}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        # Force connection reset on socket errors
                        if attempt > 0:
                            self.reset_connection_pool()
                        continue
                else:
                    # Non-socket errors - fail fast
                    break
        
        # All retries failed
        logger.error(f"All retries failed: {last_error}")
        return type('Response', (), {'data': fallback_data or [], 'error': str(last_error)})()

# Global enhanced connection manager
enhanced_connection_manager = EnhancedConnectionManager()

def with_enhanced_retry(fallback_data=None, max_retries=3):
    """Decorator for enhanced retry logic with Windows socket error handling"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            def query_func():
                return func(*args, **kwargs)
            
            return enhanced_connection_manager.safe_execute_with_fallback(
                query_func, fallback_data, max_retries
            )
        return wrapper
    return decorator

def safe_supabase_operation(operation_func, fallback_data=None):
    """Safe wrapper for Supabase operations with enhanced error handling"""
    return enhanced_connection_manager.safe_execute_with_fallback(
        operation_func, fallback_data
    )