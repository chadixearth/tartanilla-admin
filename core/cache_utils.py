# Centralized caching utilities for the entire application
from django.core.cache import cache
import hashlib
import json
from datetime import datetime, date
from functools import wraps
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

def serialize_params_for_cache(params):
    """Convert parameters to a JSON-serializable format"""
    if not params:
        return params
    
    def convert_value(value):
        if isinstance(value, UUID):
            return str(value)
        elif isinstance(value, (datetime, date)):
            return value.isoformat()
        elif isinstance(value, dict):
            return {k: convert_value(v) for k, v in value.items()}
        elif isinstance(value, (list, tuple)):
            return [convert_value(v) for v in value]
        else:
            return value
    
    if isinstance(params, dict):
        return {k: convert_value(v) for k, v in params.items()}
    else:
        return convert_value(params)

class CacheManager:
    """Centralized cache management for all modules"""
    
    # Cache timeouts (in seconds)
    CACHE_TIMEOUTS = {
        'short': 60,        # 1 minute
        'medium': 300,      # 5 minutes  
        'long': 1800,       # 30 minutes
        'extra_long': 3600  # 1 hour
    }
    
    # Cache key prefixes for different modules
    PREFIXES = {
        'tourpackage': 'tp',
        'booking': 'bk', 
        'user': 'usr',
        'carriage': 'car',
        'earnings': 'earn',
        'audit': 'audit',
        'route': 'route',
        'chat': 'chat',
        'custom_tour': 'ct',
        'special_event': 'se'
    }
    
    @staticmethod
    def generate_cache_key(module, operation, params=None):
        """Generate consistent cache keys across all modules"""
        prefix = CacheManager.PREFIXES.get(module, 'gen')
        
        if params:
            # Create a hash of the parameters for consistent cache keys
            try:
                # Serialize params to handle UUIDs and other non-JSON types
                serializable_params = serialize_params_for_cache(params)
                if isinstance(serializable_params, dict):
                    param_str = json.dumps(serializable_params, sort_keys=True)
                else:
                    param_str = str(serializable_params)
                param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]
                return f"{prefix}_{operation}_{param_hash}"
            except Exception as e:
                logger.warning(f"Error serializing cache params: {e}, using fallback")
                # Fallback to string representation
                param_hash = hashlib.md5(str(params).encode()).hexdigest()[:8]
                return f"{prefix}_{operation}_{param_hash}"
        
        return f"{prefix}_{operation}"
    
    @staticmethod
    def get_cached_data(cache_key):
        """Get data from cache with logging"""
        try:
            data = cache.get(cache_key)
            if data is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return data
            logger.debug(f"Cache MISS: {cache_key}")
            return None
        except Exception as e:
            logger.error(f"Cache GET error for {cache_key}: {e}")
            return None
    
    @staticmethod
    def set_cached_data(cache_key, data, timeout='medium'):
        """Set data in cache with flexible timeout"""
        try:
            if isinstance(timeout, str):
                timeout = CacheManager.CACHE_TIMEOUTS.get(timeout, 300)
            
            cache.set(cache_key, data, timeout)
            logger.debug(f"Cache SET: {cache_key} (timeout: {timeout}s)")
            return True
        except Exception as e:
            logger.error(f"Cache SET error for {cache_key}: {e}")
            return False
    
    @staticmethod
    def invalidate_cache(module, pattern=None, specific_key=None):
        """Invalidate cache for a module or specific pattern"""
        try:
            if specific_key:
                cache.delete(specific_key)
                logger.debug(f"Cache DELETED: {specific_key}")
                return
            
            prefix = CacheManager.PREFIXES.get(module, 'gen')
            
            # For pattern-based invalidation, we'll delete common patterns
            common_patterns = [
                f"{prefix}_list",
                f"{prefix}_detail", 
                f"{prefix}_search",
                f"{prefix}_filter"
            ]
            
            if pattern:
                common_patterns.append(f"{prefix}_{pattern}")
            
            cache.delete_many(common_patterns)
            logger.debug(f"Cache INVALIDATED: {module} patterns")
            
        except Exception as e:
            logger.error(f"Cache invalidation error for {module}: {e}")
    
    @staticmethod
    def get_or_set(cache_key, fetch_function, timeout='medium'):
        """Generic cache get-or-set pattern"""
        try:
            # Try to get from cache first
            cached_data = CacheManager.get_cached_data(cache_key)
            if cached_data is not None:
                return cached_data, True  # Data, cache_hit
            
            # Fetch fresh data
            fresh_data = fetch_function()
            
            # Cache the fresh data
            CacheManager.set_cached_data(cache_key, fresh_data, timeout)
            
            return fresh_data, False  # Data, cache_hit
            
        except Exception as e:
            logger.error(f"Cache get_or_set error for {cache_key}: {e}")
            # If cache fails, still return the fresh data
            try:
                return fetch_function(), False
            except Exception as fetch_error:
                logger.error(f"Fetch function failed: {fetch_error}")
                raise fetch_error

def cache_result(module, operation, timeout='medium', key_params=None):
    """Decorator for caching function results"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            params = key_params or kwargs
            cache_key = CacheManager.generate_cache_key(module, operation, params)
            
            # Use get_or_set pattern
            def fetch_data():
                return func(*args, **kwargs)
            
            result, cache_hit = CacheManager.get_or_set(cache_key, fetch_data, timeout)
            
            # Add cache metadata if result is a dict
            if isinstance(result, dict) and 'cached' not in result:
                result['cached'] = cache_hit
            
            return result
        return wrapper
    return decorator
