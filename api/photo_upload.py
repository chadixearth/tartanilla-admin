from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from tartanilla_admin.supabase import upload_profile_photo, upload_tourpackage_photo, upload_goods_storage, upload_tartanilla_media
from django.core.files.uploadedfile import InMemoryUploadedFile
import base64
import json

@api_view(['POST'])
@permission_classes([AllowAny])
def upload_profile_photo_api(request):
    """
    Upload a profile photo to Supabase storage
    
    Expected payload:
    {
        "photo": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
        "filename": "profile.jpg",
        "user_id": "optional_user_id"
    }
    """
    try:
        data = request.data
        files = request.FILES
        
        # Check if photo is uploaded as a file (React Native/mobile)
        if 'photo' in files:
            photo_file = files['photo']
            filename = data.get('filename', photo_file.name or 'profile_photo.jpg')
            user_id = data.get('user_id')
            
            # Read file content directly
            if isinstance(photo_file, InMemoryUploadedFile):
                file_content = photo_file.read()
            else:
                file_content = photo_file.read()
            
            # Upload to Supabase storage
            upload_result = upload_profile_photo(file_content, filename, user_id)
            
            if upload_result['success']:
                return Response({
                    'success': True,
                    'photo_url': upload_result['url'],  # For React Native compatibility
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
            filename = data.get('filename', 'profile_photo.jpg')
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
                upload_result = upload_profile_photo(file_content, filename, user_id)
                
                if upload_result['success']:
                    return Response({
                        'success': True,
                        'photo_url': upload_result['url'],  # For React Native compatibility
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

@api_view(['POST'])
@permission_classes([AllowAny])
def upload_tourpackage_photo_api(request):
    """
    Upload a tour package photo to Supabase storage
    
    Expected payload:
    {
        "photo": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
        "filename": "package_photo.jpg",
        "package_id": "optional_package_id"
    }
    """
    try:
        data = request.data
        files = request.FILES
        
        # Check if photo is uploaded as a file (React Native/mobile)
        if 'photo' in files:
            photo_file = files['photo']
            filename = data.get('filename', photo_file.name or 'package_photo.jpg')
            package_id = data.get('package_id')
            
            # Read file content directly
            if isinstance(photo_file, InMemoryUploadedFile):
                file_content = photo_file.read()
            else:
                file_content = photo_file.read()
            
            # Upload to Supabase storage
            upload_result = upload_tourpackage_photo(file_content, filename, package_id)
            
            if upload_result['success']:
                return Response({
                    'success': True,
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
            filename = data.get('filename', 'package_photo.jpg')
            package_id = data.get('package_id')
            
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
                upload_result = upload_tourpackage_photo(file_content, filename, package_id)
                
                if upload_result['success']:
                    return Response({
                        'success': True,
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

@api_view(['POST'])
@permission_classes([AllowAny])
def upload_multiple_photos_api(request):
    """
    Upload multiple photos at once
    
    Expected payload:
    {
        "photos": [
            {
                "photo": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
                "filename": "photo1.jpg"
            },
            {
                "photo": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
                "filename": "photo2.jpg"
            }
        ],
        "bucket_type": "tourpackage",  // or "profile"
        "entity_id": "optional_id"
    }
    """
    try:
        data = request.data
        
        # Validate required fields
        if not data.get('photos') or not isinstance(data['photos'], list):
            return Response({
                'success': False,
                'error': 'Photos array is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        bucket_type = data.get('bucket_type', 'tourpackage')
        entity_id = data.get('entity_id')
        
        if bucket_type not in ['tourpackage', 'profile']:
            return Response({
                'success': False,
                'error': 'Invalid bucket_type. Must be "tourpackage" or "profile"'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        uploaded_photos = []
        errors = []
        
        for i, photo_item in enumerate(data['photos']):
            if not isinstance(photo_item, dict) or not photo_item.get('photo'):
                errors.append(f'Photo {i+1}: Invalid photo data')
                continue
            
            photo_data = photo_item['photo']
            filename = photo_item.get('filename', f'photo_{i+1}.jpg')
            
            if not photo_data.startswith('data:image/'):
                errors.append(f'Photo {i+1}: Invalid photo format')
                continue
            
            try:
                # Extract base64 data
                base64_data = photo_data.split(',')[1]
                file_content = base64.b64decode(base64_data)
                
                # Upload based on bucket type
                if bucket_type == 'profile':
                    upload_result = upload_profile_photo(file_content, filename, entity_id)
                else:
                    upload_result = upload_tourpackage_photo(file_content, filename, entity_id)
                
                if upload_result['success']:
                    uploaded_photos.append({
                        'url': upload_result['url'],
                        'storage_path': upload_result['path'],
                        'filename': filename
                    })
                else:
                    errors.append(f'Photo {i+1}: {upload_result["error"]}')
                    
            except Exception as e:
                errors.append(f'Photo {i+1}: {str(e)}')
        
        return Response({
            'success': len(uploaded_photos) > 0,
            'data': {
                'uploaded_photos': uploaded_photos,
                'total_uploaded': len(uploaded_photos),
                'total_attempted': len(data['photos']),
                'errors': errors
            }
        })
        
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def upload_goods_storage_api(request):
    """
    Upload files to goods storage bucket
    
    Expected payload:
    {
        "file": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
        "filename": "inventory.jpg",
        "user_id": "optional_user_id",
        "category": "optional_category"
    }
    """
    try:
        data = request.data
        files = request.FILES
        
        # Handle file upload
        if 'file' in files:
            file_obj = files['file']
            filename = data.get('filename', file_obj.name or 'goods_file')
            user_id = data.get('user_id')
            category = data.get('category')
            
            file_content = file_obj.read()
            upload_result = upload_goods_storage(file_content, filename, user_id, category)
            
            if upload_result['success']:
                return Response({
                    'success': True,
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
        
        # Handle base64 data
        elif data.get('file'):
            file_data = data['file']
            filename = data.get('filename', 'goods_file')
            user_id = data.get('user_id')
            category = data.get('category')
            
            if isinstance(file_data, str) and file_data.startswith('data:'):
                try:
                    base64_data = file_data.split(',')[1]
                    file_content = base64.b64decode(base64_data)
                    
                    upload_result = upload_goods_storage(file_content, filename, user_id, category)
                    
                    if upload_result['success']:
                        return Response({
                            'success': True,
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
                        'error': f'Failed to process file: {str(e)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({
            'success': False,
            'error': 'File data is required'
        }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([AllowAny])
def upload_tartanilla_media_api(request):
    """
    Upload tartanilla documentation media
    
    Expected payload:
    {
        "file": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
        "filename": "registration.jpg",
        "tartanilla_id": "optional_tartanilla_id"
    }
    """
    try:
        data = request.data
        files = request.FILES
        
        # Handle file upload
        if 'file' in files:
            file_obj = files['file']
            filename = data.get('filename', file_obj.name or 'tartanilla_media')
            tartanilla_id = data.get('tartanilla_id')
            
            file_content = file_obj.read()
            upload_result = upload_tartanilla_media(file_content, filename, tartanilla_id)
            
            if upload_result['success']:
                return Response({
                    'success': True,
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
        
        # Handle base64 data
        elif data.get('file'):
            file_data = data['file']
            filename = data.get('filename', 'tartanilla_media')
            tartanilla_id = data.get('tartanilla_id')
            
            if isinstance(file_data, str) and file_data.startswith('data:'):
                try:
                    base64_data = file_data.split(',')[1]
                    file_content = base64.b64decode(base64_data)
                    
                    upload_result = upload_tartanilla_media(file_content, filename, tartanilla_id)
                    
                    if upload_result['success']:
                        return Response({
                            'success': True,
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
                        'error': f'Failed to process file: {str(e)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({
            'success': False,
            'error': 'File data is required'
        }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)