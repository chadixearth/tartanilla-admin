from django.contrib import messages
from django.shortcuts import render, redirect
from api.authentication import AuthenticationAPI
from functools import wraps
from api.data import get_customers, get_owners, get_drivers, suspend_user, unsuspend_user, check_and_update_expired_suspensions
from tartanilla_admin.supabase import supabase_admin
from api.tartanilla import get_all_tartanilla_carriages, create_tartanilla_carriage, update_tartanilla_carriage, delete_tartanilla_carriage, get_tartanilla_carriage_by_id, get_available_drivers, get_owners as get_tartanilla_owners, get_tartanilla_carriages_by_owner, get_user_by_id, get_user_by_email, get_tartanilla_carriages_by_driver
from tartanilla_admin.supabase import supabase, execute_with_retry
import traceback
from api.analytics import AnalyticsViewSet
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from core.mobile_security import mobile_safe_csrf, sanitize_input
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view
from rest_framework.response import Response
import json
from datetime import datetime,timezone
from .pdf_exports import export_users_pdf
from .tartanilla_pdf_export import export_tartanillas_pdf

def test_404(request):
    return render(request, 'custom_404.html', status=404)

# home_view redirects to the login page if the user is not authenticated
# and to the dashboard if the user is already logged in.
def home(request):
    if request.COOKIES.get('admin_authenticated') == '1':
        return redirect('accounts:dashboard')
    return redirect('accounts:login_view')

def login_view(request):
    if request.COOKIES.get('admin_authenticated') == '1':
        return redirect('accounts:dashboard')
    error = None
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        if email and password:
            result = AuthenticationAPI.login_user_with_auth(email, password, ['admin'])
            if not result.get('success'):
                error = result.get('error', 'Login failed')
            else:
                response = redirect('accounts:dashboard')
                # Set cookies with 7 days expiration (matching session settings)
                max_age = 7 * 24 * 60 * 60  # 7 days in seconds
                response.set_cookie('admin_authenticated', '1', max_age=max_age)
                response.set_cookie('admin_email', email, max_age=max_age)
                response.set_cookie('admin_user_id', result['user']['id'], max_age=max_age)  # Store user ID
                return response
        else:
            error = 'Please enter both email and password.'
    return render(request, 'accounts/login.html', {'error': error})

def logout_view(request):
    # Clear auth cookies and redirect to login without touching session (avoids DB requirement)
    response = redirect('accounts:login_view')
    response.delete_cookie('admin_authenticated')
    response.delete_cookie('admin_email')
    response.delete_cookie('admin_user_id')  # Also delete user ID
    # Strengthen anti-cache on logout response
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response

# Custom decorator for admin session authentication
def admin_authenticated(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.COOKIES.get('admin_authenticated') != '1':
            # Do not use messages to avoid session writes when DB is not configured
            return redirect('accounts:login_view')
        
        # Get user ID from cookie
        user_id = request.COOKIES.get('admin_user_id')
        user_email = request.COOKIES.get('admin_email')
        
        # Set user information on request object
        request.user = type('AdminUser', (), {
            'is_authenticated': True,
            'is_active': True,
            'id': user_id,
            'pk': user_id,
            'email': user_email,
            '__str__': lambda self: self.email
        })
        
        # Call the view function
        response = view_func(request, *args, **kwargs)
        
        # Add cache control headers to prevent browser back button access after logout
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        
        return response
    return _wrapped_view

# Remove @login_required and use @admin_authenticated for dashboard_view
@never_cache
@admin_authenticated
def dashboard_view(request):
    return render(request, 'accounts/dashboard.html', {'user': request.COOKIES.get('admin_email')}) 


@never_cache
@admin_authenticated
def listOfDrivers(request):
    drivers_data = get_drivers()
    return render(request, 'accounts/ListOfDrivers.html', {'drivers': drivers_data, 'user': request.COOKIES.get('admin_email')})

@never_cache
@admin_authenticated
def listOfCustomers(request):
    # Check and update expired suspensions before displaying the list
    check_and_update_expired_suspensions()
    customers_data = get_customers()
    return render(request, 'accounts/ListOfCustomers.html', {'customers': customers_data, 'user': request.COOKIES.get('admin_email')})

@never_cache
@admin_authenticated
def listOfOwners(request):
    owners_data = get_owners()
    return render(request, 'accounts/ListOfOwners.html', {'owners': owners_data, 'user': request.COOKIES.get('admin_email')})

@never_cache
@admin_authenticated
def listOfTartanillas(request):
    try:
        # Get carriages directly with supabase
        response = supabase.table('tartanilla_carriages').select('*').execute()
        carriages = response.data if hasattr(response, 'data') else []
        print(f"Found {len(carriages)} carriages")
        
        # Get all users at once for efficiency
        users = {}
        try:
            # Use the same pattern as other data functions
            client = supabase_admin if 'supabase_admin' in globals() else supabase
            
            def query_users():
                return client.table('users').select('*').execute()
            
            from tartanilla_admin.supabase import execute_with_retry
            users_response = execute_with_retry(query_users)
            
            if hasattr(users_response, 'data') and users_response.data:
                users = {user['id']: user for user in users_response.data}
                print(f"Found {len(users)} users via retry logic")
            else:
                print("No users found in response")
        except Exception as e:
            print(f"Error fetching users: {e}")
            # Final fallback
            try:
                users_response = supabase.table('users').select('*').execute()
                if hasattr(users_response, 'data') and users_response.data:
                    users = {user['id']: user for user in users_response.data}
                    print(f"Found {len(users)} users via fallback")
            except Exception as e2:
                print(f"Fallback also failed: {e2}")
        
        # Debug: Print first few users
        for i, (user_id, user) in enumerate(list(users.items())[:3]):
            print(f"User {i}: {user_id} -> {user}")
        
        # Attach user details to carriages
        for carriage in carriages:
            owner_id = carriage.get('assigned_owner_id')
            driver_id = carriage.get('assigned_driver_id')
            
            print(f"Carriage {carriage.get('plate_number')}: owner_id={owner_id}, driver_id={driver_id}")
            
            if owner_id:
                owner = users.get(owner_id)
                print(f"  Owner lookup result: {owner}")
                carriage['assigned_owner'] = owner
                
            if driver_id:
                driver = users.get(driver_id)
                print(f"  Driver lookup result: {driver}")
                carriage['assigned_driver'] = driver
        
    except Exception as e:
        print(f"Error loading carriages: {e}")
        import traceback
        traceback.print_exc()
        carriages = []
    
    return render(request, 'accounts/ListOfTartanillas.html', {
        'carriages': carriages,
        'user': request.COOKIES.get('admin_email')
    })

@never_cache
@admin_authenticated
def ownerTartanillas(request, owner_id):
    """
    Display tartanillas for a specific owner
    """
    # Get owner information
    owner = get_user_by_id(owner_id)
    if not owner:
        messages.error(request, 'Owner not found.')
        return redirect('accounts:listOfOwners')
    
    # Get tartanillas for this specific owner
    carriages = get_tartanilla_carriages_by_owner(owner_id)
    
    # Get all users for lookup
    try:
        users_response = supabase.table('users').select('id, name, email, role').execute()
        users = {user['id']: user for user in users_response.data} if hasattr(users_response, 'data') else {}
        
        for carriage in carriages:
            if carriage.get('assigned_owner_id'):
                carriage['assigned_owner'] = users.get(carriage['assigned_owner_id'])
            if carriage.get('assigned_driver_id'):
                carriage['assigned_driver'] = users.get(carriage['assigned_driver_id'])
    except Exception as e:
        print(f"Error loading user details: {e}")
    
    return render(request, 'accounts/ListOfTartanillas.html', {
        'carriages': carriages,
        'user': request.COOKIES.get('admin_email'),
        'owner': owner,
        'is_owner_specific': True
    })

@mobile_safe_csrf
@require_http_methods(["POST"])
@admin_authenticated
def suspend_customer(request):
    """
    API endpoint to suspend a customer
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        duration_days = int(data.get('duration_days', 7))
        reason = data.get('reason', 'No reason provided')
        suspended_by = request.COOKIES.get('admin_email', 'Unknown Admin')
        
        if not user_id:
            return JsonResponse({'success': False, 'error': 'User ID is required'})
        
        result = suspend_user(user_id, duration_days, reason, suspended_by)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid duration value'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def approve_registration(request):
    """
    API endpoint to approve a pending registration
    """
    try:
        data = json.loads(request.body)
        registration_id = data.get('registration_id')
        approved_by = request.COOKIES.get('admin_email', 'Unknown Admin')
        
        if not registration_id:
            return JsonResponse({'success': False, 'error': 'Registration ID is required'})
        
        from api.authentication import AuthenticationAPI
        result = AuthenticationAPI.approve_registration(registration_id, approved_by)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def reject_registration(request):
    """
    API endpoint to reject a pending registration
    """
    try:
        data = json.loads(request.body)
        registration_id = data.get('registration_id')
        rejected_by = request.COOKIES.get('admin_email', 'Unknown Admin')
        reason = data.get('reason', 'No reason provided')
        
        if not registration_id:
            return JsonResponse({'success': False, 'error': 'Registration ID is required'})
        
        from api.authentication import AuthenticationAPI
        result = AuthenticationAPI.reject_registration(registration_id, rejected_by, reason)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def unsuspend_customer(request):
    """
    API endpoint to unsuspend a customer
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        unsuspended_by = request.COOKIES.get('admin_email', 'Unknown Admin')
        
        if not user_id:
            return JsonResponse({'success': False, 'error': 'User ID is required'})
        
        result = unsuspend_user(user_id, unsuspended_by)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def suspend_driver(request):
    """
    API endpoint to suspend a driver
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        duration_days = int(data.get('duration_days', 7))
        reason = data.get('reason', 'No reason provided')
        suspended_by = request.COOKIES.get('admin_email', 'Unknown Admin')
        
        if not user_id:
            return JsonResponse({'success': False, 'error': 'User ID is required'})
        
        result = suspend_user(user_id, duration_days, reason, suspended_by)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid duration value'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def unsuspend_driver(request):
    """
    API endpoint to unsuspend a driver
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        unsuspended_by = request.COOKIES.get('admin_email', 'Unknown Admin')
        
        if not user_id:
            return JsonResponse({'success': False, 'error': 'User ID is required'})
        
        result = unsuspend_user(user_id, unsuspended_by)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
@admin_authenticated
def pendingRegistration(request):
    """
    Display pending registrations for admin approval
    """
    from api.authentication import AuthenticationAPI
    
    # Get pending registrations
    result = AuthenticationAPI.get_pending_registrations()
    pending_users = result.get('data', []) if result.get('success') else []
    
    return render(request, 'accounts/PendingRegistration.html', {
        'pending_users': pending_users,
        'user': request.COOKIES.get('admin_email')
    })

def registration_view(request):
    message = None
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        if password != confirm_password:
            message = "Passwords do not match."
        else:
            result = AuthenticationAPI.register_user_with_auth(email, password, 'admin')
            if not result.get('success'):
                message = result.get('error', 'Registration failed')
            else:
                message = result.get('message', 'Registration successful')
    return render(request, 'accounts/registration.html', {'message': message})

def driver_owner_application_view(request):
    """
    Handle driver/owner applications (no password required)
    """
    message = None
    if request.method == 'POST':
        # Get form data
        email = request.POST.get('email')
        role = request.POST.get('role')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        
        # Validate required fields
        if not all([email, role, first_name, last_name, phone, address]):
            message = "All fields are required."
        elif role not in ['driver', 'owner']:
            message = "Invalid role selected."
        else:
            # Prepare additional data
            additional_data = {
                'first_name': first_name,
                'last_name': last_name,
                'phone': phone,
                'address': address
            }
            
            # Submit application (no password required)
            result = AuthenticationAPI.register_user_with_auth(
                email=email,
                password=None,  # No password required
                role=role,
                additional_data=additional_data
            )
            
            if result.get('success'):
                message = f"Your {role} application has been submitted successfully! You will receive an email with your login credentials once approved by our admin team."
            else:
                message = result.get('error', 'Application submission failed')
    
    return render(request, 'accounts/driver_owner_application.html', {'message': message})

def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        if email:
            # Here you would typically send a password reset email
            messages.success(request, 'If this email is registered, a password reset link has been sent.')
            return redirect('accounts:login_view')
        else:
            messages.error(request, 'Please enter your email address.')
    return render(request, 'accounts/forgotPassword.html')

# Tartanilla Carriage API Endpoints
@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def create_tartanilla_carriage_api(request):
    """
    API endpoint to create a new tartanilla carriage (admin only)
    """
    try:
        data = json.loads(request.body)
        plate_number = data.get('plate_number')
        assigned_owner_id = data.get('assigned_owner_id')
        capacity = data.get('capacity', 4)
        status = data.get('status', 'available')
        eligibility = data.get('eligibility', 'eligible')
        notes = data.get('notes')
        
        if not plate_number or not assigned_owner_id:
            return JsonResponse({'success': False, 'error': 'Plate number and owner ID are required'})
        
        # Since only admins can access this web interface, they can assign to any owner
        carriage_data = {
            'plate_number': plate_number,
            'assigned_owner_id': assigned_owner_id,
            'capacity': capacity,
            'status': status,
            'eligibility': eligibility,
            'notes': notes
        }
        
        result = create_tartanilla_carriage(carriage_data)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def update_tartanilla_carriage_api(request):
    """
    API endpoint to update a tartanilla carriage
    """
    try:
        data = json.loads(request.body)
        carriage_id = data.get('carriage_id')
        
        if not carriage_id:
            return JsonResponse({'success': False, 'error': 'Carriage ID is required'})
        
        # Remove carriage_id from data to pass as update data
        update_data = {k: v for k, v in data.items() if k != 'carriage_id'}
        
        result = update_tartanilla_carriage(carriage_id, update_data)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def delete_tartanilla_carriage_api(request):
    """
    API endpoint to delete a tartanilla carriage
    """
    try:
        data = json.loads(request.body)
        carriage_id = data.get('carriage_id')
        
        if not carriage_id:
            return JsonResponse({'success': False, 'error': 'Carriage ID is required'})
        
        result = delete_tartanilla_carriage(carriage_id)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def get_tartanilla_carriage_api(request):
    """
    API endpoint to get a specific tartanilla carriage
    """
    try:
        carriage_id = request.GET.get('carriage_id')
        
        if not carriage_id:
            return JsonResponse({'success': False, 'error': 'Carriage ID is required'})
        
        carriage = get_tartanilla_carriage_by_id(carriage_id)
        if carriage:
            return JsonResponse({'success': True, 'data': carriage})
        else:
            return JsonResponse({'success': False, 'error': 'Carriage not found'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def get_available_drivers_api(request):
    """
    API endpoint to get available drivers for assignment
    """
    try:
        drivers = get_available_drivers()
        return JsonResponse({'success': True, 'data': drivers})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def get_tartanilla_owners_api(request):
    """
    API endpoint to get all owners for tartanilla carriage assignment
    """
    try:
        owners = get_tartanilla_owners()
        return JsonResponse({'success': True, 'data': owners})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def get_current_user_api(request):
    """
    API endpoint to get current user information (admin only)
    """
    try:
        current_user_id = request.COOKIES.get('admin_user_id')
        current_user_email = request.COOKIES.get('admin_email')
        
        # Since this is web interface, user is always admin
        current_user = {
            'id': current_user_id,
            'email': current_user_email,
            'role': 'admin'
        }
        
        return JsonResponse({'success': True, 'data': current_user})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def get_owner_tartanillas_api(request):
    """
    API endpoint to get tartanilla carriages for a specific owner
    """
    try:
        owner_id = request.GET.get('owner_id')
        
        if not owner_id:
            return JsonResponse({'success': False, 'error': 'Owner ID is required'})
        
        carriages = get_tartanilla_carriages_by_owner(owner_id)
        return JsonResponse({'success': True, 'data': carriages})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

# -------------------- Metrics APIs --------------------

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def dashboard_metrics_api(request):
    """
    GET /accounts/api/dashboard-metrics?start=YYYY-MM-DD&end=YYYY-MM-DD
    """
    try:
        start = request.GET.get('start')
        end = request.GET.get('end')

        total_revenue = AnalyticsViewSet.get_total_revenue(start, end)
        completed_count = AnalyticsViewSet.get_completed_bookings_count(start, end)
        weekly_top = AnalyticsViewSet.get_weekly_top_drivers(limit=5)
        ratings = AnalyticsViewSet.get_ratings_distribution()
        highest_rated = AnalyticsViewSet.get_highest_rated_driver(min_reviews=1)
        
        print(f"DEBUG: API returning ratings_distribution: {ratings}")

        return JsonResponse({
            'success': True,
            'data': {
                'total_revenue': total_revenue,
                'completed_bookings': completed_count,
                'weekly_top_drivers': weekly_top,
                'ratings_distribution': ratings,
                'highest_rated_driver': highest_rated,
            }
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def driver_performance_api(request):
    """
    GET /accounts/api/driver-performance?limit=50
    """
    try:
        try:
            limit = int(request.GET.get('limit')) if request.GET.get('limit') else None
        except (ValueError, TypeError):
            limit = None

        rows = AnalyticsViewSet.get_driver_performance(limit=limit)
        return JsonResponse({'success': True, 'data': rows})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def revenue_by_package_api(request):
    try:
        granularity = (request.GET.get('granularity') or '').strip().lower()

        if granularity == 'daily':
            # last N days (default 7). Frontend requests days=1 for "latest day".
            try:
                days = int(request.GET.get('days') or 7)
                if days <= 0:
                    days = 7
            except (ValueError, TypeError):
                days = 7
            data = AnalyticsViewSet.get_revenue_by_package_daily(days=days)
            return JsonResponse({'success': True, 'data': data})

        if granularity == 'weekly':
            try:
                weeks = int(request.GET.get('weeks') or 8)
                if weeks <= 0:
                    weeks = 8
            except (ValueError, TypeError):
                weeks = 8
            data = AnalyticsViewSet.get_revenue_by_package_weekly(weeks=weeks)
            return JsonResponse({'success': True, 'data': data})

        # fallback legacy totals
        raw = request.GET.get('limit')
        limit = None
        if raw not in (None, '', 'null'):
            try:
                limit = int(raw)
                if limit <= 0:
                    limit = None
            except (ValueError, TypeError):
                limit = None

        # Use monthly data as fallback for legacy totals
        data = AnalyticsViewSet.get_revenue_by_package_monthly(months=12, top=limit or 10)
        return JsonResponse({'success': True, 'data': data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def revenue_trend_api(request):
    """
    GET /accounts/api/revenue-trend?months=6
    (Optionally accepts start=YYYY-MM-DD&end=YYYY-MM-DD)
    Returns monthly totals from earnings (raw): pending+finalized, minus reversed.
    """
    try:
        months_raw = request.GET.get('months') or '6'
        try:
            months = int(months_raw)
            if months <= 0:
                months = 6
        except (ValueError, TypeError):
            months = 6

        start = request.GET.get('start')
        end = request.GET.get('end')

        data = AnalyticsViewSet.get_revenue_trend_monthly(months=months, start_date=start, end_date=end)
        return JsonResponse({'success': True, 'data': data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
@api_view(["GET"])
def revenue_by_package_monthly_api(request):
    months = int(request.GET.get("months", 6))
    top = int(request.GET.get("top", 10))
    data = AnalyticsViewSet.get_revenue_by_package_monthly(months=months, top=top)
    return Response({"success": True, "data": data})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def suspend_owner(request):
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        duration_days = int(data.get('duration_days', 7))
        reason = data.get('reason', 'No reason provided')
        suspended_by = request.COOKIES.get('admin_email', 'Unknown Admin')
        
        if not user_id:
            return JsonResponse({'success': False, 'error': 'User ID is required'})
        
        result = suspend_user(user_id, duration_days, reason, suspended_by)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid duration value'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["POST"])
@admin_authenticated
def unsuspend_owner(request):
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        unsuspended_by = request.COOKIES.get('admin_email', 'Unknown Admin')
        
        if not user_id:
            return JsonResponse({'success': False, 'error': 'User ID is required'})
        
        result = unsuspend_user(user_id, unsuspended_by)
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def package_ratings_pie_api(request):
    """
    GET /accounts/api/package-ratings-pie?top=12
    Returns { labels: [...], counts: [...] } for reviews per package.
    """
    try:
        try:
            top = int(request.GET.get('top', 12))
            if top <= 0:
                top = 12
        except (ValueError, TypeError):
            top = 12

        data = AnalyticsViewSet.get_package_ratings_pie(top=top, only_published=True)
        return JsonResponse({'success': True, 'data': data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@never_cache
@admin_authenticated
def driver_assigned_tartanillas(request):
    """
    API endpoint to get tartanillas assigned to a specific driver
    """
    try:
        driver_id = request.GET.get('driver_id')
        
        if not driver_id:
            return JsonResponse({'success': False, 'error': 'Driver ID is required'})
        
        print(f"Fetching tartanillas for driver_id: {driver_id}")
        
        # Get tartanillas assigned to this driver
        carriages = get_tartanilla_carriages_by_driver(driver_id)
        print(f"Found {len(carriages)} carriages for driver {driver_id}")
        
        # Get all users for owner lookup
        users = {}
        try:
            users_response = supabase.table('users').select('*').execute()
            if hasattr(users_response, 'data') and users_response.data:
                users = {user['id']: user for user in users_response.data}
                print(f"Loaded {len(users)} users")
        except Exception as e:
            print(f"Error fetching users: {e}")
        
        # Format for the frontend
        formatted_carriages = []
        for carriage in carriages:
            # Get owner information
            owner_name = 'No Owner'
            owner_id = carriage.get('assigned_owner_id')
            if owner_id and owner_id in users:
                owner = users[owner_id]
                if owner.get('name'):
                    owner_name = owner['name']
                elif owner.get('first_name') or owner.get('last_name'):
                    first = owner.get('first_name', '').strip()
                    last = owner.get('last_name', '').strip()
                    if first and last:
                        owner_name = f"{first} {last}"
                    elif first:
                        owner_name = first
                    elif last:
                        owner_name = last
                elif owner.get('email'):
                    owner_name = owner['email']
            elif owner_id:
                try:
                    owner_response = supabase.table('users').select('*').eq('id', owner_id).execute()
                    if hasattr(owner_response, 'data') and owner_response.data:
                        owner = owner_response.data[0]
                        owner_name = owner.get('email', owner_id)
                except:
                    owner_name = owner_id
            
            formatted_carriage = {
                'id': carriage.get('id', ''),
                'name': carriage.get('plate_number', ''),
                'code': carriage.get('plate_number', ''),
                'owner': owner_name,
                'status': carriage.get('status', '').title(),
                'details': f"Capacity: {carriage.get('capacity', 'N/A')} persons"
            }
            formatted_carriages.append(formatted_carriage)
            print(f"Formatted carriage: {formatted_carriage}")
        
        print(f"Returning {len(formatted_carriages)} formatted carriages")
        return JsonResponse(formatted_carriages, safe=False)
        
    except Exception as e:
        print(f"Error fetching driver tartanillas: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})

@never_cache
@admin_authenticated
def owner_assigned_tartanillas(request):
    """
    API endpoint to get tartanillas owned by a specific owner
    """
    try:
        owner_id = request.GET.get('owner_id')
        print(f"Fetching tartanillas for owner_id: {owner_id}")
        
        if not owner_id:
            return JsonResponse({'success': False, 'error': 'Owner ID is required'})
        
        # Get tartanillas owned by this owner
        carriages = get_tartanilla_carriages_by_owner(owner_id)
        print(f"Found {len(carriages)} carriages for owner {owner_id}")
        
        # Format for the frontend
        formatted_carriages = []
        for carriage in carriages:
            # Get driver name if assigned
            driver_name = 'Unassigned'
            if carriage.get('assigned_driver') and carriage.get('assigned_driver').get('name'):
                driver_name = carriage.get('assigned_driver').get('name')
            elif carriage.get('assigned_driver_id'):
                # Fallback: show that there's a driver assigned but name unknown
                driver_name = 'Driver Assigned'
            
            formatted_carriage = {
                'id': carriage.get('id', ''),
                'name': carriage.get('plate_number', ''),
                'code': carriage.get('plate_number', ''),
                'driver_name': driver_name,
                'status': carriage.get('status', '').title(),
                'details': f"Capacity: {carriage.get('capacity', 'N/A')} persons"
            }
            formatted_carriages.append(formatted_carriage)
            print(f"Formatted carriage: {formatted_carriage}")
        
        print(f"Returning {len(formatted_carriages)} formatted carriages")
        return JsonResponse(formatted_carriages, safe=False)
        
    except Exception as e:
        print(f"Error fetching owner tartanillas: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})

# views.py
@never_cache
@admin_authenticated
def export_users_pdf_view(request):
    """Export users to PDF"""
    return export_users_pdf(request)

@never_cache
@admin_authenticated
def export_tartanillas_pdf_view(request):
    """Export tartanilla carriages to PDF"""
    return export_tartanillas_pdf(request)

@csrf_exempt
@require_http_methods(["GET"])
@admin_authenticated
def active_drivers_count_api(request):
    try:
        count = AnalyticsViewSet.get_active_drivers_count()

        if request.GET.get('debug') == '1':
            now_iso = datetime.now(timezone.utc).isoformat()
            sample = execute_with_retry(lambda:
                supabase.table('users')
                        .select('id,email,role,status,suspended_until')
                        .eq('role', 'driver')
                        .ilike('status', 'active')
                        .or_(f'suspended_until.is.null,suspended_until.lte.{now_iso}')
                        .limit(50)
                        .execute()
            ).data or []
            return JsonResponse({'success': True, 'data': {'count': int(count), 'sample': sample}})

        return JsonResponse({'success': True, 'data': {'count': int(count)}})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)



