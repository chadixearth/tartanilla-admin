from django.urls import path
from . import views, raw_api

app_name = 'tourpackage'

urlpatterns = [
    # Page routes (render HTML templates)
    path('create/', views.create_package_page, name='create_package'),
    path('create-steps/', views.create_package_steps, name='create_package_steps'),
    path('view/', views.view_packages, name='view'),
    path('edit/<uuid:package_id>/', views.edit_package, name='edit_package'),
    
    path('viewbookings/', views.view_bookings, name='view_bookings'),
    path('viewtourpackage/', views.view_booking_detail, name='view_booking_detail'),
    path('update-booking-status/', views.update_booking_status, name='update_booking_status'),
    path('admin-approve-booking/', views.admin_approve_booking, name='admin_approve_booking'),
    
    # Raw API endpoint to bypass middleware
    path('raw_toggle/<uuid:package_id>/', raw_api.raw_toggle_status, name='raw_toggle_status'),
]   