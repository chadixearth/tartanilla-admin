from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .authentication import AuthenticationAPI

# --- Supabase clients (admin preferred for audit & reads) ---
from tartanilla_admin.supabase import supabase
try:
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# Optional project JWT helpers (used if present, mirrors refunds.py)
try:
    from core.jwt_auth import verify_token, get_token_from_request
except Exception:
    verify_token = None
    get_token_from_request = None

# PyJWT fallback (unsigned decode if no secret), mirrors refunds.py
try:
    import jwt  # PyJWT
except Exception:
    jwt = None

from datetime import datetime, date, timezone
import json
import logging
import os
import traceback

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Small shared helpers (aligning with refunds.py)
# ────────────────────────────────────────────────────────────
def _json_sanitize(obj):
    if isinstance(obj, dict):
        return {k: _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    return obj

def _get_client_ip(request):
    try:
        xfwd = request.META.get("HTTP_X_FORWARDED_FOR")
        if xfwd:
            return xfwd.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
    except Exception:
        return None

def _get_device_info(request):
    try:
        return request.META.get("HTTP_USER_AGENT")
    except Exception:
        return None

def _sb_for_read():
    return supabase_admin or supabase

def _sb_for_audit():
    return supabase_admin or supabase

# ────────────────────────────────────────────────────────────
# Actor extraction (copied/adapted from refunds.py)
# ────────────────────────────────────────────────────────────
def _read_bearer_token(request):
    # Authorization: Bearer <token>
    try:
        auth = request.META.get("HTTP_AUTHORIZATION") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
    except Exception:
        pass
    # Supabase cookies
    try:
        ck = request.COOKIES
        if ck:
            return ck.get("sb-access-token") or ck.get("access_token")
    except Exception:
        pass
    # Custom headers fallback
    for h in ["HTTP_X_SUPABASE_TOKEN", "HTTP_X_ACCESS_TOKEN", "HTTP_X_ACTOR_TOKEN"]:
        t = request.META.get(h)
        if t:
            return t
    return None

def _decode_jwt_best_effort(token):
    if not token or not jwt:
        return {}
    try:
        secret = os.environ.get("SUPABASE_JWT_SECRET") or os.environ.get("JWT_SECRET")
        if secret:
            return jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return {}

def _fetch_user_profile(user_id=None, email=None):
    """Enrich from public.users (FK target of audit_logs.user_id)."""
    try:
        sb = _sb_for_read()
        # Include both username and name for compatibility
        q = sb.table("users").select("id,email,username,name,role")
        if user_id:
            r = q.eq("id", str(user_id)).single().execute()
        elif email:
            r = q.eq("email", email).single().execute()
        else:
            return {}
        return getattr(r, "data", {}) or {}
    except Exception:
        return {}

def _extract_actor(request):
    """
    Resolve actor using the same multi-source strategy as in refunds.py:
    1) Admin cookies
    2) Project helpers (verify_token / get_token_from_request)
    3) Django request.user
    4) Body hints (actor block or top-level fields)
    """
    uid = uname = role = email = None

    # 1) Admin cookies from admin interface
    try:
        admin_user_id = request.COOKIES.get('admin_user_id')
        admin_email = request.COOKIES.get('admin_email')
        admin_authenticated = request.COOKIES.get('admin_authenticated')

        if admin_authenticated == '1' and admin_user_id and admin_email:
            uid = admin_user_id.strip() if admin_user_id else None
            email = admin_email.strip() if admin_email else None
            role = "admin"  # admin interface users are admins

            # try to get display name / role from DB
            db_user = _fetch_user_profile(user_id=uid)
            if db_user:
                uname = db_user.get("username") or db_user.get("name") or email
                role = db_user.get("role") or role
            else:
                uname = email
    except Exception:
        pass

    # 2) JWT helpers
    if not uid or not uname or not role:
        try:
            if get_token_from_request and verify_token:
                tok = get_token_from_request(request)
                if tok:
                    payload = verify_token(tok) or {}
                    jwt_uid = payload.get("sub") or payload.get("user_id") or payload.get("id") or payload.get("uid")
                    jwt_email = payload.get("email") or (payload.get("user_metadata") or {}).get("email")

                    uid = uid or (str(jwt_uid) if jwt_uid else None)
                    email = email or jwt_email

                    if uid:
                        db_user = _fetch_user_profile(user_id=uid)
                        if db_user:
                            uname = uname or db_user.get("username") or db_user.get("name") or email
                            role = role or db_user.get("role")
                        else:
                            um = (payload.get("user_metadata") or {}) or {}
                            uname = uname or um.get("username") or um.get("name") or um.get("full_name") or email
                            role = role or um.get("role")
        except Exception:
            pass

    # 3) Django user
    if not uid or not uname or not role:
        try:
            if getattr(request, "user", None) and getattr(request.user, "is_authenticated", False):
                uid = uid or str(getattr(request.user, "id", None) or getattr(request.user, "pk", None) or "")
                uname = uname or getattr(request.user, "username", None) or getattr(request.user, "email", None)
                email = email or getattr(request.user, "email", None)
                role = role or str(getattr(request.user, "role", None) or "admin")
        except Exception:
            pass

    # 4) Body hints (last resort)
    if not uid or not uname or not role:
        try:
            data = getattr(request, "data", {}) or {}
            actor_block = data.get("actor") or {}
            uid = uid or str(actor_block.get("user_id") or data.get("user_id") or data.get("admin_id") or "") or None
            uname = uname or actor_block.get("username") or data.get("username") or data.get("name")
            email = email or actor_block.get("email") or data.get("email")
            role = role or actor_block.get("role") or data.get("role")
        except Exception:
            pass

    if not uname:
        uname = email or "System Admin"
    if not role:
        role = "admin"

    return {"user_id": uid, "username": uname, "role": role, "email": email}

# ────────────────────────────────────────────────────────────
# Audit helpers for this module
# ────────────────────────────────────────────────────────────
ENTITY_NAME = "pending_registrations"

def _audit_log(request, *, action, entity_id=None, old_data=None, new_data=None, entity_name=ENTITY_NAME):
    """
    Insert a row into audit_logs. Best-effort; never raises.
    """
    try:
        actor = _extract_actor(request)
        payload = {
            "user_id": actor.get("user_id"),
            "username": actor.get("username"),
            "role": actor.get("role"),
            "action": action,
            "entity_name": entity_name,
            "entity_id": str(entity_id) if entity_id else None,
            "old_data": _json_sanitize(old_data) if old_data is not None else None,
            "new_data": _json_sanitize(new_data) if new_data is not None else None,
            "ip_address": _get_client_ip(request),
            "device_info": _get_device_info(request),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # prune Nones
        payload = {k: v for k, v in payload.items() if v is not None}
        _sb_for_audit().table("audit_logs").insert(payload).execute()
    except Exception as ex:
        logger.warning("Audit log insert failed: %s", ex)

def _fetch_pending_record_safe(registration_id):
    """
    Fetch the pending registration for audit 'old_data'. Returns None if missing or on error.
    """
    try:
        r = _sb_for_read().table("pending_registrations").select("*").eq("id", registration_id).single().execute()
        return getattr(r, "data", None)
    except Exception:
        return None

# ────────────────────────────────────────────────────────────
# Views
# ────────────────────────────────────────────────────────────
@method_decorator(csrf_exempt, name='dispatch')
class PendingRegistrationsAPI(APIView):
    """
    API endpoint to get pending registrations for admin review
    """
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            result = AuthenticationAPI.get_pending_registrations()

            # Best-effort audit (store only metadata to avoid excess PII)
            try:
                count = 0
                if isinstance(result, dict):
                    items = result.get("data") or result.get("pending") or []
                    if isinstance(items, list):
                        count = len(items)
                _audit_log(
                    request,
                    action="PENDING_LIST_VIEW",
                    entity_id=None,
                    old_data=None,
                    new_data={"success": bool(result.get("success")), "count": count}
                )
            except Exception:
                pass

            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            _audit_log(
                request,
                action="PENDING_LIST_ERROR",
                entity_id=None,
                old_data=None,
                new_data={"success": False, "error": str(e)}
            )
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class ApproveRegistrationAPI(APIView):
    """
    API endpoint to approve a pending registration
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else (request.data or {})
            registration_id = data.get('registration_id')
            approved_by = data.get('approved_by')  # kept for compatibility, actor is resolved via _extract_actor

            if not registration_id:
                return Response({
                    "success": False,
                    "error": "Registration ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)

            old_rec = _fetch_pending_record_safe(registration_id)

            result = AuthenticationAPI.approve_registration(registration_id, approved_by)

            # Audit outcome (actor resolved via _extract_actor)
            _audit_log(
                request,
                action="PENDING_APPROVE",
                entity_id=registration_id,
                old_data=old_rec,
                new_data=result
            )

            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)

        except json.JSONDecodeError:
            _audit_log(
                request,
                action="PENDING_APPROVE_INVALID_JSON",
                entity_id=None,
                old_data=None,
                new_data={"success": False, "error": "Invalid JSON data."}
            )
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            # registration_id might not be defined if JSON parsing failed earlier
            _audit_log(
                request,
                action="PENDING_APPROVE_ERROR",
                entity_id=(locals().get("registration_id") or None),
                old_data=None,
                new_data={"success": False, "error": str(e)}
            )
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class RejectRegistrationAPI(APIView):
    """
    API endpoint to reject a pending registration
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            data = json.loads(request.body) if isinstance(request.body, bytes) else (request.data or {})

            registration_id = data.get('registration_id')
            rejected_by = data.get('rejected_by')  # kept for compatibility, actor is resolved via _extract_actor
            reason = data.get('reason')

            if not registration_id:
                return Response({
                    "success": False,
                    "error": "Registration ID is required."
                }, status=status.HTTP_400_BAD_REQUEST)

            old_rec = _fetch_pending_record_safe(registration_id)

            result = AuthenticationAPI.reject_registration(registration_id, rejected_by, reason)

            # Audit outcome (include reason for traceability)
            _audit_log(
                request,
                action="PENDING_REJECT",
                entity_id=registration_id,
                old_data=old_rec,
                new_data={"result": result, "reason": reason}
            )

            if result.get("success"):
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)

        except json.JSONDecodeError:
            _audit_log(
                request,
                action="PENDING_REJECT_INVALID_JSON",
                entity_id=None,
                old_data=None,
                new_data={"success": False, "error": "Invalid JSON data."}
            )
            return Response({
                "success": False,
                "error": "Invalid JSON data."
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            _audit_log(
                request,
                action="PENDING_REJECT_ERROR",
                entity_id=(locals().get("registration_id") or None),
                old_data=None,
                new_data={"success": False, "error": str(e), "reason": locals().get("reason")}
            )
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
