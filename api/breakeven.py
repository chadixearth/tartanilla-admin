# api/breakeven.py
from tartanilla_admin.supabase import supabase
from rest_framework.permissions import AllowAny
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .breakeven_notifications import BreakevenNotificationService

from math import ceil, isfinite
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional
import calendar
import os
import asyncio

# ─────────────────────────── Timezones ───────────────────────────
PH_TZ = ZoneInfo("Asia/Manila")
UTC = timezone.utc

CRON_SECRET = os.getenv("BREAKEVEN_CRON_SECRET", None)

# ─────────────────────── Status policy (env) ─────────────────────
# DEFAULT BEHAVIOR: include only 'finalized' earnings unless EARNINGS_INCLUDE_STATUSES is set.
_raw_inc = os.getenv("EARNINGS_INCLUDE_STATUSES", None)
INCLUDED_EARNINGS_STATUSES = (
    tuple(s.strip().lower() for s in (_raw_inc or "").split(",") if s.strip())
    if (_raw_inc is not None and _raw_inc.strip() != "")
    else ("finalized","pending")
)
# Exclude list (only used when include list is empty)
EXCLUDED_EARNINGS_STATUSES = tuple(
    s.strip().lower() for s in os.getenv("EARNINGS_EXCLUDE_STATUSES", "reversed").split(",") if s.strip()
)

def _apply_status_policy(q):
    """
    If allow-list is present (default: ('finalized',)), only include those statuses;
    otherwise, exclude the excluded-list.
    """
    if INCLUDED_EARNINGS_STATUSES:
        return q.in_("status", list(INCLUDED_EARNINGS_STATUSES))
    if EXCLUDED_EARNINGS_STATUSES:
        return q.not_.in_("status", list(EXCLUDED_EARNINGS_STATUSES))
    return q

def _parse_statuses_param(val: str):
    return tuple(s.strip().lower() for s in (val or "").split(",") if s.strip())

# ───────────────────── Week mode + shares ────────────────────────
# CALENDAR (Mon→Sun) or ROLLING7 (today-6 → today)
WEEK_MODE = (os.getenv("BREAKEVEN_WEEK_MODE", "CALENDAR") or "CALENDAR").upper()

# Driver shares (override via env if needed)
BOOKING_SHARE = float(os.getenv("EARNINGS_SHARE_BOOKING_PCT", "0.80"))
CUSTOM_SHARE  = float(os.getenv("EARNINGS_SHARE_CUSTOM_PCT", "1.00"))

# ───────────────── Display & Bucket TZs ─────────────────
# display_tz: purely formatting
DEFAULT_DISPLAY_TZ = (os.getenv("BREAKEVEN_DISPLAY_TZ", "ph") or "ph").lower().strip()
# bucket_tz: defines which calendar the windows follow (PH or UTC)
DEFAULT_BUCKET_TZ  = (os.getenv("BREAKEVEN_BUCKET_TZ",  "ph") or "ph").lower().strip()

# Optional: Start-of-day cutoff hour in the chosen bucket_tz (0..23). E.g., 4 = day is 04:00→next 04:00
DAY_CUTOFF_HOUR = int(os.getenv("BREAKEVEN_DAY_CUTOFF_HOUR", "0") or "0")
DAY_CUTOFF_HOUR = max(0, min(DAY_CUTOFF_HOUR, 23))

def _resolve_tz(name: str):
    n = (name or "").lower().strip()
    if n in ("ph", "asia/manila", "manila"):
        return PH_TZ, "ph"
    if n in ("utc", "z", "+00:00"):
        return UTC, "utc"
    return PH_TZ, "ph"

# ──────────────────────── TZ + period helpers ───────────────────────
def _today_in_tz(tz) -> date:
    return datetime.now(tz).date()

def _as_utc(dt: datetime) -> datetime:
    # Return tz-aware UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)

def _with_cutoff(dt_d: date, basis_tz) -> datetime:
    """Return dt at DAY_CUTOFF_HOUR (e.g., 04:00) in basis_tz for that calendar date."""
    base = datetime.combine(dt_d, time.min, tzinfo=basis_tz)
    return base + timedelta(hours=DAY_CUTOFF_HOUR)

def _period_range_half_open_tz(period: str, basis_tz):
    """
    Returns (start_local, end_excl_local) for 'today' | 'week' | 'month'
    HALF-OPEN [start, end) using the requested basis timezone + day cutoff.
    """
    p = (period or "today").lower()
    today = _today_in_tz(basis_tz)

    if p == "week":
        if WEEK_MODE == "ROLLING7":
            start_d = today - timedelta(days=6)
            end_excl_d = today + timedelta(days=1)
        else:
            start_d = today - timedelta(days=today.weekday())  # Monday in basis tz
            end_excl_d = start_d + timedelta(days=7)
    elif p == "month":
        start_d = date(today.year, today.month, 1)
        end_excl_d = date(today.year + (1 if today.month == 12 else 0),
                          1 if today.month == 12 else today.month + 1, 1)
    else:
        start_d = today
        end_excl_d = today + timedelta(days=1)

    # Apply business-day cutoff
    return _with_cutoff(start_d, basis_tz), _with_cutoff(end_excl_d, basis_tz)

def _period_boundaries_for_type_tz(period_type: str, ref_date: date, basis_tz):
    """
    For history snapshots relative to ref_date (in basis_tz).
    HALF-OPEN [start, end) using calendar in basis_tz + cutoff.
    """
    p = (period_type or "daily").lower()
    if p == "weekly":
        start_d = ref_date - timedelta(days=ref_date.weekday())
        end_excl_d = start_d + timedelta(days=7)
    elif p == "monthly":
        start_d = date(ref_date.year, ref_date.month, 1)
        end_excl_d = date(ref_date.year + (1 if ref_date.month == 12 else 0),
                          1 if ref_date.month == 12 else ref_date.month + 1, 1)
    else:
        start_d = ref_date
        end_excl_d = ref_date + timedelta(days=1)

    return _with_cutoff(start_d, basis_tz), _with_cutoff(end_excl_d, basis_tz)

def _is_last_day_of_month(d: date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]

# ───────────────────────── Formatting helper ─────────────────────────
def _fmt_ts(value: Optional[str], tz) -> Optional[str]:
    """Render DB timestamptz as ISO in a chosen tz (formatting only)."""
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(tz).isoformat()
    except Exception:
        return value

# ─────────────────────────── Robust parsing & window check ───────────────────────────
def _parse_db_ts(iso_str: str) -> Optional[datetime]:
    if not iso_str:
        return None
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt

def _in_window_local(iso_str: str, start_dt_local: datetime, end_excl_local: datetime) -> bool:
    """Return True iff the DB timestamp, when converted to bucket tz, falls within [start, end)."""
    dt = _parse_db_ts(iso_str)
    if not dt:
        return False
    local = dt.astimezone(start_dt_local.tzinfo or UTC)
    return (start_dt_local <= local) and (local < end_excl_local)

# ───────────────────── Fetch + split (single roundtrip) ─────────────────────
def _distinct_driver_ids_in_range(start_dt_local: datetime, end_excl_dt_local: datetime):
    """
    Collect unique driver_ids that had earnings in the given local half-open range.
    Query is performed in UTC using converted boundaries.
    """
    s_utc = _as_utc(start_dt_local).isoformat()
    e_utc = _as_utc(end_excl_dt_local).isoformat()

    q = (
        supabase.table("earnings")
        .select("driver_id")
        .gte("earning_date", s_utc)
        .lt("earning_date", e_utc)
        .not_.is_("driver_id", "null")
    )
    q = _apply_status_policy(q)
    r = q.execute()
    rows = getattr(r, "data", []) or []
    return list({row["driver_id"] for row in rows if row.get("driver_id")})

def _fetch_earnings_rows(driver_id: str, start_dt_local: datetime, end_excl_dt_local: datetime,
                         status_in=None, status_ex=None):
    """
    Fetch earnings for the driver in the local half-open window (via UTC bounds),
    then post-filter by local window (bucket tz) to be rock-solid.
    """
    s_utc = _as_utc(start_dt_local).isoformat()
    e_utc = _as_utc(end_excl_dt_local).isoformat()

    q = (
        supabase.table("earnings")
        .select("id, amount, earning_date, status, booking_id, custom_tour_id, ride_hailing_booking_id, driver_earnings")
        .eq("driver_id", driver_id)
        .gte("earning_date", s_utc)
        .lt("earning_date",  e_utc)
    )
    
    print(f"[DEBUG] Fetching earnings for driver {driver_id} from {s_utc} to {e_utc}")

    if status_in:
        q = q.in_("status", list(status_in))
    elif status_ex:
        q = q.not_.in_("status", list(status_ex))
    else:
        q = _apply_status_policy(q)

    r = q.execute()
    rows_all_raw = getattr(r, "data", None) or []

    # Hard guard: keep only those in the local bucket window
    rows_all = [row for row in rows_all_raw if _in_window_local(row.get("earning_date"), start_dt_local, end_excl_dt_local)]

    rows_booking = [row for row in rows_all if row.get("booking_id")]
    rows_custom  = [row for row in rows_all if row.get("custom_tour_id")]
    rows_ride_hailing = [row for row in rows_all if row.get("ride_hailing_booking_id")]
    
    print(f"[DEBUG] Found {len(rows_all)} total earnings: {len(rows_booking)} standard, {len(rows_custom)} custom, {len(rows_ride_hailing)} ride hailing")
    
    return rows_all, rows_booking, rows_custom, rows_ride_hailing, s_utc, e_utc

def _sum_driver_share(rows_booking, rows_custom, rows_ride_hailing=None):
    revenue_from_bookings = 0.0
    for r in rows_booking:
        try:
            driver_earnings = float(r.get("driver_earnings") or 0.0)
            if driver_earnings > 0:
                revenue_from_bookings += driver_earnings
            else:
                revenue_from_bookings += max(float(r.get("amount") or 0.0), 0.0) * BOOKING_SHARE
        except Exception:
            pass

    revenue_from_custom = 0.0
    for r in rows_custom:
        try:
            driver_earnings = float(r.get("driver_earnings") or 0.0)
            if driver_earnings > 0:
                revenue_from_custom += driver_earnings
            else:
                revenue_from_custom += max(float(r.get("amount") or 0.0), 0.0) * CUSTOM_SHARE
        except Exception:
            pass
    
    revenue_from_ride_hailing = 0.0
    if rows_ride_hailing:
        for r in rows_ride_hailing:
            try:
                driver_earnings = float(r.get("driver_earnings") or 0.0)
                if driver_earnings > 0:
                    revenue_from_ride_hailing += driver_earnings
                else:
                    revenue_from_ride_hailing += max(float(r.get("amount") or 0.0), 0.0) * 0.80
            except Exception:
                pass
    
    print(f"[DEBUG] Revenue breakdown: Standard={revenue_from_bookings}, Custom={revenue_from_custom}, RideHailing={revenue_from_ride_hailing}")
    
    return revenue_from_bookings, revenue_from_custom, revenue_from_ride_hailing

def _compute_period_report(driver_id: str, start_dt_local: datetime, end_excl_dt_local: datetime, expenses: float):
    rows_all, rows_booking, rows_custom, rows_ride_hailing, *_ = _fetch_earnings_rows(driver_id, start_dt_local, end_excl_dt_local)

    revenue_from_bookings, revenue_from_custom, revenue_from_ride_hailing = _sum_driver_share(rows_booking, rows_custom, rows_ride_hailing)
    total_bookings = len(rows_booking) + len(rows_custom) + len(rows_ride_hailing)
    revenue_period = revenue_from_bookings + revenue_from_custom + revenue_from_ride_hailing

    fare_per_ride = (revenue_period / total_bookings) if total_bookings > 0 else 0.0
    if fare_per_ride < 0:
        fare_per_ride = 0.0

    denom = fare_per_ride if fare_per_ride and fare_per_ride > 0 else 0.01
    rides_needed = int(ceil(expenses / denom)) if isfinite(expenses) else 0

    profit_value = revenue_period - expenses

    return {
        "expenses": round(expenses, 2),
        "revenue_driver": round(revenue_period, 2),
        "profit": round(profit_value, 2),
        "rides_needed": rides_needed,
        "rides_done": total_bookings,
        "breakeven_hit": profit_value >= 0,
        "profitable":   profit_value >  0,
        "breakdown": {
            "standard_share": round(revenue_from_bookings, 2),
            "custom_share":   round(revenue_from_custom, 2),
            "ride_hailing_share": round(revenue_from_ride_hailing, 2),
        },
        "debug_counts": {
            "rows_all": len(rows_all),
            "rows_booking": len(rows_booking),
            "rows_custom": len(rows_custom),
            "rows_ride_hailing": len(rows_ride_hailing),
        },
    }

# ───────────────────────────── ViewSet ─────────────────────────────
class BreakevenViewSet(viewsets.ViewSet):
    """
    Bucket by PH calendar day (default) or DB UTC day via `bucket_tz`:
      - ?bucket_tz=ph  → PH calendar day/week/month (+ optional cutoff)
      - ?bucket_tz=utc → UTC calendar day/week/month (+ optional cutoff)

    `display_tz` controls only how times are formatted, not the math.

    STATUS POLICY:
      - Default: include only 'finalized' earnings.
      - Override globally with EARNINGS_INCLUDE_STATUSES / EARNINGS_EXCLUDE_STATUSES env vars.
      - Override per-request with ?status_in=... or ?status_exclude=...
    """
    permission_classes = [AllowAny]

    def list(self, request):
        driver_id = request.query_params.get('driver_id')
        period = request.query_params.get('period', 'today')
        expenses_raw = request.query_params.get('expenses', '0')
        debug = request.query_params.get('debug') in ('1', 'true', 'True')

        # Display tz for formatting only
        display_tz_name = (request.query_params.get('display_tz') or DEFAULT_DISPLAY_TZ).lower().strip()
        tz_out, display_tz_name = _resolve_tz(display_tz_name)

        # Bucket tz for math/windowing
        bucket_tz_name_req = (request.query_params.get('bucket_tz') or DEFAULT_BUCKET_TZ).lower().strip()
        bucket_tz, bucket_tz_name = _resolve_tz(bucket_tz_name_req)

        # Request-level status overrides (optional)
        status_in_param = _parse_statuses_param(request.query_params.get("status_in"))
        status_ex_param = _parse_statuses_param(request.query_params.get("status_exclude"))

        try:
            expenses = float(expenses_raw)
        except Exception:
            expenses = 0.0

        if not driver_id:
            return Response({"success": False, "error": "driver_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Local half-open window in the chosen BUCKET timezone (with cutoff)
        start_dt_local, end_excl_dt_local = _period_range_half_open_tz(period, bucket_tz)
        s_utc = _as_utc(start_dt_local).isoformat()
        e_utc = _as_utc(end_excl_dt_local).isoformat()

        try:
            rows_all, rows_booking, rows_custom, rows_ride_hailing, q_gte, q_lt = _fetch_earnings_rows(
                driver_id, start_dt_local, end_excl_dt_local,
                status_in=status_in_param, status_ex=status_ex_param
            )
        except Exception as e:
            return Response({"success": False, "error": f"DB query failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        revenue_from_bookings, revenue_from_custom, revenue_from_ride_hailing = _sum_driver_share(rows_booking, rows_custom, rows_ride_hailing)
        total_bookings = len(rows_booking) + len(rows_custom) + len(rows_ride_hailing)
        revenue_period = revenue_from_bookings + revenue_from_custom + revenue_from_ride_hailing

        fare_per_ride = (revenue_period / total_bookings) if total_bookings > 0 else 0.0
        if fare_per_ride < 0:
            fare_per_ride = 0.0

        denom = fare_per_ride if fare_per_ride and fare_per_ride > 0 else 0.01
        bookings_needed = int(ceil(expenses / denom)) if isfinite(expenses) else 0

        profit_value = revenue_period - expenses
        deficit_amount = max(expenses - revenue_period, 0)

        # Inclusive-looking end for UI
        display_end = (end_excl_dt_local - timedelta(seconds=1))

        payload = {
            "success": True,
            "data": {
                "period": period,
                "driver_id": driver_id,
                "date_start": start_dt_local.isoformat(),
                "date_end": display_end.isoformat(),
                "expenses": round(expenses, 2),

                "total_bookings": total_bookings,
                "revenue_period": round(revenue_period, 2),
                "revenue_today": round(revenue_period, 2) if (period or "").lower() == "today" else None,
                "fare_per_ride": round(fare_per_ride, 2),
                "bookings_needed": bookings_needed,

                "profitable": profit_value >= 0,
                "deficit_amount": round(deficit_amount, 2),

                "breakdown": {
                    "driver_share_from_standard": round(revenue_from_bookings, 2),
                    "driver_share_from_custom":   round(revenue_from_custom, 2),
                    "driver_share_from_ride_hailing": round(revenue_from_ride_hailing, 2),
                },
            },
        }
        
        # Check for breakeven notifications (async, non-blocking)
        try:
            if driver_id and expenses > 0:  # Only check if meaningful data
                # Get previous data for comparison
                try:
                    prev_result = supabase.table("breakeven_history") \
                        .select("expenses, revenue_driver, profit") \
                        .eq("driver_id", driver_id) \
                        .eq("period_type", "daily") \
                        .order("snapshot_at", desc=True) \
                        .limit(1) \
                        .execute()
                    
                    previous_data = None
                    if prev_result.data:
                        prev = prev_result.data[0]
                        previous_data = {
                            'expenses': float(prev.get('expenses', 0)),
                            'revenue': float(prev.get('revenue_driver', 0)),
                            'profit': float(prev.get('profit', 0))
                        }
                except:
                    previous_data = None
                
                # Run notification check in background (non-blocking)
                def run_notification_check():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        result = loop.run_until_complete(
                            BreakevenNotificationService.check_and_notify_breakeven_status(
                                driver_id, payload, previous_data
                            )
                        )
                        loop.close()
                    except Exception as e:
                        print(f"Breakeven notification error: {e}")
                
                import threading
                threading.Thread(target=run_notification_check, daemon=True).start()
        except Exception as e:
            print(f"Breakeven notification setup error: {e}")

        if debug:
            tally = {}
            for r in rows_all:
                sname = (r.get("status") or "").lower()
                tally[sname] = tally.get(sname, 0) + 1

            rows_preview = []
            for r in rows_all[:5]:
                raw_iso = r.get("earning_date")
                parsed = _parse_db_ts(raw_iso)
                rows_preview.append({
                    "id": r.get("id"),
                    "status": r.get("status"),
                    "amount": r.get("amount"),
                    "earning_db": raw_iso,
                    "earning_display": _fmt_ts(raw_iso, tz_out),
                    "earning_bucket_day": (parsed.astimezone(bucket_tz).date().isoformat() if parsed else None),
                    "has_booking": bool(r.get("booking_id")),
                    "has_custom":  bool(r.get("custom_tour_id")),
                    "has_ride_hailing": bool(r.get("ride_hailing_booking_id")),
                    "driver_earnings": r.get("driver_earnings"),
                })

            payload["data"]["_debug"] = {
                "server_now_ph": datetime.now(PH_TZ).isoformat(),
                "server_now_utc": datetime.now(UTC).isoformat(),
                "display_tz": display_tz_name,
                "bucket_tz": bucket_tz_name,
                "day_cutoff_hour": DAY_CUTOFF_HOUR,
                "bucket_window": {"gte": start_dt_local.isoformat(), "lt": end_excl_dt_local.isoformat()},
                "utc_window": {"gte": s_utc, "lt": e_utc},
                "query_bounds_used": {"gte": q_gte, "lt": q_lt},
                "counts": {
                    "all_rows": len(rows_all),
                    "booking_rows": len(rows_booking),
                    "custom_rows": len(rows_custom),
                    "ride_hailing_rows": len(rows_ride_hailing),
                },
                "week_mode": WEEK_MODE,
                "included_statuses_env": list(INCLUDED_EARNINGS_STATUSES),
                "excluded_statuses_env": list(EXCLUDED_EARNINGS_STATUSES),
                "status_in_param":  list(status_in_param),
                "status_exclude_param": list(status_ex_param),
                "status_tally": tally,
                "shares": {"booking": BOOKING_SHARE, "custom": CUSTOM_SHARE},
                "rows_preview": rows_preview,
            }

        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=False, methods=['GET'], url_path='history')
    def history(self, request):
        driver_id = request.query_params.get('driver_id')
        period_type = (request.query_params.get('period_type') or 'daily').lower()
        limit_raw = request.query_params.get('limit') or '30'
        exclude_current = request.query_params.get('exclude_current', '1') in ('1', 'true', 'True')

        # History uses the server's DEFAULT_BUCKET_TZ (+ cutoff)
        bucket_tz, bucket_tz_name = _resolve_tz(DEFAULT_BUCKET_TZ)

        if not driver_id:
            return Response({"success": False, "error": "driver_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            limit = max(1, min(int(limit_raw), 200))
        except Exception:
            limit = 30

        today_local = _today_in_tz(bucket_tz)
        current_start, _ = _period_boundaries_for_type_tz(period_type, today_local, bucket_tz)
        try:
            q = (
                supabase.table("breakeven_history")
                .select("*")
                .eq("driver_id", driver_id)
                .eq("period_type", period_type)
            )
            if exclude_current:
                q = q.lt("period_start", current_start.isoformat())
            r = q.order("period_start", desc=True).limit(limit).execute()
            items = getattr(r, "data", None) or []
            return Response({"success": True, "data": {"items": items}}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "error": f"DB query failed: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=False, methods=['POST'], url_path='snapshot')
    def snapshot(self, request):
        # Snapshots follow DEFAULT_BUCKET_TZ (+ cutoff) unless overridden later.
        if CRON_SECRET:
            if request.headers.get("X-Cron-Secret") != CRON_SECRET:
                return Response({"success": False, "error": "unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        body = request.data or {}
        only_driver = body.get("driver_id")

        bucket_tz, bucket_tz_name = _resolve_tz(DEFAULT_BUCKET_TZ)
        now = datetime.now(bucket_tz)
        today = now.date()

        jobs = [("daily",) + _period_boundaries_for_type_tz("daily", today, bucket_tz)]
        if today.weekday() == 6:  # Sunday in BUCKET_TZ
            jobs.append(("weekly",) + _period_boundaries_for_type_tz("weekly", today, bucket_tz))
        if _is_last_day_of_month(today):
            jobs.append(("monthly",) + _period_boundaries_for_type_tz("monthly", today, bucket_tz))

        results = []
        for period_type, start_dt_local, end_excl_dt_local in jobs:
            driver_ids = [only_driver] if only_driver else _distinct_driver_ids_in_range(start_dt_local, end_excl_dt_local)
            if not driver_ids:
                results.append({"period_type": period_type, "count": 0})
                continue

            rows_to_upsert = []
            for drv in driver_ids:
                # Optional user-entered expense cache
                try:
                    r = (
                        supabase.table("breakeven_expense_cache")
                        .select("expenses")
                        .eq("driver_id", drv)
                        .limit(1)
                        .execute()
                    )
                    data = getattr(r, "data", []) or []
                    expenses_cached = float(data[0].get("expenses") or 0) if data else 0.0
                except Exception:
                    expenses_cached = 0.0

                rep = _compute_period_report(drv, start_dt_local, end_excl_dt_local, expenses_cached)

                # Keep inclusive-looking end (end_excl - 1s) for display
                display_end = (end_excl_dt_local - timedelta(seconds=1))

                rows_to_upsert.append({
                    "driver_id": drv,
                    "period_type": period_type,
                    "period_start": start_dt_local.isoformat(),
                    "period_end": display_end.isoformat(),
                    **{k: v for k, v in rep.items() if k != "debug_counts"},
                    "snapshot_at": now.isoformat(),
                    "bucket_tz": bucket_tz_name,
                    "day_cutoff_hour": DAY_CUTOFF_HOUR,
                })

            try:
                supabase.table("breakeven_history") \
                    .upsert(rows_to_upsert, on_conflict="driver_id,period_type,period_start") \
                    .execute()
                results.append({"period_type": period_type, "count": len(rows_to_upsert)})
            except Exception as e:
                results.append({"period_type": period_type, "error": str(e)})

        return Response({"success": True, "data": results}, status=status.HTTP_200_OK)
