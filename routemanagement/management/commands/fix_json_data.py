from django.core.management.base import BaseCommand
from tartanilla_admin.supabase import supabase
import json
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Fix malformed JSON data in route management tables'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting JSON data cleanup...'))
        
        try:
            # Fix map_points table
            self.fix_map_points()
            
            self.stdout.write(self.style.SUCCESS('JSON data cleanup completed successfully!'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error during cleanup: {str(e)}'))

    def fix_map_points(self):
        """Fix malformed JSON in map_points table"""
        self.stdout.write('Fixing map_points table...')
        
        try:
            # Get all points with image_urls
            response = supabase.table('map_points').select('*').execute()
            
            if not hasattr(response, 'data') or not response.data:
                self.stdout.write('No points found in database')
                return
            
            points = response.data
            fixed_count = 0
            
            for point in points:
                if not point.get('image_urls'):
                    continue
                    
                original_urls = point['image_urls']
                fixed_urls = self.fix_image_urls(original_urls)
                
                if fixed_urls != original_urls:
                    # Update the point with fixed data
                    update_data = {'image_urls': fixed_urls}
                    
                    update_response = supabase.table('map_points').update(update_data).eq('id', point['id']).execute()
                    
                    if hasattr(update_response, 'data') and update_response.data:
                        fixed_count += 1
                        self.stdout.write(f'Fixed point ID {point["id"]}: {original_urls} -> {fixed_urls}')
                    else:
                        self.stdout.write(self.style.WARNING(f'Failed to update point ID {point["id"]}'))
            
            self.stdout.write(self.style.SUCCESS(f'Fixed {fixed_count} points in map_points table'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error fixing map_points: {str(e)}'))

    def fix_image_urls(self, urls_data):
        """Fix malformed image URLs data"""
        if not urls_data:
            return None
            
        # If it's already a proper string or None, return as is
        if urls_data is None:
            return None
            
        # Convert to string if not already
        urls_str = str(urls_data).strip()
        
        if not urls_str:
            return None
            
        # If it looks like JSON, try to parse and re-serialize properly
        if urls_str.startswith('[') or urls_str.startswith('"'):
            try:
                parsed = json.loads(urls_str)
                if isinstance(parsed, list):
                    # Clean the list and re-serialize
                    clean_list = [str(url).strip() for url in parsed if url and str(url).strip()]
                    if clean_list:
                        return json.dumps(clean_list, ensure_ascii=False)
                    else:
                        return None
                elif isinstance(parsed, str):
                    return parsed.strip() if parsed.strip() else None
                else:
                    return str(parsed).strip() if str(parsed).strip() else None
            except (json.JSONDecodeError, ValueError, TypeError):
                # If JSON parsing fails, treat as single URL
                return urls_str if urls_str else None
        else:
            # Not JSON format, return as single URL
            return urls_str if urls_str else None