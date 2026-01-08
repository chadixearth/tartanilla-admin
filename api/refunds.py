# refunds.py
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer

from tartanilla_admin.supabase import supabase
try:
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# optional project helpers (used if present)
try:
    from core.jwt_auth import verify_token, get_token_from_request
except Exception:
    verify_token = None
    get_token_from_request = None

from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from math import ceil
import json
import traceback
import logging
import os

# PyJWT (strongly recommended)
try:
    import jwt  # PyJWT
except Exception:
    jwt = None

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Utils
# ────────────────────────────────────────────────────────────
def _to_decimal(v, default=Decimal("0")):
    try:
        if v is None:
            return default
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return default

def _to_float(v):
    try:
        return float(_to_decimal(v))
    except Exception:
        return 0.0

def _iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _fmt_short_ref(ref_id):
    s = str(ref_id or "")
    tail = s.replace("-", "")[-6:] or s
    return f"RF-{tail.upper()}"

def _fmt_row(row):
    row = dict(row or {})
    row["refund_amount"] = _to_float(row.get("refund_amount", 0))
    row["refund_amount_formatted"] = f"₱{row['refund_amount']:,.2f}"
    row["short_ref"] = _fmt_short_ref(row.get("id"))
    if "status" in row and isinstance(row["status"], str):
        row["status"] = row["status"].strip().lower()
    return row

def _json_sanitize(obj):
    if isinstance(obj, dict):
        return {k: _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
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

def _sb_for_read():   # use admin where possible to bypass RLS
    return supabase_admin or supabase

def _sb_for_audit():  # use admin where possible to bypass RLS
    return supabase_admin or supabase

# ────────────────────────────────────────────────────────────
# Actor extraction
# ────────────────────────────────────────────────────────────
def _read_bearer_token(request):
    # Standard Authorization: Bearer <token>
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
        q = sb.table("users").select("id,email,username,role")
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
    Resolve actor using the same logic as earnings.py
    """
    uid = uname = role = email = None

    # 1) Admin cookies (from @admin_authenticated decorator)
    try:
        admin_user_id = request.COOKIES.get('admin_user_id')
        admin_email = request.COOKIES.get('admin_email')
        admin_authenticated = request.COOKIES.get('admin_authenticated')
        
        if admin_authenticated == '1' and admin_user_id and admin_email:
            uid = admin_user_id.strip() if admin_user_id else None
            email = admin_email.strip() if admin_email else None
            role = "admin"  # Admin web interface users are always admin
            
            # Try to get user name from database
            db_user = _fetch_user_profile(user_id=uid)
            if db_user:
                uname = db_user.get("username") or db_user.get("name") or email
            else:
                uname = email
    except Exception:
        pass

    # 2) Project helper (JWT)
    if not uid or not uname or not role:
        try:
            if get_token_from_request and verify_token:
                tok = get_token_from_request(request)
                if tok:
                    payload = verify_token(tok) or {}
                    jwt_uid = payload.get("sub") or payload.get("user_id") or payload.get("id") or payload.get("uid")
                    jwt_email = payload.get("email") or (payload.get("user_metadata") or {}).get("email")
                    
                    uid = uid or str(jwt_uid) if jwt_uid else uid
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

    # 3) Django user fallback
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

    # Final fallbacks
    if not uname:
        uname = email or "System Admin"
    if not role:
        role = "admin"

    return {"user_id": uid, "username": uname, "role": role, "email": email}

# ────────────────────────────────────────────────────────────
# Audit helper (only used for approve/reject/void)
#   - description is STRICTLY the remarks
# ────────────────────────────────────────────────────────────
def _audit_log(request, *, action, entity_name, entity_id=None, old_data=None, new_data=None):
    """
    Called only for:
      - REFUND_APPROVE
      - REFUND_REJECT
      - REFUND_VOID

    Writes 'description' = remarks (if present). Falls back without 'description' if column is absent.
    """
    try:
        actor = _extract_actor(request)

        # Description is just the remarks (prefer new_data, then old_data)
        remarks = None
        try:
            remarks = (new_data or {}).get("remarks") or (old_data or {}).get("remarks")
        except Exception:
            pass

        base_payload = {
            "user_id": actor.get("user_id"),
            "username": actor.get("username"),
            "role": actor.get("role"),
            "action": action,
            "entity_name": entity_name,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "old_data": _json_sanitize(old_data) if old_data is not None else None,
            "new_data": _json_sanitize(new_data) if new_data is not None else None,
            "ip_address": _get_client_ip(request),
            "device_info": _get_device_info(request),
        }
        payload = {k: v for k, v in base_payload.items() if v is not None}

        # Try insert with description first
        if remarks:
            try:
                _sb_for_audit().table("audit_logs").insert(dict(payload, description=remarks)).execute()
                return
            except Exception as ex:
                logger.info("Audit insert with description failed; retrying without it: %s", ex)

        # Fallback without description
        _sb_for_audit().table("audit_logs").insert(payload).execute()
    except Exception as ex:
        logger.warning("Audit log insert failed: %s", ex)

# ────────────────────────────────────────────────────────────
# Viewset
# ────────────────────────────────────────────────────────────
class RefundsViewSet(viewsets.ViewSet):
    """
    /api/refunds/                -> list (?page, ?page_size, ?status, ?booking_id)
    /api/refunds/<id>/           -> retrieve
    /api/refunds/ (POST)         -> create
    /api/refunds/<id>/approve/   -> approve
    /api/refunds/<id>/reject/    -> reject
    /api/refunds/<id>/void/      -> void
    """
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer, BrowsableAPIRenderer]

    # ---------- Business helpers ----------
    def _calculate_refund_amount(self, booking, cancelled_by='customer'):
        original_amount = _to_decimal(booking.get('total_amount', 0))
        paid = str(booking.get('payment_status', '')).lower() == 'paid'

        if not paid:
            return {
                'refund_amount': Decimal('0.00'),
                'original_amount': original_amount,
                'refund_percentage': Decimal('0.00'),
                'cancellation_fee': Decimal('0.00'),
                'reason': 'No payment was made'
            }

        who = (cancelled_by or 'customer').strip().lower()
        if who in ('driver', 'system', 'admin'):
            reason = 'Driver cancellation - full refund' if who == 'driver' else f'{who.title()} cancellation - full refund'
            return {
                'refund_amount': original_amount.quantize(Decimal('0.01')),
                'original_amount': original_amount,
                'refund_percentage': Decimal('100.00'),
                'cancellation_fee': Decimal('0.00'),
                'reason': reason
            }

        # No cancellation fee for customer cancellations - always full refund
        return {
            'refund_amount': original_amount.quantize(Decimal('0.01')),
            'original_amount': original_amount,
            'refund_percentage': Decimal('100.00'),
            'cancellation_fee': Decimal('0.00'),
            'reason': 'Customer cancellation - full refund (no fees)'
        }

    # ---------- CRUD ----------
    def list(self, request):
        try:
            q = request.query_params if hasattr(request, "query_params") else request.GET
            page = int(q.get("page", 1) or 1)
            page_size = int(q.get("page_size", 10) or 10)
            page = 1 if page < 1 else page
            page_size = 1 if page_size < 1 else page_size
            status_filter = (q.get("status") or "").strip().lower()
            booking_id = (q.get("booking_id") or "").strip()
            current_user = (q.get("current_user") or "").strip()

            # If current_user is provided, filter for user's refunds only
            if current_user:
                # Get all refunds and filter manually
                all_refunds_query = supabase.table('refunds').select('*')
                if status_filter:
                    try:
                        all_refunds_query = all_refunds_query.ilike('status', status_filter)
                    except Exception:
                        all_refunds_query = all_refunds_query.eq('status', status_filter)
                if booking_id:
                    all_refunds_query = all_refunds_query.eq('booking_id', booking_id)
                all_refunds_resp = all_refunds_query.execute()
                all_refunds = getattr(all_refunds_resp, "data", []) or []
                
                # Filter refunds for current user
                user_refunds = []
                for refund in all_refunds:
                    # Check if tourist_id matches current user
                    if refund.get('tourist_id') == current_user:
                        user_refunds.append(refund)
                    # Check if tourist_id is null and booking belongs to user
                    elif not refund.get('tourist_id'):
                        booking_resp = supabase.table('bookings').select('customer_id').eq('id', refund.get('booking_id')).single().execute()
                        booking = getattr(booking_resp, "data", {})
                        if booking and booking.get('customer_id') == current_user:
                            user_refunds.append(refund)
                
                # Sort by created_at desc
                user_refunds.sort(key=lambda x: x.get('created_at', ''), reverse=True)
                
                total = len(user_refunds)
                start = (page - 1) * page_size
                end = start + page_size
                rows = user_refunds[start:end]
            else:
                # Original logic for admin/all refunds
                count_query = supabase.table('refunds').select('id', count='exact')
                if status_filter:
                    try:
                        count_query = count_query.ilike('status', status_filter)
                    except Exception:
                        count_query = count_query.eq('status', status_filter)
                if booking_id:
                    count_query = count_query.eq('booking_id', booking_id)
                count_query = count_query.order('created_at', desc=True)
                count_resp = count_query.execute()
                total = getattr(count_resp, "count", None)
                if total is None:
                    total = len(getattr(count_resp, "data", []) or [])

                start = (page - 1) * page_size
                end = start + page_size - 1

                data_query = supabase.table('refunds').select('*')
                if status_filter:
                    try:
                        data_query = data_query.ilike('status', status_filter)
                    except Exception:
                        data_query = data_query.eq('status', status_filter)
                if booking_id:
                    data_query = data_query.eq('booking_id', booking_id)
                data_query = data_query.order('created_at', desc=True).range(start, end)
                data_resp = data_query.execute()
                rows = getattr(data_resp, "data", []) or []
            
            # Enrich rows with driver names
            enriched_rows = []
            for row in rows:
                enriched_row = _fmt_row(row)
                # Get driver name from earnings or bookings
                driver_name = 'No Driver Assigned'
                if row.get('driver_id'):
                    # Try earnings table first (has driver_name field)
                    if row.get('earning_id'):
                        try:
                            earning_resp = supabase.table('earnings').select('driver_name').eq('id', row['earning_id']).single().execute()
                            earning_data = getattr(earning_resp, "data", {})
                            if earning_data and earning_data.get('driver_name'):
                                driver_name = earning_data['driver_name']
                        except Exception:
                            pass
                    
                    # Fallback to bookings table if earnings didn't work
                    if driver_name == 'No Driver Assigned' and row.get('booking_id'):
                        try:
                            booking_resp = supabase.table('bookings').select('driver_name').eq('id', row['booking_id']).single().execute()
                            booking_data = getattr(booking_resp, "data", {})
                            if booking_data and booking_data.get('driver_name'):
                                driver_name = booking_data['driver_name']
                        except Exception:
                            pass
                
                enriched_row['driver_name'] = driver_name
                
                enriched_rows.append(enriched_row)
                
            results = enriched_rows

            # (Audit removed for list view)

            return Response({
                "success": True,
                "results": results,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": ceil(total / page_size) if page_size else 1,
            })
        except Exception as e:
            traceback.print_exc()
            return Response({
                "success": False,
                "results": [],
                "error": f"Failed to fetch refunds: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def retrieve(self, request, pk=None):
        try:
            resp = supabase.table('refunds').select('*').eq('id', pk).single().execute()
            data = getattr(resp, "data", None)
            if not data:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

            # Get driver name from earnings or bookings
            driver_name = 'No Driver Assigned'
            if data.get('driver_id'):
                # Try earnings table first
                if data.get('earning_id'):
                    try:
                        earning_resp = supabase.table('earnings').select('driver_name').eq('id', data['earning_id']).single().execute()
                        earning_data = getattr(earning_resp, "data", {})
                        if earning_data and earning_data.get('driver_name'):
                            driver_name = earning_data['driver_name']
                    except Exception:
                        pass
                
                # Fallback to bookings table
                if driver_name == 'No Driver Assigned' and data.get('booking_id'):
                    try:
                        booking_resp = supabase.table('bookings').select('driver_name').eq('id', data['booking_id']).single().execute()
                        booking_data = getattr(booking_resp, "data", {})
                        if booking_data and booking_data.get('driver_name'):
                            driver_name = booking_data['driver_name']
                    except Exception:
                        pass
            
            enriched_data = _fmt_row(data)
            enriched_data['driver_name'] = driver_name

            return Response(enriched_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request):
        try:
            data = request.data if hasattr(request, 'data') else json.loads(request.body or "{}")
            required = ['booking_id', 'customer_id', 'reason', 'cancelled_by']
            for f in required:
                if not data.get(f):
                    return Response({"success": False, "error": f"Missing required field: {f}"}, status=400)

            booking_id = data['booking_id']
            customer_id = data['customer_id']
            reason = data['reason']
            cancelled_by = data['cancelled_by']

            b_resp = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
            booking = getattr(b_resp, "data", None)
            if not booking:
                return Response({"success": False, "error": "Booking not found"}, status=404)

            dup = supabase.table('refunds').select('id').eq('booking_id', booking_id).execute()
            if getattr(dup, "data", None):
                return Response({
                    "success": False,
                    "error": "Refund request already exists for this booking",
                    "existing_refund_id": dup.data[0]["id"]
                }, status=409)

            e_resp = supabase.table('earnings').select('id').eq('booking_id', booking_id).single().execute()
            earning = getattr(e_resp, "data", None)
            if not earning:
                return Response({"success": False, "error": "No earning record found for this booking"}, status=400)

            calc = self._calculate_refund_amount(booking, cancelled_by)
            insert_data = {
                "earning_id": earning["id"],
                "booking_id": booking_id,
                "driver_id": booking.get("driver_id"),
                "refund_amount": _to_float(calc["refund_amount"]),
                "reason": reason,
                "status": "pending",
                "initiated_by": customer_id,
                "tourist_id": customer_id,
                "tourist_name": booking.get("customer_name") or booking.get("tourist_name"),
            }
            ins = supabase.table('refunds').insert(insert_data).execute()
            created = getattr(ins, "data", []) or []
            if not created:
                return Response({"success": False, "error": "Failed to create refund request"}, status=500)

            created_row = created[0]

            # (Audit removed for create)

            return Response({"success": True, "data": _fmt_row(created_row), "message": "Refund request created successfully"}, status=201)
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    # ---------- Actions (ONLY these keep audit logs) ----------
    @action(detail=True, methods=['post'], url_path='approve')
    def approve_refund(self, request, pk=None):
        try:
            payload = request.data if hasattr(request, "data") else {}
            admin_id = payload.get("admin_id") or getattr(getattr(request, "user", None), "id", None)
            remarks = payload.get("remarks") or None

            ref = supabase.table('refunds').select('*').eq('id', pk).single().execute()
            refund = getattr(ref, "data", None)
            if not refund:
                return Response({"success": False, "error": "Refund not found"}, status=404)
            if str(refund.get("status", "")).lower() != "pending":
                return Response({"success": False, "error": f"Cannot approve refund with status: {refund.get('status')}"}, status=400)

            upd = {
                "status": "approved",
                "approved_by": admin_id,
                "approved_at": _iso_now(),
                "remarks": remarks
            }
            u = supabase.table('refunds').update(upd).eq('id', pk).execute()
            row = (getattr(u, "data", []) or [None])[0]
            if not row:
                return Response({"success": False, "error": "Failed to approve refund"}, status=500)

            _audit_log(
                request,
                action="REFUND_APPROVE",
                entity_name="refunds",
                entity_id=pk,
                old_data=refund,
                new_data=row,
            )

            return Response({"success": True, "data": _fmt_row(row), "message": "Refund approved successfully"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject_refund(self, request, pk=None):
        try:
            payload = request.data if hasattr(request, "data") else {}
            admin_id = payload.get("admin_id") or getattr(getattr(request, "user", None), "id", None)
            remarks = (payload.get("remarks") or "").strip()
            if not remarks:
                return Response({"success": False, "error": "Remarks are required for rejection"}, status=400)

            ref = supabase.table('refunds').select('*').eq('id', pk).single().execute()
            refund = getattr(ref, "data", None)
            if not refund:
                return Response({"success": False, "error": "Refund not found"}, status=404)
            if str(refund.get("status", "")).lower() != "pending":
                return Response({"success": False, "error": f"Cannot reject refund with status: {refund.get('status')}"}, status=400)

            upd = {
                "status": "rejected",
                "approved_by": admin_id,
                "approved_at": _iso_now(),
                "remarks": remarks
            }
            u = supabase.table('refunds').update(upd).eq('id', pk).execute()
            row = (getattr(u, "data", []) or [None])[0]
            if not row:
                return Response({"success": False, "error": "Failed to reject refund"}, status=500)

            _audit_log(
                request,
                action="REFUND_REJECT",
                entity_name="refunds",
                entity_id=pk,
                old_data=refund,
                new_data=row,
            )

            return Response({"success": True, "data": _fmt_row(row), "message": "Refund rejected"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)

    @action(detail=True, methods=['post'], url_path='void')
    def void_refund(self, request, pk=None):
        try:
            payload = request.data if hasattr(request, "data") else {}
            admin_id = payload.get("admin_id") or getattr(getattr(request, "user", None), "id", None)
            remarks = (payload.get("remarks") or "").strip()
            if not remarks:
                return Response({"success": False, "error": "Remarks are required to void a refund"}, status=400)

            ref = supabase.table('refunds').select('*').eq('id', pk).single().execute()
            refund = getattr(ref, "data", None)
            if not refund:
                return Response({"success": False, "error": "Refund not found"}, status=404)

            status_now = str(refund.get("status", "")).lower()
            if status_now in ("void", "voided"):
                return Response({"success": False, "error": "Refund is already voided"}, status=400)

            upd = {
                "status": "voided",
                "approved_by": admin_id,
                "approved_at": _iso_now(),
                "remarks": remarks
            }
            u = supabase.table('refunds').update(upd).eq('id', pk).execute()
            row = (getattr(u, "data", []) or [None])[0]
            if not row:
                return Response({"success": False, "error": "Failed to void refund"}, status=500)

            _audit_log(
                request,
                action="REFUND_VOID",
                entity_name="refunds",
                entity_id=pk,
                old_data=refund,
                new_data=row,
            )

            return Response({"success": True, "data": _fmt_row(row), "message": "Refund voided"})
        except Exception as e:
            traceback.print_exc()
            return Response({"success": False, "error": str(e)}, status=500)
