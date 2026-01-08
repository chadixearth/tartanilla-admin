import os
import uuid
import mimetypes
import time
import logging
import gc
from datetime import datetime
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()  # Loads variables from .env if present

# Configure logging
logger = logging.getLogger(__name__)

# Use standard environment variable names
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Optionally, you can also load the service role key if you need it for admin tasks
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")



# Connection health check function
def check_connection_health():
    """Check if Supabase connection is healthy"""
    try:
        response = execute_with_retry(lambda: supabase.table('users').select('id').limit(1).execute())
        return hasattr(response, 'data') and response.data is not None
    except Exception as e:
        logger.warning(f"Connection health check failed: {e}")
        return False

# Safe query wrapper
def safe_query(table_name, operation, *args, **kwargs):
    """Safely execute a query with automatic retry and fallback"""
    def query_func():
        table = supabase.table(table_name)
        if operation == 'select':
            return table.select(*args, **kwargs)
        elif operation == 'insert':
            return table.insert(*args, **kwargs)
        elif operation == 'update':
            return table.update(*args, **kwargs)
        elif operation == 'delete':
            return table.delete(*args, **kwargs)
        else:
            raise ValueError(f"Unsupported operation: {operation}")
    
    return execute_with_retry(query_func)

# Enhanced Supabase client configuration with connection pooling
try:
    # Use the service role key for backend operations to avoid JWT expiration
    # The service role key doesn't expire like user JWT tokens
    if SUPABASE_SERVICE_ROLE_KEY:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Initialized Supabase clients with service role key")
    else:
        # Fallback to anon key if service role not available
        supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        supabase_admin = None
        logger.warning("Using anon key - JWT expiration issues may occur")
except Exception as e:
    logger.error(f"Failed to initialize Supabase clients: {e}")
    # Create minimal fallback clients
    if SUPABASE_SERVICE_ROLE_KEY:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    else:
        supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        supabase_admin = None

def execute_with_retry(query_func, max_retries=3, delay=0.5):
    """Execute a Supabase query with enhanced retry logic for connection errors.
    Non-connection errors are re-raised immediately so callers see the real error (e.g., auth failures).
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return query_func()
        except Exception as e:
            error_str = str(e).lower()
            # Enhanced connection error detection including Windows-specific errors
            connection_errors = [
                'connectionterminated', 'remoteprotocolerror', 'connection reset', 
                'timeout', 'connection closed', 'winerror 10035', 'winerror 10054',
                'non-blocking socket operation', 'readerror', 'httpx.readerror', 
                'httpcore.readerror', 'connection aborted', 'broken pipe', 
                'network is unreachable', 'forcibly closed', 'existing connection',
                'connection pool', 'ssl error', 'certificate verify failed',
                'name resolution failed', 'temporary failure', 'service unavailable',
                'stream_id', 'http2', 'connectionerror'
            ]
            
            if any(keyword in error_str for keyword in connection_errors):
                last_error = e
                logger.warning(f"Connection error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    # Aggressive cleanup for Windows socket errors
                    if 'winerror 10054' in error_str or 'forcibly closed' in error_str:
                        # Force connection cleanup
                        try:
                            if hasattr(supabase, '_client') and hasattr(supabase._client, '_client'):
                                client = supabase._client._client
                                if hasattr(client, 'close'):
                                    client.close()
                        except:
                            pass
                        gc.collect()
                        sleep_time = delay * (2 ** attempt)  # Exponential backoff
                    else:
                        sleep_time = delay * (1.5 ** attempt) + (0.1 * attempt)
                    
                    logger.info(f"Retrying in {sleep_time:.1f} seconds...")
                    time.sleep(sleep_time)
                    continue
                else:
                    logger.error(f"Max retries ({max_retries}) exceeded for connection error: {e}")
                    raise Exception(f"Database connection error after {max_retries} retries: {e}")
            # Not a connection error: re-raise immediately
            raise
    # If somehow we exit the loop without returning, raise error
    if last_error:
        logger.error(f"All retries failed: {last_error}")
        raise Exception(f"Database connection error: {last_error}")
    raise Exception("Max retries exceeded")

# Storage utility functions
def upload_photo_to_storage(file_content, filename, bucket_name, folder=None):
    """
    Upload a photo to Supabase storage
    
    Args:
        file_content: File content (bytes)
        filename: Original filename
        bucket_name: Name of the storage bucket ('profile-photos' or 'tourpackage-photos')
        folder: Optional folder within the bucket
    
    Returns:
        dict: {'success': bool, 'url': str, 'path': str, 'error': str}
    """
    try:
        # Generate unique filename to avoid conflicts
        file_extension = os.path.splitext(filename)[1].lower()
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        
        # Create file path
        if folder:
            file_path = f"{folder}/{unique_filename}"
        else:
            file_path = unique_filename
        
        # Determine content type (images only helper)
        content_type, _ = mimetypes.guess_type(filename)
        if not content_type or not content_type.startswith('image/'):
            content_type = 'image/jpeg'  # Default fallback for image uploads
        
        # Use service role client for uploads to bypass RLS
        storage_client = supabase_admin if supabase_admin else supabase
        
        # Upload file to Supabase storage
        response = storage_client.storage.from_(bucket_name).upload(
            file_path,
            file_content,
            file_options={
                "content-type": content_type,
                "cache-control": "3600"
            }
        )
        
        # Handle different response formats
        success = False
        if hasattr(response, 'status_code'):
            success = response.status_code == 200 or response.status_code == 201
        elif hasattr(response, 'data') and response.data:
            success = True
        elif response and not hasattr(response, 'error'):
            success = True
        
        if success:
            # Get public URL using regular client (public URLs don't need admin privileges)
            public_url_response = supabase.storage.from_(bucket_name).get_public_url(file_path)
            
            return {
                'success': True,
                'url': public_url_response,
                'path': file_path,
                'error': None
            }
        else:
            error_msg = 'Upload failed'
            if hasattr(response, 'error') and response.error:
                error_msg = str(response.error)
            elif hasattr(response, 'status_code'):
                error_msg = f'Upload failed with status: {response.status_code}'
                
            return {
                'success': False,
                'url': None,
                'path': None,
                'error': error_msg
            }
            
    except Exception as e:
        return {
            'success': False,
            'url': None,
            'path': None,
            'error': str(e)
        }

def upload_media_to_storage(file_content, filename, bucket_name, folder=None):
    """
    Upload arbitrary media (image/video/other) to Supabase storage with sensible content-type.
    """
    try:
        file_extension = os.path.splitext(filename)[1].lower()
        unique_filename = f"{uuid.uuid4()}{file_extension}"

        # Create file path
        if folder:
            file_path = f"{folder}/{unique_filename}"
        else:
            file_path = unique_filename

        # Determine content type more generally
        content_type, _ = mimetypes.guess_type(filename)
        if not content_type:
            # Simple extension-based fallback
            if file_extension in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                content_type = 'image/jpeg'
            elif file_extension in ['.mp4', '.mov', '.avi', '.webm']:
                content_type = 'video/mp4'
            else:
                content_type = 'application/octet-stream'

        storage_client = supabase_admin if supabase_admin else supabase

        response = storage_client.storage.from_(bucket_name).upload(
            file_path,
            file_content,
            file_options={
                "content-type": content_type,
                "cache-control": "3600"
            }
        )

        success = False
        if hasattr(response, 'status_code'):
            success = response.status_code in (200, 201)
        elif hasattr(response, 'data') and response.data:
            success = True
        elif response and not hasattr(response, 'error'):
            success = True

        if success:
            public_url_response = supabase.storage.from_(bucket_name).get_public_url(file_path)
            return {
                'success': True,
                'url': public_url_response,
                'path': file_path,
                'error': None
            }
        else:
            error_msg = 'Upload failed'
            if hasattr(response, 'error') and response.error:
                error_msg = str(response.error)
            elif hasattr(response, 'status_code'):
                error_msg = f'Upload failed with status: {response.status_code}'

            return {
                'success': False,
                'url': None,
                'path': None,
                'error': error_msg
            }
    except Exception as e:
        return {
            'success': False,
            'url': None,
            'path': None,
            'error': str(e)
        }

def upload_profile_photo(file_content, filename, user_id=None):
    """
    Upload a profile photo to the profile-photos bucket
    
    Args:
        file_content: File content (bytes)
        filename: Original filename
        user_id: Optional user ID for organizing photos
    
    Returns:
        dict: Upload result
    """
    folder = f"user_{user_id}" if user_id else "general"
    return upload_photo_to_storage(file_content, filename, "profile-photos", folder)

def upload_tourpackage_photo(file_content, filename, package_id=None):
    """
    Upload a tour package photo to the tourpackage-photos bucket
    
    Args:
        file_content: File content (bytes)
        filename: Original filename
        package_id: Optional package ID for organizing photos
    
    Returns:
        dict: Upload result
    """
    folder = f"package_{package_id}" if package_id else "general"
    return upload_photo_to_storage(file_content, filename, "tourpackage-photos", folder)

def upload_booking_verification_photo(file_content, filename, booking_id, driver_id):
    """
    Upload a verification photo for booking completion
    
    Args:
        file_content: File content (bytes)
        filename: Original filename
        booking_id: The booking ID this verification is for
        driver_id: The driver ID uploading the verification
    
    Returns:
        dict: Upload result with URL and path
    """
    # Create a structured folder path for organization
    folder = f"bookings/{booking_id}/driver_{driver_id}"
    bucket_name = "booking-verifications"

    # Best-effort: ensure the bucket exists using the service role client
    try:
        if supabase_admin:
            try:
                # Check presence first to avoid noisy errors
                supabase_admin.storage.get_bucket(bucket_name)
            except Exception:
                # Create if missing
                supabase_admin.storage.create_bucket(bucket_name, {"public": True})
        else:
            logger.warning(
                "SUPABASE_SERVICE_ROLE_KEY not set; cannot programmatically ensure bucket '%s' exists.",
                bucket_name,
            )
    except Exception as ensure_err:
        # Log but do not fail the request here; we'll try upload and handle errors gracefully
        logger.warning("Could not ensure bucket '%s' exists: %s", bucket_name, ensure_err)

    # Try primary upload
    result = upload_photo_to_storage(file_content, filename, bucket_name, folder)
    if result.get("success"):
        return result

    # If it failed due to missing bucket, try once more to create with admin then retry upload
    error_text = str(result.get("error") or "").lower()
    if ("bucket" in error_text and "not found" in error_text) and supabase_admin:
        try:
            supabase_admin.storage.create_bucket(bucket_name, {"public": True})
            # Retry upload after creation
            retry_result = upload_photo_to_storage(file_content, filename, bucket_name, folder)
            if retry_result.get("success"):
                return retry_result
        except Exception as create_err:
            logger.error("Retry bucket creation failed for '%s': %s", bucket_name, create_err)

    # Final fallback: store under an existing general bucket to avoid blocking the flow
    fallback_folder = f"verification/booking_{booking_id}/driver_{driver_id}"
    fallback = upload_photo_to_storage(file_content, filename, "profile-photos", fallback_folder)
    return fallback

def upload_goodsservices_media(file_content, filename, post_id=None, bucket='goods-storage'):
    """
    Upload media for goods & services posts to a dedicated bucket.
    """
    folder = f"post_{post_id}" if post_id else "general"
    return upload_media_to_storage(file_content, filename, bucket, folder)

def upload_goods_storage(file_content, filename, user_id=None, category=None):
    """
    Upload files to goods storage bucket for inventory/product management.
    """
    folder_parts = []
    if user_id:
        folder_parts.append(f"user_{user_id}")
    if category:
        folder_parts.append(category)
    folder = "/".join(folder_parts) if folder_parts else "general"
    return upload_media_to_storage(file_content, filename, "goods-storage", folder)

def upload_tartanilla_media(file_content, filename, tartanilla_id=None):
    """
    Upload media for tartanilla documentation (registration, photos, etc.)
    """
    folder = f"tartanilla_{tartanilla_id}" if tartanilla_id else "general"
    return upload_media_to_storage(file_content, filename, "tartanilla-media", folder)

def delete_photo_from_storage(file_path, bucket_name):
    """
    Delete a photo from Supabase storage
    
    Args:
        file_path: Path to the file in storage
        bucket_name: Name of the storage bucket
    
    Returns:
        dict: {'success': bool, 'error': str}
    """
    try:
        response = supabase.storage.from_(bucket_name).remove([file_path])
        
        return {
            'success': True,
            'error': None
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

# --- Direct psycopg2 connection for standalone scripts only ---
def test_db_connection():
    import psycopg2
    USER = os.getenv("DB_USER")
    PASSWORD = os.getenv("DB_PASSWORD")
    HOST = os.getenv("DB_HOST")
    PORT = os.getenv("DB_PORT")
    DBNAME = os.getenv("DB_NAME")
    try:
        connection = psycopg2.connect(
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT,
            dbname=DBNAME
        )
        print("Connection successful!")
        cursor = connection.cursor()
        cursor.execute("SELECT NOW();")
        result = cursor.fetchone()
        print("Current Time:", result)
        cursor.close()
        connection.close()
        print("Connection closed.")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test_db_connection()