# Centralized view utilities for Django views
from django.shortcuts import render, redirect
from django.http import JsonResponse
from .cache_utils import CacheManager
from .database_utils import DatabaseManager, DataProcessor
import logging

logger = logging.getLogger(__name__)

class OptimizedViewMixin:
    """Mixin to add optimization to Django views"""
    
    # Override these in your view
    TABLE_NAME = None
    MODULE_NAME = None
    DATE_FIELDS = []
    JSON_FIELDS = []
    COMPUTED_FIELDS = {}
    CACHE_TIMEOUT = 'medium'
    TEMPLATE_NAME = None
    
    def get_cache_key(self, operation, params=None):
        """Generate cache key for this view"""
        return CacheManager.generate_cache_key(
            self.MODULE_NAME or self.TABLE_NAME, 
            operation, 
            params
        )
    
    def invalidate_cache(self, record_id=None):
        """Invalidate cache for this module"""
        CacheManager.invalidate_cache(
            self.MODULE_NAME or self.TABLE_NAME,
            specific_key=self.get_cache_key('detail', record_id) if record_id else None
        )
    
    def process_data(self, data):
        """Process data with date, JSON, and computed fields"""
        if self.DATE_FIELDS:
            data = DataProcessor.process_dates(data, self.DATE_FIELDS)
        
        if self.JSON_FIELDS:
            data = DataProcessor.process_json_fields(data, self.JSON_FIELDS)
        
        if self.COMPUTED_FIELDS:
            data = DataProcessor.add_computed_fields(data, self.COMPUTED_FIELDS)
        
        return data
    
    def optimized_list_view(self, request, context=None, filters=None, order_by=None):
        """Optimized list view with caching"""
        try:
            # Generate cache key based on request parameters
            query_params = dict(request.GET)
            if filters:
                query_params.update(filters)
            
            cache_key = self.get_cache_key('list_view', query_params)
            
            def fetch_data():
                records = DatabaseManager.get_all(
                    self.TABLE_NAME,
                    filters=filters,
                    order_by=order_by or '-created_at'
                )
                return self.process_data(records)
            
            data, cached = CacheManager.get_or_set(cache_key, fetch_data, self.CACHE_TIMEOUT)
            
            # Prepare context
            view_context = {
                f'{self.TABLE_NAME}': data,
                'error': None,
                'cached': cached
            }
            
            if context:
                view_context.update(context)
            
            return render(request, self.TEMPLATE_NAME, view_context)
            
        except Exception as e:
            logger.error(f"Error in optimized_list_view for {self.TABLE_NAME}: {e}")
            return render(request, self.TEMPLATE_NAME, {
                f'{self.TABLE_NAME}': [],
                'error': f'Failed to load {self.TABLE_NAME}'
            })
    
    def optimized_detail_view(self, request, record_id, context=None):
        """Optimized detail view with caching"""
        try:
            cache_key = self.get_cache_key('detail_view', record_id)
            
            def fetch_data():
                record = DatabaseManager.get_by_id(self.TABLE_NAME, record_id)
                if not record:
                    return None
                return self.process_data(record)
            
            data, cached = CacheManager.get_or_set(cache_key, fetch_data, self.CACHE_TIMEOUT)
            
            if not data:
                return redirect(f'{self.MODULE_NAME}:list')
            
            # Prepare context
            view_context = {
                f'{self.TABLE_NAME[:-1]}': data,  # Remove 's' for singular
                'error': None,
                'cached': cached
            }
            
            if context:
                view_context.update(context)
            
            return render(request, self.TEMPLATE_NAME, view_context)
            
        except Exception as e:
            logger.error(f"Error in optimized_detail_view for {self.TABLE_NAME}: {e}")
            return redirect(f'{self.MODULE_NAME}:list')

def cached_view(module, operation, timeout='medium'):
    """Decorator for caching view results"""
    def decorator(func):
        def wrapper(request, *args, **kwargs):
            # Generate cache key
            query_params = dict(request.GET)
            if kwargs:
                query_params.update(kwargs)
            
            cache_key = CacheManager.generate_cache_key(module, operation, query_params)
            
            def fetch_data():
                return func(request, *args, **kwargs)
            
            try:
                result, cached = CacheManager.get_or_set(cache_key, fetch_data, timeout)
                
                # If result is an HttpResponse, we can't modify it easily
                # So we'll just return it as is
                return result
            except Exception as e:
                logger.error(f"Cached view error: {e}")
                return func(request, *args, **kwargs)
        
        return wrapper
    return decorator

class OptimizedJSONResponseMixin:
    """Mixin for optimized JSON responses in views"""
    
    @staticmethod
    def success_json_response(data=None, message=None, cached=False):
        """Standard success JSON response"""
        response_data = {'success': True}
        
        if data is not None:
            response_data['data'] = data
        if message:
            response_data['message'] = message
        if cached:
            response_data['cached'] = True
            
        return JsonResponse(response_data)
    
    @staticmethod
    def error_json_response(error_message, status_code=400):
        """Standard error JSON response"""
        return JsonResponse({
            'success': False,
            'error': error_message
        }, status=status_code)
