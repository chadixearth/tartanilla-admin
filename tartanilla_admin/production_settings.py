import os
import dj_database_url
from .settings import *

# Production settings
DEBUG = False
SECRET_KEY = os.environ.get('SECRET_KEY')

# Allowed hosts for production
ALLOWED_HOSTS = [
    'tartanilla-admin.onrender.com',
    '.onrender.com',
    'localhost',
    '127.0.0.1'
]

# Database configuration for production (using dummy backend)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.dummy'
    }
}

# Static files configuration for production
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [BASE_DIR / 'static']

# Security settings for production
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# CORS settings for production
CORS_ALLOWED_ORIGINS = [
    "https://tartanilla-admin.onrender.com",
]

CORS_ALLOW_CREDENTIALS = True

# Update CSRF trusted origins
CSRF_TRUSTED_ORIGINS = [
    "https://tartanilla-admin.onrender.com",
]

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}