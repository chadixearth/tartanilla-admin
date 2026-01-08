"""
URL configuration for tartanilla_admin project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from accounts.views import home
from admin_views import admin_applications_view, admin_dashboard_view
from api.health import quick_health 


urlpatterns = [
    path('admin/', admin.site.urls),  # Enable Django admin
    path('health/', quick_health, name='root_health'),  # Root health check
    path('', home, name='home'),  # This makes the home page accessible at /
    # Use a namespace for accounts to ensure consistent URL reversing
    path('accounts/', include(('accounts.urls', 'accounts'), namespace='accounts')),  # For login/logout
    path('chat/', include('chat.urls')),  # Add this
    path('chatsupport/', include('chatsupport.urls')),
    # Namespace API to prevent URL name collisions with web views
    path('api/', include(('api.urls', 'api'), namespace='api')),  # DRF API endpoints - MUST come before tourpackage
    path('routemanagement/', include('routemanagement.urls')),  # DRF API endpoints
    path('earningsAndshares/', include('earningsAndshares.urls')),  # DRF API endpoints
    path('auditlogs/', include('auditlogs.urls')),  # DRF API endpoints
    path('tartanillacarriages/', include('tartanillacarriages.urls')),  # Tartanilla carriages endpoints
    path('tourpackage/', include('tourpackage.urls')),  # Web page endpoints - MUST come after API
    path('announcements/', include('announcements.urls')),
    path('reports/', include('reports.urls')),  # Announcements
    
    # Admin interface views
    path('admin-panel/applications/', admin_applications_view, name='admin_applications'),
    path('admin-panel/dashboard/', admin_dashboard_view, name='admin_dashboard'),
]
