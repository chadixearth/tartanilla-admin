/**
 * Photo Upload Utility for Supabase Storage Integration
 * Handles uploading photos to profile-photos and tourpackage-photos buckets
 */

class PhotoUploadManager {
    constructor() {
        this.apiBaseUrl = '/api';
        this.maxFileSize = 5 * 1024 * 1024; // 5MB
        this.allowedTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
    }

    /**
     * Validate a file before upload
     * @param {File} file - The file to validate
     * @returns {Object} - Validation result
     */
    validateFile(file) {
        const errors = [];

        if (!file) {
            errors.push('No file selected');
        } else {
            if (file.size > this.maxFileSize) {
                errors.push(`File size must be less than ${this.maxFileSize / (1024 * 1024)}MB`);
            }

            if (!this.allowedTypes.includes(file.type)) {
                errors.push('File type not supported. Please use JPEG, PNG, WebP, or GIF.');
            }
        }

        return {
            isValid: errors.length === 0,
            errors: errors
        };
    }

    /**
     * Convert file to base64
     * @param {File} file - The file to convert
     * @returns {Promise<string>} - Base64 string
     */
    fileToBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = error => reject(error);
            reader.readAsDataURL(file);
        });
    }

    /**
     * Upload a profile photo
     * @param {File} file - The image file
     * @param {string} userId - Optional user ID
     * @returns {Promise<Object>} - Upload result
     */
    async uploadProfilePhoto(file, userId = null) {
        const validation = this.validateFile(file);
        if (!validation.isValid) {
            return {
                success: false,
                error: validation.errors.join(', ')
            };
        }

        try {
            const base64Data = await this.fileToBase64(file);
            
            const response = await fetch(`${this.apiBaseUrl}/upload/profile-photo/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    photo: base64Data,
                    filename: file.name,
                    user_id: userId
                })
            });

            const result = await response.json();
            return result;
        } catch (error) {
            return {
                success: false,
                error: `Upload failed: ${error.message}`
            };
        }
    }

    /**
     * Upload a tour package photo
     * @param {File} file - The image file
     * @param {string} packageId - Optional package ID
     * @returns {Promise<Object>} - Upload result
     */
    async uploadTourPackagePhoto(file, packageId = null) {
        const validation = this.validateFile(file);
        if (!validation.isValid) {
            return {
                success: false,
                error: validation.errors.join(', ')
            };
        }

        try {
            const base64Data = await this.fileToBase64(file);
            
            const response = await fetch(`${this.apiBaseUrl}/upload/tourpackage-photo/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    photo: base64Data,
                    filename: file.name,
                    package_id: packageId
                })
            });

            const result = await response.json();
            return result;
        } catch (error) {
            return {
                success: false,
                error: `Upload failed: ${error.message}`
            };
        }
    }

    /**
     * Upload multiple photos at once
     * @param {FileList} files - The files to upload
     * @param {string} bucketType - 'profile' or 'tourpackage'
     * @param {string} entityId - Optional entity ID
     * @param {Function} progressCallback - Progress callback function
     * @returns {Promise<Object>} - Upload result
     */
    async uploadMultiplePhotos(files, bucketType = 'tourpackage', entityId = null, progressCallback = null) {
        const photos = [];
        const errors = [];

        // Validate all files first
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const validation = this.validateFile(file);
            
            if (!validation.isValid) {
                errors.push(`File ${i + 1} (${file.name}): ${validation.errors.join(', ')}`);
                continue;
            }

            try {
                const base64Data = await this.fileToBase64(file);
                photos.push({
                    photo: base64Data,
                    filename: file.name
                });

                if (progressCallback) {
                    progressCallback({
                        processed: photos.length + errors.length,
                        total: files.length,
                        currentFile: file.name
                    });
                }
            } catch (error) {
                errors.push(`File ${i + 1} (${file.name}): Failed to process - ${error.message}`);
            }
        }

        if (photos.length === 0) {
            return {
                success: false,
                error: 'No valid photos to upload',
                errors: errors
            };
        }

        try {
            const response = await fetch(`${this.apiBaseUrl}/upload/multiple-photos/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    photos: photos,
                    bucket_type: bucketType,
                    entity_id: entityId
                })
            });

            const result = await response.json();
            
            // Merge local validation errors with server errors
            if (result.data && result.data.errors) {
                result.data.errors = [...errors, ...result.data.errors];
            }

            return result;
        } catch (error) {
            return {
                success: false,
                error: `Upload failed: ${error.message}`,
                errors: errors
            };
        }
    }

    /**
     * Get CSRF token for Django
     * @returns {string} - CSRF token
     */
    getCSRFToken() {
        const token = document.querySelector('[name=csrfmiddlewaretoken]');
        return token ? token.value : '';
    }

    /**
     * Create a preview element for an uploaded image
     * @param {string} imageUrl - The image URL
     * @param {string} filename - The filename
     * @param {Function} onRemove - Remove callback
     * @returns {HTMLElement} - Preview element
     */
    createImagePreview(imageUrl, filename, onRemove = null) {
        const previewDiv = document.createElement('div');
        previewDiv.className = 'photo-item';
        previewDiv.innerHTML = `
            <img src="${imageUrl}" alt="${filename}" />
            ${onRemove ? '<button type="button" class="photo-remove" title="Remove photo">×</button>' : ''}
        `;

        if (onRemove) {
            const removeBtn = previewDiv.querySelector('.photo-remove');
            removeBtn.addEventListener('click', onRemove);
        }

        return previewDiv;
    }

    /**
     * Show upload progress
     * @param {HTMLElement} container - Container element
     * @param {Object} progress - Progress object
     */
    showUploadProgress(container, progress) {
        let progressDiv = container.querySelector('.upload-progress');
        if (!progressDiv) {
            progressDiv = document.createElement('div');
            progressDiv.className = 'upload-progress';
            container.appendChild(progressDiv);
        }

        const percentage = Math.round((progress.processed / progress.total) * 100);
        progressDiv.innerHTML = `
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${percentage}%"></div>
            </div>
            <div class="progress-text">
                Uploading ${progress.currentFile} (${progress.processed}/${progress.total})
            </div>
        `;
    }

    /**
     * Hide upload progress
     * @param {HTMLElement} container - Container element
     */
    hideUploadProgress(container) {
        const progressDiv = container.querySelector('.upload-progress');
        if (progressDiv) {
            progressDiv.remove();
        }
    }

    /**
     * Show error message
     * @param {HTMLElement} container - Container element
     * @param {string} message - Error message
     */
    showError(container, message) {
        let errorDiv = container.querySelector('.upload-error');
        if (!errorDiv) {
            errorDiv = document.createElement('div');
            errorDiv.className = 'upload-error';
            container.appendChild(errorDiv);
        }

        errorDiv.textContent = message;
        errorDiv.style.display = 'block';

        // Auto-hide after 5 seconds
        setTimeout(() => {
            errorDiv.style.display = 'none';
        }, 5000);
    }
}

// Create global instance
window.photoUploadManager = new PhotoUploadManager();

// CSS styles for upload components (inject if not already present)
if (!document.querySelector('#photo-upload-styles')) {
    const styles = document.createElement('style');
    styles.id = 'photo-upload-styles';
    styles.textContent = `
        .upload-progress {
            margin: 10px 0;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 4px;
        }

        .progress-bar {
            width: 100%;
            height: 20px;
            background: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            background: #531B24;
            transition: width 0.3s ease;
        }

        .progress-text {
            margin-top: 5px;
            font-size: 12px;
            color: #6c757d;
        }

        .upload-error {
            margin: 10px 0;
            padding: 10px;
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
            border-radius: 4px;
            display: none;
        }

        .photo-remove {
            position: absolute;
            top: 5px;
            right: 5px;
            width: 20px;
            height: 20px;
            background: rgba(0, 0, 0, 0.7);
            color: white;
            border: none;
            border-radius: 50%;
            cursor: pointer;
            font-size: 14px;
            line-height: 1;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .photo-remove:hover {
            background: rgba(0, 0, 0, 0.9);
        }
    `;
    document.head.appendChild(styles);
}
