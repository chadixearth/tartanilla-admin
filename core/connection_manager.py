"""
Enhanced Connection Management for Supabase
Handles connection pooling, retry logic, and error recovery
"""

import logging
import time
import gc
from functools import wraps
from typing import Any, Callable, Optional
from tartanilla_admin.supabase import supabase, execute_with_retry

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages Supabase connections with enhanced error handling and recovery"""
    
    def __init__(self):
        self.connection_errors = 0
        self.last_error_time = 0
        self.max_errors_per_minute = 10
        
    def is_connection_healthy(self) -> bool:
        """Check if connection is healthy"""
        try:
            response = execute_with_retry(lambda: supabase.table('users').select('id').limit(1).execute())
            return hasattr(response, 'data') and response.data is not None
        except Exception as e:
            logger.warning(f"Connection health check failed: {e}")
            return False
    
    def reset_connection_state(self):
        """Reset connection error tracking"""
        current_time = time.time()
        if current_time - self.last_error_time > 60:  # Reset every minute
            self.connection_errors = 0
            self.last_error_time = current_time
    
    def should_circuit_break(self) -> bool:
        """Determine if we should circuit break due to too many errors"""
        self.reset_connection_state()
        return self.connection_errors >= self.max_errors_per_minute
    
    def record_error(self):
        """Record a connection error"""
        self.connection_errors += 1
        self.last_error_time = time.time()
    
    def safe_execute(self, query_func: Callable, fallback_data: Any = None) -> Any:
        """Safely execute a query with circuit breaker pattern"""
        if self.should_circuit_break():
            logger.warning("Circuit breaker activated - too many connection errors")
            return type('Response', (), {'data': fallback_data or [], 'error': 'Circuit breaker active'})()
        
        try:
            result = execute_with_retry(query_func)
            # Reset error count on successful operation
            if hasattr(result, 'data') and result.data is not None:
                self.connection_errors = max(0, self.connection_errors - 1)
            return result
        except Exception as e:
            self.record_error()
            logger.error(f"Query execution failed: {e}")
            return type('Response', (), {'data': fallback_data or [], 'error': str(e)})()

# Global connection manager instance
connection_manager = ConnectionManager()

def with_connection_retry(fallback_data=None):
    """Decorator to add connection retry logic to API methods"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_str = str(e).lower()
                connection_errors = [
                    'connection', 'timeout', 'network', 'ssl', 'certificate',
                    'winerror 10054', 'forcibly closed', 'readerror'
                ]
                
                if any(err in error_str for err in connection_errors):
                    logger.warning(f"Connection error in {func.__name__}: {e}")
                    connection_manager.record_error()
                    
                    # Force cleanup
                    gc.collect()
                    
                    # Return safe fallback response
                    from rest_framework.response import Response
                    from rest_framework import status
                    
                    return Response({
                        'success': False,
                        'error': 'Connection temporarily unavailable. Please try again.',
                        'data': fallback_data or [],
                        'retry_suggested': True
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
                else:
                    # Re-raise non-connection errors
                    raise
        return wrapper
    return decorator

def safe_supabase_query(table_name: str, operation: str, *args, **kwargs):
    """Safe wrapper for Supabase queries with automatic retry"""
    def query_func():
        table = supabase.table(table_name)
        if operation == 'select':
            query = table.select(*args)
            # Apply additional filters from kwargs
            for key, value in kwargs.items():
                if key == 'eq':
                    query = query.eq(*value) if isinstance(value, (list, tuple)) else query.eq(key, value)
                elif key == 'order':
                    query = query.order(*value) if isinstance(value, (list, tuple)) else query.order(value)
                elif key == 'limit':
                    query = query.limit(value)
            return query.execute()
        elif operation == 'insert':
            return table.insert(*args).execute()
        elif operation == 'update':
            return table.update(*args).execute()
        elif operation == 'delete':
            return table.delete().execute()
        else:
            raise ValueError(f"Unsupported operation: {operation}")
    
    return connection_manager.safe_execute(query_func)

# Utility functions for common operations
def safe_select(table_name: str, columns: str = '*', **filters):
    """Safely select data from a table"""
    return safe_supabase_query(table_name, 'select', columns, **filters)

def safe_insert(table_name: str, data: dict):
    """Safely insert data into a table"""
    return safe_supabase_query(table_name, 'insert', data)

def safe_update(table_name: str, data: dict, **filters):
    """Safely update data in a table"""
    return safe_supabase_query(table_name, 'update', data, **filters)

def safe_delete(table_name: str, **filters):
    """Safely delete data from a table"""
    return safe_supabase_query(table_name, 'delete', **filters)