# Centralized API utilities for the entire application
from rest_framework.response import Response
from rest_framework import status
from .cache_utils import CacheManager
from .database_utils import DatabaseManager, DataProcessor
import logging
from typing import Dict, List, Any, Optional, Callable
from functools import wraps

logger = logging.getLogger(__name__)

class APIResponseManager:
    """Centralized API response management"""
    
    @staticmethod
    def success_response(data=None, message=None, status_code=status.HTTP_200_OK, cached=False):
        """Standard success response format"""
        response_data = {'success': True}
        
        if data is not None:
            response_data['data'] = data
        if message:
            response_data['message'] = message
        if cached:
            response_data['cached'] = True
            
        return Response(response_data, status=status_code)
    
    @staticmethod
    def error_response(error_message, status_code=status.HTTP_400_BAD_REQUEST, details=None):
        """Standard error response format"""
        response_data = {
            'success': False,
            'error': error_message
        }
        
        if details:
            response_data['details'] = details
            
        return Response(response_data, status=status_code)
    
    @staticmethod
    def not_found_response(resource="Resource"):
        """Standard 404 response"""
        return Response({
            'success': False,
            'error': f"{resource} not found"
        }, status=status.HTTP_404_NOT_FOUND)
    
    @staticmethod
    def validation_error_response(validation_errors):
        """Standard validation error response"""
        return APIResponseManager.error_response(
            "Validation failed",
            status.HTTP_400_BAD_REQUEST,
            validation_errors
        )

class OptimizedViewSetMixin:
    """Mixin to add optimization to ViewSets"""
    
    # Override these in your ViewSet
    TABLE_NAME = None
    MODULE_NAME = None
    DATE_FIELDS = []
    JSON_FIELDS = []
    COMPUTED_FIELDS = {}
    CACHE_TIMEOUT = 'medium'
    
    def get_cache_key(self, operation, params=None):
        """Generate cache key for this ViewSet"""
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
    
    def optimized_list(self, request, filters=None, order_by=None):
        """Optimized list operation with caching"""
        try:
            # Generate cache key based on request parameters
            query_params = dict(request.GET) if hasattr(request, 'GET') else {}
            if filters:
                query_params.update(filters)
            
            cache_key = self.get_cache_key('list', query_params)
            
            def fetch_data():
                records = DatabaseManager.get_all(
                    self.TABLE_NAME,
                    filters=filters,
                    order_by=order_by or '-created_at'
                )
                return self.process_data(records)
            
            data, cached = CacheManager.get_or_set(cache_key, fetch_data, self.CACHE_TIMEOUT)
            
            return APIResponseManager.success_response(
                data=data,
                cached=cached
            )
            
        except Exception as e:
            logger.error(f"Error in optimized_list for {self.TABLE_NAME}: {e}")
            return APIResponseManager.error_response(
                f"Failed to fetch {self.TABLE_NAME}",
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def optimized_retrieve(self, request, pk):
        """Optimized retrieve operation with caching"""
        try:
            cache_key = self.get_cache_key('detail', pk)
            
            def fetch_data():
                record = DatabaseManager.get_by_id(self.TABLE_NAME, pk)
                if not record:
                    return None
                return self.process_data(record)
            
            data, cached = CacheManager.get_or_set(cache_key, fetch_data, self.CACHE_TIMEOUT)
            
            if not data:
                return APIResponseManager.not_found_response(self.TABLE_NAME.replace('_', ' ').title())
            
            return APIResponseManager.success_response(
                data=data,
                cached=cached
            )
            
        except Exception as e:
            logger.error(f"Error in optimized_retrieve for {self.TABLE_NAME}: {e}")
            return APIResponseManager.error_response(
                f"Failed to fetch {self.TABLE_NAME}",
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def optimized_create(self, request, data):
        """Optimized create operation with cache invalidation"""
        try:
            created_record = DatabaseManager.create_record(self.TABLE_NAME, data)
            
            if not created_record:
                return APIResponseManager.error_response(
                    f"Failed to create {self.TABLE_NAME}",
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Invalidate cache
            self.invalidate_cache()
            
            processed_data = self.process_data(created_record)
            
            return APIResponseManager.success_response(
                data=processed_data,
                message=f"{self.TABLE_NAME.title()} created successfully",
                status_code=status.HTTP_201_CREATED
            )
            
        except Exception as e:
            logger.error(f"Error in optimized_create for {self.TABLE_NAME}: {e}")
            return APIResponseManager.error_response(
                f"Failed to create {self.TABLE_NAME}",
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def optimized_update(self, request, pk, data):
        """Optimized update operation with cache invalidation"""
        try:
            updated_record = DatabaseManager.update_record(self.TABLE_NAME, pk, data)
            
            if not updated_record:
                return APIResponseManager.not_found_response(self.TABLE_NAME.title())
            
            # Invalidate cache
            self.invalidate_cache(pk)
            
            processed_data = self.process_data(updated_record)
            
            return APIResponseManager.success_response(
                data=processed_data,
                message=f"{self.TABLE_NAME.title()} updated successfully"
            )
            
        except Exception as e:
            logger.error(f"Error in optimized_update for {self.TABLE_NAME}: {e}")
            return APIResponseManager.error_response(
                f"Failed to update {self.TABLE_NAME}",
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def optimized_destroy(self, request, pk):
        """Optimized delete operation with cache invalidation"""
        try:
            deleted = DatabaseManager.delete_record(self.TABLE_NAME, pk)
            
            if not deleted:
                return APIResponseManager.not_found_response(self.TABLE_NAME.title())
            
            # Invalidate cache
            self.invalidate_cache(pk)
            
            return APIResponseManager.success_response(
                message=f"{self.TABLE_NAME.title()} deleted successfully",
                status_code=status.HTTP_204_NO_CONTENT
            )
            
        except Exception as e:
            logger.error(f"Error in optimized_destroy for {self.TABLE_NAME}: {e}")
            return APIResponseManager.error_response(
                f"Failed to delete {self.TABLE_NAME}",
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )

def cached_api_method(module, operation, timeout='medium'):
    """Decorator for caching API method results"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            # Generate cache key
            query_params = dict(request.GET) if hasattr(request, 'GET') else {}
            cache_key = CacheManager.generate_cache_key(module, operation, query_params)
            
            def fetch_data():
                return func(self, request, *args, **kwargs)
            
            try:
                result, cached = CacheManager.get_or_set(cache_key, fetch_data, timeout)
                
                # If result is a Response object, modify its data to include cache info
                if hasattr(result, 'data') and isinstance(result.data, dict):
                    result.data['cached'] = cached
                
                return result
            except Exception as e:
                logger.error(f"Cached API method error: {e}")
                return func(self, request, *args, **kwargs)
        
        return wrapper
    return decorator
