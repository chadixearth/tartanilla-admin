# Utility functions for tour package processing
from datetime import datetime, date
from django.core.cache import cache
import hashlib

def process_package_expiration(packages):
    """
    Process packages to add expiration status efficiently
    Handles both single package (dict) and multiple packages (list)
    """
    if not packages:
        return packages
    
    # Handle single package
    if isinstance(packages, dict):
        packages = [packages]
        single_package = True
    else:
        single_package = False
    
    today = date.today()
    
    for package in packages:
        if package.get('expiration_date'):
            try:
                # Parse the expiration date string to a date object
                expiration_date = datetime.fromisoformat(package['expiration_date']).date()
                package['is_expired'] = expiration_date < today
                # Format the date for display
                package['expiration_date'] = expiration_date.strftime('%b %d, %Y')
            except (ValueError, TypeError):
                package['is_expired'] = False
        else:
            package['is_expired'] = False
    
    return packages[0] if single_package else packages

def get_cache_key(prefix, params=None):
    """Generate a cache key based on prefix and parameters"""
    if params:
        # Create a hash of the parameters for consistent cache keys
        param_str = str(sorted(params.items()) if isinstance(params, dict) else params)
        param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]
        return f"{prefix}_{param_hash}"
    return prefix

def get_cached_packages(cache_key, cache_timeout=300):
    """Get packages from cache"""
    return cache.get(cache_key)

def set_cached_packages(cache_key, packages, cache_timeout=300):
    """Set packages in cache"""
    cache.set(cache_key, packages, cache_timeout)

def invalidate_package_cache(package_id=None):
    """
    Invalidate package-related cache entries
    If package_id is provided, invalidate specific package cache
    Otherwise, invalidate all package caches
    """
    if package_id:
        # Invalidate specific package cache
        cache.delete(get_cache_key('tourpackage_detail', package_id))
        cache.delete(get_cache_key('edit_package', package_id))
    
    # Always invalidate list caches when any package changes
    # Since we can't easily track all possible query parameter combinations,
    # we'll use a pattern-based approach
    cache.delete_many([
        get_cache_key('tourpackages_list', {}),
        get_cache_key('view_packages', {}),
    ])
    
    # For production, you might want to use cache versioning instead
    # This is a simple approach for development

def get_or_set_cache(cache_key, fetch_function, timeout=300):
    """
    Generic cache get-or-set function
    """
    cached_data = cache.get(cache_key)
    if cached_data is not None:
        return cached_data, True  # Return data and cache hit flag
    
    # Fetch fresh data
    fresh_data = fetch_function()
    cache.set(cache_key, fresh_data, timeout)
    return fresh_data, False  # Return data and cache miss flag
