from django.urls import path
# from .views import LoginView, LogoutView
from . import views

urlpatterns = [
    path("login/", views.login_view, name="login_view"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path('logout/', views.logout_view, name='logout'),
    path("driver-profile/", views.driver_profile_view, name="driver_profile"),
    path("list-of-customers/", views.listOfCustomers, name="listOfCustomers"),
    path("list-of-owners/", views.listOfOwners, name="listOfOwners"),
    path('pending-registration/', views.pendingRegistration, name='pendingRegistration'),
    path('registration/', views.registration_view, name='registration'),
    path('test-404/', views.test_404, name='test_404'),
]