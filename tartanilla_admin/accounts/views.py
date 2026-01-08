from django.contrib import messages
from django.shortcuts import render, redirect
from api.authentication import AuthenticationAPI
from functools import wraps
from api.data import get_customers, get_owners


def test_404(request):
    return render(request, 'custom_404.html', status=404)

# home_view redirects to the login page if the user is not authenticated
# and to the dashboard if the user is already logged in.
def home(request):
    if request.COOKIES.get('admin_authenticated') == '1':
        return redirect('dashboard')
    return redirect('login_view')

def login_view(request):
    if request.COOKIES.get('admin_authenticated') == '1':
        return redirect('dashboard')
    error = None
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        if email and password:
            result = AuthenticationAPI.login_user_with_auth(email, password, ['admin'])
            if not result.get('success'):
                error = result.get('error', 'Login failed')
            else:
                response = redirect('dashboard')
                response.set_cookie('admin_authenticated', '1')
                response.set_cookie('admin_email', email)
                response.set_cookie('admin_user_id', result['user']['id'])  # Store user ID
                return response
        else:
            error = 'Please enter both email and password.'
    return render(request, 'accounts/login.html', {'error': error})

def logout_view(request):
    response = redirect('login_view')
    response.delete_cookie('admin_authenticated')
    response.delete_cookie('admin_email')
    messages.success(request, 'You have been logged out successfully.')
    return response

# Custom decorator for admin session authentication
def admin_authenticated(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.COOKIES.get('admin_authenticated') != '1':
            messages.error(request, 'Please log in to access the dashboard.')
            return redirect('login_view')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

# Remove @login_required and use @admin_authenticated for dashboard_view
@admin_authenticated
def dashboard_view(request):
    return render(request, 'accounts/dashboard.html', {'user': request.COOKIES.get('admin_email')})

@admin_authenticated
def driver_profile_view(request):
    return render(request, 'accounts/ListOfDrivers.html', {'user': request.COOKIES.get('admin_email')})

@admin_authenticated
def listOfCustomers(request):
    customers = get_customers()
    return render(request, 'accounts/ListOfCustomers.html', {'customers': customers, 'user': request.COOKIES.get('admin_email')})

@admin_authenticated
def listOfOwners(request):
    owners = get_owners()
    return render(request, 'accounts/ListOfOwners.html', {'owners': owners, 'user': request.COOKIES.get('admin_email')})


# @login_required
# def update_admin_profile(request):
#     if request.method == 'POST':
#         user = request.user
#         username = request.POST.get('username')
#         email = request.POST.get('email')
#         current_password = request.POST.get('current_password')
#         new_password = request.POST.get('new_password')
#         confirm_password = request.POST.get('confirm_password')

#         # Update username/email if they were edited
#         if username and username != user.username:
#             user.username = username
#         if email and email != user.email:
#             user.email = email

#         # If changing password
#         if current_password and new_password and confirm_password:
#             if not user.check_password(current_password):
#                 messages.error(request, 'Current password is incorrect.')
#             elif new_password != confirm_password:
#                 messages.error(request, 'New passwords do not match.')
#             else:
#                 user.set_password(new_password)
#                 update_session_auth_hash(request, user)  # keep user logged in
#                 messages.success(request, 'Password updated successfully.')

#         user.save()
#         messages.success(request, 'Profile updated successfully.')
#     return redirect('dashboard')  # or wherever you want

def pendingRegistration(request):
    # This view can be used to show a pending registration page
    # For now, it just renders a simple template
    return render(request, 'accounts/PendingRegistration.html')

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
