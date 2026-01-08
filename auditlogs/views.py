# auditlogs/views.py
from django.shortcuts import render
from django.urls import reverse, NoReverseMatch
from accounts.views import admin_authenticated
from django.utils.safestring import mark_safe
import json

# reuse the same helpers as the API for shaping rows
from api.auditlogs import _client, _apply_filters, _format_ts, _diff_summary

@admin_authenticated
def auditlogs_view(request):
    # resolve API url with trailing slash
    try:
        api = reverse('api:auditlogs-list')
    except NoReverseMatch:
        api = "/api/auditlogs/"
    api = (api or "/api/auditlogs/").rstrip("/") + "/"

    # --- server-side bootstrap (first page), so you SEE data immediately ---
    try:
        sclient = _client()
        page = 1
        limit = 10
        desc = True
        offset = (page - 1) * limit
        to_idx = offset + limit - 1
        filters = {}  # no filters on initial load

        # count
        count_q = sclient.table("audit_logs").select("audit_id", count="exact")
        count_q = _apply_filters(count_q, filters)
        count_res = count_q.execute()
        total = getattr(count_res, "count", None)
        if total is None and isinstance(count_res, dict):
            total = count_res.get("count") or 0
        total = int(total or 0)
        print(f"DEBUG: Total audit logs: {total}")

        # page data
        data_q = (
            sclient.table("audit_logs")
            .select("audit_id,user_id,username,role,action,entity_name,entity_id,old_data,new_data,ip_address,device_info,created_at")
        )
        data_q = _apply_filters(data_q, filters)
        data_q = data_q.order("created_at", desc=desc).range(offset, to_idx)
        rows_res = data_q.execute()
        rows = getattr(rows_res, "data", None) or (rows_res.get("data", []) if isinstance(rows_res, dict) else [])
        print(f"DEBUG: Raw rows count: {len(rows) if rows else 0}")
    except Exception as e:
        print(f"DEBUG: Error fetching data: {e}")
        rows = []
        total = 0

    shaped = []
    for r in rows or []:
        target = (r.get("entity_name") or "").strip()
        if r.get("entity_id"):
            target = f"{target} #{r.get('entity_id')}"
        shaped.append({
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
        })
    
    print(f"DEBUG: Shaped data count: {len(shaped)}")
    if shaped:
        print(f"DEBUG: First row: {shaped[0]}")

    bootstrap = {
        "success": True,
        "data": shaped,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "has_next": (offset + limit) < total,
            "has_previous": page > 1,
        },
    }

    bootstrap_json = json.dumps(bootstrap)
    print(f"DEBUG: Bootstrap JSON length: {len(bootstrap_json)}")
    
    return render(request, "auditlogs.html", {
        "audit_api": api,
        "current_page": page,
        "limit": limit,
        "sort": "newest",
        "bootstrap_json": mark_safe(bootstrap_json),
    })
