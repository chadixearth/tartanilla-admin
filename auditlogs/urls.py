from django.urls import path
from . import views

urlpatterns = [
    path('auditlogs/', views.auditlogs_view, name='auditlogs_view'),
]
