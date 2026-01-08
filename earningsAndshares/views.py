# earnings/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache

from accounts.views import admin_authenticated
from api.earnings import EarningsViewSet

import json
from datetime import datetime
from zoneinfo import ZoneInfo


@never_cache
@admin_authenticated
def earningsAndshares(request):
    """
    Render the Earnings & Shares page with totals, pending & released payouts,
    and chart data. Includes 'user' from cookies to match dashboard_view style.
    """
    try:
        viewset = EarningsViewSet()

        # Aggregates
        totals = viewset._get_totals()
        pending = viewset._pending_payouts()
        released = viewset._released_payouts()

        # Use local PH timezone for daily/hourly figures
        tz = ZoneInfo("Asia/Manila")
        today_local = datetime.now(tz)

        daily_total = viewset._get_daily_total_income(today_local.year, today_local.month)
        hourly_total = viewset._get_hourly_income(today_local, tz_name="Asia/Manila")

        context = {
            "user": request.COOKIES.get("admin_email"),  # ← match dashboard_view
            "total_income": totals.get("gross_total", 0),
            "organization_total_shares": totals.get("admin_total", 0),
            "driver_total_shares": totals.get("driver_total", 0),
            "pending_payouts": pending,
            "released_payouts": released,
            "daily_total_json": json.dumps(daily_total),
            "hourly_total_json": json.dumps(hourly_total),
        }
        return render(request, "earningsAndshares.html", context)

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_POST
@admin_authenticated
def release_payout(request, payout_id):
    """
    Mark a payout as released. Returns JSON (kept as an API endpoint).
    """
    try:
        try:
            body = json.loads(request.body or "{}")
        except Exception:
            body = {}

        remarks = body.get("remarks")
        payout = EarningsViewSet()._mark_payouts_as_released([str(payout_id)], remarks=remarks)

        if not payout:
            return JsonResponse({"error": "Payout not found."}, status=404)

        return JsonResponse({"success": True, "payout": payout})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
