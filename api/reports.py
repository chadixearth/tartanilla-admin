from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny

from tartanilla_admin.supabase import supabase
try:
    from tartanilla_admin.supabase import supabase_admin
except Exception:
    supabase_admin = None

# Optional JWT helpers (used if available)
try:
    from core.jwt_auth import get_token_from_request, verify_token
except Exception:
    get_token_from_request = None
    verify_token = None

from datetime import datetime, date, timezone
import json
import logging
import os
import traceback

# Optional PyJWT for best-effort decode (not required)
try:
    import jwt  # PyJWT
except Exception:
    jwt = None

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Shared helpers (aligned with refunds.py)
# ────────────────────────────────────────────────────────────
def _json_sanitize(obj):
    from decimal import Decimal
    if isinstance(obj, dict):
        return {k: _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, Decimal):
        try:
            return float(obj)
        except Exception:
            return str(obj)
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

def _iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _fetch_user_profile(user_id=None, email=None):
    """Load from public.users (FK target of audit_logs.user_id)."""
    try:
        sb = _sb_for_read()
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

def _extract_actor(request):
    """
    Same resolution order used in refunds.py:
      1) Admin cookies
      2) Project helpers (verify_token/get_token_from_request)
      3) Django request.user
      4) Body hints (actor block)
    """
    uid = uname = role = email = None

    # 1) Admin cookies
    try:
        admin_user_id = request.COOKIES.get('admin_user_id')
        admin_email = request.COOKIES.get('admin_email')
        admin_authenticated = request.COOKIES.get('admin_authenticated')
        if admin_authenticated == '1' and admin_user_id and admin_email:
            uid = admin_user_id.strip() if admin_user_id else None
            email = admin_email.strip() if admin_email else None
            role = "admin"

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

def _audit_log(request, *, action, entity_name, entity_id=None, old_data=None, new_data=None):
    """
    Insert into public.audit_logs (best-effort).
    Columns: user_id, username, role, action, entity_name, entity_id, old_data, new_data, ip_address, device_info
    """
    try:
        actor = _extract_actor(request)
        payload = {
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
        payload = {k: v for k, v in payload.items() if v is not None}
        _sb_for_audit().table("audit_logs").insert(payload).execute()
    except Exception as ex:
        logger.warning(f"Audit log insert failed: {ex}")

# ────────────────────────────────────────────────────────────
# ViewSet
# ────────────────────────────────────────────────────────────
class ReportsViewSet(viewsets.ViewSet):
    """ViewSet for managing all types of reports in the system"""
    permission_classes = [AllowAny]
    
    def list(self, request):
        """Get all reports with filtering options"""
        try:
            report_type = request.query_params.get('type')
            status_filter = request.query_params.get('status')
            priority = request.query_params.get('priority')
            limit = request.query_params.get('limit', 50)
            
            query = supabase.table('reports').select('*').order('created_at', desc=True).limit(int(limit))
            if report_type:
                query = query.eq('report_type', report_type)
            if status_filter:
                query = query.eq('status', status_filter)
            if priority:
                query = query.eq('priority', priority)
            
            response = query.execute()
            reports = response.data if hasattr(response, 'data') else []

            # Audit: list view
            _audit_log(
                request,
                action="REPORT_LIST_VIEW",
                entity_name="reports",
                entity_id=None,
                old_data=None,
                new_data={"filters": {"type": report_type, "status": status_filter, "priority": priority, "limit": int(limit)},
                         "count": len(reports)}
            )
            
            return Response({
                'success': True,
                'data': reports,
                'count': len(reports)
            })
        except Exception as e:
            _audit_log(
                request,
                action="REPORT_LIST_ERROR",
                entity_name="reports",
                entity_id=None,
                old_data=None,
                new_data={"error": str(e)}
            )
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def create(self, request):
        """Create a new report"""
        try:
            data = request.data
            
            required_fields = ['report_type', 'title', 'description', 'reporter_id', 'reporter_type']
            for field in required_fields:
                if not data.get(field):
                    _audit_log(
                        request,
                        action="REPORT_CREATE_INVALID_INPUT",
                        entity_name="reports",
                        entity_id=None,
                        old_data=None,
                        new_data={"missing_field": field}
                    )
                    return Response({'success': False, 'error': f'Missing required field: {field}'}, status=status.HTTP_400_BAD_REQUEST)
            
            report_data = {
                'report_type': data['report_type'],
                'title': data['title'],
                'description': data['description'],
                'reporter_id': data['reporter_id'],
                'reporter_type': data['reporter_type'],
                'related_booking_id': data.get('related_booking_id'),
                'related_user_id': data.get('related_user_id'),
                'status': 'pending',
                'priority': data.get('priority', 'medium'),
                'created_at': datetime.now().isoformat()
            }
            
            response = supabase.table('reports').insert(report_data).execute()
            if hasattr(response, 'data') and response.data:
                created = response.data[0]

                # Audit: created
                _audit_log(
                    request,
                    action="REPORT_CREATE",
                    entity_name="reports",
                    entity_id=created.get("id"),
                    old_data=None,
                    new_data=created
                )

                # Notify admin of new report (no audit needed here)
                self._notify_admin_of_new_report(created)
                
                return Response({
                    'success': True,
                    'data': created,
                    'message': 'Report created successfully'
                }, status=status.HTTP_201_CREATED)
            else:
                _audit_log(
                    request,
                    action="REPORT_CREATE_FAILED",
                    entity_name="reports",
                    entity_id=None,
                    old_data=None,
                    new_data={"input": report_data}
                )
                return Response({'success': False, 'error': 'Failed to create report'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            _audit_log(
                request,
                action="REPORT_CREATE_ERROR",
                entity_name="reports",
                entity_id=None,
                old_data=None,
                new_data={"error": str(e)}
            )
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'])
    def review_driver_cancellation(self, request):
        """Admin reviews driver cancellation and decides if it affects metrics"""
        try:
            data = request.data
            report_id = data.get('report_id')
            admin_decision = data.get('decision')  # 'justified' or 'unjustified'
            admin_notes = data.get('admin_notes', '')
            admin_id = data.get('admin_id')
            
            if not report_id or admin_decision not in ['justified', 'unjustified']:
                _audit_log(
                    request,
                    action="REPORT_REVIEW_INVALID_INPUT",
                    entity_name="reports",
                    entity_id=report_id,
                    old_data=None,
                    new_data={"decision": admin_decision, "error": "report_id and decision (justified/unjustified) are required"}
                )
                return Response({'success': False, 'error': 'report_id and decision (justified/unjustified) are required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Load report (old state)
            report_response = supabase.table('reports').select('*').eq('id', report_id).execute()
            if not report_response.data:
                _audit_log(
                    request,
                    action="REPORT_REVIEW_NOT_FOUND",
                    entity_name="reports",
                    entity_id=report_id,
                    old_data=None,
                    new_data=None
                )
                return Response({'success': False, 'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
            
            report = report_response.data[0]
            
            if report.get('report_type') != 'driver_cancellation':
                _audit_log(
                    request,
                    action="REPORT_REVIEW_WRONG_TYPE",
                    entity_name="reports",
                    entity_id=report_id,
                    old_data=report,
                    new_data={"error": "Endpoint only for driver_cancellation reports"}
                )
                return Response({'success': False, 'error': 'This endpoint is only for driver cancellation reports'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Admin client for update
            client = supabase_admin if supabase_admin else supabase
            
            decision_note = f"Admin Decision: {admin_decision.upper()}\nReview Date: {datetime.now().isoformat()}\n{admin_notes}"
            update_data = {
                'status': 'resolved',
                'admin_notes': decision_note,
                'decision': admin_decision,
                'priority': 'high' if admin_decision == 'unjustified' else 'medium'
            }
            update_response = client.table('reports').update(update_data).eq('id', report_id).execute()
            if not hasattr(update_response, 'data'):
                _audit_log(
                    request,
                    action="REPORT_REVIEW_UPDATE_FAILED",
                    entity_name="reports",
                    entity_id=report_id,
                    old_data=report,
                    new_data=update_data
                )
                return Response({'success': False, 'error': 'Failed to update report in database'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Process metrics effect
            affects_metrics = False
            driver_suspended = False
            suspension_details = None
            message = f'Cancellation marked as {admin_decision}.'

            try:
                driver_id = report.get('reporter_id')
                booking_id = report.get('related_booking_id')
                description = report.get('description', '')
                reason_line = [line for line in description.split('\n') if 'Cancellation Reason:' in line]
                reason = reason_line[0].split('Cancellation Reason:')[1].strip() if reason_line else 'Admin reviewed'
                
                if driver_id and booking_id:
                    if admin_decision == 'unjustified':
                        from api.driver_metrics import record_driver_cancellation, check_and_suspend_driver_if_needed
                        record_driver_cancellation(driver_id=driver_id, booking_id=booking_id, reason=reason, booking_type='tour')
                        affects_metrics = True
                        suspension = check_and_suspend_driver_if_needed(driver_id, admin_id)
                        driver_suspended = suspension.get('success', False) if suspension else False
                        suspension_details = suspension if suspension else None
                        message = f'Cancellation marked as {admin_decision}. Driver metrics updated and cancellation count increased.'
                    else:
                        message = f'Cancellation marked as {admin_decision}. No impact on driver metrics.'
            except Exception as e:
                _audit_log(
                    request,
                    action="REPORT_REVIEW_METRICS_ERROR",
                    entity_name="reports",
                    entity_id=report_id,
                    old_data=report,
                    new_data={"error": str(e)}
                )
                return Response({'success': False, 'error': f'Failed to process admin decision: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Audit: review outcome
            _audit_log(
                request,
                action="REPORT_REVIEW_DRIVER_CANCELLATION",
                entity_name="reports",
                entity_id=report_id,
                old_data=report,
                new_data={
                    "decision": admin_decision,
                    "admin_notes": admin_notes,
                    "update": update_data,
                    "affects_metrics": affects_metrics,
                    "driver_suspended": driver_suspended,
                    "suspension_details": suspension_details
                }
            )

            return Response({
                'success': True,
                'message': message,
                'driver_suspended': driver_suspended,
                'suspension_details': suspension_details,
                'admin_decision': admin_decision,
                'affects_metrics': affects_metrics
            })
        except Exception as e:
            _audit_log(
                request,
                action="REPORT_REVIEW_ERROR",
                entity_name="reports",
                entity_id=None,
                old_data=None,
                new_data={"error": str(e)}
            )
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['put'])
    def update_status(self, request, pk=None):
        """Update report status"""
        try:
            data = request.data
            admin_id = data.get('admin_id')
            new_status = data.get('status')
            admin_notes = data.get('admin_notes', '')
            
            if not new_status:
                _audit_log(
                    request,
                    action="REPORT_STATUS_INVALID_INPUT",
                    entity_name="reports",
                    entity_id=pk,
                    old_data=None,
                    new_data={"error": "Status is required"}
                )
                return Response({'success': False, 'error': 'Status is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Load old for audit
            old = None
            try:
                old_resp = supabase.table('reports').select('*').eq('id', pk).single().execute()
                old = getattr(old_resp, 'data', None)
            except Exception:
                pass

            update_data = {
                'status': new_status,
                'admin_notes': admin_notes,
                'updated_at': datetime.now().isoformat()
            }
            if new_status == 'resolved' and admin_id:
                update_data['resolved_by'] = admin_id
                update_data['resolved_at'] = datetime.now().isoformat()
            
            response = supabase.table('reports').update(update_data).eq('id', pk).execute()
            if hasattr(response, 'data') and response.data:
                updated_row = response.data[0]

                _audit_log(
                    request,
                    action="REPORT_UPDATE_STATUS",
                    entity_name="reports",
                    entity_id=pk,
                    old_data=old,
                    new_data=updated_row
                )

                return Response({'success': True, 'data': updated_row, 'message': 'Report status updated successfully'})
            else:
                _audit_log(
                    request,
                    action="REPORT_UPDATE_STATUS_FAILED",
                    entity_name="reports",
                    entity_id=pk,
                    old_data=old,
                    new_data=update_data
                )
                return Response({'success': False, 'error': 'Failed to update report'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            _audit_log(
                request,
                action="REPORT_UPDATE_STATUS_ERROR",
                entity_name="reports",
                entity_id=pk,
                old_data=None,
                new_data={"error": str(e)}
            )
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'])
    def trip_report(self, request):
        """Create a trip report after booking completion"""
        try:
            data = request.data
            required_fields = ['booking_id', 'driver_id', 'reason']
            for field in required_fields:
                if not data.get(field):
                    _audit_log(
                        request,
                        action="REPORT_TRIP_CREATE_INVALID_INPUT",
                        entity_name="reports",
                        entity_id=None,
                        old_data=None,
                        new_data={"missing_field": field}
                    )
                    return Response({'success': False, 'error': f'Missing required field: {field}'}, status=status.HTTP_400_BAD_REQUEST)
            
            booking_response = supabase.table('bookings').select('*').eq('id', data['booking_id']).execute()
            booking = booking_response.data[0] if booking_response.data else None
            if not booking:
                _audit_log(
                    request,
                    action="REPORT_TRIP_CREATE_NO_BOOKING",
                    entity_name="reports",
                    entity_id=None,
                    old_data=None,
                    new_data={"booking_id": data.get('booking_id')}
                )
                return Response({'success': False, 'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
            
            detailed_description = f"""Trip Issue Report
                
Reason: {data['reason']}
Additional Details: {data.get('description', 'None provided')}

Booking Information:
- Booking Reference: {booking.get('booking_reference', 'N/A')}
- Customer: {booking.get('customer_name', 'N/A')}
- Driver ID: {data['driver_id']}
- Booking ID: {data['booking_id']}

This report was submitted by the driver after trip completion."""
            
            report_data = {
                'report_type': 'trip_issue',
                'title': f'Trip Issue Report - Booking #{data["booking_id"]}',
                'description': detailed_description,
                'reporter_id': data['driver_id'],
                'reporter_type': 'driver',
                'related_booking_id': data['booking_id'],
                'related_user_id': booking.get('customer_id'),
                'status': 'pending',
                'priority': 'medium',
                'created_at': datetime.now().isoformat()
            }
            
            response = supabase.table('reports').insert(report_data).execute()
            if hasattr(response, 'data') and response.data:
                created = response.data[0]

                _audit_log(
                    request,
                    action="REPORT_TRIP_CREATE",
                    entity_name="reports",
                    entity_id=created.get("id"),
                    old_data=None,
                    new_data=created
                )

                self._notify_admin_of_new_report(created)
                
                return Response({'success': True, 'data': created, 'message': 'Trip report submitted successfully'}, status=status.HTTP_201_CREATED)
            else:
                _audit_log(
                    request,
                    action="REPORT_TRIP_CREATE_FAILED",
                    entity_name="reports",
                    entity_id=None,
                    old_data=None,
                    new_data={"input": report_data}
                )
                return Response({'success': False, 'error': 'Failed to create trip report'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            _audit_log(
                request,
                action="REPORT_TRIP_CREATE_ERROR",
                entity_name="reports",
                entity_id=None,
                old_data=None,
                new_data={"error": str(e)}
            )
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get report statistics"""
        try:
            response = supabase.table('reports').select('report_type, status, priority, created_at').execute()
            reports = response.data if hasattr(response, 'data') else []
            
            stats = {
                'total_reports': len(reports),
                'by_type': {},
                'by_status': {},
                'by_priority': {},
                'pending_count': 0
            }
            
            for report in reports:
                rtype = report.get('report_type', 'unknown')
                stats['by_type'][rtype] = stats['by_type'].get(rtype, 0) + 1
                
                rstatus = report.get('status', 'unknown')
                stats['by_status'][rstatus] = stats['by_status'].get(rstatus, 0) + 1
                
                prio = report.get('priority', 'unknown')
                stats['by_priority'][prio] = stats['by_priority'].get(prio, 0) + 1
                
                if rstatus == 'pending':
                    stats['pending_count'] += 1

            _audit_log(
                request,
                action="REPORT_STATS_VIEW",
                entity_name="reports",
                entity_id=None,
                old_data=None,
                new_data={"summary": {
                    "total": stats["total_reports"],
                    "pending": stats["pending_count"],
                    "types": list(stats["by_type"].keys())
                }}
            )
            
            return Response({'success': True, 'data': stats})
        except Exception as e:
            _audit_log(
                request,
                action="REPORT_STATS_ERROR",
                entity_name="reports",
                entity_id=None,
                old_data=None,
                new_data={"error": str(e)}
            )
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _notify_admin_of_new_report(self, report):
        """Notify admin of new report (no audit entry needed here)"""
        try:
            admin_response = supabase.table('users').select('id').eq('role', 'admin').execute()
            admin_ids = [admin['id'] for admin in admin_response.data] if admin_response.data else []
            if not admin_ids:
                return
            
            notification_data = {
                'title': f'New {report["report_type"].replace("_", " ").title()} Report',
                'message': f'{report["title"]} - Priority: {report["priority"].upper()}',
                'type': 'booking',
                'created_at': datetime.now().isoformat()
            }
            
            notification = supabase.table('notifications').insert(notification_data).execute()
            if notification.data:
                notification_id = notification.data[0]['id']
                recipients = [{
                    'notification_id': notification_id,
                    'user_id': admin_id,
                    'role': 'admin',
                    'delivery_status': 'sent'
                } for admin_id in admin_ids]
                supabase.table('notification_recipients').insert(recipients).execute()
        except Exception as e:
            logger.info(f"Failed to notify admin of new report: {e}")
