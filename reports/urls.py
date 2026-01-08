from django.urls import path
from . import views

urlpatterns = [
    path('', views.reports_list, name='reports_list'),
    path('view/<str:report_id>/', views.report_detail, name='report_detail'),
    path('api/pending-count/', views.reports_pending_count, name='reports_pending_count'),
]