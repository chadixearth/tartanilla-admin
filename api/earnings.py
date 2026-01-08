# api/earnings.py
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from collections import defaultdict
import copy
import json
import logging

from tartanilla_admin.supabase import supabase, execute_with_retry
try:
    # Prefer the admin client (bypasses RLS for audit_logs)
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

from core.jwt_auth import verify_token, get_token_from_request
from core.response_limiter import create_limited_response  # kept for compatibility
from .response_fix import create_safe_response              # kept for compatibility

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Audit & Actor helpers (actor extraction is very defensive)
# ────────────────────────────────────────────────────────────

def _extract_ip(request):
    try:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
    except Exception:
        return None

def _extract_device(request):
    try:
        return request.META.get("HTTP_USER_AGENT")
    except Exception:
        return None

def _ensure_str(v):
    if v is None:
        return None
    try:
        s = str(v).strip()
        return s if s else None
    except Exception:
        return None

def _extract_actor_from_django_user(request):
    """
    Pulls (user_id, username, role, email) from Django's request.user if present.
    Very forgiving—works even if auth is off.
    """
    try:
        u = getattr(request, "user", None)
        if not u:
            return (None, None, None, None)

        uid = _ensure_str(getattr(u, "id", None) or getattr(u, "pk", None))
        uname = _ensure_str(getattr(u, "username", None) or getattr(u, "get_username", lambda: None)())
        email = _ensure_str(getattr(u, "email", None))

        role = None
        # common patterns: user.role, user.profile.role, first group name
        role = _ensure_str(getattr(u, "role", None)) or role
        profile = getattr(u, "profile", None)
        if not role and profile:
            role = _ensure_str(getattr(profile, "role", None))
        if not role:
            try:
                groups = getattr(u, "groups", None)
                if groups and hasattr(groups, "first"):
                    g = groups.first()
                    if g:
                        role = _ensure_str(getattr(g, "name", None))
            except Exception:
                pass

        return (uid, uname, role, email)
    except Exception:
        return (None, None, None, None)

def _extract_actor_from_headers(request):
    """
    Honors proxy/gateway-provided headers:
      X-User-Id, X-User-Email, X-User-Name / X-Username, X-User-Role / X-Role
    """
    try:
        H = request.META or {}
        uid   = _ensure_str(H.get("HTTP_X_USER_ID"))
        email = _ensure_str(H.get("HTTP_X_USER_EMAIL"))
        uname = _ensure_str(H.get("HTTP_X_USER_NAME") or H.get("HTTP_X_USERNAME"))
        role  = _ensure_str(H.get("HTTP_X_USER_ROLE") or H.get("HTTP_X_ROLE"))
        return (uid, uname, role, email)
    except Exception:
        return (None, None, None, None)

def _extract_actor_from_body(request):
    """
    LAST RESORT. Uses client-sent fields. Only used if nothing else available.
    """
    try:
        data = getattr(request, "data", None) or getattr(request, "POST", None) or {}
        uid   = _ensure_str(data.get("user_id"))
        email = _ensure_str(data.get("email"))
        uname = _ensure_str(data.get("username") or data.get("name"))
        role  = _ensure_str(data.get("role"))
        return (uid, uname, role, email)
    except Exception:
        return (None, None, None, None)

def _get_user_from_db(user_id):
    """Fetch user details from users table by ID"""
    try:
        if not user_id:
            logger.info(f"[USER_DB] No user_id provided")
            return None
        logger.info(f"[USER_DB] Fetching user with ID: {user_id}")
        res = supabase.table("users").select("id, name, role, email").eq("id", str(user_id)).limit(1).execute()
        user_data = res.data[0] if res.data else None
        logger.info(f"[USER_DB] Found user: {user_data}")
        return user_data
    except Exception as e:
        logger.error(f"[USER_DB] Error fetching user {user_id}: {e}")
        return None

def _resolve_actor(request):
    """
    Resolve (user_id, username, role) with multiple fallbacks.
    Priority:
      1) Admin cookies (from @admin_authenticated decorator)
      2) Supabase JWT (verify_token) + users table lookup
      3) Django request.user
      4) X-User-* headers
      5) Body (LAST resort)
    username falls back to email whenever available.
    """
    uid = uname = role = email = None

    # 1) Admin cookies (from @admin_authenticated decorator)
    try:
        admin_user_id = request.COOKIES.get('admin_user_id')
        admin_email = request.COOKIES.get('admin_email')
        admin_authenticated = request.COOKIES.get('admin_authenticated')
        
        if admin_authenticated == '1' and admin_user_id and admin_email:
            uid = _ensure_str(admin_user_id)
            email = _ensure_str(admin_email)
            role = "admin"  # Admin web interface users are always admin
            
            # Try to get user name from database
            db_user = _get_user_from_db(uid)
            if db_user:
                uname = _ensure_str(db_user.get("name")) or email
            else:
                uname = email
            
            logger.info(f"[ACTOR] From admin cookies - uid: {uid}, name: {uname}, role: {role}")
    except Exception as e:
        logger.error(f"[ACTOR] Admin cookie processing error: {e}")

    # 2) Supabase JWT + users table lookup (if not already resolved)
    if not uid or not uname or not role:
        try:
            token = get_token_from_request(request)
            if token:
                user = verify_token(token)
                if user:
                    # Extract user ID and email from JWT
                    jwt_uid = _ensure_str(getattr(user, "id", None) if not isinstance(user, dict) else user.get("id"))
                    jwt_email = _ensure_str(getattr(user, "email", None) if not isinstance(user, dict) else user.get("email"))
                    
                    uid = uid or jwt_uid
                    email = email or jwt_email
                    
                    # Get user details from database
                    if uid:
                        db_user = _get_user_from_db(uid)
                        if db_user:
                            uname = uname or _ensure_str(db_user.get("name")) or email
                            role = role or _ensure_str(db_user.get("role"))
                        else:
                            # Fallback to JWT metadata if DB lookup fails
                            meta = getattr(user, "user_metadata", None)
                            if meta is None and isinstance(user, dict):
                                meta = user.get("user_metadata")
                            meta = meta or {}
                            uname = uname or (
                                _ensure_str(meta.get("username"))
                                or _ensure_str(meta.get("name"))
                                or _ensure_str(meta.get("full_name"))
                                or email
                            )
                            role = role or _ensure_str(meta.get("role"))
                    logger.info(f"[ACTOR] From JWT - uid: {uid}, name: {uname}, role: {role}")
        except Exception as e:
            logger.error(f"[ACTOR] JWT processing error: {e}")

    # 3) Django user (fills any gaps)
    if not uid or not uname or not role:
        d_uid, d_uname, d_role, d_email = _extract_actor_from_django_user(request)
        uid   = uid   or d_uid
        uname = uname or d_uname
        role  = role  or d_role
        email = email or d_email

    # 4) Headers (fills any gaps)
    if not uid or not uname or not role:
        h_uid, h_uname, h_role, h_email = _extract_actor_from_headers(request)
        uid   = uid   or h_uid
        uname = uname or h_uname
        role  = role  or h_role
        email = email or h_email

    # 5) Body (LAST resort)
    if not uid or not uname or not role:
        b_uid, b_uname, b_role, b_email = _extract_actor_from_body(request)
        uid   = uid   or b_uid
        uname = uname or b_uname
        role  = role  or b_role
        email = email or b_email

    # Final fallbacks
    if not uname:
        uname = email or "System Admin"
    if not role:
        role = "admin"

    logger.info(f"[ACTOR] Final result - uid: {uid}, name: {uname}, role: {role}")
    return (uid, uname, role)

def _actor_from_request(request):
    uid, uname, role = _resolve_actor(request)
    return {"user_id": uid, "username": uname, "role": role}

def _add_actor_headers(resp: Response, actor: dict):
    try:
        resp["X-Actor-Id"] = actor.get("user_id") or ""
        resp["X-Actor-Username"] = actor.get("username") or ""
        resp["X-Actor-Role"] = actor.get("role") or ""
    except Exception:
        pass
    return resp

# Only truly sensitive names go here
_SENSITIVE_KEYS = {
    "password", "current_password", "new_password",
    "access_token", "refresh_token", "token", "authorization"
}

def _redact_sensitive(obj):
    try:
        if obj is None:
            return None
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if str(k).lower() in _SENSITIVE_KEYS:
                    out[k] = "[REDACTED]"
                else:
                    out[k] = _redact_sensitive(v)
            return out
        if isinstance(obj, list):
            return [_redact_sensitive(x) for x in obj]
        return obj
    except Exception:
        return None

def _insert_audit_log(
    *,
    action,
    entity_name,
    request=None,
    entity_id=None,
    user_id=None,
    username=None,
    role=None,
    old_data=None,
    new_data=None,
    ip_address=None,
    device_info=None
):
    """
    Best-effort insert to public.audit_logs.
    Used ONLY for:
      - PAYOUT_RELEASED (when releasing payout)
      - SALES_REPORT_VIEW (when viewing sales report)
    """
    try:
        admin_client = supabase_admin if supabase_admin else supabase

        if request:
            ip_address = ip_address or _extract_ip(request)
            device_info = device_info or _extract_device(request)

            # Resolve all missing actor fields
            rid, rusername, rrole = _resolve_actor(request)
            user_id  = user_id  or rid
            username = username or rusername
            role     = role     or rrole

        # Ensure we have required fields
        if not username:
            username = "System User"
        if not role:
            role = "system"

        payload = {
            "action": action,
            "entity_name": entity_name,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "username": username,
            "role": role,
            "old_data": _redact_sensitive(copy.deepcopy(old_data)) if old_data is not None else None,
            "new_data": _redact_sensitive(copy.deepcopy(new_data)) if new_data is not None else None,
            "ip_address": ip_address,
            "device_info": device_info,
        }
        
        # Only add user_id if it's not None to avoid foreign key constraint issues
        if user_id:
            payload["user_id"] = user_id

        try:
            execute_with_retry(
                lambda: admin_client.table("audit_logs").insert(payload).execute(),
                max_retries=2,
                delay=0.25,
            )
        except Exception:
            # last try without retry wrapper
            admin_client.table("audit_logs").insert(payload).execute()
    except Exception as e:
        logger.warning(f"[AUDIT] insert failed for {action}/{entity_name}: {e}")

# ────────────────────────────────────────────────────────────
# Earnings constants
# ────────────────────────────────────────────────────────────
DEFAULT_ADMIN_PERCENTAGE = Decimal("0.20")   # Default 20% to admin
REVERSED_STATUS = "reversed"

# Global variable for current percentage (fallback)
CURRENT_ORG_PERCENTAGE = None

def get_organization_percentage():
    """Get current organization percentage from system_settings table"""
    try:
        res = supabase.table('system_settings').select('value').eq('key', 'organization_percentage').execute()
        print(f"[DEBUG API] System settings query result: {res.data}")
        if res.data and res.data[0].get('value'):
            percentage = Decimal(str(res.data[0]['value'])) / 100
            print(f"[DEBUG API] Found percentage: {res.data[0]['value']}% -> {percentage}")
            return percentage
        print(f"[DEBUG API] No data found, using default: {DEFAULT_ADMIN_PERCENTAGE}")
    except Exception as e:
        print(f"[DEBUG API] Error fetching organization percentage: {e}")
    return DEFAULT_ADMIN_PERCENTAGE

# Timezone constants
_TZ_UTC = timezone.utc

def _parse_iso_dt(ts_str):
    if not ts_str:
        return None
    try:
        s = str(ts_str)
        if s.endswith('Z'):
            s = s.replace('Z', '+00:00')
        return datetime.fromisoformat(s)
    except Exception:
        return None

def _to_mnl_iso(dt):
    if not dt:
        manila_tz = ZoneInfo('Asia/Manila')
        return datetime.now(manila_tz).isoformat()
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        manila_tz = ZoneInfo('Asia/Manila')
        return dt.astimezone(manila_tz).isoformat()
    except Exception:
        manila_tz = ZoneInfo('Asia/Manila')
        return dt.isoformat() if dt else datetime.now(manila_tz).isoformat()

def _q2(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _safe_decimal(value, default: Decimal = Decimal("0.00")) -> Decimal:
    if value is None:
        return default
    try:
        text = str(value).strip()
        if text == '' or text.lower() == 'none':
            return default
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return default

def _get_amount(row: dict) -> Decimal:
    if isinstance(row, dict):
        if 'total_amount' in row:
            return _safe_decimal(row.get('total_amount'))
        return _safe_decimal(row.get('amount'))
    return Decimal("0.00")

def _split_amount(row: dict) -> tuple[Decimal, Decimal, Decimal]:
    # Get total amount from either 'amount' or 'total_amount' field
    total = _safe_decimal(row.get('total_amount')) or _safe_decimal(row.get('amount'))
    admin_val = _safe_decimal(row.get('admin_earnings'))
    driver_val = _safe_decimal(row.get('driver_earnings'))
    
    # Check if this is a ride hailing package
    package_name = str(row.get('package_name', '')).lower()
    booking_type = row.get('booking_type', 'tour_package')
    is_ride_hailing = booking_type == 'ride_hailing' or bool(row.get('ride_hailing_booking_id')) or 'ride' in package_name or 'hailing' in package_name
    
    # Always recalculate based on package type
    if total > Decimal("0.00"):
        if is_ride_hailing:
            # Ride hailing: 100% to driver, 0% to admin
            driver_val = _q2(total)
            admin_val = Decimal("0.00")
            print(f"[RIDE_HAILING_BACKEND] Package: {package_name}, Total: {total}, Driver gets: {driver_val} (100%)")
        else:
            # Regular packages: use percentage from this record's organization_percentage column
            record_percentage = _safe_decimal(row.get('organization_percentage'))
            if record_percentage > Decimal("0"):
                admin_percentage = record_percentage / 100
            else:
                # Fallback to current system setting if record doesn't have percentage
                admin_percentage = get_organization_percentage()
            driver_percentage = Decimal("1.00") - admin_percentage
            admin_val = _q2(total * admin_percentage)
            driver_val = _q2(total * driver_percentage)
    
    return total, admin_val, driver_val

# ────────────────────────────────────────────────────────────
# ViewSets
# ────────────────────────────────────────────────────────────

class EarningsViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]
    authentication_classes = []  # Explicitly disable authentication (JWT is read manually)

    def list(self, request):
        actor = _actor_from_request(request)
        totals = self._get_totals()
        
        org_percentage = get_organization_percentage()
        admin_pct = float(org_percentage * 100)
        driver_pct = float((Decimal("1.00") - org_percentage) * 100)
        
        print(f"[DEBUG API] list() returning percentages - admin: {admin_pct}%, driver: {driver_pct}%")
        
        resp = Response({
            "total_income": float(totals["gross_total"]),
            "admin_total_earnings": float(totals["admin_total"]),
            "driver_total_earnings": float(totals["driver_total"]),
            "admin_percentage": admin_pct,
            "driver_percentage": driver_pct,
            "can_update_percentage": True,
            "pending_payouts": self._pending_payouts(),
            "released_payouts": self._released_payouts(),
            "actor": actor,
        })
        return _add_actor_headers(resp, actor)

    @action(detail=False, methods=['post'], url_path='update-percentage')
    def update_organization_percentage(self, request):
        """Update the organization's earnings percentage"""
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body)
            percentage = data.get('percentage')
            
            if percentage is None:
                return Response({
                    'success': False,
                    'error': 'percentage field is required'
                }, status=400)
            
            # Validate percentage range (0-100)
            try:
                pct_val = float(percentage)
                if not (0 <= pct_val <= 100):
                    return Response({
                        'success': False,
                        'error': 'Percentage must be between 0 and 100'
                    }, status=400)
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'error': 'Invalid percentage value'
                }, status=400)
            
            # Store the new percentage in system_settings table
            print(f"[DEBUG API] Storing new percentage: {pct_val}%")
            
            # Update system_settings table (record exists)
            supabase.table('system_settings').update({
                'value': str(pct_val),
                'updated_at': datetime.now(ZoneInfo('Asia/Manila')).isoformat()
            }).eq('key', 'organization_percentage').execute()
            
            # Log the change
            _insert_audit_log(
                action='UPDATE_ORG_PERCENTAGE',
                entity_name='system_settings',
                request=request,
                entity_id='organization_percentage',
                new_data={'percentage': pct_val}
            )
            
            print(f"[DEBUG API] Successfully stored percentage {pct_val}% in system_settings")
            
            return Response({
                'success': True,
                'message': f'Organization percentage updated to {pct_val}%',
                'data': {
                    'organization_percentage': pct_val,
                    'driver_percentage': 100 - pct_val
                }
            })
            
        except Exception as e:
            print(f"[DEBUG API] Error in update_organization_percentage: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=500)

    def retrieve(self, request, pk=None):
        actor = _actor_from_request(request)
        res = supabase.table("payouts").select(
            "id, driver_id, driver_name, total_amount, payout_method, payout_date, remarks, status "
        ).eq("id", str(pk)).limit(1).execute()
        data = (res.data or [])
        if not data:
            resp = Response({"detail": "Not found.", "actor": actor}, status=404)
            return _add_actor_headers(resp, actor)
        payload = data[0]
        payload["actor"] = actor
        resp = Response(payload)
        return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["get"])
    def pending(self, request):
        actor = _actor_from_request(request)
        try:
            payouts = self._pending_payouts()
            resp = Response(payouts if payouts else [])
            return _add_actor_headers(resp, actor)
        except Exception as e:
            logger.error(f"Error in pending payouts: {e}")
            resp = Response([], status=200)
            return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["get"])
    def released(self, request):
        actor = _actor_from_request(request)
        items = self._released_payouts()
        resp = Response(items)
        return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["get"])
    def tour_package_earnings(self, request):
        """Ultra-minimal endpoint to prevent JSON truncation"""
        actor = _actor_from_request(request)
        try:
            resp = Response({
                'success': True,
                'data': {
                    'earnings': [],
                    'statistics': {
                        'total_driver_earnings': 0,
                        'count': 0
                    }
                },
                'actor': actor
            })
            return _add_actor_headers(resp, actor)
        except Exception as e:
            resp = Response({'success': False, 'error': str(e), 'actor': actor}, status=500)
            return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["get"])
    def mobile_earnings(self, request):
        """Mobile app earnings with date filtering support"""
        actor = _actor_from_request(request)
        try:
            qp = getattr(request, "query_params", request.GET)
            driver_id = qp.get("driver_id")
            date_from = qp.get("date_from")
            date_to = qp.get("date_to")
            
            # Build query
            q = supabase.table("earnings").select("*")
            
            # Filter by driver if specified
            if driver_id:
                q = q.eq("driver_id", str(driver_id))
            
            # Filter by date range if specified
            if date_from:
                q = q.gte("earning_date", date_from)
            if date_to:
                q = q.lt("earning_date", date_to)
            
            # Execute query
            response = q.execute()
            earnings_rows = response.data if hasattr(response, 'data') else []
            
            # Calculate total ride hailing earnings across all time (not filtered by date)
            total_ride_hailing_query = supabase.table("earnings").select("*")
            if driver_id:
                total_ride_hailing_query = total_ride_hailing_query.eq("driver_id", str(driver_id))
            total_ride_hailing_response = total_ride_hailing_query.execute()
            all_earnings_rows = total_ride_hailing_response.data if hasattr(total_ride_hailing_response, 'data') else []
            
            total_ride_hailing_earnings = Decimal('0.00')
            for row in all_earnings_rows:
                if (row.get("status") or "").lower() == REVERSED_STATUS:
                    continue
                booking_type = row.get('booking_type', 'tour_package')
                is_ride_hailing = booking_type == 'ride_hailing' or bool(row.get('ride_hailing_booking_id'))
                if is_ride_hailing:
                    total, admin_e, driver_e = _split_amount(row)
                    total_ride_hailing_earnings += driver_e
            
            # Filter out reversed earnings and calculate totals
            valid_earnings = []
            total_driver_earnings = Decimal('0.00')
            total_revenue = Decimal('0.00')
            custom_booking_earnings = Decimal('0.00')
            ride_hailing_earnings = Decimal('0.00')
            
            for row in earnings_rows:
                if (row.get("status") or "").lower() == REVERSED_STATUS:
                    continue
                    
                total, admin_e, driver_e = _split_amount(row)
                total_revenue += total
                total_driver_earnings += driver_e
                
                # Check booking type
                booking_type = row.get('booking_type', 'tour_package')
                is_custom = bool(row.get('custom_tour_id'))
                is_ride_hailing = booking_type == 'ride_hailing' or bool(row.get('ride_hailing_booking_id'))
                
                if is_custom:
                    custom_booking_earnings += driver_e
                elif is_ride_hailing:
                    ride_hailing_earnings += driver_e
                
                valid_earnings.append({
                    'id': row.get('id'),
                    'booking_id': row.get('booking_id'),
                    'package_name': row.get('package_name', 'Tour Package'),
                    'earning_date': row.get('earning_date'),
                    'total_amount': float(total),
                    'driver_earnings': float(driver_e),
                    'admin_earnings': float(admin_e),
                    'status': row.get('status'),
                    'is_custom_booking': bool(row.get('custom_tour_id'))
                })
            
            resp = Response({
                'success': True,
                'data': {
                    'earnings': valid_earnings,
                    'statistics': {
                        'total_revenue': float(total_revenue),
                        'total_driver_earnings': float(total_driver_earnings),
                        'total_admin_earnings': float(total_revenue - total_driver_earnings),
                        'admin_percentage': float(get_organization_percentage() * 100),
                        'driver_percentage': float((Decimal("1.00") - get_organization_percentage()) * 100),
                        'count': len(valid_earnings),
                        'avg_earning_per_booking': float(total_driver_earnings / len(valid_earnings)) if valid_earnings else 0,
                        'custom_booking_earnings': float(custom_booking_earnings),
                        'ride_hailing_earnings': float(ride_hailing_earnings),
                        'total_ride_hailing_earnings': float(total_ride_hailing_earnings)
                    }
                },
                'actor': actor
            })
            return _add_actor_headers(resp, actor)
        except Exception as e:
            logger.error(f"Error in mobile_earnings: {e}")
            resp = Response({'success': False, 'error': str(e), 'actor': actor}, status=500)
            return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["get"])
    def driver_earnings(self, request):
        actor = _actor_from_request(request)
        try:
            response = supabase.table('earnings').select('*').execute()
            earnings_rows = response.data if hasattr(response, 'data') else []

            driver_map = defaultdict(lambda: {
                'driver_id': '',
                'driver_name': '',
                'total_bookings': 0,
                'total_revenue': Decimal('0.00'),
                'total_driver_earnings': Decimal('0.00'),
                'total_admin_earnings': Decimal('0.00'),
                'bookings': []
            })

            for row in earnings_rows:
                if (row.get("status") or "").lower() == REVERSED_STATUS:
                    continue

                driver_id = row.get('driver_id')
                if not driver_id:
                    continue

                total, admin_e, driver_e = _split_amount(row)
                driver_data = driver_map[driver_id]
                driver_data['driver_id'] = driver_id
                driver_data['driver_name'] = row.get('driver_name', 'Unknown')
                driver_data['total_bookings'] += 1
                driver_data['total_revenue'] += total
                driver_data['total_driver_earnings'] += driver_e
                driver_data['total_admin_earnings'] += admin_e
                driver_data['bookings'].append({
                    'booking_id': row.get('booking_id'),
                    'package_name': row.get('package_name', 'Tour Package'),
                    'earning_date': row.get('earning_date'),
                    'total_amount': float(total),
                    'driver_earnings': float(driver_e)
                })

            result = []
            for driver_data in driver_map.values():
                result.append({
                    'driver_id': driver_data['driver_id'],
                    'driver_name': driver_data['driver_name'],
                    'total_bookings': driver_data['total_bookings'],
                    'total_revenue': float(driver_data['total_revenue']),
                    'total_driver_earnings': float(driver_data['total_driver_earnings']),
                    'total_admin_earnings': float(driver_data['total_admin_earnings']),
                    'total_revenue_formatted': f"₱{driver_data['total_revenue']:,.2f}",
                    'total_driver_earnings_formatted': f"₱{driver_data['total_driver_earnings']:,.2f}",
                    'recent_bookings': sorted(driver_data['bookings'], key=lambda x: x.get('earning_date', ''), reverse=True)[:5]
                })

            result.sort(key=lambda x: x['total_driver_earnings'], reverse=True)
            resp = Response({'success': True, 'data': result, 'count': len(result), 'actor': actor})
            return _add_actor_headers(resp, actor)

        except Exception as e:
            logger.error(f'Error fetching driver earnings summary: {str(e)}')
            resp = Response({'success': False, 'error': 'Failed to fetch driver earnings summary', 'data': [], 'actor': actor}, status=500)
            return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["get"])
    def sales_report(self, request):
        """
        Sales report grouped by week / month / year using earnings (bookings that generated earnings).
        """
        actor = _actor_from_request(request)
        try:
            qp = getattr(request, "query_params", request.GET)
            date_from = (qp.get("date_from") or "").strip()
            date_to   = (qp.get("date_to") or "").strip()
            group_by  = (qp.get("group_by") or "monthly").lower().strip()

            tz_mnl = ZoneInfo("Asia/Manila")

            def _parse_date(d):
                if not d: return None
                return datetime.fromisoformat(d).replace(tzinfo=tz_mnl, hour=0, minute=0, second=0, microsecond=0)

            # Smart defaults based on group_by
            now_mnl = datetime.now(tz_mnl)
            if group_by == "yearly":
                if not date_from or not date_to:
                    start = datetime(now_mnl.year - 4, 1, 1, tzinfo=tz_mnl)
                    end   = datetime(now_mnl.year, 12, 31, 0, 0, 0, tzinfo=tz_mnl)
                else:
                    start = _parse_date(date_from)
                    end   = _parse_date(date_to)
            elif group_by == "weekly":
                if not date_from or not date_to:
                    # Start from 1st day of current month
                    start = datetime(now_mnl.year, now_mnl.month, 1, tzinfo=tz_mnl)
                    # End at last day of current month
                    if now_mnl.month == 12:
                        end = datetime(now_mnl.year, 12, 31, tzinfo=tz_mnl)
                    else:
                        end = datetime(now_mnl.year, now_mnl.month + 1, 1, tzinfo=tz_mnl) - timedelta(days=1)
                else:
                    start = _parse_date(date_from)
                    end   = _parse_date(date_to)
            elif group_by == "daily":
                if not date_from or not date_to:
                    # Start from 1st day of current month
                    start = datetime(now_mnl.year, now_mnl.month, 1, tzinfo=tz_mnl)
                    # End at last day of current month
                    if now_mnl.month == 12:
                        end = datetime(now_mnl.year, 12, 31, tzinfo=tz_mnl)
                    else:
                        end = datetime(now_mnl.year, now_mnl.month + 1, 1, tzinfo=tz_mnl) - timedelta(days=1)
                else:
                    start = _parse_date(date_from)
                    end   = _parse_date(date_to)
            else:
                # Monthly: start from 1st day of year, end at last day of year
                if not date_from or not date_to:
                    start = datetime(now_mnl.year, 1, 1, tzinfo=tz_mnl)
                    end   = datetime(now_mnl.year, 12, 31, tzinfo=tz_mnl)
                else:
                    start = _parse_date(date_from)
                    end   = _parse_date(date_to)

            if not start or not end:
                end = now_mnl.replace(hour=0, minute=0, second=0, microsecond=0)
                start_month = (end.month - 3) % 12 or 12
                start_year  = end.year if end.month > 3 else end.year - 1
                start = end.replace(year=start_year, month=start_month, day=1)

            end_inclusive = end + timedelta(days=1)
            start_utc = start.astimezone(timezone.utc).isoformat()
            end_utc   = end_inclusive.astimezone(timezone.utc).isoformat()

            q = (
                supabase.table("earnings")
                .select("id, amount, earning_date, status, custom_tour_id")
                .gte("earning_date", start_utc)
                .lt("earning_date", end_utc)
            )
            try:
                q = q.is_("custom_tour_id", None)
            except Exception:
                q = q.filter("custom_tour_id", "is", None)

            resp_q = q.execute()
            rows = (getattr(resp_q, "data", None) or [])

            def _to_local(dt_str):
                if not dt_str: return None
                s = str(dt_str)
                if s.endswith("Z"):
                    s = s.replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.astimezone(tz_mnl)
                except Exception:
                    return None

            from collections import OrderedDict

            def _month_iter(a, b):
                cur = datetime(a.year, a.month, 1, tzinfo=tz_mnl)
                end_m = datetime(b.year, b.month, 1, tzinfo=tz_mnl)
                while cur <= end_m:
                    yield cur
                    y, m = cur.year, cur.month
                    cur = cur.replace(year=y + (1 if m == 12 else 0), month=(1 if m == 12 else m + 1))

            def _year_iter(a, b):
                cur = datetime(a.year, 1, 1, tzinfo=tz_mnl)
                end_y = datetime(b.year, 1, 1, tzinfo=tz_mnl)
                while cur <= end_y:
                    yield cur
                    cur = cur.replace(year=cur.year + 1)

            def _day_iter(a, b):
                cur = datetime(a.year, a.month, a.day, tzinfo=tz_mnl)
                end_d = datetime(b.year, b.month, b.day, tzinfo=tz_mnl)
                while cur <= end_d:
                    yield cur
                    cur = cur + timedelta(days=1)

            buckets = OrderedDict()

            if group_by == "yearly":
                for y in _year_iter(start, end):
                    key = f"{y.year}"
                    buckets.setdefault(key, {"sales": Decimal("0.00"), "count": 0, "cancels": 0, "cancel_amt": Decimal("0.00")})
            elif group_by == "weekly":
                # Create weekly buckets starting from Monday
                current = start
                # Adjust to start from Monday
                days_since_monday = current.weekday()
                current = current - timedelta(days=days_since_monday)
                
                week_num = 1
                while current <= end:
                    # Find the end of this week (Sunday) - allow crossing month boundaries
                    week_end = current + timedelta(days=6)
                    key = f"Week {week_num} ({current.strftime('%b %d')}-{week_end.strftime('%b %d') if week_end.month != current.month else week_end.strftime('%d')})"
                    buckets.setdefault(key, {"sales": Decimal("0.00"), "count": 0, "cancels": 0, "cancel_amt": Decimal("0.00")})
                    current = current + timedelta(days=7)
                    week_num += 1
            elif group_by == "daily":
                # Create daily buckets for each day in the month (1st to last day)
                month_start = start.replace(day=1)
                if start.month == 12:
                    month_end = datetime(start.year + 1, 1, 1, tzinfo=tz_mnl) - timedelta(days=1)
                else:
                    month_end = datetime(start.year, start.month + 1, 1, tzinfo=tz_mnl) - timedelta(days=1)
                
                # Update start and end to match month boundaries for data fetching
                start = month_start
                end = month_end
                
                for d in _day_iter(month_start, month_end):
                    key = d.strftime("%b %d")
                    buckets.setdefault(key, {"sales": Decimal("0.00"), "count": 0, "cancels": 0, "cancel_amt": Decimal("0.00")})
            else:
                # Monthly: ensure we start from 1st and end at last day of each month
                for m in _month_iter(start, end):
                    key = f"{m.year}-{m.month:02d}"
                    buckets.setdefault(key, {"sales": Decimal("0.00"), "count": 0, "cancels": 0, "cancel_amt": Decimal("0.00")})

            for r in rows:
                amt = _safe_decimal(r.get("amount"))
                dt_local = _to_local(r.get("earning_date"))
                if not dt_local:
                    continue

                if group_by == "yearly":
                    key = f"{dt_local.year}"
                elif group_by == "weekly":
                    # Find which week this date belongs to (starting from Monday)
                    # Adjust start to Monday
                    monday_start = start - timedelta(days=start.weekday())
                    days_from_monday = (dt_local.date() - monday_start.date()).days
                    week_num = (days_from_monday // 7) + 1
                    week_start = monday_start + timedelta(days=(week_num-1)*7)
                    week_end = week_start + timedelta(days=6)
                    key = f"Week {week_num} ({week_start.strftime('%b %d')}-{week_end.strftime('%b %d') if week_end.month != week_start.month else week_end.strftime('%d')})"
                elif group_by == "daily":
                    key = dt_local.strftime("%b %d")
                else:
                    key = f"{dt_local.year}-{dt_local.month:02d}"

                if key not in buckets:
                    buckets[key] = {"sales": Decimal("0.00"), "count": 0, "cancels": 0, "cancel_amt": Decimal("0.00")}

                if (str(r.get("status") or "")).lower().strip() == REVERSED_STATUS:
                    buckets[key]["cancels"] += 1
                    buckets[key]["cancel_amt"] += amt
                else:
                    buckets[key]["sales"] += amt
                    buckets[key]["count"] += 1

            labels = list(buckets.keys())
            sales  = [float(_q2(v["sales"])) for v in buckets.values()]
            books  = [int(v["count"]) for v in buckets.values()]
            avg    = [float(_q2((Decimal(str(s or 0))) / (Decimal(b) if b else Decimal("1")))) for s, b in zip(sales, books)]
            canc   = [int(v["cancels"]) for v in buckets.values()]
            canc_amt = [float(_q2(v["cancel_amt"])) for v in buckets.values()]

            out = {
                "labels": labels,
                "sales": sales,
                "bookings": books,
                "avg": avg,
                "cancellations": canc,
                "cancellations_amount": canc_amt,
                "total_sales": float(_q2(sum(Decimal(str(x or 0)) for x in sales))),
                "total_bookings": int(sum(books)),
                "total_cancellations": int(sum(canc)),
                "total_cancellations_amount": float(_q2(sum(Decimal(str(x or 0)) for x in canc_amt))),
            }

            # KEEP: Viewing the sales report
            _insert_audit_log(
                action="SALES_REPORT_VIEW",
                entity_name="earnings",
                request=request,
                new_data={"group_by": group_by, "date_from": date_from, "date_to": date_to}
            )
            resp = Response({"success": True, "data": out, "actor": actor})
            return _add_actor_headers(resp, actor)
        except Exception as e:
            logger.error("sales_report error: %s", e)
            resp = Response({"success": False, "error": "Failed to build sales report", "actor": actor}, status=500)
            return _add_actor_headers(resp, actor)

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        actor = _actor_from_request(request)
        remarks = (request.data or {}).get("remarks")
        payout = self._mark_payouts_as_released([str(pk)], remarks=remarks, request=request)
        if not payout:
            resp = Response({"success": False, "error": "No matching payout found", "actor": actor}, status=404)
            return _add_actor_headers(resp, actor)
        resp = Response({"success": True, "payout": payout, "actor": actor})
        return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["post"])
    def create_driver_payout(self, request):
        actor = _actor_from_request(request)
        try:
            data = request.data if hasattr(request, 'data') else request.POST.dict()
            driver_id = data.get('driver_id')
            if not driver_id:
                resp = Response({'success': False, 'error': 'driver_id is required', 'actor': actor}, status=400)
                return _add_actor_headers(resp, actor)

            earnings_response = supabase.table('earnings').select('*').execute()
            all_earnings = earnings_response.data if hasattr(earnings_response, 'data') else []
            earnings = [e for e in all_earnings if (e.get("status") or "").lower() != REVERSED_STATUS]
            if not earnings:
                resp = Response({'success': False, 'error': 'No earnings found for this driver', 'actor': actor}, status=404)
                return _add_actor_headers(resp, actor)

            existing_payout = supabase.table('payouts').select('*').eq('driver_id', driver_id).eq('status', 'pending').execute()
            if hasattr(existing_payout, 'data') and existing_payout.data:
                resp = Response({'success': False, 'error': 'Driver already has a pending payout', 'actor': actor}, status=400)
                return _add_actor_headers(resp, actor)

            total_driver_earnings = sum(Decimal(str(e.get('driver_earnings', 0))) for e in earnings)
            if total_driver_earnings <= 0:
                resp = Response({'success': False, 'error': 'No earnings available for payout', 'actor': actor}, status=400)
                return _add_actor_headers(resp, actor)

            driver_name = earnings[0].get('driver_name', 'Unknown Driver') if earnings else 'Unknown Driver'
            payout_data = {
                'driver_id': driver_id,
                'driver_name': driver_name,
                'total_amount': float(total_driver_earnings),
                'payout_method': data.get('payout_method', 'cash'),
                'status': 'pending',
                'remarks': data.get('remarks', f'Payout for {len(earnings)} completed tour bookings'),
                'created_at': datetime.now(ZoneInfo('Asia/Manila')).isoformat()
            }
            payout_response = supabase.table('payouts').insert(payout_data).execute()
            if hasattr(payout_response, 'data') and payout_response.data:
                row = payout_response.data[0]
                resp = Response({
                    'success': True,
                    'data': row,
                    'message': f'Payout created for {driver_name}: ₱{total_driver_earnings:,.2f}',
                    'actor': actor
                })
                return _add_actor_headers(resp, actor)
            else:
                resp = Response({'success': False, 'error': 'Failed to create payout', 'actor': actor}, status=500)
                return _add_actor_headers(resp, actor)

        except Exception as e:
            logger.error(f'Error creating driver payout: {str(e)}')
            resp = Response({'success': False, 'error': str(e), 'actor': actor}, status=500)
            return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["get"])
    def notifications(self, request):
        # Ensure we always include actor info in body + headers
        actor = _actor_from_request(request)
        try:
            token = get_token_from_request(request)
            if not token:
                resp = Response({'success': False, 'error': 'Authentication required', 'actor': actor}, status=401)
                return _add_actor_headers(resp, actor)

            user = verify_token(token)
            if not user:
                resp = Response({'success': False, 'error': 'Invalid token', 'actor': actor}, status=401)
                return _add_actor_headers(resp, actor)

            user_role = user.user_metadata.get('role') if getattr(user, "user_metadata", None) else None
            if user_role not in ['driver', 'driver-owner']:
                resp = Response({'success': False, 'error': 'Access denied', 'actor': actor}, status=403)
                return _add_actor_headers(resp, actor)

            driver_id = getattr(user, "id", None)

            qp = getattr(request, "query_params", request.GET)
            try:
                limit = int(qp.get("limit")) if qp.get("limit") is not None else 5
            except Exception:
                limit = 5
            limit = max(1, min(limit, 50))

            items = []

            q_rel = supabase.table("payouts").select(
                "id, driver_id, driver_name, total_amount, payout_date, remarks, status, updated_at, created_at"
            ).eq("status", "released").order("payout_date", desc=True).limit(limit * 3)
            if driver_id:
                q_rel = q_rel.eq("driver_id", str(driver_id))
            rel = q_rel.execute()
            for r in (rel.data or []):
                ts = _parse_iso_dt(r.get("payout_date")) or _parse_iso_dt(r.get("updated_at")) or _parse_iso_dt(r.get("created_at"))
                items.append({
                    "id": f"payout_released:{r.get('id')}",
                    "type": "payout_released",
                    "title": "Payout released",
                    "message": f"Payout of ₱{_safe_decimal(r.get('total_amount')):,.2f} has been released.",
                    "amount": float(_safe_decimal(r.get("total_amount"))),
                    "generated_at": _to_mnl_iso(ts),
                    "meta": {
                        "payout_id": r.get("id"),
                        "driver_id": r.get("driver_id"),
                        "driver_name": r.get("driver_name"),
                        "remarks": r.get("remarks"),
                    },
                })

            q_pen = supabase.table("payouts").select(
                "id, driver_id, driver_name, total_amount, remarks, status, updated_at, created_at"
            ).eq("status", "pending").order("updated_at", desc=True).limit(limit * 3)
            if driver_id:
                q_pen = q_pen.eq("driver_id", str(driver_id))
            pen = q_pen.execute()
            for r in (pen.data or []):
                ts = _parse_iso_dt(r.get("updated_at")) or _parse_iso_dt(r.get("created_at"))
                items.append({
                    "id": f"payout_pending:{r.get('id')}",
                    "type": "payout_pending_updated",
                    "title": "Pending payout updated",
                    "message": f"Pending payout is now ₱{_safe_decimal(r.get('total_amount')):,.2f}.",
                    "amount": float(_safe_decimal(r.get("total_amount"))),
                    "generated_at": _to_mnl_iso(ts),
                    "meta": {
                        "payout_id": r.get("id"),
                        "driver_id": r.get("driver_id"),
                        "driver_name": r.get("driver_name"),
                        "remarks": r.get("remarks"),
                    },
                })

            q_e = supabase.table("earnings").select(
                "id, driver_id, driver_name, amount, driver_earnings, package_name, earning_date, status, created_at"
            ).order("earning_date", desc=True).limit(limit * 3)
            if driver_id:
                q_e = q_e.eq("driver_id", str(driver_id))
            e_rows = q_e.execute()
            for r in (e_rows.data or []):
                if (str(r.get("status") or "")).lower() == REVERSED_STATUS:
                    continue
                ts = _parse_iso_dt(r.get("created_at")) or _parse_iso_dt(r.get("earning_date"))
                amt_driver = _safe_decimal(r.get("driver_earnings"))
                amt_total = _safe_decimal(r.get("amount"))
                shown = amt_driver if amt_driver > Decimal("0") else amt_total
                items.append({
                    "id": f"earning:{r.get('id')}",
                    "type": "earning_added",
                    "title": "New earning added",
                    "message": f"New earning of ₱{shown:,.2f} recorded.",
                    "amount": float(shown),
                    "generated_at": _to_mnl_iso(ts),
                    "meta": {
                        "earning_id": r.get("id"),
                        "driver_id": r.get("driver_id"),
                        "driver_name": r.get("driver_name"),
                        "package_name": r.get("package_name"),
                        "status": r.get("status"),
                    },
                })

            def _key(it):
                return _parse_iso_dt(it.get("generated_at")) or datetime.now(_TZ_UTC)
            items.sort(key=_key, reverse=True)
            items = items[:limit]

            resp = Response({"success": True, "data": items, "count": len(items), "actor": actor})
            return _add_actor_headers(resp, actor)

        except Exception as e:
            logger.error("notifications error: %s", e)
            resp = Response({"success": False, "data": [], "error": "Failed to fetch notifications", "actor": actor}, status=500)
            return _add_actor_headers(resp, actor)

    # ------------------------ internal helpers ------------------------

    def _recalculate_pending_payouts(self, new_percentage):
        """Recalculate pending payout amounts when organization percentage changes"""
        try:
            # Get all pending payouts
            pending_payouts = supabase.table("payouts").select("*").eq("status", "pending").execute()
            
            for payout in (pending_payouts.data or []):
                payout_id = payout["id"]
                driver_id = payout["driver_id"]
                
                # Get all payout_earnings for this payout
                pe_response = supabase.table("payout_earnings").select("*").eq("payout_id", payout_id).eq("status", "pending").execute()
                
                new_total = Decimal("0.00")
                
                # Recalculate each payout_earning
                for pe in (pe_response.data or []):
                    earning_id = pe["earning_id"]
                    
                    # Get the earnings record to recalculate
                    earning_response = supabase.table("earnings").select("*").eq("id", earning_id).execute()
                    if earning_response.data:
                        earning = earning_response.data[0]
                        total_amount = _safe_decimal(earning.get("total_amount")) or _safe_decimal(earning.get("amount"))
                        
                        # Calculate new driver share with updated percentage
                        new_driver_percentage = Decimal("1.00") - (Decimal(str(new_percentage)) / 100)
                        new_driver_share = _q2(total_amount * new_driver_percentage)
                        
                        # Update payout_earnings with new amount
                        supabase.table("payout_earnings").update({
                            "share_amount": float(new_driver_share)
                        }).eq("id", pe["id"]).execute()
                        
                        new_total += new_driver_share
                
                # Update payout total
                supabase.table("payouts").update({
                    "total_amount": float(_q2(new_total))
                }).eq("id", payout_id).execute()
                
                logger.info(f"Recalculated payout {payout_id} for driver {driver_id}: new total = {new_total}")
                
        except Exception as e:
            logger.error(f"Error recalculating pending payouts: {e}")

    def _get_totals(self):
        """Calculate totals from earnings with booking_id only, using organization_percentage column from each record"""
        earnings_res = supabase.table("earnings").select("*").not_.is_("booking_id", "null").execute()
        gross = Decimal("0.00")
        admin_total = Decimal("0.00")
        driver_total = Decimal("0.00")

        for row in (getattr(earnings_res, 'data', None) or []):
            if (str(row.get("status") or "").lower() == REVERSED_STATUS):
                continue
            if not row.get("booking_id"):
                continue
            
            # Use _split_amount which handles the percentage logic correctly
            total, admin_share, driver_share = _split_amount(row)
            gross += total
            admin_total += admin_share
            driver_total += driver_share

        return {"gross_total": _q2(gross), "admin_total": _q2(admin_total), "driver_total": _q2(driver_total)}

    def _get_monthly_total_income(self, start_year=2025, start_month=1):
        res = supabase.table("earnings").select("amount, earning_date, status").execute()
        rows = res.data or []

        by_month = defaultdict(Decimal)
        for r in rows:
            if (str(r.get("status") or "").lower() == REVERSED_STATUS):
                continue
            amt = _safe_decimal(r.get("amount", 0))
            ts = r.get("earning_date")
            dt = None
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except Exception:
                    dt = None
            if not dt:
                continue
            key = dt.strftime("%Y-%m")
            by_month[key] += amt

        now = datetime.now(timezone.utc)
        year, month = start_year, start_month
        series = []
        while (year < now.year) or (year == now.year and month <= now.month):
            key = f"{year:04d}-{month:02d}"
            series.append({"month": key, "total_amount": float(by_month.get(key, Decimal("0.00")))})
            month += 1
            if month == 13:
                month, year = 1, year + 1
        return series

    def _get_daily_total_income(self, year: int, month: int):
        res = supabase.table("earnings").select("amount, earning_date, status").execute()
        rows = res.data or []

        by_day = defaultdict(Decimal)
        for r in rows:
            if (str(r.get("status") or "").lower() == REVERSED_STATUS):
                continue
            amt = _safe_decimal(r.get("amount", 0))
            ts = r.get("earning_date")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                continue

            if dt.year == year and dt.month == month:
                key = dt.strftime("%Y-%m-%d")
                by_day[key] += amt

        first_day = datetime(year, month, 1)
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        delta = (next_month - first_day).days

        series = []
        for i in range(delta):
            day = first_day + timedelta(days=i)
            key = day.strftime("%Y-%m-%d")
            series.append({"date": key, "total_amount": float(by_day.get(key, Decimal("0.00")))})
        return series

    def _get_total_admin_income(self):
        res = supabase.table("earnings").select("admin_earnings, status").execute()
        total_income = Decimal("0.00")
        if hasattr(res, "data"):
            for e in (res.data or []):
                if (str(e.get("status") or "").lower() == REVERSED_STATUS):
                    continue
                total_income += _safe_decimal(e.get("admin_earnings", 0))
        return total_income

    def _pending_payouts(self):
        try:
            res = execute_with_retry(lambda: supabase.table("payouts").select(
                "id, driver_id, driver_name, total_amount, payout_date, remarks, status"
            ).eq("status", "pending").limit(5).execute())
            return res.data or []
        except Exception as e:
            logger.error(f"Error fetching pending payouts: {e}")
            return []

    def _released_payouts(self):
        res = supabase.table("payouts").select(
            "id, driver_id, driver_name, total_amount, payout_date, remarks, status"
        ).eq("status", "released").order("payout_date", desc=True).execute()
        return res.data or []

    def _mark_payouts_as_released(self, payout_ids, remarks=None, request=None):
        """
        Marks payout(s) as released and audits each change with old/new snapshots.
        (KEEP audit log here)
        """
        if isinstance(payout_ids, str):
            payout_ids = [payout_ids]
        elif isinstance(payout_ids, list):
            payout_ids = [str(pid) for pid in payout_ids]
        else:
            return None

        # fetch old rows
        old_rows_res = supabase.table("payouts") \
            .select("id, driver_id, driver_name, total_amount, status, payout_date, remarks") \
            .in_("id", payout_ids).execute()
        old_rows_map = {str(r["id"]): r for r in (old_rows_res.data or [])}

        manila_tz = ZoneInfo('Asia/Manila')
        update_payload = {"status": "released", "payout_date": datetime.now(manila_tz).isoformat()}
        if remarks is not None:
            update_payload["remarks"] = remarks

        supabase.table("payouts").update(update_payload).in_("id", payout_ids).execute()

        payout_res = supabase.table("payouts") \
            .select("id, driver_id, driver_name, total_amount, status, payout_date, remarks") \
            .in_("id", payout_ids) \
            .order("payout_date", desc=True) \
            .limit(1) \
            .execute()

        if not payout_res.data:
            return None

        # KEEP: audit each payout we touched
        for new_row in payout_res.data:
            pid = str(new_row.get("id"))
            _insert_audit_log(
                action="PAYOUT_RELEASED",
                entity_name="payouts",
                request=request,
                entity_id=pid,
                old_data=old_rows_map.get(pid),
                new_data=new_row
            )

        # return last one (keeps API behavior)
        return payout_res.data[0]

    def _get_hourly_income(self, now_local: datetime, tz_name: str = "Asia/Manila"):
        DEBUG = True
        tz = ZoneInfo(tz_name)
        utc = ZoneInfo("UTC")

        now_local = now_local.astimezone(tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local   = start_local + timedelta(days=1)

        wide_start_local = start_local - timedelta(days=1)
        wide_end_local   = end_local + timedelta(days=1)
        start_utc = wide_start_local.astimezone(utc).isoformat()
        end_utc   = wide_end_local.astimezone(utc).isoformat()

        if DEBUG:
            print(f"[HOUR] tz_name              = {tz_name}")
            print(f"[HOUR] today local window   = {start_local.isoformat()} → {end_local.isoformat()}")
            print(f"[HOUR] WIDE UTC fetch win   = {start_utc} → {end_utc}")

        q = (
            supabase.table("earnings")
            .select("id, amount, earning_date, status, custom_tour_id, booking_id")
            .gte("earning_date", start_utc)
            .lt("earning_date", end_utc)
        )
        try:
            q = q.is_("custom_tour_id", None).not_.is_("booking_id", None)
        except Exception as e:
            if DEBUG: print("[HOUR] .is_ unavailable, fallback .filter:", e)
            q = q.filter("custom_tour_id", "is", None).filter("booking_id", "not.is", None)

        resp = q.execute()
        rows = (getattr(resp, "data", None) or [])
        if DEBUG:
            print("[HOUR] fetched rows (wide)   =", len(rows))
            if rows[:5]: print("[HOUR] sample rows        =", rows[:5])

        buckets = [0.0] * 24
        skipped_reversed = bad_ts = outside_today = 0
        traced = 0
        traced_outside = 0

        for r in rows:
            if str(r.get("status") or "").lower() == "reversed":
                skipped_reversed += 1
                continue

            # Only include earnings with booking_id (not null)
            if not r.get("booking_id"):
                continue

            amt = float(r.get("amount") or 0)
            ts  = r.get("earning_date")
            if not ts:
                bad_ts += 1
                continue

            raw = _parse_iso_dt(ts)
            if not raw:
                bad_ts += 1
                continue

            # Correct timezone handling: convert to local via astimezone
            if raw.tzinfo is None:
                raw = raw.replace(tzinfo=utc)
            dt_local = raw.astimezone(tz)

            if not (start_local <= dt_local < end_local):
                outside_today += 1
                if DEBUG and traced_outside < 4:
                    print(f"[HOUR] outside-today raw={raw.isoformat()} -> local={dt_local.isoformat()}")
                    traced_outside += 1
                continue

            h = dt_local.hour
            buckets[h] += amt

            if DEBUG and traced < 6:
                print(f"[HOUR] + row {r.get('id')} raw={raw.isoformat()} -> local={dt_local.isoformat()} h={h} amt={amt}")
                traced += 1

        if DEBUG:
            print("[HOUR] skipped_reversed  =", skipped_reversed)
            print("[HOUR] bad_ts            =", bad_ts)
            print("[HOUR] outside_today     =", outside_today)
            print("[HOUR] buckets           =", buckets)

        return [{"hour": h, "total_amount": round(buckets[h], 2)} for h in range(24)]

    @action(detail=False, methods=['get'], url_path='pending-count')
    def pending_count(self, request):
        try:
            res = execute_with_retry(
                lambda: supabase.table('payouts').select('id', count='exact').eq('status', 'pending').execute(),
                max_retries=2,
                delay=0.25
            )
            count = (getattr(res, 'count', None) or (len(res.data or [])))
            return Response({'count': int(count)})
        except Exception as e:
            logger.warning("pending-count failed: %s", e)
            return Response({'count': 0})

    @action(detail=False, methods=["get"])
    def weekly_activity(self, request):
        """Weekly activity data for driver dashboard chart"""
        actor = _actor_from_request(request)
        try:
            qp = getattr(request, "query_params", request.GET)
            driver_id = qp.get("driver_id")
            
            if not driver_id:
                resp = Response({'success': False, 'error': 'driver_id is required', 'actor': actor}, status=400)
                return _add_actor_headers(resp, actor)
            
            # Get current week (Monday to Sunday)
            tz_mnl = ZoneInfo("Asia/Manila")
            now_mnl = datetime.now(tz_mnl)
            
            # Find Monday of current week
            days_since_monday = now_mnl.weekday()
            monday = now_mnl - timedelta(days=days_since_monday)
            monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Generate 7 days from Monday
            week_data = []
            day_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            
            for i in range(7):
                day = monday + timedelta(days=i)
                day_end = day + timedelta(days=1)
                
                # Convert to UTC for database query
                day_utc = day.astimezone(timezone.utc).isoformat()
                day_end_utc = day_end.astimezone(timezone.utc).isoformat()
                
                # Query earnings for this day
                earnings_q = supabase.table("earnings").select("*") \
                    .eq("driver_id", str(driver_id)) \
                    .gte("earning_date", day_utc) \
                    .lt("earning_date", day_end_utc)
                
                earnings_resp = earnings_q.execute()
                earnings_rows = earnings_resp.data if hasattr(earnings_resp, 'data') else []
                
                # Query bookings for trip count
                bookings_q = supabase.table("bookings").select("id, total_amount, custom_tour_id") \
                    .eq("driver_id", str(driver_id)) \
                    .eq("status", "completed") \
                    .gte("updated_at", day_utc) \
                    .lt("updated_at", day_end_utc)
                
                bookings_resp = bookings_q.execute()
                bookings_rows = bookings_resp.data if hasattr(bookings_resp, 'data') else []
                
                # Calculate metrics
                trips = len(bookings_rows)
                gross = sum(_safe_decimal(row.get('total_amount', 0)) for row in bookings_rows)
                custom_bookings = sum(
                    _safe_decimal(row.get('total_amount', 0)) * Decimal('0.8') 
                    for row in bookings_rows 
                    if row.get('custom_tour_id')
                )
                
                week_data.append({
                    'label': day_labels[i],
                    'date': day.strftime('%Y-%m-%d'),
                    'trips': trips,
                    'gross': float(gross),
                    'customBookings': float(custom_bookings)
                })
            
            resp = Response({
                'success': True,
                'data': week_data,
                'actor': actor
            })
            return _add_actor_headers(resp, actor)
            
        except Exception as e:
            logger.error(f"Error in weekly_activity: {e}")
            resp = Response({'success': False, 'error': str(e), 'actor': actor}, status=500)
            return _add_actor_headers(resp, actor)

    @action(detail=False, methods=["get"])
    def payout_history(self, request):
        """Get payout history for a specific driver"""
        actor = _actor_from_request(request)
        try:
            qp = getattr(request, "query_params", request.GET)
            driver_id = qp.get("driver_id")
            
            if not driver_id:
                resp = Response({'success': False, 'error': 'driver_id is required', 'actor': actor}, status=400)
                return _add_actor_headers(resp, actor)
            
            # Query payouts for this driver
            q = supabase.table("payouts").select(
                "id, driver_id, driver_name, total_amount, payout_date, payout_method, status, remarks"
            ).eq("driver_id", str(driver_id)).order("payout_date", desc=True)
            
            response = q.execute()
            payouts = response.data if hasattr(response, 'data') else []
            
            # Format the response
            formatted_payouts = []
            for payout in payouts:
                formatted_payouts.append({
                    'id': payout.get('id'),
                    'amount': float(_safe_decimal(payout.get('total_amount', 0))),
                    'status': payout.get('status', 'pending'),
                    'payout_date': payout.get('payout_date'),
                    'reference_number': payout.get('id'),  # Use ID as reference
                    'method': payout.get('payout_method', 'bank_transfer'),
                    'remarks': payout.get('remarks', '')
                })
            
            resp = Response({
                'success': True,
                'data': formatted_payouts,
                'count': len(formatted_payouts),
                'actor': actor
            })
            return _add_actor_headers(resp, actor)
            
        except Exception as e:
            logger.error(f"Error in payout_history: {e}")
            resp = Response({'success': False, 'error': str(e), 'actor': actor}, status=500)
            return _add_actor_headers(resp, actor)
