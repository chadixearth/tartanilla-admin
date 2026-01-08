from rest_framework.routers import DefaultRouter
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from . import tourpackage
from . import map
from . import booking
from . import ride_hailing
from . import tartanilla
from . import earnings
from . import reviews
from . import authentication
from . import pending_registrations
from . import photo_upload
from . import custompackagerequest
from . import goods_services_post
from . import auditlogs
from . import analytics
from . import account_deletion
from . import payment
from . import user_management
from . import refunds

from . import notifications_fix as notifications
from . import sync_user
from . import realtime_notifications
from . import location
from . import user_list
from . import payment_completion
from . import debug_booking
from . import reports
from . import goods_services_reports
from . import driver_schedule
from . import map_photo_upload
from . import breakeven
from . import driver_carriage_helper
from . import quick_carriage_assign
from . import test_eligibility
from . import health_check
from . import health
from . import routing
from . import breakeven_notifications
from . import csrf_token
from . import security_test
from . import admin_approval
from . import verification
from . import test_endpoint
from . import role_switch
from . import device_verification
from . import reports_goods_services

# Debug endpoint to test routing
class DebugView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        return Response({
            'message': 'This is the API debug endpoint',
            'path': request.path,
            'method': request.method,
            'headers': dict(request.headers)
        })

# Simple test endpoint for JSON parsing
class SimpleTestView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        return Response({'ok': 1})

# Ultra minimal test
class TinyTestView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        from django.http import JsonResponse
        return JsonResponse({'a': 1})

# Example ViewSet
class StatusViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=['get'])
    def ping(self, request):
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)

router = DefaultRouter()
router.register(r'status', StatusViewSet, basename='status')
router.register(r'tourpackage', tourpackage.TourPackageViewSet, basename='tourpackage')
router.register(r'tour-booking', booking.TourBookingViewSet, basename='tour-booking')
router.register(r'ride-hailing', ride_hailing.RideHailingViewSet, basename='ride-hailing')
router.register(r'tartanilla-carriages', tartanilla.TartanillaCarriageViewSet, basename='tartanilla-carriages')
router.register(r'earnings', earnings.EarningsViewSet, basename='earnings')
router.register(r'refunds', refunds.RefundsViewSet, basename='refunds')
router.register(r'reviews', reviews.ReviewViewSet, basename='reviews')
router.register(r'auditlogs', auditlogs.AuditLogsViewSet, basename='auditlogs')
router.register(r'breakeven', breakeven.BreakevenViewSet, basename='breakeven')
router.register(r'custom-tour-requests', custompackagerequest.CustomTourRequestViewSet, basename='custom-tour-requests')
router.register(r'special-event-requests', custompackagerequest.SpecialEventRequestViewSet, basename='special-event-requests')
router.register(r'goods-services-profiles', goods_services_post.GoodsServicesPostViewSet, basename='goods-services-profiles')
# Backward-compatible alias (older clients may call /goods-services-posts/)
router.register(r'goods-services-posts', goods_services_post.GoodsServicesPostViewSet, basename='goods-services-posts')
router.register(r'analytics', analytics.AnalyticsViewSet, basename='analytics')
router.register(r'payments', payment.PaymentViewSet, basename='payments')
router.register(r'reports', reports.ReportsViewSet, basename='reports')
router.register(r'goods-services-reports', goods_services_reports.GoodsServicesReportViewSet, basename='goods-services-reports')
router.register(r'driver-schedule', driver_schedule.DriverScheduleViewSet, basename='driver-schedule')
router.register(r'driver-carriage-helper', driver_carriage_helper.DriverCarriageHelperViewSet, basename='driver-carriage-helper')
router.register(r'quick-carriage-assign', quick_carriage_assign.QuickCarriageAssignViewSet, basename='quick-carriage-assign')
router.register(r'test-eligibility', test_eligibility.TestEligibilityViewSet, basename='test-eligibility')
router.register(r'health-check', health_check.HealthCheckViewSet, basename='health-check')


urlpatterns = [
    path('', include(router.urls)),
    path('debug/', DebugView.as_view(), name='debug'),
    path('test/simple/', SimpleTestView.as_view(), name='simple_test'),
    path('test/tiny/', TinyTestView.as_view(), name='tiny_test'),
    
    # Health check endpoints
    path('health/', health.health_check, name='health_check'),
    path('ping/', health.ping, name='ping'),
    path('quick/', health.quick_health, name='quick_health'),

    
    # Authentication endpoints
    path('auth/register/', authentication.RegisterAPI.as_view(), name='register'),
    path('register/', authentication.RegisterAPI.as_view(), name='register_alt'),  # Alternative path
    path('test/register/', test_endpoint.TestRegistrationAPI.as_view(), name='test_register'),
    path('auth/login/', authentication.LoginAPI.as_view(), name='login'),
    path('auth/admin-login/', authentication.AdminLoginAPI.as_view(), name='admin_login'),
    path('auth/logout/', authentication.LogoutAPI.as_view(), name='logout'),
    path('auth/refresh/', authentication.RefreshTokenAPI.as_view(), name='refresh_token'),
    path('auth/verify-token/', authentication.VerifyTokenAPI.as_view(), name='verify_token'),
    path('auth/profile/', authentication.UserProfileAPI.as_view(), name='user_profile'),
    path('auth/user/<str:user_id>/', authentication.UserProfileAPI.as_view(), name='user_profile_by_id'),
    path('auth/profile/update/', authentication.UpdateProfileAPI.as_view(), name='update_profile'),
    path('auth/profile/photo/', authentication.UploadProfilePhotoAPI.as_view(), name='upload_photo'),
    path('auth/change-password/', authentication.ChangePasswordAPI.as_view(), name='change_password'),
    path('auth/resend-confirmation/', authentication.ResendConfirmationAPI.as_view(), name='resend_confirmation'),
    path('auth/forgot-password/', authentication.ForgotPasswordAPI.as_view(), name='forgot_password'),
    path('auth/verify-reset-code/', authentication.VerifyResetCodeAPI.as_view(), name='verify_reset_code'),
    path('auth/reset-password-confirm/', authentication.ResetPasswordConfirmAPI.as_view(), name='reset_password_confirm'),
    
    # Verification endpoints
    path('auth/send-verification/', verification.SendVerificationCodeAPI.as_view(), name='send_verification'),
    path('auth/verify-code/', verification.VerifyCodeAPI.as_view(), name='verify_code'),
    path('auth/resend-verification/', verification.ResendVerificationCodeAPI.as_view(), name='resend_verification'),
    
    # Pending registration endpoints
    path('auth/pending/', pending_registrations.PendingRegistrationsAPI.as_view(), name='pending_registrations'),
    path('auth/pending/approve/', pending_registrations.ApproveRegistrationAPI.as_view(), name='approve_registration'),
    path('auth/pending/reject/', pending_registrations.RejectRegistrationAPI.as_view(), name='reject_registration'),
    
    # Admin approval system endpoints
    path('admin/applications/', admin_approval.PendingApplicationsAPI.as_view(), name='pending_applications'),
    path('admin/applications/approve/', admin_approval.ApproveApplicationAPI.as_view(), name='approve_application'),
    path('admin/applications/reject/', admin_approval.RejectApplicationAPI.as_view(), name='reject_application'),
    path('admin/applications/resend-credentials/', admin_approval.ResendCredentialsAPI.as_view(), name='resend_credentials'),
    
    # Account deletion endpoints
    path('auth/request-deletion/', account_deletion.RequestAccountDeletionAPI.as_view(), name='request_account_deletion'),
    path('auth/cancel-deletion/', account_deletion.CancelAccountDeletionAPI.as_view(), name='cancel_account_deletion'),
    path('auth/cancel-deletion-and-login/', account_deletion.CancelDeletionAndLoginAPI.as_view(), name='cancel_deletion_and_login'),
    path('auth/deletion-status/', account_deletion.UserDeletionStatusAPI.as_view(), name='user_deletion_status'),
    path('auth/deletion-requests/', account_deletion.AccountDeletionRequestsAPI.as_view(), name='account_deletion_requests'),
    path('auth/process-scheduled-deletions/', account_deletion.ProcessScheduledDeletionsAPI.as_view(), name='process_scheduled_deletions'),
    

    
    # Suspension check endpoint (enhanced)
    path('auth/check-suspension/', authentication.CheckSuspensionAPI.as_view(), name='check_suspension'),
    
    # User management endpoints
    path('admin/users/suspend/', user_management.SuspendUserAPI.as_view(), name='suspend_user'),
    path('admin/users/unsuspend/', user_management.UnsuspendUserAPI.as_view(), name='unsuspend_user'),
    path('admin/users/suspension-status/', user_management.UserSuspensionStatusAPI.as_view(), name='user_suspension_status'),
    path('admin/users/suspended/', user_management.ListSuspendedUsersAPI.as_view(), name='list_suspended_users'),
    
    # Role switch endpoints
    path('auth/switch-role/', role_switch.SwitchRoleAPI.as_view(), name='switch_role'),
    path('auth/available-roles/', role_switch.GetAvailableRolesAPI.as_view(), name='get_available_roles'),
    
    # Device verification endpoints
    path('auth/check-device/', device_verification.CheckDeviceAPI.as_view(), name='check_device'),
    path('auth/verify-device/', device_verification.VerifyDeviceCodeAPI.as_view(), name='verify_device'),
    
    # User list endpoint for notifications
    path('auth/users/', user_list.UserListAPI.as_view(), name='user_list'),
    
    # Debug endpoints for development
    path('debug/create-test-users/', user_list.CreateTestUsersAPI.as_view(), name='create_test_users'),
    path('debug/users/', user_list.DebugUsersAPI.as_view(), name='debug_users'),
    
    # Map endpoints
    path('map/data/', map.get_map_data, name='get_map_data'),
    path('map/terminals/', map.get_terminals, name='get_terminals'),
    path('map/stops/', map.get_stops, name='get_stops'),
    path('map/dropoff-points/', map.get_dropoff_points, name='get_dropoff_points'),
    path('map/points/', map.add_map_point, name='add_map_point'),
    path('map/points/<str:point_id>/', map.update_map_point, name='update_map_point'),
    path('map/points/<str:point_id>/delete/', map.delete_map_point, name='delete_map_point'),
    path('map/roads/', map.add_road_highlight, name='add_road_highlight'),
    path('map/road-highlights/', map.get_road_highlights, name='get_road_highlights'),
    path('map/routes/', map.get_routes, name='get_routes'),
    
    # Photo upload endpoints
    path('upload/profile-photo/', photo_upload.upload_profile_photo_api, name='upload_profile_photo_api'),
    path('upload/tourpackage-photo/', photo_upload.upload_tourpackage_photo_api, name='upload_tourpackage_photo_api'),
    path('upload/multiple-photos/', photo_upload.upload_multiple_photos_api, name='upload_multiple_photos_api'),
    path('upload/goods-storage/', photo_upload.upload_goods_storage_api, name='upload_goods_storage_api'),
    path('upload/tartanilla-media/', photo_upload.upload_tartanilla_media_api, name='upload_tartanilla_media_api'),
    path('upload/map-point-photo/', map_photo_upload.upload_map_point_photo_api, name='upload_map_point_photo_api'),
    path('map/points/<str:point_id>/image/', map_photo_upload.update_map_point_image_api, name='update_map_point_image_api'),
    
    # Custom package request endpoints are now handled by the router ViewSets:
    # /api/custom-tour-requests/ and /api/special-event-requests/
    
    # Notification endpoints
    path('notifications/', notifications.NotificationAPI.as_view(), name='notifications'),
    path('notifications/mark-read/', notifications.MarkReadAPI.as_view(), name='mark_notification_read'),
    path('notifications/store-token/', notifications.StorePushTokenAPI.as_view(), name='store_push_token'),
    path('notifications/stream/', realtime_notifications.NotificationStreamAPI.as_view(), name='notification_stream'),
    path('notifications/push/', realtime_notifications.PushNotificationAPI.as_view(), name='push_notification'),
    path('notifications/breakeven/', breakeven_notifications.BreakevenNotificationAPI.as_view(), name='breakeven_notifications'),
    
    # User sync endpoint
    path('auth/sync-user/', sync_user.SyncUserAPI.as_view(), name='sync_user'),
    
    # Alternative endpoint for mobile compatibility
    path('auth/update-profile/', authentication.UpdateProfileAPI.as_view(), name='update_profile_alt'),
    
    # Location endpoints
    path('location/update/', location.LocationUpdateAPI.as_view(), name='location_update'),
    path('location/drivers/', location.LocationUpdateAPI.as_view(), name='driver_locations'),
    
    # Routing endpoints
    path('map/route/', routing.RouteAPI.as_view(), name='map_route'),
    
    # Payment completion endpoint
    path('payment/complete/', payment_completion.PaymentCompletionAPI.as_view(), name='payment_complete'),
    
    # Debug booking endpoint
    path('debug/booking/<str:booking_id>/', debug_booking.DebugBookingAPI.as_view(), name='debug_booking'),
    


    
    # Security endpoints
    path('csrf-token/', csrf_token.get_csrf_token, name='csrf_token'),
    path('validate-input/', csrf_token.validate_input, name='validate_input'),
    path('test/rate-limit/', security_test.test_rate_limit, name='test_rate_limit'),
    path('test/input-sanitization/', security_test.test_input_sanitization, name='test_input_sanitization'),
    
    # Booking custom endpoints - these are now handled by the router's @action decorators
    # The router will automatically create these endpoints with proper trailing slashes
    
    # Goods & Services Violation Review
    path('reports/review_goods_services_violation/', reports_goods_services.review_goods_services_violation_api, name='review_goods_services_violation'),
]