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
from api.health import quick_health 

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', quick_health, name='root_health'),
    path('', home, name='home'),
    path('accounts/', include(('accounts.urls', 'accounts'), namespace='accounts')),
    path('chat/', include('chat.urls')),
    path('chatsupport/', include('chatsupport.urls')),
    path('api/', include(('api.urls', 'api'), namespace='api')),
    path('routemanagement/', include('routemanagement.urls')),
    path('earningsAndshares/', include('earningsAndshares.urls')),
    path('auditlogs/', include('auditlogs.urls')),
    path('tartanillacarriages/', include('tartanillacarriages.urls')),
    path('tourpackage/', include('tourpackage.urls')),
    path('announcements/', include('announcements.urls')),
    path('reports/', include('reports.urls')),
]
