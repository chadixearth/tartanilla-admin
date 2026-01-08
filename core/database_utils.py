# Centralized database utilities for the entire application
from tartanilla_admin.supabase import supabase, execute_with_retry
import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional, Callable
import json

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Centralized database operations with optimization"""
    
    @staticmethod
    def execute_query(query_func: Callable, max_retries: int = 3, delay: int = 1):
        """Execute database query with retry logic"""
        try:
            return execute_with_retry(query_func, max_retries, delay)
        except Exception as e:
            logger.error(f"Database query failed after retries: {e}")
            raise e
    
    @staticmethod
    def get_all(table: str, columns: str = '*', filters: Dict = None, order_by: str = None, limit: int = None) -> List[Dict]:
        """Get all records from a table with optional filtering"""
        def query():
            query_builder = supabase.table(table).select(columns)
            
            if filters:
                for key, value in filters.items():
                    if isinstance(value, list):
                        query_builder = query_builder.in_(key, value)
                    else:
                        query_builder = query_builder.eq(key, value)
            
            if order_by:
                desc = order_by.startswith('-')
                column = order_by.lstrip('-')
                query_builder = query_builder.order(column, desc=desc)
            
            if isinstance(limit, int) and limit > 0:
                query_builder = query_builder.limit(limit)
            
            return query_builder.execute()
        
        try:
            response = DatabaseManager.execute_query(query)
            return response.data if hasattr(response, 'data') else []
        except Exception as e:
            logger.error(f"Error fetching from {table}: {e}")
            return []
    
    @staticmethod
    def get_by_id(table: str, record_id: str, columns: str = '*') -> Optional[Dict]:
        """Get a single record by ID"""
        def query():
            return supabase.table(table).select(columns).eq('id', record_id).single().execute()
        
        try:
            response = DatabaseManager.execute_query(query)
            return response.data if hasattr(response, 'data') and response.data else None
        except Exception as e:
            logger.error(f"Error fetching {record_id} from {table}: {e}")
            return None
    
    @staticmethod
    def create_record(table: str, data: Dict) -> Optional[Dict]:
        """Create a new record"""
        def query():
            # Remove None values
            clean_data = {k: v for k, v in data.items() if v is not None}
            return supabase.table(table).insert(clean_data).execute()
        
        try:
            response = DatabaseManager.execute_query(query)
            if hasattr(response, 'data') and response.data:
                logger.info(f"Created record in {table}")
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error creating record in {table}: {e}")
            return None
    
    @staticmethod
    def update_record(table: str, record_id: str, data: Dict) -> Optional[Dict]:
        """Update an existing record"""
        def query():
            # Remove None values
            clean_data = {k: v for k, v in data.items() if v is not None}
            logger.info(f"Updating {table} record {record_id} with data: {clean_data}")
            return supabase.table(table).update(clean_data).eq('id', record_id).execute()
        
        try:
            response = DatabaseManager.execute_query(query)
            logger.info(f"Update response for {table} {record_id}: {response}")
            if hasattr(response, 'data') and response.data:
                logger.info(f"Successfully updated record {record_id} in {table}. New data: {response.data[0]}")
                return response.data[0]
            else:
                logger.warning(f"Update response has no data for {table} {record_id}")
                return None
        except Exception as e:
            logger.error(f"Error updating {record_id} in {table}: {e}")
            logger.error(f"Update data was: {data}")
            return None
    
    @staticmethod
    def delete_record(table: str, record_id: str) -> bool:
        """Delete a record"""
        def query():
            return supabase.table(table).delete().eq('id', record_id).execute()
        
        try:
            response = DatabaseManager.execute_query(query)
            if hasattr(response, 'data') and response.data:
                logger.info(f"Deleted record {record_id} from {table}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting {record_id} from {table}: {e}")
            return False
    
    @staticmethod
    def count_records(table: str, filters: Dict = None) -> int:
        """Count records in a table"""
        def query():
            query_builder = supabase.table(table).select('id', count='exact', head=True)
            
            if filters:
                for key, value in filters.items():
                    if isinstance(value, list):
                        query_builder = query_builder.in_(key, value)
                    else:
                        query_builder = query_builder.eq(key, value)
            
            return query_builder.execute()
        
        try:
            response = DatabaseManager.execute_query(query)
            return response.count if hasattr(response, 'count') else 0
        except Exception as e:
            logger.error(f"Error counting records in {table}: {e}")
            return 0
    
    @staticmethod
    def batch_get_by_ids(table: str, ids: List[str], columns: str = '*') -> Dict[str, Dict]:
        """Get multiple records by IDs and return as a dictionary keyed by ID"""
        if not ids:
            return {}
        
        def query():
            return supabase.table(table).select(columns).in_('id', ids).execute()
        
        try:
            response = DatabaseManager.execute_query(query)
            records = response.data if hasattr(response, 'data') else []
            return {record['id']: record for record in records}
        except Exception as e:
            logger.error(f"Error batch fetching from {table}: {e}")
            return {}
    
    @staticmethod
    def search_records(table: str, search_column: str, search_term: str, 
                      columns: str = '*', limit: int = 50) -> List[Dict]:
        """Search records using text search"""
        def query():
            return (supabase.table(table)
                   .select(columns)
                   .ilike(search_column, f'%{search_term}%')
                   .limit(limit)
                   .execute())
        
        try:
            response = DatabaseManager.execute_query(query)
            return response.data if hasattr(response, 'data') else []
        except Exception as e:
            logger.error(f"Error searching {table}: {e}")
            return []

class DataProcessor:
    """Centralized data processing utilities"""
    
    @staticmethod
    def process_dates(data, date_fields: List[str]):
        """Process date fields in data"""
        if isinstance(data, list):
            return [DataProcessor.process_dates(item, date_fields) for item in data]
        
        if not isinstance(data, dict):
            return data
        
        processed_data = data.copy()
        today = date.today()
        
        for field in date_fields:
            if processed_data.get(field):
                try:
                    # Parse the date string to a date object
                    if field.endswith('_date'):
                        date_obj = datetime.fromisoformat(processed_data[field]).date()
                        
                        # Add expiration status for expiration dates
                        if 'expiration' in field:
                            processed_data['is_expired'] = date_obj < today
                        
                        # Format the date for display
                        processed_data[field] = date_obj.strftime('%b %d, %Y')
                        
                    elif field.endswith('_at') or field.endswith('_time'):
                        # Handle datetime fields
                        datetime_obj = datetime.fromisoformat(processed_data[field].split('T')[0])
                        processed_data[f"{field}_formatted"] = datetime_obj.strftime('%Y-%m-%d')
                        
                except (ValueError, TypeError, AttributeError):
                    # Keep original value if parsing fails
                    if 'expiration' in field:
                        processed_data['is_expired'] = False
                    continue
            else:
                # Set default values for missing date fields
                if 'expiration' in field:
                    processed_data['is_expired'] = False
        
        return processed_data
    
    @staticmethod
    def process_json_fields(data, json_fields: List[str]):
        """Process JSON fields in data"""
        if isinstance(data, list):
            return [DataProcessor.process_json_fields(item, json_fields) for item in data]
        
        if not isinstance(data, dict):
            return data
        
        processed_data = data.copy()
        
        for field in json_fields:
            if processed_data.get(field):
                try:
                    if isinstance(processed_data[field], str):
                        processed_data[field] = json.loads(processed_data[field])
                except (json.JSONDecodeError, TypeError):
                    # Keep original value if parsing fails
                    continue
        
        return processed_data
    
    @staticmethod
    def add_computed_fields(data, computations: Dict[str, Callable]):
        """Add computed fields to data"""
        if isinstance(data, list):
            return [DataProcessor.add_computed_fields(item, computations) for item in data]
        
        if not isinstance(data, dict):
            return data
        
        processed_data = data.copy()
        
        for field_name, computation_func in computations.items():
            try:
                processed_data[field_name] = computation_func(processed_data)
            except Exception as e:
                logger.error(f"Error computing field {field_name}: {e}")
                processed_data[field_name] = None
        
        return processed_data
