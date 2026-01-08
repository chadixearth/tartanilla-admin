# JWT Authentication with Supabase

This document provides an overview of the JWT authentication implementation using Supabase in the Tartanilla Admin application.

## Overview

The application uses Supabase for authentication and JWT (JSON Web Tokens) for securing API endpoints. JWT tokens are issued by Supabase Auth when a user logs in and are used to authenticate subsequent API requests.

## Components

### Backend (Django)

1. **JWT Authentication Middleware** (`core/jwt_auth.py`)
   - `SupabaseJWTMiddleware`: Django middleware that extracts and verifies JWT tokens from requests
   - `SupabaseJWTAuthentication`: DRF authentication class for API endpoints
   - Utility functions for token management (`get_token_from_request`, `verify_token`)

2. **Authentication Decorators** (`core/auth_decorators.py`)
   - `jwt_authenticated`: Decorator for views that require authentication
   - `jwt_role_required`: Decorator for views that require specific roles

3. **Authentication API** (`api/authentication.py`)
   - `LoginAPI`: Handles user login and returns JWT tokens
   - `VerifyTokenAPI`: Verifies JWT tokens and returns user information

### Frontend (JavaScript)

1. **JWT Authentication Utilities** (`static/js/auth/jwt_auth.js`)
   - Functions for login, logout, token management, and authenticated requests
   - Integration with Supabase client

## How It Works

### Authentication Flow

1. User logs in with email and password via `/api/auth/login/` endpoint
2. Supabase verifies credentials and issues JWT tokens
3. The application returns tokens to the client
4. Client stores tokens in localStorage
5. Client includes token in Authorization header for subsequent requests
6. Server verifies token and grants access to protected resources

### Token Verification

Tokens are verified using Supabase's `auth.get_user()` method, which validates the token and returns user information if valid.

### Protected Resources

API endpoints can be protected using:

1. **DRF Authentication Classes**:
   ```python
   from rest_framework.permissions import IsAuthenticated
   from core.jwt_auth import SupabaseJWTAuthentication
   
   class ProtectedAPI(APIView):
       authentication_classes = [SupabaseJWTAuthentication]
       permission_classes = [IsAuthenticated]
   ```

2. **View Decorators**:
   ```python
   from core.auth_decorators import jwt_authenticated, jwt_role_required
   
   @jwt_authenticated
   def protected_view(request):
       # Only authenticated users can access this view
       pass
       
   @jwt_role_required(['admin'])
   def admin_view(request):
       # Only admins can access this view
       pass
   ```

## Client-Side Usage

```javascript
// Login
async function handleLogin() {
  const result = await window.jwtAuth.login(email, password);
  if (result.success) {
    // Redirect to dashboard
  }
}

// Making authenticated requests
async function fetchData() {
  try {
    const response = await window.jwtAuth.fetchWithAuth('/api/protected-endpoint/');
    const data = await response.json();
    // Handle data
  } catch (error) {
    // Handle error
  }
}

// Checking authentication status
if (window.jwtAuth.isAuthenticated()) {
  // Show authenticated UI
} else {
  // Show login form
}
```

## Security Considerations

1. **Token Storage**: Tokens are stored in localStorage, which is vulnerable to XSS attacks. Consider using more secure storage methods for production.
2. **Token Expiration**: Tokens have a default expiration time of 1 hour. Implement token refresh logic for long-lived sessions.
3. **HTTPS**: Always use HTTPS in production to prevent token interception.
4. **Cache Control**: All authenticated views should include cache control headers to prevent access to sensitive pages after logout via browser back button.
5. **Session Termination**: Ensure proper session termination by clearing all authentication cookies and adding cache control headers during logout.

## Template Authentication and Cache Control

### Preventing Access After Logout

To prevent access to authenticated templates after logout (via browser back button):

1. **Use `@never_cache` Decorator**: Apply to all authenticated views to prevent browser caching.
   ```python
   from django.views.decorators.cache import never_cache
   from accounts.views import admin_authenticated
   
   @never_cache
   @admin_authenticated
   def protected_view(request):
       # View code here
   ```

2. **Add Cache Control Headers**: The `admin_authenticated` decorator adds cache control headers to responses:
   ```python
   def _wrapped_view(request, *args, **kwargs):
       # Authentication check
       response = view_func(request, *args, **kwargs)
       # Add cache control headers
       response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
       response['Pragma'] = 'no-cache'
       response['Expires'] = '0'
       return response
   ```

3. **Class-Based Views**: For class-based views, use `method_decorator`:
   ```python
   from django.utils.decorators import method_decorator
   
   @method_decorator(never_cache, name='dispatch')
   @method_decorator(admin_authenticated, name='dispatch')
   class ProtectedView(View):
       # View code here
   ```

## Further Improvements

1. Implement token refresh mechanism
2. Add CSRF protection for sensitive operations
3. Implement rate limiting for authentication endpoints
4. Add support for multi-factor authentication
5. Consider using secure cookies with the `secure` and `httponly` flags