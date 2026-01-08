from django.urls import path
# Namespace for URL reversing
app_name = 'accounts'
# from .views import LoginView, LogoutView
from . import views

urlpatterns = [
    path('', views.home, name='home'),

    #AUTHENTICATION
    path('login/', views.login_view, name='login_view'),
    path('logout/', views.logout_view, name='logout'),
    path('registration/', views.registration_view, name='registration_view'),
    path('driver-owner-application/', views.driver_owner_application_view, name='driver_owner_application'),
    path('pending-registration/', views.pendingRegistration, name='pendingRegistration'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),

    # DASHBOARD
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('api/dashboard-metrics', views.dashboard_metrics_api, name='dashboard_metrics_api'),
    path('api/driver-performance', views.driver_performance_api, name='driver_performance_api'),
    path('api/revenue-by-package', views.revenue_by_package_api, name='revenue_by_package_api'),
    path('api/revenue-trend', views.revenue_trend_api, name='revenue_trend_api'),
    path("api/revenue-by-package-monthly/", views.revenue_by_package_monthly_api, name="revenue_by_package_monthly_api"),
    path('api/package-ratings-pie', views.package_ratings_pie_api, name='package_ratings_pie_api'),
    path("api/active-drivers-count/", views.active_drivers_count_api, name="active_drivers_count_api"),


    #USERS
    path('listOfCustomers/', views.listOfCustomers, name='listOfCustomers'),
    path('listOfDrivers/', views.listOfDrivers, name='listOfDrivers'),
    path('listOfOwners/', views.listOfOwners, name='listOfOwners'),
    path('listOfTartanillas/', views.listOfTartanillas, name='listOfTartanillas'),
    path('owner/<str:owner_id>/tartanillas/', views.ownerTartanillas, name='ownerTartanillas'),
    path('test-404/', views.test_404, name='test_404'),
    
    
    # API endpoints for admin actions
    path('api/suspend-customer/', views.suspend_customer, name='suspend_customer'),
    path('api/unsuspend-customer/', views.unsuspend_customer, name='unsuspend_customer'),
    path('api/suspend-driver/', views.suspend_driver, name='suspend_driver'),
    path('api/unsuspend-driver/', views.unsuspend_driver, name='unsuspend_driver'),
    
    # Registration approval endpoints
    path('api/approve-registration/', views.approve_registration, name='approve_registration'),
    path('api/reject-registration/', views.reject_registration, name='reject_registration'),
    
    # Tartanilla Carriage API endpoints
    path('api/create-tartanilla-carriage/', views.create_tartanilla_carriage_api, name='create_tartanilla_carriage_api'),
    path('api/update-tartanilla-carriage/', views.update_tartanilla_carriage_api, name='update_tartanilla_carriage_api'),
    path('api/delete-tartanilla-carriage/', views.delete_tartanilla_carriage_api, name='delete_tartanilla_carriage_api'),
    path('api/get-tartanilla-carriage/', views.get_tartanilla_carriage_api, name='get_tartanilla_carriage_api'),
    path('api/get-available-drivers/', views.get_available_drivers_api, name='get_available_drivers_api'),
    path('api/get-tartanilla-owners/', views.get_tartanilla_owners_api, name='get_tartanilla_owners_api'),
    path('api/get-current-user/', views.get_current_user_api, name='get_current_user_api'),
    path('api/get-owner-tartanillas/', views.get_owner_tartanillas_api, name='get_owner_tartanillas_api'),
    path('api/suspend-owner/', views.suspend_owner, name='suspend_owner'),
    path('api/unsuspend-owner/', views.unsuspend_owner, name='unsuspend_owner'),
    
    # Driver and owner tartanillas endpoints
    path('api/driver-assigned-tartanillas/', views.driver_assigned_tartanillas, name='driver_assigned_tartanillas'),
    path('api/owner-assigned-tartanillas/', views.owner_assigned_tartanillas, name='owner_assigned_tartanillas'),
    
    # PDF Export
    path('export/users-pdf/', views.export_users_pdf_view, name='export_users_pdf'),
    path('export/tartanillas-pdf/', views.export_tartanillas_pdf_view, name='export_tartanillas_pdf'),
]