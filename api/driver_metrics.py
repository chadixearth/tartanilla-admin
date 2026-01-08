from datetime import datetime, timedelta, date
from typing import Optional, Dict
from tartanilla_admin.supabase import supabase
from api.data import suspend_user

DRIVER_METRICS_TABLE = 'driver_metrics'
DRIVER_CANCEL_LOGS_TABLE = 'driver_cancellation_logs'
DRIVER_COMPLETE_LOGS_TABLE = 'driver_completion_logs'

CANCELLATION_THRESHOLD_30D = 5
SUSPENSION_DAYS = 7


def _now_iso() -> str:
    return datetime.now().isoformat()


def ensure_metrics_row(driver_id: str) -> Dict:
    """Ensure a metrics row exists for the driver and return it.

    Avoids PostgREST PGRST116 by not using `.single()` when the row may not exist yet.
    """
    # Try to fetch existing without forcing a single JSON object
    response = supabase.table(DRIVER_METRICS_TABLE).select('*').eq('driver_id', driver_id).execute()
    rows = getattr(response, 'data', None) or []
    if rows:
        # If multiple rows somehow exist, return the most recent by updated_at
        if len(rows) > 1:
            try:
                rows.sort(key=lambda r: (r.get('updated_at') or r.get('created_at') or ''), reverse=True)
            except Exception:
                pass
        return rows[0]

    # Create if not exists
    payload = {
        'driver_id': driver_id,
        'cancellation_count': 0,
        'completed_count': 0,
        'last_cancellation_at': None,
        'last_completion_at': None,
        'updated_at': _now_iso(),
        'created_at': _now_iso(),
    }
    # Insert the row (no upsert to stay compatible); ignore duplicate errors implicitly
    resp = supabase.table(DRIVER_METRICS_TABLE).insert(payload).execute()
    created_rows = getattr(resp, 'data', None) or []
    return created_rows[0] if created_rows else payload


def record_driver_cancellation_for_review(driver_id: str, booking_id: str, reason: Optional[str] = None, booking_type: str = 'tour') -> None:
    """Log a cancellation event for admin review without affecting metrics."""
    try:
        # Insert basic log entry - admin will review via reports system
        supabase.table(DRIVER_CANCEL_LOGS_TABLE).insert({
            'driver_id': driver_id,
            'booking_id': booking_id,
            'reason': reason or 'unspecified',
            'booking_type': booking_type,
            'cancelled_at': _now_iso(),
        }).execute()
    except Exception as e:
        print(f"Warning: Could not log cancellation for review: {e}")
        # Continue execution - the report system will handle the review


def record_driver_cancellation(driver_id: str, booking_id: str, reason: Optional[str] = None, booking_type: str = 'tour') -> None:
    """Increment cancellation counters and log a cancellation event (for unjustified cancellations)."""
    ensure_metrics_row(driver_id)
    # Increment metrics
    metrics_resp = supabase.table(DRIVER_METRICS_TABLE).select('*').eq('driver_id', driver_id).execute()
    metrics_rows = getattr(metrics_resp, 'data', None) or []
    metrics = metrics_rows[0] if metrics_rows else {}
    current_count = (metrics.get('cancellation_count') or 0) + 1
    supabase.table(DRIVER_METRICS_TABLE).update({
        'cancellation_count': current_count,
        'last_cancellation_at': _now_iso(),
        'updated_at': _now_iso(),
    }).eq('driver_id', driver_id).execute()

    # Insert log for unjustified cancellation
    supabase.table(DRIVER_CANCEL_LOGS_TABLE).insert({
        'driver_id': driver_id,
        'booking_id': booking_id,
        'reason': reason or 'unspecified',
        'booking_type': booking_type,
        'cancelled_at': _now_iso(),
    }).execute()


def record_driver_completion(driver_id: str, booking_id: str, booking_type: str = 'tour') -> None:
    """Increment completion counters and log a completion event."""
    ensure_metrics_row(driver_id)
    # Increment metrics
    metrics_resp = supabase.table(DRIVER_METRICS_TABLE).select('*').eq('driver_id', driver_id).execute()
    metrics_rows = getattr(metrics_resp, 'data', None) or []
    metrics = metrics_rows[0] if metrics_rows else {}
    current_count = (metrics.get('completed_count') or 0) + 1
    supabase.table(DRIVER_METRICS_TABLE).update({
        'completed_count': current_count,
        'last_completion_at': _now_iso(),
        'updated_at': _now_iso(),
    }).eq('driver_id', driver_id).execute()

    # Insert log
    supabase.table(DRIVER_COMPLETE_LOGS_TABLE).insert({
        'driver_id': driver_id,
        'booking_id': booking_id,
        'booking_type': booking_type,
        'completed_at': _now_iso(),
    }).execute()


def get_driver_metrics_summary(driver_id: str) -> Dict:
    """Return metrics and last-30-days aggregates for a driver."""
    ensure_metrics_row(driver_id)
    # Overall
    metrics_resp = supabase.table(DRIVER_METRICS_TABLE).select('*').eq('driver_id', driver_id).execute()
    metrics_rows = getattr(metrics_resp, 'data', None) or []
    metrics = metrics_rows[0] if metrics_rows else {}

    # 30-day window
    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
    cancels_30_resp = supabase.table(DRIVER_CANCEL_LOGS_TABLE).select('id', count='exact').eq('driver_id', driver_id).gte('cancelled_at', thirty_days_ago).execute()
    completes_30_resp = supabase.table(DRIVER_COMPLETE_LOGS_TABLE).select('id', count='exact').eq('driver_id', driver_id).gte('completed_at', thirty_days_ago).execute()
    cancels_30 = getattr(cancels_30_resp, 'count', 0) or 0
    completes_30 = getattr(completes_30_resp, 'count', 0) or 0

    return {
        'driver_id': driver_id,
        'cancellation_count': metrics.get('cancellation_count', 0),
        'completed_count': metrics.get('completed_count', 0),
        'cancellations_30d': cancels_30,
        'completions_30d': completes_30,
        'last_cancellation_at': metrics.get('last_cancellation_at'),
        'last_completion_at': metrics.get('last_completion_at'),
    }


def check_and_suspend_driver_if_needed(driver_id: str, admin_email: str = 'system@auto') -> Optional[Dict]:
    """Suspend driver if 30-day cancellations exceed threshold."""
    summary = get_driver_metrics_summary(driver_id)
    if summary['cancellations_30d'] >= CANCELLATION_THRESHOLD_30D:
        reason = f"Auto-suspension: {summary['cancellations_30d']} cancellations in last 30 days"
        return suspend_user(driver_id, SUSPENSION_DAYS, reason, admin_email)
    return None
