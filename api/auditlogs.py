# api/auditlogs.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny  # swap to IsAuthenticated if needed
from rest_framework.response import Response

# Supabase clients & retry helper
from tartanilla_admin.supabase import supabase, execute_with_retry
try:
    # Prefer service-role client to bypass RLS for audit logs
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# Timezone-safe formatting
try:
    from zoneinfo import ZoneInfo
except Exception:
    from backports.zoneinfo import ZoneInfo  # type: ignore

PH_TZ = ZoneInfo("Asia/Manila")


def _client():
    """Return admin client when available (bypasses RLS); else anon client."""
    return supabase_admin or supabase


def _get_user_info(request):
    """Extract user info from request for audit logging."""
    user_id = None
    username = None
    role = None
    
    # Try to get from JWT token or session
    if hasattr(request, 'user') and request.user.is_authenticated:
        user_id = str(request.user.id) if hasattr(request.user, 'id') else None
        username = getattr(request.user, 'username', None) or getattr(request.user, 'email', None)
        role = getattr(request.user, 'role', None) or getattr(request.user, 'user_type', None)
    
    # Try to get from headers (for API requests)
    if not user_id:
        user_id = request.META.get('HTTP_X_USER_ID')
        username = request.META.get('HTTP_X_USERNAME')
        role = request.META.get('HTTP_X_USER_ROLE')
    
    return user_id, username, role


def create_audit_log(action, entity_name, entity_id=None, old_data=None, new_data=None, 
                    user_id=None, username=None, role=None, ip_address=None, device_info=None, request=None):
    """Utility function to create audit logs from anywhere in the application."""
    try:
        sclient = _client()
        
        # Get user info from request if not provided
        if request and not all([user_id, username, role]):
            req_user_id, req_username, req_role = _get_user_info(request)
            user_id = user_id or req_user_id
            username = username or req_username
            role = role or req_role
        
        # Get IP address from request if not provided
        if request and not ip_address:
            ip_address = (
                request.META.get("HTTP_X_FORWARDED_FOR")
                or request.META.get("REMOTE_ADDR")
            )
        
        insert_data = {
            "user_id": user_id,
            "username": username,
            "role": role,
            "action": action,
            "entity_name": entity_name,
            "entity_id": entity_id,
            "old_data": old_data,
            "new_data": new_data,
            "ip_address": ip_address,
            "device_info": device_info,
        }
        
        execute_with_retry(
            lambda: sclient.table("audit_logs").insert(insert_data).execute()
        )
        return True
    except Exception as e:
        print(f"Failed to create audit log: {e}")
        return False


def _format_ts(ts: Optional[str]) -> str:
    """Format ISO timestamp to Asia/Manila 'YYYY-MM-DD hh:mm AM/PM'."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(PH_TZ).strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        return ts


def _diff_summary(old_data: Optional[Dict[str, Any]], new_data: Optional[Dict[str, Any]]) -> str:
    """Generate a lightweight 'Updated fields: a, b, c' summary from JSON columns."""
    if not isinstance(old_data, dict) or not isinstance(new_data, dict):
        return "—"
    changed = []
    keys = set(old_data.keys()) | set(new_data.keys())
    for k in sorted(keys):
        if old_data.get(k) != new_data.get(k):
            changed.append(k)
    return f"Updated fields: {', '.join(changed)}" if changed else "—"


def _apply_filters(query, filters: Dict[str, str]):
    """
    Apply ilike filters and an OR free-text query across relevant columns.

    Supported filters: action, role, username, entity_name, q
    Aliases supported by list(): role can be provided as user_type, username as user_email.
    """
    action = (filters.get("action") or "").strip()
    role = (filters.get("role") or "").strip()
    username = (filters.get("username") or "").strip()
    entity_name = (filters.get("entity_name") or "").strip()
    q = (filters.get("q") or "").strip()

    if action:
        query = query.ilike("action", f"%{action}%")
    if role:
        query = query.ilike("role", f"%{role}%")
    if username:
        query = query.ilike("username", f"%{username}%")
    if entity_name:
        query = query.ilike("entity_name", f"%{entity_name}%")
    if q:
        # Supabase/PostgREST OR syntax: "col.op.value,col2.op.value"
        or_expr = (
            f"username.ilike.%{q}%,"
            f"role.ilike.%{q}%,"
            f"action.ilike.%{q}%,"
            f"entity_name.ilike.%{q}%,"
            f"entity_id.ilike.%{q}%"
        )
        query = query.or_(or_expr)
    return query


class AuditLogsViewSet(viewsets.ViewSet):
    """
    Endpoints:
      GET /api/auditlogs/            -> list with paging & filters
      POST /api/auditlogs/create_log -> optional helper to insert a test log
    """
    permission_classes = [AllowAny]  # tighten if needed

    def list(self, request):
        """
        Query params:
          page (int, default 1), limit (int, default 50), sort = newest|oldest (default newest)
          action, role, username, entity_name, q (free text)
          Aliases supported: role<-user_type, username<-user_email, q<-search
        Response:
          { success, data: [...], pagination: { page, limit, total, has_next, has_previous } }
        """
        try:
            sclient = _client()

            # Pagination
            page = max(int(request.query_params.get("page", 1)), 1)
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 200)
            sort = (request.query_params.get("sort") or "newest").lower()
            desc = True if sort in ("newest", "desc") else False
            offset = (page - 1) * limit
            to_idx = offset + limit - 1

            # Filters (with aliases)
            filters = {
                "action": request.query_params.get("action", ""),
                "role": request.query_params.get("user_type", "") or request.query_params.get("role", ""),
                "username": request.query_params.get("user_email", "") or request.query_params.get("username", ""),
                "entity_name": request.query_params.get("entity_name", ""),
                "q": request.query_params.get("q", "") or request.query_params.get("search", ""),
            }

            # Count (exact)
            count_q = sclient.table("audit_logs").select("audit_id", count="exact")
            count_q = _apply_filters(count_q, filters)
            count_res = execute_with_retry(lambda: count_q.execute())
            total = getattr(count_res, "count", None)
            if total is None and isinstance(count_res, dict):
                total = count_res.get("count") or 0
            total = int(total or 0)

            # Data
            data_q = (
                sclient.table("audit_logs")
                .select(
                    "audit_id,user_id,username,role,action,entity_name,entity_id,"
                    "old_data,new_data,ip_address,device_info,created_at"
                )
            )
            data_q = _apply_filters(data_q, filters)
            data_q = data_q.order("created_at", desc=desc).range(offset, to_idx)
            rows_res = execute_with_retry(lambda: data_q.execute())

            rows = getattr(rows_res, "data", None)
            if rows is None and isinstance(rows_res, dict):
                rows = rows_res.get("data", [])  # safety

            # Shape rows for the frontend
            shaped: List[Dict[str, Any]] = []
            for r in rows or []:
                target = (r.get("entity_name") or "").strip()
                if r.get("entity_id"):
                    target = f"{target} #{r.get('entity_id')}"
                shaped.append(
                    {
                        "id": r.get("audit_id"),
                        "timestamp": _format_ts(r.get("created_at")),
                        "user_id": r.get("user_id"),
                        "username": r.get("username"),
                        "role": r.get("role"),
                        "action": r.get("action"),
                        "target": target or "—",
                        "description": _diff_summary(r.get("old_data"), r.get("new_data")),
                        "ip_address": r.get("ip_address"),
                        "device_info": r.get("device_info"),
                    }
                )

            return Response(
                {
                    "success": True,
                    "data": shaped,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total,
                        "has_next": (offset + limit) < total,
                        "has_previous": page > 1,
                    },
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["post"])
    def create_log(self, request):
        """
        Optional manual insert for testing.

        Body (JSON):
          Required: action, entity_name
          Optional: entity_id, user_id, username, role, old_data, new_data, ip_address, device_info
        """
        try:
            sclient = _client()
            payload = request.data or {}

            if not payload.get("action") or not payload.get("entity_name"):
                return Response(
                    {"success": False, "error": "Fields 'action' and 'entity_name' are required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get user info from request if not provided in payload
            req_user_id, req_username, req_role = _get_user_info(request)
            
            ip_addr = (
                payload.get("ip_address")
                or request.META.get("HTTP_X_FORWARDED_FOR")
                or request.META.get("REMOTE_ADDR")
            )

            insert_data = {
                "user_id": payload.get("user_id") or req_user_id,
                "username": payload.get("username") or req_username,
                "role": payload.get("role") or req_role,
                "action": payload.get("action"),
                "entity_name": payload.get("entity_name"),
                "entity_id": payload.get("entity_id"),
                "old_data": payload.get("old_data"),
                "new_data": payload.get("new_data"),
                "ip_address": ip_addr,
                "device_info": payload.get("device_info"),
            }

            ins_res = execute_with_retry(
                lambda: sclient.table("audit_logs").insert(insert_data).select("*").execute()
            )
            created = getattr(ins_res, "data", None)
            if created is None and isinstance(ins_res, dict):
                created = ins_res.get("data", [])

            row = (created or [None])[0]
            out = {
                "id": row.get("audit_id") if row else None,
                "timestamp": _format_ts(row.get("created_at") if row else ""),
                "user_id": row.get("user_id") if row else None,
                "username": row.get("username") if row else None,
                "role": row.get("role") if row else None,
                "action": row.get("action") if row else None,
                "target": ((row.get("entity_name") or "") + (f" #{row.get('entity_id')}" if row and row.get("entity_id") else "")) if row else None,
                "description": _diff_summary(row.get("old_data") if row else None, row.get("new_data") if row else None),
            }

            return Response(
                {"success": True, "data": out, "message": "Audit log created successfully"},
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
