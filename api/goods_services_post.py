from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.permissions import AllowAny
from datetime import datetime
import base64
import json
import logging

from core.api_utils import OptimizedViewSetMixin, APIResponseManager
from core.database_utils import DatabaseManager
from tartanilla_admin.supabase import supabase, upload_goodsservices_media

logger = logging.getLogger(__name__)


def log_audit(user_id, username, role, action, entity_name, entity_id=None, old_data=None, new_data=None, ip_address=None):
    """Log audit trail for goods & services operations"""
    try:
        audit_data = {
            'user_id': user_id,
            'username': username,
            'role': role,
            'action': action,
            'entity_name': entity_name,
            'entity_id': str(entity_id) if entity_id else None,
            'old_data': old_data,
            'new_data': new_data,
            'ip_address': ip_address
        }
        supabase.table('audit_logs').insert(audit_data).execute()
    except Exception as e:
        logger.error(f"Audit logging failed: {e}")


class GoodsServicesPostViewSet(OptimizedViewSetMixin, viewsets.ViewSet):
    """CRUD for Goods & Services posts. Only drivers/owners can create; everyone can view."""

    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer, BrowsableAPIRenderer]
    
    def get_permissions(self):
        return [AllowAny()]

    # Optimization configuration
    TABLE_NAME = 'goods_services_profiles'
    MODULE_NAME = 'goods_services_profile'
    DATE_FIELDS = ['created_at', 'updated_at']
    JSON_FIELDS = ['media']
    CACHE_TIMEOUT = 'medium'

    def list(self, request):
        """Public list of driver/owner bios with enhanced author info. Optional filters: author_id, author_role."""
        filters = {}
        author_id = request.GET.get('author_id') if hasattr(request, 'GET') else None
        author_role = request.GET.get('author_role') if hasattr(request, 'GET') else None
        if author_id:
            filters['author_id'] = author_id
        if author_role:
            filters['author_role'] = author_role
        
        # Get the basic list
        response = self.optimized_list(request, filters=filters, order_by='-created_at')
        
        # Enhance with author information
        if hasattr(response, 'data') and response.data.get('success'):
            posts = response.data.get('data', [])
            enhanced_posts = []
            
            for post in posts:
                # Fetch author details from auth system
                try:
                    from tartanilla_admin.supabase import supabase_admin
                    admin_client = supabase_admin if supabase_admin else supabase
                    auth_user = admin_client.auth.admin.get_user_by_id(post.get('author_id'))
                    if auth_user and auth_user.user:
                        metadata = auth_user.user.user_metadata or {}
                        post['author_name'] = metadata.get('name', post.get('author_name', ''))
                        post['author_email'] = auth_user.user.email or ''
                        post['author_phone'] = metadata.get('phone', '')
                        post['author_role'] = metadata.get('role', post.get('author_role', ''))
                        
                        # Add profile photo from multiple sources
                        profile_photo = (
                            metadata.get('profile_photo_url') or 
                            metadata.get('profile_photo') or 
                            metadata.get('avatar_url') or
                            auth_user.user.user_metadata.get('profile_photo_url') if auth_user.user.user_metadata else None
                        )
                        post['author_profile_photo_url'] = profile_photo
                        post['profile_photo_url'] = profile_photo  # Alternative field name
                        post['avatar_url'] = profile_photo  # Alternative field name
                        
                        # Add driver rating from reviews
                        if post.get('author_role') in ['driver', 'driver-owner']:
                            try:
                                reviews_resp = supabase.table('reviews').select('rating').eq('driver_id', post.get('author_id')).execute()
                                if hasattr(reviews_resp, 'data') and reviews_resp.data:
                                    ratings = [r['rating'] for r in reviews_resp.data if r.get('rating')]
                                    if ratings:
                                        post['author_rating'] = round(sum(ratings) / len(ratings), 1)
                                        post['author_review_count'] = len(ratings)
                                    else:
                                        post['author_rating'] = 0
                                        post['author_review_count'] = 0
                                else:
                                    post['author_rating'] = 0
                                    post['author_review_count'] = 0
                            except Exception:
                                post['author_rating'] = 0
                                post['author_review_count'] = 0
                except Exception:
                    # Keep original data if fetch fails
                    pass
                
                enhanced_posts.append(post)
            
            response.data['data'] = enhanced_posts
        
        return response

    def retrieve(self, request, pk=None):
        return self.optimized_retrieve(request, pk)

    def create(self, request):
        """Create or update a single bio per author. Requires author_id and description. Optional media array."""
        # Support both DRF and plain Django requests
        if hasattr(request, 'data'):
            data = request.data
        else:
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST.dict()

        author_id = data.get('author_id')
        description = data.get('description')

        if not author_id or not description:
            return APIResponseManager.error_response(
                'author_id and description are required', status.HTTP_400_BAD_REQUEST
            )

        # Get author from auth system first
        try:
            from tartanilla_admin.supabase import supabase_admin
            admin_client = supabase_admin if supabase_admin else supabase
            auth_user = admin_client.auth.admin.get_user_by_id(author_id)
            if not auth_user or not auth_user.user:
                return APIResponseManager.error_response('Author not found', status.HTTP_400_BAD_REQUEST)
            
            user_role = auth_user.user.user_metadata.get('role', 'tourist') if auth_user.user.user_metadata else 'tourist'
            user_name = auth_user.user.user_metadata.get('name', '') if auth_user.user.user_metadata else ''
            user_email = auth_user.user.email or ''
            
            if user_role not in ['driver', 'owner', 'driver-owner']:
                return APIResponseManager.error_response('Only drivers and owners can create posts', status.HTTP_403_FORBIDDEN)
            
            author = {
                'id': author_id,
                'role': user_role,
                'name': user_name,
                'email': user_email
            }
            
        except Exception as e:
            print(f"Error fetching author: {e}")
            return APIResponseManager.error_response('Author not found', status.HTTP_400_BAD_REQUEST)

        # Process media uploads if any
        media_items = []
        raw_media = data.get('media')
        if raw_media:
            try:
                if isinstance(raw_media, str):
                    raw_media = json.loads(raw_media)
            except (json.JSONDecodeError, TypeError):
                raw_media = []

            if isinstance(raw_media, list):
                for media in raw_media:
                    if not isinstance(media, dict):
                        continue
                    url = media.get('url') or media.get('data')
                    filename = media.get('filename') or f"media_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
                    if isinstance(url, str) and url.startswith('data:'):
                        try:
                            base64_data = url.split(',')[1]
                            file_bytes = base64.b64decode(base64_data)
                            upload_result = upload_goodsservices_media(file_bytes, filename, author_id, bucket='goods-storage')
                            if upload_result['success']:
                                media_type = 'video' if filename.lower().endswith(('.mp4', '.mov', '.avi', '.webm')) else 'image'
                                media_items.append({
                                    'url': upload_result['url'],
                                    'type': media_type
                                })
                        except Exception:
                            continue
                    elif isinstance(url, str) and not url.startswith('data:'):
                        media_items.append({
                            'url': url,
                            'type': media.get('type', 'image')
                        })

        post_data = {
            'author_id': author_id,
            'author_role': user_role,
            'description': description,
            'media': media_items,
            'is_active': True
        }

        # If a bio already exists for this author, update instead of creating a new row
        try:
            existing_resp = supabase.table(self.TABLE_NAME).select('id').eq('author_id', author_id).execute()
            existing_id = existing_resp.data[0]['id'] if hasattr(existing_resp, 'data') and existing_resp.data else None
        except Exception as e:
            print(f"Error checking existing profile: {e}")
            existing_id = None

        try:
            ip_address = request.META.get('REMOTE_ADDR') if hasattr(request, 'META') else None
            
            if existing_id:
                # Get old data for audit
                old_data = DatabaseManager.get_by_id(self.TABLE_NAME, existing_id)
                
                # Update existing record
                response = supabase.table(self.TABLE_NAME).update(post_data).eq('id', existing_id).execute()
                if hasattr(response, 'data') and response.data:
                    log_audit(
                        user_id=author_id,
                        username=user_name,
                        role=user_role,
                        action='UPDATE',
                        entity_name='goods_services_profile',
                        entity_id=existing_id,
                        old_data=old_data,
                        new_data=response.data[0],
                        ip_address=ip_address
                    )
                    return Response({
                        'success': True,
                        'data': response.data[0],
                        'message': 'Profile updated successfully'
                    })
            else:
                # Create new record
                response = supabase.table(self.TABLE_NAME).insert(post_data).execute()
                if hasattr(response, 'data') and response.data:
                    log_audit(
                        user_id=author_id,
                        username=user_name,
                        role=user_role,
                        action='CREATE',
                        entity_name='goods_services_profile',
                        entity_id=response.data[0]['id'],
                        new_data=response.data[0],
                        ip_address=ip_address
                    )
                    return Response({
                        'success': True,
                        'data': response.data[0],
                        'message': 'Profile created successfully'
                    }, status=status.HTTP_201_CREATED)
            
            return Response({
                'success': False,
                'error': 'Failed to save profile'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f"Error saving profile: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, pk=None):
        """Update an existing bio. Only the author (driver/owner) can update."""
        if hasattr(request, 'data'):
            data = request.data
        else:
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.POST.dict()

        if not pk:
            return APIResponseManager.error_response('Profile ID required', status.HTTP_400_BAD_REQUEST)

        # Fetch existing post
        existing = DatabaseManager.get_by_id(self.TABLE_NAME, pk)
        if not existing:
            return APIResponseManager.not_found_response('Profile')

        author_id = data.get('author_id')
        if not author_id or author_id != existing.get('author_id'):
            return APIResponseManager.error_response('Only the author can update this profile', status.HTTP_403_FORBIDDEN)

        # Verify role is still driver/owner
        author_resp = supabase.table('users').select('id, role').eq('id', author_id).execute()
        author = author_resp.data[0] if hasattr(author_resp, 'data') and author_resp.data else None
        if not author or author.get('role') not in ['driver', 'owner', 'driver-owner']:
            return APIResponseManager.error_response('Only drivers and owners can update profiles', status.HTTP_403_FORBIDDEN)

        update_fields = {}
        if 'description' in data:
            update_fields['description'] = data.get('description')
        if 'is_active' in data:
            update_fields['is_active'] = data.get('is_active')

        # Optional media replacement
        if 'media' in data:
            media_items = []
            raw_media = data.get('media')
            try:
                if isinstance(raw_media, str):
                    raw_media = json.loads(raw_media)
            except (json.JSONDecodeError, TypeError):
                raw_media = []

            if isinstance(raw_media, list):
                for media in raw_media:
                    if not isinstance(media, dict):
                        continue
                    url = media.get('url') or media.get('data')
                    filename = media.get('filename') or f"media_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"
                    if isinstance(url, str) and url.startswith('data:'):
                        try:
                            base64_data = url.split(',')[1]
                            file_bytes = base64.b64decode(base64_data)
                            upload_result = upload_goodsservices_media(file_bytes, filename, post_id=pk)
                            if upload_result['success']:
                                media_type = 'video' if filename.lower().endswith(('.mp4', '.mov', '.avi', '.webm')) else 'image'
                                media_items.append({
                                    'url': upload_result['url'],
                                    'storage_path': upload_result['path'],
                                    'filename': filename,
                                    'type': media_type,
                                    'caption': media.get('caption', ''),
                                    'uploaded_at': datetime.now().isoformat()
                                })
                        except Exception:
                            continue
                    elif isinstance(url, str) and not url.startswith('data:'):
                        media_items.append({
                            'url': url,
                            'storage_path': media.get('storage_path', ''),
                            'filename': filename,
                            'type': media.get('type', ''),
                            'caption': media.get('caption', ''),
                            'uploaded_at': media.get('uploaded_at', datetime.now().isoformat())
                        })
            update_fields['media'] = media_items

        # Get old data and perform update with audit logging
        old_data = existing
        result = self.optimized_update(request, pk, update_fields)
        
        if hasattr(result, 'data') and result.data.get('success'):
            ip_address = request.META.get('REMOTE_ADDR') if hasattr(request, 'META') else None
            log_audit(
                user_id=author_id,
                username=author.get('name', ''),
                role=author.get('role', ''),
                action='UPDATE',
                entity_name='goods_services_profile',
                entity_id=pk,
                old_data=old_data,
                new_data=result.data.get('data'),
                ip_address=ip_address
            )
        
        return result

    def destroy(self, request, pk=None):
        """Delete a bio profile. Only the author can delete."""
        if not pk:
            return APIResponseManager.error_response('Profile ID required', status.HTTP_400_BAD_REQUEST)

        # Support both DRF and plain Django requests
        if hasattr(request, 'data'):
            data = request.data
        else:
            try:
                data = json.loads(request.body) if request.body else {}
            except Exception:
                data = {}

        existing = DatabaseManager.get_by_id(self.TABLE_NAME, pk)
        if not existing:
            return APIResponseManager.not_found_response('Profile')

        author_id = data.get('author_id')
        if not author_id or author_id != existing.get('author_id'):
            return APIResponseManager.error_response('Only the author can delete this profile', status.HTTP_403_FORBIDDEN)

        # Verify author still has proper role
        author_resp = supabase.table('users').select('id, role').eq('id', author_id).execute()
        author = author_resp.data[0] if hasattr(author_resp, 'data') and author_resp.data else None
        if not author or author.get('role') not in ['driver', 'owner', 'driver-owner']:
            return APIResponseManager.error_response('Only drivers and owners can delete profiles', status.HTTP_403_FORBIDDEN)

        # Perform delete with audit logging
        result = self.optimized_destroy(request, pk)
        
        if hasattr(result, 'status_code') and result.status_code == 204:
            ip_address = request.META.get('REMOTE_ADDR') if hasattr(request, 'META') else None
            log_audit(
                user_id=author_id,
                username=author.get('name', ''),
                role=author.get('role', ''),
                action='DELETE',
                entity_name='goods_services_profile',
                entity_id=pk,
                old_data=existing,
                ip_address=ip_address
            )
        
        return result
