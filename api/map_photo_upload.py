from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from tartanilla_admin.supabase import supabase
from django.core.files.uploadedfile import InMemoryUploadedFile
import base64
import json
import uuid
import logging

logger = logging.getLogger(__name__)

@api_view(['POST'])
@permission_classes([AllowAny])
def upload_map_point_photo_api(request):
    """
    Upload a photo for a map point to Supabase storage
    
    Expected payload:
    {
        "photo": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
        "filename": "map_point_photo.jpg",
        "point_id": "optional_point_id",
        "user_id": "optional_user_id"
    }
    """
    try:
        data = request.data
        files = request.FILES
        
        # Check if photo is uploaded as a file (React Native/mobile)
        if 'photo' in files:
            photo_file = files['photo']
            filename = data.get('filename', photo_file.name or 'map_point_photo.jpg')
            point_id = data.get('point_id')
            user_id = data.get('user_id')
            
            # Read file content directly
            if isinstance(photo_file, InMemoryUploadedFile):
                file_content = photo_file.read()
            else:
                file_content = photo_file.read()
            
            # Upload to Supabase storage
            upload_result = upload_map_point_photo(file_content, filename, point_id, user_id)
            
            if upload_result['success']:
                return Response({
                    'success': True,
                    'photo_url': upload_result['url'],
                    'data': {
                        'url': upload_result['url'],
                        'storage_path': upload_result['path'],
                        'filename': filename
                    }
                })
            else:
                return Response({
                    'success': False,
                    'error': upload_result['error']
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Check if photo is sent as base64 data (web/JSON)
        elif data.get('photo'):
            photo_data = data['photo']
            filename = data.get('filename', 'map_point_photo.jpg')
            point_id = data.get('point_id')
            user_id = data.get('user_id')
            
            # Check if it's base64 encoded
            if not isinstance(photo_data, str) or not photo_data.startswith('data:image/'):
                return Response({
                    'success': False,
                    'error': 'Invalid photo format. Expected base64 encoded image.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                # Extract base64 data
                base64_data = photo_data.split(',')[1]
                file_content = base64.b64decode(base64_data)
                
                # Upload to Supabase storage
                upload_result = upload_map_point_photo(file_content, filename, point_id, user_id)
                
                if upload_result['success']:
                    return Response({
                        'success': True,
                        'photo_url': upload_result['url'],
                        'data': {
                            'url': upload_result['url'],
                            'storage_path': upload_result['path'],
                            'filename': filename
                        }
                    })
                else:
                    return Response({
                        'success': False,
                        'error': upload_result['error']
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    
            except Exception as e:
                return Response({
                    'success': False,
                    'error': f'Failed to process base64 image: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        else:
            return Response({
                'success': False,
                'error': 'Photo data is required (either as file upload or base64 data)'
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def upload_map_point_photo(file_content, filename, point_id=None, user_id=None):
    """
    Upload map point photo to Supabase storage
    """
    try:
        # Generate unique filename
        file_extension = filename.split('.')[-1] if '.' in filename else 'jpg'
        unique_filename = f"{user_id or 'anonymous'}_{int(uuid.uuid4().int % 1000000000)}_{filename}"
        
        # Upload to stoppoints_photos bucket (same as existing photos)
        storage_path = f"stoppoints_photos/{unique_filename}"
        
        # Upload file to Supabase storage
        upload_response = supabase.storage.from_("stoppoints_photos").upload(
            path=unique_filename,
            file=file_content,
            file_options={"content-type": f"image/{file_extension}"}
        )
        
        if hasattr(upload_response, 'error') and upload_response.error:
            logger.error(f"Storage upload error: {upload_response.error}")
            return {
                'success': False,
                'error': f'Storage upload failed: {upload_response.error}'
            }
        
        # Get public URL
        public_url_response = supabase.storage.from_("stoppoints_photos").get_public_url(unique_filename)
        
        if hasattr(public_url_response, 'error') and public_url_response.error:
            logger.error(f"Public URL error: {public_url_response.error}")
            return {
                'success': False,
                'error': f'Failed to get public URL: {public_url_response.error}'
            }
        
        public_url = public_url_response if isinstance(public_url_response, str) else public_url_response.get('publicURL', '')
        
        # If point_id is provided, update the map point with the image URL
        if point_id:
            try:
                # Get existing point to check current image_url
                existing_response = supabase.table('map_points').select('image_url').eq('id', point_id).execute()
                
                if hasattr(existing_response, 'data') and existing_response.data:
                    # Update the point with the new image URL
                    update_response = supabase.table('map_points').update({
                        'image_url': public_url
                    }).eq('id', point_id).execute()
                    
                    if hasattr(update_response, 'error') and update_response.error:
                        logger.warning(f"Failed to update map point {point_id} with image URL: {update_response.error}")
            except Exception as e:
                logger.warning(f"Failed to update map point {point_id}: {e}")
        
        return {
            'success': True,
            'url': public_url,
            'path': storage_path
        }
        
    except Exception as e:
        logger.error(f"Error uploading map point photo: {e}")
        return {
            'success': False,
            'error': str(e)
        }

@api_view(['POST'])
@permission_classes([AllowAny])
def update_map_point_image_api(request, point_id):
    """
    Update a map point's image URL
    
    Expected payload:
    {
        "image_url": "https://example.com/image.jpg"
    }
    """
    try:
        data = request.data
        image_url = data.get('image_url')
        
        if not image_url:
            return Response({
                'success': False,
                'error': 'image_url is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update the map point
        response = supabase.table('map_points').update({
            'image_url': image_url
        }).eq('id', point_id).execute()
        
        if hasattr(response, 'data') and response.data:
            return Response({
                'success': True,
                'data': response.data[0],
                'message': 'Map point image updated successfully'
            })
        else:
            return Response({
                'success': False,
                'error': 'Map point not found'
            }, status=status.HTTP_404_NOT_FOUND)
            
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)