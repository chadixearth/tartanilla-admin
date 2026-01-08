from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action
from tartanilla_admin.supabase import supabase, upload_booking_verification_photo, execute_with_retry, safe_query
from core.error_handlers import handle_api_errors, safe_supabase_operation, APIErrorHandler
from core.connection_health_monitor import ensure_healthy_connection
from datetime import datetime, date
import traceback
import json
import uuid
import random
import string
import base64
from decimal import Decimal, ROUND_HALF_UP
from core.api_utils import OptimizedViewSetMixin, APIResponseManager, cached_api_method
from core.cache_utils import CacheManager
from core.database_utils import DatabaseManager, DataProcessor
from api.driver_metrics import record_driver_cancellation, record_driver_completion, check_and_suspend_driver_if_needed
from django.utils import timezone
from datetime import timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# Dynamic earnings distribution - matches earnings.py implementation
DEFAULT_ADMIN_PERCENTAGE = Decimal("0.20")   # Default 20% to admin

def get_organization_percentage():
    """Get current organization percentage from system_settings table"""
    try:
        res = supabase.table('system_settings').select('value').eq('key', 'organization_percentage').execute()
        if res.data and res.data[0].get('value'):
            return Decimal(str(res.data[0]['value'])) / 100
    except Exception as e:
        print(f"[BOOKING] Error fetching organization percentage: {e}")
    return DEFAULT_ADMIN_PERCENTAGE

def get_driver_percentage():
    """Get driver percentage (100% - organization%)"""
    return Decimal("1.00") - get_organization_percentage()

def _quantize_money(amount: Decimal) -> Decimal:
    """Keep money to 2 decimal places for consistency"""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _log_audit(user_id, username, role, action, entity_name, entity_id, old_data=None, new_data=None, request=None):
    """Log audit trail for booking operations"""
    try:
        ip_address = None
        device_info = None
        
        if request:
            # Get IP address
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0]
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            
            # Get device info from user agent
            device_info = request.META.get('HTTP_USER_AGENT', '')[:255]
        
        audit_data = {
            'user_id': user_id,
            'username': username or 'Unknown',
            'role': role or 'system',
            'action': action,
            'entity_name': entity_name,
            'entity_id': str(entity_id) if entity_id else None,
            'old_data': old_data,
            'new_data': new_data,
            'ip_address': ip_address,
            'device_info': device_info
        }
        
        supabase.table('audit_logs').insert(audit_data).execute()
    except Exception as e:
        print(f"Audit log error: {e}")


class TourBookingViewSet(OptimizedViewSetMixin, viewsets.ViewSet):
    """ViewSet for tour package bookings - Tourist books package, admin approves, driver accepts & completes"""
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer, BrowsableAPIRenderer]
    
    # Optimization configuration
    TABLE_NAME = 'bookings'
    MODULE_NAME = 'tour_booking'
    DATE_FIELDS = ['booking_date', 'created_at', 'updated_at']
    JSON_FIELDS = []
    CACHE_TIMEOUT = 'short'  # Bookings change frequently

    # =========================
    # NEW/UPDATED HELPER LOGIC
    # =========================

    DEFAULT_PAYOUT_METHOD = "cash"  # change if you prefer 'gcash' etc.

    def _dec(self, n) -> Decimal:
        return Decimal(str(n or "0"))

    def _now_iso(self):
        """Get current time in Asia/Manila timezone as ISO string"""
        manila_tz = ZoneInfo('Asia/Manila')
        return datetime.now(manila_tz).isoformat()

    def _safe_first(self, resp):
        rows = resp.data if hasattr(resp, "data") and resp.data else []
        return rows[0] if rows else None

    def _ensure_earnings_for_booking(self, booking: dict) -> dict | None:
        """Insert a pending earnings row only if booking is paid."""
        try:
            # Only create earnings if payment_status is 'paid'
            if booking.get("payment_status") != "paid":
                return None
                
            # Already has one?
            existing = supabase.table("earnings").select("*").eq("booking_id", booking["id"]).limit(1).execute()
            row = self._safe_first(existing)
            if row:
                return row

            payload = {
                "booking_id": booking["id"],
                "custom_tour_id": None,                          # for tour packages
                "driver_id": booking.get("driver_id"),           # may be None at create time
                "driver_name": booking.get("driver_name"),
                "amount": float(self._dec(booking.get("total_amount"))),
                "earning_date": self._now_iso(),
                "status": "pending",
                "organization_percentage": float(get_organization_percentage() * 100),
            }
            ins = supabase.table("earnings").insert(payload).execute()
            return self._safe_first(ins)
        except Exception as e:
            print(f"[earnings:create] skipped: {e}")
            return None

    def _tag_earnings_with_driver(self, booking_id: str, driver_id: str, driver_name: str):
        """If an earnings row exists for this booking, fill in the driver info."""
        try:
            supabase.table("earnings").update({
                "driver_id": driver_id,
                "driver_name": driver_name
            }).eq("booking_id", booking_id).execute()
        except Exception as e:
            print(f"[earnings:tag driver] ignored: {e}")

    def _get_or_create_pending_payout(self, *, driver_id: str, driver_name: str, add_amount: Decimal) -> dict:
        """Find a pending payout for the driver or create a new one, and add the amount."""
        # 1) find existing pending
        existing = supabase.table("payouts").select("*") \
            .eq("driver_id", driver_id).eq("status", "pending").limit(1).execute()
        payout = self._safe_first(existing)

        if payout:
            new_total = self._dec(payout.get("total_amount")) + add_amount
            upd = supabase.table("payouts").update({
                "total_amount": float(_quantize_money(new_total)),
                "updated_at": self._now_iso()  # safe even if column doesn't exist (Supabase ignores unknown)
            }).eq("id", payout["id"]).execute()
            return self._safe_first(upd) or payout

        # 2) create new pending payout
        payload = {
            "driver_id": driver_id,
            "driver_name": driver_name or "Unknown Driver",
            "total_amount": float(_quantize_money(add_amount)),
            "payout_method": self.DEFAULT_PAYOUT_METHOD,
            "status": "pending",
            "remarks": "Auto-created from completed booking",
            "payout_date": self._now_iso(),  # has default; ok to set
        }
        ins = supabase.table("payouts").insert(payload).execute()
        return self._safe_first(ins)

    def _finalize_earnings_and_queue_payout(self, booking: dict) -> dict:
        """
        When a booking completes:
          - ensure an earnings row exists (created at booking creation),
          - compute shares based on booking type,
          - insert payout_earnings (idempotent by earning_id),
          - create/update pending payout and add driver's share,
          - flip earnings.status -> finalized.
        Returns a small summary dict for the response.
        """
        booking_id = booking["id"]
        driver_id = booking.get("driver_id")
        driver_name = booking.get("driver_name") or "Unknown Driver"

        if not driver_id:
            return {"ok": False, "reason": "Missing driver_id on booking"}

        # 1) find/create earnings (only if booking is paid)
        earn_res = supabase.table("earnings").select("*").eq("booking_id", booking_id).limit(1).execute()
        earning = self._safe_first(earn_res)
        if not earning:
            earning = self._ensure_earnings_for_booking(booking)

        if not earning:
            return {"ok": False, "reason": "No earnings found - booking may not be paid yet"}

        # If already finalized, make this idempotent.
        if (earning.get("status") or "").lower() == "finalized":
            return {"ok": True, "already_finalized": True, "earning_id": earning["id"]}

        total = self._dec(earning.get("amount")) or self._dec(booking.get("total_amount"))
        
        # Check if this is a tour package booking or ride hailing/custom tour
        # Tour package bookings have booking_id in the earnings table and no custom_tour_id
        # Custom tours and ride hailing have custom_tour_id or no booking_id
        earning_booking_id = earning.get("booking_id")
        custom_tour_id = earning.get("custom_tour_id")
        
        if earning_booking_id and not custom_tour_id:
            # Tour package booking - organization gets percentage share
            org_percentage = get_organization_percentage()
            driver_percentage = Decimal("1.00") - org_percentage
            driver_share = _quantize_money(total * driver_percentage)
            admin_share = _quantize_money(total * org_percentage)
        else:
            # Ride hailing or custom tour - driver gets 100%
            driver_share = _quantize_money(total)
            admin_share = _quantize_money(Decimal("0.00"))
            org_percentage = Decimal("0.00")

        # 2) ensure payout exists / updated
        payout = self._get_or_create_pending_payout(
            driver_id=driver_id, driver_name=driver_name, add_amount=driver_share
        )
        if not payout:
            return {"ok": False, "reason": "Failed to create/find pending payout"}

        # 3) insert payout_earnings (idempotent by earning_id)
        exists = supabase.table("payout_earnings").select("id") \
            .eq("earning_id", earning["id"]).limit(1).execute()
        pe_existing = self._safe_first(exists)

        if not pe_existing:
            supabase.table("payout_earnings").insert({
                "payout_id": payout["id"],
                "earning_id": earning["id"],
                "driver_id": driver_id,
                "driver_name": driver_name,
                "share_amount": float(driver_share),
                "status": "pending",
            }).execute()

        # 4) finalize earnings with breakdown - use current percentage from system_settings
        current_percentage = get_organization_percentage()
        supabase.table("earnings").update({
            "status": "finalized",
            "driver_id": driver_id,
            "driver_name": driver_name,
            "total_amount": float(total),
            "driver_earnings": float(driver_share),
            "admin_earnings": float(admin_share),
            "organization_percentage": float(current_percentage * 100),
        }).eq("id", earning["id"]).execute()

        return {
            "ok": True,
            "earning_id": earning["id"],
            "payout_id": payout["id"],
            "driver_share": float(driver_share),
            "admin_share": float(admin_share),
            "total_amount": float(total),
        }

    # === NEW: reverse earnings + create refund on cancellation ===

    def _refund_reference(self):
        """Generate unique refund reference number"""
        today = date.today().strftime('%Y%m%d')
        random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        return f"RF-{today}-{random_chars}"

    def _check_and_cancel_unpaid_bookings(self):
        """Check for bookings that have been driver_assigned for more than 3 hours without payment"""
        try:
            # Calculate 3 hours ago
            three_hours_ago = timezone.now() - timedelta(hours=3)
            
            # Find bookings that are driver_assigned, payment_status is pending, and driver_assigned_at is more than 12 hours ago
            query = supabase.table('bookings').select('*').eq('status', 'driver_assigned').eq('payment_status', 'pending')
            response = query.execute()
            
            bookings_to_cancel = []
            if hasattr(response, 'data') and response.data:
                for booking in response.data:
                    driver_assigned_at = booking.get('driver_assigned_at')
                    if driver_assigned_at:
                        try:
                            assigned_time = datetime.fromisoformat(driver_assigned_at.replace('Z', '+00:00'))
                            if assigned_time.replace(tzinfo=timezone.utc) < three_hours_ago:
                                bookings_to_cancel.append(booking)
                        except Exception as e:
                            print(f"Error parsing driver_assigned_at for booking {booking.get('id')}: {e}")
            
            cancelled_count = 0
            for booking in bookings_to_cancel:
                try:
                    # Get old booking data for audit
                    old_booking_data = dict(booking)
                    
                    # Cancel the booking
                    update_data = {
                        'status': 'cancelled',
                        'cancel_reason': 'Automatic cancellation - Payment not completed within 3 hours',
                        'cancelled_by': 'system',
                        'cancelled_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat(),
                        'driver_id': None,  # Remove driver assignment
                        'driver_name': None,
                        'driver_assigned_at': None
                    }
                    
                    result = supabase.table('bookings').update(update_data).eq('id', booking['id']).execute()
                    
                    # Log audit trail for auto-cancellation
                    if hasattr(result, 'data') and result.data:
                        try:
                            _log_audit(
                                user_id=None,
                                username='System',
                                role='system',
                                action='AUTO_CANCEL_UNPAID',
                                entity_name='bookings',
                                entity_id=booking['id'],
                                old_data=old_booking_data,
                                new_data=result.data[0],
                                request=None
                            )
                        except Exception as audit_error:
                            print(f"Audit log error: {audit_error}")
                    
                    # Create refund (no payment was made, so refund amount is 0)
                    self._reverse_earnings_and_create_refund(
                        booking, 
                        reason='Automatic cancellation - Payment not completed within 3 hours',
                        cancelled_by='system'
                    )
                    
                    # Notify customer
                    try:
                        customer_id = booking.get('customer_id')
                        if customer_id:
                            notification_data = {
                                'title': 'Booking Cancelled ⏰',
                                'message': f'Your booking for {booking.get("package_name", "tour package")} has been automatically cancelled due to non-payment within 3 hours. You can book again anytime.',
                                'type': 'booking',
                                'created_at': datetime.now().isoformat()
                            }
                            
                            notification = supabase.table('notifications').insert(notification_data).execute()
                            
                            if notification.data:
                                notification_id = notification.data[0]['id']
                                supabase.table('notification_recipients').insert({
                                    'notification_id': notification_id,
                                    'user_id': customer_id,
                                    'role': 'tourist',
                                    'delivery_status': 'sent'
                                }).execute()
                    except Exception as e:
                        print(f"Failed to notify customer of auto-cancellation: {e}")
                    
                    cancelled_count += 1
                    print(f"Auto-cancelled booking {booking['id']} due to non-payment")
                    
                except Exception as e:
                    print(f"Error auto-cancelling booking {booking.get('id')}: {e}")
            
            return {
                'success': True,
                'cancelled_count': cancelled_count,
                'message': f'Auto-cancelled {cancelled_count} unpaid bookings'
            }
            
        except Exception as e:
            print(f"Error in auto-cancellation check: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _reverse_earnings_and_create_refund(self, booking: dict, *, reason: str, cancelled_by: str) -> dict:
        """
        Flip earnings for this booking to 'reversed', undo any pending payout_earnings,
        reduce pending payout totals accordingly, and create a refund request using the new refunds API.
        Safe to call multiple times (idempotent).
        """
        try:
            # 1) locate earning
            earn_res = supabase.table("earnings").select("*").eq("booking_id", booking["id"]).limit(1).execute()
            earning = self._safe_first(earn_res)

            # 2) if not found, nothing to reverse (still push refund below)
            earning_id = earning.get("id") if earning else None
            already_reversed = bool(earning and str(earning.get("status", "")).lower() == "reversed")

            # 3) mark earnings reversed
            if earning and not already_reversed:
                try:
                    supabase.table("earnings").update({
                        "status": "reversed",
                        "reversed_at": self._now_iso(),
                        "reversed_reason": reason or "Booking cancelled",
                        "reversed_by": cancelled_by or "system",
                    }).eq("id", earning_id).execute()
                except Exception as e:
                    print(f"[earnings:reverse] update failed: {e}")

                # 4) if there is a payout_earnings, mark reversed and adjust pending payout total
                try:
                    pe_res = supabase.table("payout_earnings").select("*").eq("earning_id", earning_id).limit(1).execute()
                    pe = self._safe_first(pe_res)
                    if pe and (pe.get("status") or "").lower() != "reversed":
                        supabase.table("payout_earnings").update({"status": "reversed"}).eq("id", pe["id"]).execute()
                        # adjust payout only if still pending
                        payout_id = pe.get("payout_id")
                        if payout_id:
                            po_res = supabase.table("payouts").select("*").eq("id", payout_id).limit(1).execute()
                            payout = self._safe_first(po_res)
                            if payout and (payout.get("status") or "").lower() == "pending":
                                current_total = self._dec(payout.get("total_amount"))
                                deduct = self._dec(pe.get("share_amount"))
                                new_total = current_total - deduct
                                if new_total < Decimal("0.00"):
                                    new_total = Decimal("0.00")
                                supabase.table("payouts").update({
                                    "total_amount": float(_quantize_money(new_total)),
                                    "updated_at": self._now_iso()
                                }).eq("id", payout_id).execute()
                            # If payout already released, we only flag the payout_earnings as reversed;
                            # handling clawbacks is out-of-scope here by request.
                except Exception as e:
                    print(f"[payout:deduct] ignored: {e}")

            # 5) Create refund request using the new refunds system
            refund_row = None
            refund_amount = 0
            try:
                # Check if refund already exists to avoid duplicates
                existing_refund = supabase.table("refunds").select("*").eq("booking_id", booking["id"]).limit(1).execute()
                if existing_refund.data:
                    refund_row = existing_refund.data[0]
                    refund_amount = refund_row.get("refund_amount", 0)
                    print(f"[refunds] Using existing refund: {refund_row['id']}")
                else:
                    # Get earning_id for this booking
                    earning_res = supabase.table("earnings").select("id").eq("booking_id", booking["id"]).limit(1).execute()
                    earning_row = self._safe_first(earning_res)
                    
                    if earning_row:
                        # Calculate refund amount
                        refund_amount = self._dec(booking.get("total_amount", 0))
                        # No cancellation fee for tourists - always full refund
                        # refund_amount remains unchanged regardless of cancelled_by
                        
                        refund_payload = {
                            "earning_id": earning_row["id"],
                            "booking_id": booking["id"],
                            "driver_id": booking.get("driver_id"),
                            "refund_amount": float(refund_amount if str(booking.get("payment_status", "")).lower() == "paid" else Decimal("0.00")),
                            "reason": reason or "Booking cancelled",
                            "status": "pending",
                            "initiated_by": booking.get("customer_id") or "system",
                            "tourist_id": booking.get("customer_id"),
                            "tourist_name": booking.get("customer_name") or booking.get("tourist_name")
                        }
                        
                        r_ins = supabase.table("refunds").insert(refund_payload).execute()
                        refund_row = self._safe_first(r_ins)
                        refund_amount = refund_amount
                    
                    print(f"[refunds] Created new refund: {refund_row['id'] if refund_row else 'failed'}")
                    
            except Exception as e:
                print(f"[refunds:create] error: {e}")
                # Fallback to basic refund creation if refunds API fails
                try:
                    basic_refund_amount = self._dec(booking.get("total_amount", 0))
                    # No cancellation fee for tourists - always full refund
                    # basic_refund_amount remains unchanged (full refund)
                    
                    # Get earning for fallback
                    earning_res = supabase.table("earnings").select("id").eq("booking_id", booking["id"]).limit(1).execute()
                    earning_row = self._safe_first(earning_res)
                    
                    if earning_row:
                        fallback_payload = {
                            "earning_id": earning_row["id"],
                            "booking_id": booking["id"],
                            "driver_id": booking.get("driver_id"),
                            "refund_amount": float(basic_refund_amount if str(booking.get("payment_status", "")).lower() == "paid" else Decimal("0.00")),
                            "reason": reason or "Booking cancelled",
                            "status": "pending",
                            "initiated_by": booking.get("customer_id") or "system",
                            "tourist_id": booking.get("customer_id"),
                            "tourist_name": booking.get("customer_name") or booking.get("tourist_name")
                        }
                        r_ins = supabase.table("refunds").insert(fallback_payload).execute()
                        refund_row = self._safe_first(r_ins)
                        refund_amount = basic_refund_amount
                        print(f"[refunds] Used fallback refund creation")
                    else:
                        print(f"[refunds:fallback] No earning found for booking {booking['id']}")
                except Exception as fallback_error:
                    print(f"[refunds:fallback] also failed: {fallback_error}")

            return {
                "ok": True,
                "earning_reversed": bool(earning) and not already_reversed,
                "already_reversed": already_reversed,
                "earning_id": earning_id,
                "refund": refund_row or {"attempted": True},
                "refund_amount": float(refund_amount) if refund_amount else 0,
            }
        except Exception as e:
            print(f"[reverse pipeline] error: {e}")
            return {"ok": False, "error": str(e)}

    def _notify_drivers_of_new_booking(self, booking_data):
        """Notify only drivers who have assigned tartanilla carriages"""
        try:
            print(f"[NOTIFICATION] Starting driver notification for booking {booking_data.get('id', 'unknown')}")
            
            # Get drivers who have assigned tartanilla carriages
            carriages_response = supabase.table('tartanilla_carriages').select('assigned_driver_id, capacity').not_.is_('assigned_driver_id', 'null').execute()
            
            if not hasattr(carriages_response, 'data') or not carriages_response.data:
                print("[NOTIFICATION] No drivers with assigned carriages found")
                return {'success': False, 'message': 'No drivers with assigned carriages found'}
            
            # Get unique driver IDs from carriages
            driver_ids = list(set([c['assigned_driver_id'] for c in carriages_response.data if c.get('assigned_driver_id')]))
            
            if not driver_ids:
                print("[NOTIFICATION] No valid driver IDs found from carriages")
                return {'success': False, 'message': 'No valid driver IDs found'}
            
            # Get driver details for those with carriages
            drivers_response = supabase.table('users').select('id, name, email, status').in_('id', driver_ids).execute()
            drivers = drivers_response.data if hasattr(drivers_response, 'data') else []
            
            if not drivers:
                print("[NOTIFICATION] No driver details found")
                return {'success': False, 'message': 'No driver details found'}
            
            active_count = len([d for d in drivers if d.get('status') == 'active'])
            print(f"[NOTIFICATION] Found {len(driver_ids)} drivers with carriages ({active_count} active, {len(driver_ids) - active_count} inactive)")
            
            # Create notification with enhanced message
            tourist_name = booking_data.get('customer_name') or booking_data.get('tourist_name') or 'A tourist'
            package_name = booking_data.get('package_name', 'Tour Package')
            pax_count = booking_data.get('number_of_pax', 1)
            pickup_time = booking_data.get('pickup_time', '09:00')
            booking_date = booking_data.get('booking_date', 'TBD')
            
            notification_data = {
                'title': 'New Booking Request! 🚗',
                'message': f"{tourist_name} needs a driver for {package_name} ({pax_count} pax). Pickup: {pickup_time} on {booking_date}. Only drivers with assigned carriages can accept!",
                'type': 'booking'
            }
            
            notification = supabase.table('notifications').insert(notification_data).execute()
            
            if notification.data:
                notification_id = notification.data[0]['id']
                print(f"[NOTIFICATION] Created notification {notification_id}")
                
                # Create recipients with better error handling
                recipients = []
                for driver_id in driver_ids:
                    try:
                        # Validate UUID format
                        import uuid
                        uuid.UUID(driver_id)
                        recipients.append({
                            'notification_id': notification_id,
                            'user_id': driver_id,
                            'role': 'driver',
                            'delivery_status': 'sent'
                        })
                    except ValueError:
                        print(f"[NOTIFICATION] Skipping invalid driver ID: {driver_id}")
                
                if recipients:
                    recipient_result = supabase.table('notification_recipients').insert(recipients).execute()
                    if recipient_result.data:
                        print(f"[NOTIFICATION] Successfully notified {len(recipient_result.data)} drivers")
                        return {
                            'success': True, 
                            'message': f'Notified {len(recipient_result.data)} drivers (active and inactive)',
                            'notification_id': notification_id,
                            'drivers_notified': len(recipient_result.data),
                            'total_drivers': len(driver_ids),
                            'active_drivers': active_count
                        }
                    else:
                        print(f"[NOTIFICATION] Failed to create recipients")
                        return {'success': False, 'message': 'Failed to create notification recipients'}
                else:
                    print(f"[NOTIFICATION] No valid driver IDs to notify")
                    return {'success': False, 'message': 'No valid driver IDs found'}
            else:
                print(f"[NOTIFICATION] Failed to create notification")
                return {'success': False, 'message': 'Failed to create notification'}
                
        except Exception as e:
            print(f"[NOTIFICATION] Error notifying drivers: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': f'Notification error: {str(e)}'}
    
    def _notify_tourist_of_accepted_booking(self, booking_data, driver_name):
        """Notify tourist that driver accepted their booking"""
        try:
            customer_id = booking_data.get('customer_id')
            if not customer_id:
                print(f"[NOTIFICATION] No customer_id for tourist notification")
                return {'success': False, 'message': 'No customer ID provided'}
            
            print(f"[NOTIFICATION] Notifying tourist {customer_id} of booking acceptance by {driver_name}")
            
            # Validate customer ID format
            try:
                import uuid
                uuid.UUID(customer_id)
            except ValueError:
                print(f"[NOTIFICATION] Invalid customer ID format: {customer_id}")
                return {'success': False, 'message': 'Invalid customer ID format'}
            
            # Create notification with enhanced message
            package_name = booking_data.get('package_name', 'your tour')
            booking_date = booking_data.get('booking_date', 'the scheduled date')
            pickup_time = booking_data.get('pickup_time', 'the scheduled time')
            
            notification_data = {
                'title': 'Booking Accepted! ✅',
                'message': f"Great news! {driver_name} has accepted your {package_name} booking for {booking_date} at {pickup_time}. Get ready for your tour!",
                'type': 'booking',
                'is_broadcast': False,
                'audience_roles': ['tourist'],
                'target_user': customer_id,
                'priority': 'normal'
            }
            
            notification = supabase.table('notifications').insert(notification_data).execute()
            
            if notification.data:
                notification_id = notification.data[0]['id']
                print(f"[NOTIFICATION] Created tourist notification {notification_id}")
                
                # Create recipient
                recipient_result = supabase.table('notification_recipients').insert({
                    'notification_id': notification_id,
                    'user_id': customer_id,
                    'role': 'tourist',
                    'delivery_status': 'sent'
                }).execute()
                
                if recipient_result.data:
                    print(f"[NOTIFICATION] Successfully notified tourist")
                    return {
                        'success': True,
                        'message': 'Tourist notified successfully',
                        'notification_id': notification_id
                    }
                else:
                    print(f"[NOTIFICATION] Failed to create tourist recipient")
                    return {'success': False, 'message': 'Failed to create notification recipient'}
            else:
                print(f"[NOTIFICATION] Failed to create tourist notification")
                return {'success': False, 'message': 'Failed to create notification'}
                
        except Exception as e:
            print(f"[NOTIFICATION] Error notifying tourist: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': f'Tourist notification error: {str(e)}'}
    
    def _get_user_info(self, user_id):
        """Get user info for audit logging"""
        try:
            if not user_id:
                return None, 'system'
            response = supabase.table('users').select('name, role').eq('id', user_id).single().execute()
            if hasattr(response, 'data') and response.data:
                return response.data.get('name'), response.data.get('role')
            return 'Unknown User', 'user'
        except:
            return 'Unknown User', 'user'
    
    # =========================
    # END NEW/UPDATED HELPERS
    # =========================
    
    def _generate_booking_reference(self):
        """Generate a unique booking reference"""
        # Format: TB-YYYYMMDD-XXXXX (TB = Tour Booking)
        today = date.today().strftime('%Y%m%d')
        random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        return f"TB-{today}-{random_chars}"
    
    def _get_customer_info(self, customer_id):
        """Get customer information from users table"""
        try:
            response = supabase.table('users').select('name, email').eq('id', customer_id).execute()
            if hasattr(response, 'data') and response.data:
                user_data = response.data[0]
                return user_data.get('name', ''), user_data.get('email', '')
            else:
                print(f"No tourist found with ID: {customer_id}")
                # Try to get from auth and auto-create user
                try:
                    auth_user = supabase.auth.admin.get_user_by_id(customer_id)
                    if auth_user.user:
                        name = auth_user.user.user_metadata.get('name', auth_user.user.email.split('@')[0] if auth_user.user.email else 'User')
                        email = auth_user.user.email or ''
                        role = auth_user.user.user_metadata.get('role', 'tourist')
                        
                        # Try to auto-create user (may fail due to RLS, but that's ok)
                        try:
                            supabase.table('users').insert({
                                'id': customer_id,
                                'email': email,
                                'name': name,
                                'role': role,
                                'status': 'active'
                            }).execute()
                            print(f"Auto-created user record for {customer_id}")
                        except Exception as rls_error:
                            # RLS policy may block this, but we can still return the user info
                            print(f"Could not auto-create user (RLS policy): {rls_error}")
                        
                        return name, email
                except Exception as auth_error:
                    print(f"Could not fetch auth user {customer_id}: {auth_error}")
                    pass
                
                # Return default values if user doesn't exist
                return 'User', ''
        except Exception as e:
            print(f"Error fetching tourist info for ID {customer_id}: {str(e)}")
            return 'User', ''
    
    def _get_package_info(self, package_id):
        """Get tour package information from tourpackages table"""
        try:
            response = supabase.table('tourpackages').select('package_name, price').eq('id', package_id).single().execute()
            if hasattr(response, 'data') and response.data:
                return response.data.get('package_name', ''), response.data.get('price', 0)
            else:
                print(f"No tour package found with ID: {package_id}")
                return '', 0
        except Exception as e:
            print(f"Error fetching tour package info for ID {package_id}: {str(e)}")
            return '', 0

    def _get_package_availability(self, package_id, booking_date=None):
        """Check if a tour package can be booked on a given date."""
        try:
            response = (
                supabase
                .table('tourpackages')
                .select('package_name, price, is_active, expiration_date, available_days')
                .eq('id', package_id)
                .single()
                .execute()
            )

            package = response.data if hasattr(response, 'data') and response.data else None
            if not package:
                return {'ok': False, 'reason': f'Tour package with ID {package_id} does not exist', 'package': None}

            # Active flag
            if not package.get('is_active', False):
                return {'ok': False, 'reason': 'Tour package is unavailable for booking', 'package': package}

            # Expiration date check
            expiration_value = package.get('expiration_date')
            if expiration_value:
                try:
                    expiration_date_str = str(expiration_value).split('T')[0]
                    expiration_date = datetime.fromisoformat(expiration_date_str).date()
                    if expiration_date < date.today():
                        return {'ok': False, 'reason': 'Tour package has expired and cannot be booked', 'package': package}
                except Exception:
                    pass

            # Day-of-week availability
            if booking_date:
                try:
                    if isinstance(booking_date, str):
                        desired_date = datetime.fromisoformat(booking_date).date()
                    else:
                        desired_date = booking_date

                    available_days = package.get('available_days') or []
                    if isinstance(available_days, list) and len(available_days) > 0:
                        desired_day_name = desired_date.strftime('%A').lower()
                        normalized_days = [str(day).lower() for day in available_days]
                        if desired_day_name not in normalized_days:
                            return {
                                'ok': False,
                                'reason': f"Tour package is not available on {desired_date.strftime('%A')}",
                                'package': package
                            }
                except Exception:
                    pass

            return {'ok': True, 'reason': None, 'package': package}
        except Exception as e:
            print(f"Error checking tour package availability for ID {package_id}: {str(e)}")
            return {'ok': False, 'reason': 'Failed to verify tour package availability', 'package': None}
    
    def list(self, request):
        """Get all tour bookings with optional filtering"""
        try:
            # Get query parameters for filtering
            if hasattr(request, 'query_params'):
                status_filter = request.query_params.get('status')
                customer_id = request.query_params.get('customer_id')
                package_id = request.query_params.get('package_id')
                date_from = request.query_params.get('date_from')
                date_to = request.query_params.get('date_to')
            else:
                status_filter = request.GET.get('status')
                customer_id = request.GET.get('customer_id')
                package_id = request.GET.get('package_id')
                date_from = request.GET.get('date_from')
                date_to = request.GET.get('date_to')
            
            # Build query
            query = supabase.table('bookings').select('*').order('created_at', desc=True)
            
            # Apply filters
            if status_filter:
                query = query.eq('status', status_filter)
            if customer_id:
                query = query.eq('customer_id', customer_id)
            if package_id:
                query = query.eq('package_id', package_id)
            if date_from:
                query = query.gte('booking_date', date_from)
            if date_to:
                query = query.lte('booking_date', date_to)
            
            response = query.execute()
            bookings = response.data if hasattr(response, 'data') else []
            
            return Response({
                'success': True,
                'data': bookings,
                'count': len(bookings)
            })
            
        except Exception as e:
            print(f'Error fetching tour bookings: {str(e)}')
            return Response({
                'success': False,
                'error': 'Failed to fetch tour bookings',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def retrieve(self, request, pk=None):
        """Get a specific tour booking by ID"""
        try:
            response = supabase.table('bookings').select('*').eq('id', pk).single().execute()
            booking = response.data if hasattr(response, 'data') and response.data else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found',
                    'data': None
                }, status=status.HTTP_404_NOT_FOUND)
            
            return Response({
                'success': True,
                'data': booking
            })
            
        except Exception as e:
            print(f'Error fetching tour booking: {str(e)}')
            return Response({
                'success': False,
                'error': 'Failed to fetch tour booking',
                'data': None
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def create(self, request):
        """Tourist creates a new tour package booking"""
        try:
            # Handle both DRF and Django requests
            if hasattr(request, 'data'):
                data = request.data
            else:
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                else:
                    data = request.POST.dict()
            
            # Validate required fields for tour package booking
            required_fields = ['package_id', 'customer_id', 'booking_date', 'number_of_pax']
            for field in required_fields:
                if not data.get(field):
                    return Response({
                        'success': False,
                        'error': f'Missing required field: {field}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate number_of_pax
            number_of_pax = data.get('number_of_pax', 0)
            if number_of_pax <= 0:
                return Response({
                    'success': False,
                    'error': 'Number of passengers must be greater than 0'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate tour package availability (only check if package exists and is active)
            availability = self._get_package_availability(
                data['package_id'],
                data.get('booking_date')
            )
            # Only block if package doesn't exist or is expired - allow bookings even if not available on specific day
            if not availability['ok']:
                error_msg = availability['reason'] or ''
                # Block only for critical errors (expired, doesn't exist)
                if 'expired' in error_msg.lower() or 'does not exist' in error_msg.lower():
                    return Response({
                        'success': False,
                        'error': availability['reason']
                    }, status=status.HTTP_400_BAD_REQUEST)
                # For day-of-week availability, just log a warning but allow booking
                print(f"[BOOKING] Package availability warning (non-blocking): {error_msg}")

            package = availability['package'] or {}
            package_name = package.get('package_name', '')
            package_price = package.get('price', 0)
            
            # Get customer info (will auto-create if possible, or use defaults)
            customer_name, customer_email = self._get_customer_info(data['customer_id'])
            # Don't fail if customer doesn't exist - use defaults and let booking proceed
            if not customer_name:
                customer_name = 'Tourist'
            if not customer_email:
                customer_email = ''
            
            # Calculate total amount
            total_amount = package_price * number_of_pax
            
            # Generate booking reference
            booking_reference = self._generate_booking_reference()
            
            # Prepare tour booking data
            booking_data = {
                'package_id': data['package_id'],
                'customer_id': data['customer_id'],
                'booking_date': data['booking_date'],
                'pickup_time': data.get('pickup_time', '09:00:00'),
                'number_of_pax': number_of_pax,
                'total_amount': total_amount,
                'special_requests': data.get('special_requests', ''),
                'contact_number': data.get('contact_number', ''),
                'pickup_address': data.get('pickup_address', 'Plaza Independencia, Cebu City'),
                'status': 'pending',  # Start as pending, will become waiting_for_driver after payment
                'payment_status': 'pending',  # Track payment status
                'booking_reference': booking_reference,
                'package_name': package_name,
                'package_price': package_price,
                'customer_name': customer_name or 'Tourist',
                'customer_email': customer_email or '',
                'created_at': datetime.now().isoformat()
            }
            
            # Insert into database
            response = supabase.table('bookings').insert(booking_data).execute()
            
            if hasattr(response, 'data') and response.data:
                booking_data = response.data[0]
                
                # Log audit trail for booking creation
                try:
                    username, role = self._get_user_info(data['customer_id'])
                    _log_audit(
                        user_id=data['customer_id'],
                        username=username,
                        role=role,
                        action='CREATE_BOOKING',
                        entity_name='bookings',
                        entity_id=booking_data['id'],
                        new_data=booking_data,
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")

                # NEW: create a pending earnings row immediately (no split yet)
                warn = None
                try:
                    self._ensure_earnings_for_booking(booking_data)
                except Exception as ee:
                    print(f"Warning: failed to insert earnings on create: {ee}")
                    warn = "Earnings row was not created automatically; will be generated on completion."

                # Notify all drivers of new booking
                notification_result = self._notify_drivers_of_new_booking(booking_data)
                print(f"[BOOKING] Driver notification result: {notification_result}")

                response_data = {
                    'success': True,
                    'data': booking_data,
                    'message': 'Tour package booking created successfully. Please proceed with payment.',
                    'next_step': 'Complete payment to confirm your booking.',
                    'payment_required': True,
                    'booking_id': booking_data['id'],
                    'notification_result': notification_result
                }
                
                if warn:
                    response_data['warning'] = warn
                    
                return Response(response_data, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to create tour booking'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error creating tour booking: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='admin-approve/(?P<booking_id>[^/.]+)')
    def admin_approve_booking(self, request, booking_id=None):
        """DEPRECATED: Admin approval no longer required - bookings go directly to drivers
        
        This method is kept for backward compatibility but is no longer used in the flow.
        New bookings are automatically set to 'waiting_for_driver' status.
        """
        try:
            # Check if booking exists
            response = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
            booking = response.data if hasattr(response, 'data') and response.data else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # If booking is already waiting for driver or beyond, return success
            if booking.get('status') in ['waiting_for_driver', 'driver_assigned', 'in_progress', 'completed']:
                return Response({
                    'success': True,
                    'data': booking,
                    'message': 'Booking is already available for drivers'
                })
            
            # For legacy bookings that might still be pending
            if booking.get('status') in ['pending_admin_approval', 'pending']:
                update_data = {
                    'status': 'waiting_for_driver',
                    'updated_at': datetime.now().isoformat()
                }
                
                # Get old booking data for audit
                old_booking_data = dict(booking)
                
                response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
                
                # Log audit trail for admin approval (deprecated)
                if hasattr(response, 'data') and response.data:
                    try:
                        _log_audit(
                            user_id=None,
                            username='Admin',
                            role='admin',
                            action='ADMIN_APPROVE_BOOKING',
                            entity_name='bookings',
                            entity_id=booking_id,
                            old_data=old_booking_data,
                            new_data=response.data[0],
                            request=request
                        )
                    except Exception as audit_error:
                        print(f"Audit log error: {audit_error}")
                
                if hasattr(response, 'data') and response.data:
                    return Response({
                        'success': True,
                        'data': response.data[0],
                        'message': 'Legacy booking approved and made available for drivers'
                    })
            
            return Response({
                'success': False,
                'error': 'Invalid booking status for approval'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            print(f'Error in deprecated admin approval: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='available-for-drivers')
    @handle_api_errors(fallback_data=[])
    def get_available_bookings_for_drivers(self, request):
        """Get all tour bookings that are waiting for drivers to accept - filtered by package creator"""
        # Get query parameters for filtering
        if hasattr(request, 'query_params'):
            driver_id = request.query_params.get('driver_id')
            status_filter = request.query_params.get('status', 'pending')
        else:
            driver_id = request.GET.get('driver_id')
            status_filter = request.GET.get('status', 'pending')
        
        print(f"[AVAILABLE_BOOKINGS] Looking for bookings with status: {status_filter}, driver_id: {driver_id}")
        
        # Build query - get tour bookings waiting for drivers (show pending bookings)
        # Join with tourpackages to get the driver_id of the package creator
        def query_func():
            return supabase.table('bookings').select('*, tourpackages!inner(driver_id)').eq('status', status_filter).order('created_at', desc=True).execute()
        
        print(f"[AVAILABLE_BOOKINGS] Query built for status: {status_filter}")
        
        response = safe_supabase_operation(query_func, fallback_data=[])
        bookings = response.data if hasattr(response, 'data') else []
        
        print(f"[AVAILABLE_BOOKINGS] Found {len(bookings)} bookings with status {status_filter}")
        
        # Filter bookings based on package creator:
        # - If package has no driver_id (admin-created), show to ALL drivers
        # - If package has driver_id (driver-created), show ONLY to that driver
        if driver_id:
            filtered_bookings = []
            for booking in bookings:
                # Check if the package was created by a driver or admin
                package_driver_id = None
                if 'tourpackages' in booking and booking['tourpackages']:
                    package_driver_id = booking['tourpackages'].get('driver_id')
                
                # Show booking if:
                # 1. Package created by admin (driver_id is null) - show to all drivers
                # 2. Package created by this specific driver - show only to creator
                if package_driver_id is None:
                    # Admin-created package - show to all drivers
                    print(f"[AVAILABLE_BOOKINGS] Including booking {booking.get('id')} - admin-created package")
                    filtered_bookings.append(booking)
                elif package_driver_id == driver_id:
                    # Driver-created package - show only to creator
                    print(f"[AVAILABLE_BOOKINGS] Including booking {booking.get('id')} - created by this driver")
                    filtered_bookings.append(booking)
                else:
                    # Driver-created package by different driver - hide
                    print(f"[AVAILABLE_BOOKINGS] Filtering out booking {booking.get('id')} - package created by different driver ({package_driver_id})")
            
            bookings = filtered_bookings
            print(f"[AVAILABLE_BOOKINGS] After driver filter: {len(bookings)} bookings")
        
        # Filter out bookings where this driver is excluded (keep existing logic)
        filtered_bookings = []
        for booking in bookings:
            excluded_drivers = booking.get('excluded_drivers', [])
            if driver_id not in excluded_drivers:
                filtered_bookings.append(booking)
            else:
                print(f"[AVAILABLE_BOOKINGS] Excluding booking {booking.get('id')} - driver {driver_id} is excluded")
        bookings = filtered_bookings
        print(f"[AVAILABLE_BOOKINGS] After filtering exclusions: {len(bookings)} bookings")
        
        # Process bookings for better display
        processed_bookings = []
        for booking in bookings:
            # Format dates for display
            if booking.get('booking_date'):
                try:
                    booking_date = datetime.fromisoformat(booking['booking_date'].split('T')[0])
                    booking['booking_date_formatted'] = booking_date.strftime('%B %d, %Y')
                except:
                    booking['booking_date_formatted'] = booking['booking_date']
            
            # Format total amount
            if booking.get('total_amount'):
                booking['total_amount_formatted'] = f"₱{booking['total_amount']:,.2f}"
            
            # Add booking summary
            booking['summary'] = f"{booking.get('package_name', 'Tour Package')} - {booking.get('number_of_pax', 0)} pax"
            
            # Add pickup details
            booking['pickup_info'] = {
                'address': booking.get('pickup_address', 'Plaza Independencia'),
                'time': booking.get('pickup_time', '09:00:00'),
                'date': booking.get('booking_date_formatted', 'TBD')
            }
            
            processed_bookings.append(booking)
        
        print(f"[AVAILABLE_BOOKINGS] Returning {len(processed_bookings)} processed bookings")
        
        return Response(APIErrorHandler.create_success_response({
            'bookings': processed_bookings,
            'count': len(processed_bookings),
            'driver_id': driver_id
        }))
    
    @action(detail=False, methods=['post'], url_path='admin-reopen/(?P<booking_id>[^/.]+)')
    def admin_reopen_booking(self, request, booking_id=None):
        """Admin reopens a cancelled booking for drivers to accept again"""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            clear_exclusions = data.get('clear_exclusions', False)
            
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            bookings = response.data if hasattr(response, 'data') and response.data else []
            booking = bookings[0] if bookings else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            if booking.get('status') not in ['cancelled']:
                return Response({
                    'success': False,
                    'error': 'Only cancelled bookings can be reopened'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get old booking data for audit
            old_booking_data = dict(booking)
            
            update_data = {
                'status': 'waiting_for_driver',
                'driver_id': None,
                'driver_name': None,
                'reopened_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            if clear_exclusions:
                update_data['excluded_drivers'] = []
            
            update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for admin reopening booking
            if hasattr(update_response, 'data') and update_response.data:
                try:
                    _log_audit(
                        user_id=None,
                        username='Admin',
                        role='admin',
                        action='REOPEN_BOOKING',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=update_response.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")
            
            if hasattr(update_response, 'data') and update_response.data:
                return Response({
                    'success': True,
                    'data': update_response.data[0],
                    'message': 'Booking reopened successfully for drivers to accept'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to reopen booking'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error reopening booking: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='driver-accept/(?P<booking_id>[^/.]+)')
    def driver_accept_booking(self, request, booking_id=None):
        """Driver accepts a tour booking"""
        try:
            # Handle both DRF and Django requests
            if hasattr(request, 'data'):
                data = request.data
            else:
                if request.content_type == 'application/json':
                    data = json.loads(request.body)
                else:
                    data = request.POST.dict()
            
            # Validate required fields
            driver_id = data.get('driver_id')
            driver_name = data.get('driver_name')
            
            if not driver_id or not driver_name:
                return Response({
                    'success': False,
                    'error': 'Missing driver_id or driver_name'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if booking exists and is available for drivers
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            bookings = response.data if hasattr(response, 'data') and response.data else []
            booking = bookings[0] if bookings else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            if booking.get('status') not in ['pending']:
                return Response({
                    'success': False,
                    'error': 'Tour booking is not available for drivers to accept'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if driver has any assigned tartanilla carriage that is eligible for tour packages
            try:
                carriage_response = supabase.table('tartanilla_carriages').select('id, eligibility, status').eq('assigned_driver_id', driver_id).execute()
                
                if not hasattr(carriage_response, 'data') or not carriage_response.data:
                    return Response({
                        'success': False,
                        'error': 'No tartanilla carriage assigned',
                        'error_code': 'NO_CARRIAGE_ASSIGNED',
                        'can_view_only': True,
                        'friendly_message': 'You need an assigned tartanilla carriage to accept bookings. Please contact admin for carriage assignment.'
                    }, status=status.HTTP_403_FORBIDDEN)
                
                # Check if any assigned carriage is eligible for tour packages
                eligible_carriages = [c for c in carriage_response.data if c.get('eligibility') == 'eligible']
                
                if not eligible_carriages:
                    return Response({
                        'success': False,
                        'error': 'No eligible tartanilla carriage for tour packages',
                        'error_code': 'NO_ELIGIBLE_CARRIAGE',
                        'can_view_only': True,
                        'friendly_message': 'Your assigned tartanilla carriage is not eligible for tour packages. Please contact admin to check your carriage eligibility status.'
                    }, status=status.HTTP_403_FORBIDDEN)
                    
            except Exception as carriage_error:
                return Response({
                    'success': False,
                    'error': 'Unable to verify carriage assignment',
                    'error_code': 'CARRIAGE_CHECK_FAILED'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Check for existing PAID bookings (block if driver has paid booking)
            try:
                existing_paid = supabase.table('bookings').select('*')\
                    .eq('driver_id', driver_id)\
                    .eq('payment_status', 'paid')\
                    .in_('status', ['driver_assigned', 'in_progress'])\
                    .execute()
                
                if existing_paid.data:
                    return Response({
                        'success': False,
                        'error': 'You have an active paid booking. Complete it before accepting new bookings.',
                        'existing_booking': existing_paid.data[0]
                    }, status=status.HTTP_409_CONFLICT)
            except Exception as e:
                print(f"Error checking existing paid bookings: {e}")
            
            # Auto-cancel existing UNPAID bookings (allow driver to accept new booking)
            try:
                existing_unpaid = supabase.table('bookings').select('*')\
                    .eq('driver_id', driver_id)\
                    .eq('status', 'driver_assigned')\
                    .eq('payment_status', 'pending')\
                    .execute()
                
                if existing_unpaid.data:
                    for unpaid_booking in existing_unpaid.data:
                        # Cancel the unpaid booking
                        supabase.table('bookings').update({
                            'status': 'cancelled',
                            'cancel_reason': 'Driver accepted another booking before payment',
                            'cancelled_by': 'system',
                            'cancelled_at': datetime.now().isoformat(),
                            'driver_id': None,
                            'driver_name': None,
                            'driver_assigned_at': None
                        }).eq('id', unpaid_booking['id']).execute()
                        
                        # Notify tourist
                        try:
                            customer_id = unpaid_booking.get('customer_id')
                            if customer_id:
                                supabase.table('notifications').insert({
                                    'title': 'Booking Cancelled - Payment Required ⏰',
                                    'message': f'Your booking for {unpaid_booking.get("package_name", "tour")} was cancelled because payment was not completed in time. The driver has accepted another booking.',
                                    'type': 'booking',
                                    'created_at': datetime.now().isoformat()
                                }).execute()
                        except Exception as notif_error:
                            print(f"Failed to notify tourist of auto-cancel: {notif_error}")
                        
                        print(f"Auto-cancelled unpaid booking {unpaid_booking['id']} - driver accepting new booking")
            except Exception as e:
                print(f"Error auto-cancelling unpaid bookings: {e}")
            
            # Check for schedule conflicts (more lenient approach)
            try:
                from api.driver_schedule import DriverScheduleViewSet
                schedule_checker = DriverScheduleViewSet()
                has_conflict, conflict_reason = schedule_checker._check_schedule_conflict(driver_id, booking['booking_date'], booking.get('pickup_time', '09:00'))
                
                if has_conflict and "Error checking schedule" not in str(conflict_reason):
                    return Response({
                        'success': False,
                        'error': f'Schedule conflict: {conflict_reason}',
                        'can_override': False,
                        'debug_info': {
                            'driver_id': driver_id,
                            'booking_date': booking['booking_date'],
                            'pickup_time': booking.get('pickup_time', '09:00'),
                            'conflict_reason': conflict_reason
                        }
                    }, status=status.HTTP_409_CONFLICT)
            except Exception as schedule_error:
                print(f"Schedule check failed for driver {driver_id}: {schedule_error}")
                # Allow booking to proceed if schedule check fails
                pass
            
            # Get old booking data for audit
            old_booking_data = dict(booking)
            
            # Update booking with driver information
            update_data = {
                'status': 'driver_assigned',
                'driver_id': driver_id,
                'driver_name': driver_name,
                'driver_assigned_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for driver assignment
            if hasattr(response, 'data') and response.data:
                try:
                    username, role = self._get_user_info(driver_id)
                    _log_audit(
                        user_id=driver_id,
                        username=username,
                        role=role,
                        action='ASSIGN_DRIVER',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=response.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")
            
            if hasattr(response, 'data') and response.data:
                # Add to driver calendar
                try:
                    from api.driver_schedule import DriverScheduleViewSet
                    schedule_api = DriverScheduleViewSet()
                    calendar_data = {
                        'driver_id': driver_id,
                        'booking_id': booking_id,
                        'booking_date': booking['booking_date'],
                        'booking_time': booking.get('pickup_time', '09:00'),
                        'package_name': booking.get('package_name', 'Tour Package'),
                        'customer_name': booking.get('customer_name', 'Customer')
                    }
                    supabase.table('driver_calendar').insert(calendar_data).execute()
                except Exception as e:
                    print(f"Failed to add to calendar: {e}")
                
                # NEW: tag earnings row with driver info if it already exists
                try:
                    self._tag_earnings_with_driver(booking_id, driver_id, driver_name)
                except Exception as e:
                    print(f"Tag earnings failed (non-fatal): {e}")

                # Check for duplicate notifications before sending
                try:
                    customer_id = response.data[0].get('customer_id')
                    if customer_id:
                        # Check for recent duplicate notifications
                        recent_time = (datetime.now() - timedelta(minutes=5)).isoformat()
                        existing_notif = supabase.table('notifications').select('id').eq('title', 'New Driver Assigned! ✅').gte('created_at', recent_time).execute()
                        
                        if not (hasattr(existing_notif, 'data') and existing_notif.data):
                            notification_data = {
                                'title': 'New Driver Assigned! ✅',
                                'message': f'Great news! {driver_name} has been assigned as your driver. Please complete payment to confirm your tour.',
                                'type': 'booking'
                            }
                            
                            notification = supabase.table('notifications').insert(notification_data).execute()
                            
                            if notification.data:
                                notification_id = notification.data[0]['id']
                                supabase.table('notification_recipients').insert({
                                    'notification_id': notification_id,
                                    'user_id': customer_id,
                                    'role': 'tourist',
                                    'delivery_status': 'sent'
                                }).execute()
                                print(f"[BOOKING] Driver assignment notification sent to tourist")
                        else:
                            print(f"[BOOKING] Skipping duplicate notification")
                except Exception as e:
                    print(f"[BOOKING] Failed to send driver assignment notification: {e}")

                return Response({
                    'success': True,
                    'data': response.data[0],
                    'message': f'Tour booking accepted by {driver_name}. Tourist has been notified of the new driver assignment.'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to assign driver to tour booking'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'[BOOKING_ACCEPT] Error driver accepting tour booking: {str(e)}')
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='start/(?P<booking_id>[^/.]+)')
    def start_booking(self, request, booking_id=None):
        """Driver starts a tour booking on or after the scheduled date, transitioning to in_progress."""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            driver_id = data.get('driver_id')
            client_time = data.get('client_time')  # Get phone's current time

            # Get the booking (avoid forcing single)
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            rows = response.data if hasattr(response, 'data') and response.data else []
            booking = rows[0] if rows else None

            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)

            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'driver_id is required to start tour booking'
                }, status=status.HTTP_400_BAD_REQUEST)

            if booking.get('driver_id') != driver_id:
                return Response({
                    'success': False,
                    'error': 'Only the assigned driver can start this tour booking'
                }, status=status.HTTP_403_FORBIDDEN)

            # Validate payment status
            if booking.get('payment_status') != 'paid':
                return Response({
                    'success': False,
                    'error': 'Trip cannot start. Customer has not paid yet.',
                    'payment_status': booking.get('payment_status')
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Validate scheduled time (allow starting 1 hour before scheduled time)
            try:
                booking_date_str = str(booking.get('booking_date', '')).split('T')[0]
                booking_time_str = booking.get('pickup_time', '09:00:00')
                
                booking_datetime = datetime.fromisoformat(f"{booking_date_str}T{booking_time_str}")
                
                # Use client time if provided, otherwise use server time
                if client_time:
                    try:
                        # Parse ISO time and convert from UTC to Asia/Manila timezone
                        from datetime import timezone as dt_timezone
                        utc_time = datetime.fromisoformat(client_time.replace('Z', '+00:00'))
                        manila_tz = ZoneInfo('Asia/Manila')
                        current_datetime = utc_time.astimezone(manila_tz).replace(tzinfo=None)
                        print(f'[START_TRIP] Using client time (converted to Manila): {current_datetime}')
                    except Exception as e:
                        current_datetime = datetime.now()
                        print(f'[START_TRIP] Failed to parse client time ({e}), using server time: {current_datetime}')
                else:
                    current_datetime = datetime.now()
                    print(f'[START_TRIP] No client time provided, using server time: {current_datetime}')
                
                print(f'[START_TRIP] Booking time: {booking_datetime}')
                
                # Allow starting 1 hour before scheduled time
                early_start_allowed = booking_datetime - timedelta(hours=1)
                
                if current_datetime < early_start_allowed:
                    time_diff = booking_datetime - current_datetime
                    hours = int(time_diff.total_seconds() // 3600)
                    minutes = int((time_diff.total_seconds() % 3600) // 60)
                    
                    time_until = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                    
                    print(f'[START_TRIP] ❌ Too early! Current: {current_datetime}, Can start: {early_start_allowed}')
                    
                    return Response({
                        'success': False,
                        'error': f'Trip starts at {booking_time_str}. You can start 1 hour early (in {time_until}).',
                        'scheduled_time': booking_time_str,
                        'scheduled_date': booking_date_str,
                        'time_until_start': time_until,
                        'early_start_allowed_at': early_start_allowed.strftime('%Y-%m-%d %H:%M:%S'),
                        'current_time': current_datetime.strftime('%Y-%m-%d %H:%M:%S')
                    }, status=status.HTTP_400_BAD_REQUEST)
            except Exception as time_error:
                print(f'Time validation error (allowing start): {time_error}')
                # Allow start if time validation fails

            # Get old booking data for audit
            old_booking_data = dict(booking)
            
            update_data = {
                'status': 'in_progress',
                'updated_at': datetime.now().isoformat()
            }
            update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for booking start
            if hasattr(update_response, 'data') and update_response.data:
                try:
                    username, role = self._get_user_info(driver_id)
                    _log_audit(
                        user_id=driver_id,
                        username=username,
                        role=role,
                        action='START_BOOKING',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=update_response.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")

            if hasattr(update_response, 'data') and update_response.data:
                return Response({
                    'success': True,
                    'data': update_response.data[0],
                    'message': 'Tour booking started and set to in_progress'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to start tour booking'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f'Error starting tour booking: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='complete/(?P<booking_id>[^/.]+)')
    def complete_booking(self, request, booking_id=None):
        """Driver completes a tour booking and finalizes earnings/payouts (requires verification photo uploaded first)."""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            driver_id = data.get('driver_id')

            # Get the booking robustly (avoid PostgREST PGRST116 by not forcing single)
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            rows = response.data if hasattr(response, 'data') and response.data else []
            booking = rows[0] if rows else None

            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)

            # Only the assigned driver can complete the booking
            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'driver_id is required to complete tour booking'
                }, status=status.HTTP_400_BAD_REQUEST)

            if booking.get('driver_id') != driver_id:
                return Response({
                    'success': False,
                    'error': 'Only the assigned driver can complete this tour booking'
                }, status=status.HTTP_403_FORBIDDEN)

            # Allow driver to complete trip anytime (removed time restriction for flexibility)

            # Require the trip to be started (in_progress) before completion
            if booking.get('status') != 'in_progress':
                return Response({
                    'success': False,
                    'error': 'Tour booking must be in progress to complete',
                    'current_status': booking.get('status'),
                    'required_status': 'in_progress'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Check if verification is required and if photo has been uploaded
            verification_required = booking.get('verification_required', True)
            if verification_required and not booking.get('verification_photo_url'):
                return Response({
                    'success': False,
                    'error': 'Verification photo must be uploaded before completing the tour',
                    'verification_required': True
                }, status=status.HTTP_400_BAD_REQUEST)

            # Get old booking data for audit
            old_booking_data = dict(booking)
            
            # Update booking status to completed
            update_data = {
                'status': 'completed',
                'updated_at': datetime.now().isoformat()
            }

            update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for booking completion
            if hasattr(update_response, 'data') and update_response.data:
                try:
                    username, role = self._get_user_info(driver_id)
                    _log_audit(
                        user_id=driver_id,
                        username=username,
                        role=role,
                        action='COMPLETE_BOOKING',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=update_response.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")

            if not (hasattr(update_response, 'data') and update_response.data):
                return Response({
                    'success': False,
                    'error': 'Failed to complete tour booking'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Record driver completion metrics (keep your existing logic)
            if booking_id:
                record_driver_completion(driver_id=driver_id, booking_id=booking_id, booking_type='tour')

            # ============
            # NEW MONEY FLOW (no earnings insert here; it was created on booking create)
            # ============
            finalize = self._finalize_earnings_and_queue_payout(booking)

            if not finalize.get("ok"):
                # Booking is completed; money pipeline failed — return success with a warning
                return Response({
                    'success': True,
                    'data': update_response.data[0],
                    'message': 'Tour booking completed.',
                    'warning': f"Money pipeline failed: {finalize.get('reason', 'unknown error')}. You may need to retry."
                })

            # Success money flow
            return Response({
                'success': True,
                'data': update_response.data[0],
                'money_flow': {
                    'earning_id': finalize.get('earning_id'),
                    'payout_id': finalize.get('payout_id'),
                    'driver_share': finalize.get('driver_share'),
                    'driver_percentage': float(get_driver_percentage() * 100),
                    'admin_percentage': float(get_organization_percentage() * 100),
                    'total_amount': finalize.get('total_amount'),
                },
                'message': 'Tour booking completed. Earnings finalized, payout_earnings added, and payout updated/created (pending).'
            })

        except Exception as e:
            print(f'Error completing tour booking: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='complete-with-photo/(?P<booking_id>[^/.]+)')
    def complete_booking_with_photo(self, request, booking_id=None):
        """Driver completes booking by uploading verification photo in one step"""
        try:
            files = request.FILES
            data = request.data if hasattr(request, 'data') else request.POST.dict()
            driver_id = data.get('driver_id')
            
            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'driver_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get the booking
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            rows = response.data if hasattr(response, 'data') and response.data else []
            booking = rows[0] if rows else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Verify the driver is assigned to this booking
            if booking.get('driver_id') != driver_id:
                return Response({
                    'success': False,
                    'error': 'Only the assigned driver can complete this booking'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check booking status - must be driver_assigned or in_progress
            if booking.get('status') not in ['driver_assigned', 'in_progress']:
                return Response({
                    'success': False,
                    'error': 'Booking must be assigned or in progress to complete'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Allow completion anytime after trip is started (no date restriction)
            
            # Handle file upload
            photo_uploaded = False
            photo_url = None
            
            # Check if photo is uploaded as a file
            if 'photo' in files:
                photo_file = files['photo']
                filename = data.get('filename', photo_file.name or f'verification_{booking_id}.jpg')
                
                # Read file content
                file_content = photo_file.read()
                
                # Upload to Supabase storage
                upload_result = upload_booking_verification_photo(
                    file_content, filename, booking_id, driver_id
                )
                
                if upload_result['success']:
                    photo_uploaded = True
                    photo_url = upload_result['url']
                else:
                    return Response({
                        'success': False,
                        'error': f"Failed to upload photo: {upload_result['error']}"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Check if photo is sent as base64 data
            elif data.get('photo'):
                photo_data = data['photo']
                filename = data.get('filename', f'verification_{booking_id}.jpg')
                
                # Check if it's base64 encoded
                if not isinstance(photo_data, str) or not photo_data.startswith('data:image/'):
                    return Response({
                        'success': False,
                        'error': 'Invalid photo format. Expected base64 encoded image.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    # Extract base64 data
                    base64_data = photo_data.split(',')[1]
                    file_content = base64.b64decode(base64_data)
                    
                    # Upload to Supabase storage
                    upload_result = upload_booking_verification_photo(
                        file_content, filename, booking_id, driver_id
                    )
                    
                    if upload_result['success']:
                        photo_uploaded = True
                        photo_url = upload_result['url']
                    else:
                        return Response({
                            'success': False,
                            'error': f"Failed to upload photo: {upload_result['error']}"
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                        
                except Exception as e:
                    return Response({
                        'success': False,
                        'error': f'Failed to process base64 image: {str(e)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            else:
                return Response({
                    'success': False,
                    'error': 'Photo data is required (either as file upload or base64 data)'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Complete booking with verification photo
            if photo_uploaded and photo_url:
                update_data = {
                    'verification_photo_url': photo_url,
                    'verification_status': 'pending',
                    'verification_uploaded_at': datetime.now().isoformat(),
                    'status': 'completed',
                    'updated_at': datetime.now().isoformat()
                }
                
                update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
                
                if hasattr(update_response, 'data') and update_response.data:
                    completed_booking = update_response.data[0]
                    
                    # Record driver completion metrics
                    try:
                        record_driver_completion(driver_id=driver_id, booking_id=booking_id, booking_type='tour')
                    except Exception as metrics_error:
                        print(f'Error recording completion metrics: {metrics_error}')
                    
                    # Finalize earnings and queue payout
                    finalize_result = None
                    try:
                        finalize_result = self._finalize_earnings_and_queue_payout(completed_booking)
                    except Exception as money_error:
                        print(f'Error finalizing earnings: {money_error}')
                    
                    response_data = {
                        'success': True,
                        'data': {
                            'booking_id': booking_id,
                            'verification_photo_url': photo_url,
                            'verification_status': 'pending',
                            'booking_status': 'completed',
                            'booking_data': completed_booking
                        },
                        'message': 'Booking completed successfully with verification photo'
                    }
                    
                    # Add money flow info if available
                    if finalize_result and finalize_result.get('ok'):
                        response_data['money_flow'] = {
                            'earning_id': finalize_result.get('earning_id'),
                            'payout_id': finalize_result.get('payout_id'),
                            'driver_share': finalize_result.get('driver_share'),
                            'driver_percentage': float(get_driver_percentage() * 100),
                            'admin_percentage': float(get_organization_percentage() * 100),
                            'total_amount': finalize_result.get('total_amount'),
                        }
                    
                    return Response(response_data)
                else:
                    return Response({
                        'success': False,
                        'error': 'Failed to complete booking'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            return Response({
                'success': False,
                'error': 'Failed to process verification photo'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error completing booking with photo: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='upload-verification/(?P<booking_id>[^/.]+)')
    def upload_verification_photo(self, request, booking_id=None):
        """Driver uploads a verification photo before completing the tour"""
        try:
            files = request.FILES
            data = request.data if hasattr(request, 'data') else request.POST.dict()
            driver_id = data.get('driver_id')
            
            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'driver_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get the booking
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            rows = response.data if hasattr(response, 'data') and response.data else []
            booking = rows[0] if rows else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Verify the driver is assigned to this booking
            if booking.get('driver_id') != driver_id:
                return Response({
                    'success': False,
                    'error': 'Only the assigned driver can upload verification for this booking'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check booking status
            if booking.get('status') not in ['driver_assigned', 'in_progress']:
                return Response({
                    'success': False,
                    'error': 'Booking must be in progress to upload verification'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Handle file upload
            photo_uploaded = False
            photo_url = None
            
            # Check if photo is uploaded as a file
            if 'photo' in files:
                photo_file = files['photo']
                filename = data.get('filename', photo_file.name or f'verification_{booking_id}.jpg')
                
                # Read file content
                file_content = photo_file.read()
                
                # Upload to Supabase storage
                upload_result = upload_booking_verification_photo(
                    file_content, filename, booking_id, driver_id
                )
                
                if upload_result['success']:
                    photo_uploaded = True
                    photo_url = upload_result['url']
                else:
                    return Response({
                        'success': False,
                        'error': f"Failed to upload photo: {upload_result['error']}"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Check if photo is sent as base64 data
            elif data.get('photo'):
                photo_data = data['photo']
                filename = data.get('filename', f'verification_{booking_id}.jpg')
                
                # Check if it's base64 encoded
                if not isinstance(photo_data, str) or not photo_data.startswith('data:image/'):
                    return Response({
                        'success': False,
                        'error': 'Invalid photo format. Expected base64 encoded image.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    # Extract base64 data
                    base64_data = photo_data.split(',')[1]
                    file_content = base64.b64decode(base64_data)
                    
                    # Upload to Supabase storage
                    upload_result = upload_booking_verification_photo(
                        file_content, filename, booking_id, driver_id
                    )
                    
                    if upload_result['success']:
                        photo_uploaded = True
                        photo_url = upload_result['url']
                    else:
                        return Response({
                            'success': False,
                            'error': f"Failed to upload photo: {upload_result['error']}"
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                        
                except Exception as e:
                    return Response({
                        'success': False,
                        'error': f'Failed to process base64 image: {str(e)}'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            else:
                return Response({
                    'success': False,
                    'error': 'Photo data is required (either as file upload or base64 data)'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update booking with verification photo URL and complete the booking
            if photo_uploaded and photo_url:
                # Allow completion anytime after trip is started (no date restriction)
                # Update booking with verification photo and complete it
                update_data = {
                    'verification_photo_url': photo_url,
                    'verification_status': 'pending',
                    'verification_uploaded_at': datetime.now().isoformat(),
                    'status': 'completed',  # Complete the booking immediately
                    'updated_at': datetime.now().isoformat()
                }
                
                update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
                
                if hasattr(update_response, 'data') and update_response.data:
                    completed_booking = update_response.data[0]
                    
                    # Record driver completion metrics
                    try:
                        record_driver_completion(driver_id=driver_id, booking_id=booking_id, booking_type='tour')
                    except Exception as metrics_error:
                        print(f'Error recording completion metrics: {metrics_error}')
                    
                    # Finalize earnings and queue payout
                    try:
                        finalize = self._finalize_earnings_and_queue_payout(completed_booking)
                        if not finalize.get("ok"):
                            print(f"Money pipeline warning: {finalize.get('reason', 'unknown error')}")
                    except Exception as money_error:
                        print(f'Error finalizing earnings: {money_error}')
                    
                    return Response({
                        'success': True,
                        'data': {
                            'booking_id': booking_id,
                            'verification_photo_url': photo_url,
                            'verification_status': 'pending',
                            'booking_status': 'completed',
                            'message': 'Verification photo uploaded and booking completed successfully',
                            'redirect_to_complete': False  # No need to redirect since booking is already completed
                        }
                    })
                else:
                    return Response({
                        'success': False,
                        'error': 'Failed to update booking with verification photo'
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            return Response({
                'success': False,
                'error': 'Failed to process verification photo'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error uploading verification photo: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='verification/(?P<booking_id>[^/.]+)')
    def get_verification(self, request, booking_id=None):
        """Tourist views the verification photo for their booking"""
        try:
            # Get query parameters
            customer_id = request.query_params.get('customer_id') if hasattr(request, 'query_params') else request.GET.get('customer_id')
            
            # Get the booking
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            rows = response.data if hasattr(response, 'data') and response.data else []
            booking = rows[0] if rows else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Verify the customer (optional but recommended)
            if customer_id and booking.get('customer_id') != customer_id:
                return Response({
                    'success': False,
                    'error': 'Unauthorized access to booking verification'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check if verification photo exists
            if not booking.get('verification_photo_url'):
                return Response({
                    'success': True,
                    'data': {
                        'booking_id': booking_id,
                        'verification_available': False,
                        'message': 'No verification photo uploaded yet'
                    }
                })
            
            return Response({
                'success': True,
                'data': {
                    'booking_id': booking_id,
                    'verification_available': True,
                    'verification_photo_url': booking.get('verification_photo_url'),
                    'verification_status': booking.get('verification_status', 'pending'),
                    'verification_uploaded_at': booking.get('verification_uploaded_at'),
                    'tourist_reported': booking.get('tourist_reported', False),
                    'report_reason': booking.get('report_reason'),
                    'booking_status': booking.get('status')
                }
            })
            
        except Exception as e:
            print(f'Error getting verification: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='report-verification/(?P<booking_id>[^/.]+)')
    def report_verification(self, request, booking_id=None):
        """Tourist reports a verification photo as fraudulent/scam"""
        try:
            data = request.data if hasattr(request, 'data') else request.POST.dict()
            customer_id = data.get('customer_id')
            report_reason = data.get('reason', '')
            
            if not customer_id:
                return Response({
                    'success': False,
                    'error': 'customer_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not report_reason:
                return Response({
                    'success': False,
                    'error': 'Report reason is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get the booking
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            rows = response.data if hasattr(response, 'data') and response.data else []
            booking = rows[0] if rows else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Verify the customer owns this booking
            if booking.get('customer_id') != customer_id:
                return Response({
                    'success': False,
                    'error': 'Only the booking owner can report verification photos'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check if verification photo exists
            if not booking.get('verification_photo_url'):
                return Response({
                    'success': False,
                    'error': 'No verification photo to report'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if already reported
            if booking.get('tourist_reported'):
                return Response({
                    'success': True,
                    'message': 'This verification has already been reported',
                    'data': {
                        'booking_id': booking_id,
                        'previous_report_reason': booking.get('report_reason'),
                        'report_timestamp': booking.get('report_timestamp')
                    }
                })
            
            # Get old booking data for audit
            old_booking_data = dict(booking)
            
            # Update booking with report information
            update_data = {
                'tourist_reported': True,
                'report_reason': report_reason,
                'report_timestamp': datetime.now().isoformat(),
                'verification_status': 'reported',
                'updated_at': datetime.now().isoformat()
            }
            
            update_response = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for verification report
            if hasattr(update_response, 'data') and update_response.data:
                try:
                    username, role = self._get_user_info(customer_id)
                    _log_audit(
                        user_id=customer_id,
                        username=username,
                        role=role,
                        action='REPORT_VERIFICATION',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=update_response.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")
            
            if hasattr(update_response, 'data') and update_response.data:
                # Log the report for admin review (you might want to create a separate reports table)
                print(f"VERIFICATION REPORT: Booking {booking_id} reported by customer {customer_id}")
                print(f"Driver: {booking.get('driver_id')}, Reason: {report_reason}")
                
                return Response({
                    'success': True,
                    'data': {
                        'booking_id': booking_id,
                        'report_submitted': True,
                        'message': 'Thank you for reporting. Our team will review this case.'
                    }
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to submit report'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            print(f'Error reporting verification: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='customer-cancel/(?P<booking_id>[^/.]+)')
    def customer_cancel_booking(self, request, booking_id=None):
        """Tourist cancels a tour package booking"""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            customer_id = data.get('customer_id')
            reason = data.get('reason', '')
            
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            bookings = response.data if hasattr(response, 'data') and response.data else []
            booking = bookings[0] if bookings else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
            if booking.get('customer_id') != customer_id:
                return Response({
                    'success': False,
                    'error': 'Unauthorized cancellation'
                }, status=status.HTTP_403_FORBIDDEN)
                
            if booking.get('status') in ['completed', 'cancelled']:
                return Response({
                    'success': False,
                    'error': 'Tour booking already finalized'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # No cancellation fee for tourists - always full refund
            cancellation_fee = 0
            refund_amount = booking.get('total_amount', 0)
            
            # Tourist cancellations always get full refund regardless of timing
            # This provides better customer experience and encourages bookings
            
            # Get old booking data for audit
            old_booking_data = dict(booking)
            
            update_data = {
                'status': 'cancelled',
                'cancel_reason': reason,
                'cancelled_by': 'customer',
                'cancelled_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            update = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for customer cancellation
            if hasattr(update, 'data') and update.data:
                try:
                    username, role = self._get_user_info(customer_id)
                    _log_audit(
                        user_id=customer_id,
                        username=username,
                        role=role,
                        action='CANCEL_BOOKING_CUSTOMER',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=update.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")

            # NEW: reverse earnings + create refund request
            reverse_info = self._reverse_earnings_and_create_refund(booking, reason=reason, cancelled_by='customer')
            
            return Response({
                'success': True,
                'data': update.data[0] if hasattr(update, 'data') and update.data else {},
                'reversal': reverse_info,
                'cancellation_policy': {
                    'cancellation_fee': 0,  # No fee for tourists
                    'refund_amount': refund_amount,
                    'original_amount': booking.get('total_amount', 0),
                    'policy': 'No cancellation fee - full refund for all tourist cancellations'
                },
                'refund_info': {
                    'refund_reference': reverse_info.get('refund', {}).get('refund_reference'),
                    'refund_amount': reverse_info.get('refund_amount', refund_amount),
                    'processing_time': '3-5 business days'
                },
                'message': 'Tour booking cancelled successfully. Refund will be processed within 3-5 business days.'
            })
            
        except Exception as e:
            print(f'Error customer cancelling tour booking: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='cancellation-policy/(?P<booking_id>[^/.]+)')
    def get_cancellation_policy(self, request, booking_id=None):
        """Get cancellation policy and fees for a booking"""
        try:
            customer_id = request.query_params.get('customer_id') if hasattr(request, 'query_params') else request.GET.get('customer_id')
            
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            bookings = response.data if hasattr(response, 'data') and response.data else []
            booking = bookings[0] if bookings else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
            if customer_id and booking.get('customer_id') != customer_id:
                return Response({
                    'success': False,
                    'error': 'Unauthorized access'
                }, status=status.HTTP_403_FORBIDDEN)
            
            if booking.get('status') in ['completed', 'cancelled']:
                return Response({
                    'success': False,
                    'error': 'Booking cannot be cancelled',
                    'can_cancel': False
                })
            
            # No cancellation fee for tourists - always full refund
            total_amount = booking.get('total_amount', 0)
            cancellation_fee = 0
            refund_amount = total_amount
            policy_message = "Free cancellation - No fees for tourist cancellations"
            
            return Response({
                'success': True,
                'data': {
                    'booking_id': booking_id,
                    'can_cancel': True,
                    'total_amount': total_amount,
                    'cancellation_fee': cancellation_fee,
                    'refund_amount': refund_amount,
                    'policy_message': policy_message,
                    'booking_date': booking.get('booking_date'),
                    'booking_status': booking.get('status')
                }
            })
            
        except Exception as e:
            print(f'Error getting cancellation policy: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='driver-cancel/(?P<booking_id>[^/.]+)')
    def driver_cancel_booking(self, request, booking_id=None):
        """Driver cancels a tour package booking with enhanced reporting and reassignment"""
        try:
            data = request.data if hasattr(request, 'data') else (request.POST.dict())
            driver_id = data.get('driver_id')
            reason = data.get('reason', '')
            
            response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            bookings = response.data if hasattr(response, 'data') and response.data else []
            booking = bookings[0] if bookings else None
            
            if not booking:
                return Response({
                    'success': False,
                    'error': 'Tour booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
            if not driver_id or (booking.get('driver_id') and booking.get('driver_id') != driver_id):
                return Response({
                    'success': False,
                    'error': 'Unauthorized driver'
                }, status=status.HTTP_403_FORBIDDEN)
            
            if booking.get('status') in ['completed', 'cancelled']:
                return Response({
                    'success': False,
                    'error': 'Tour booking already finalized'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Store cancelled driver in excluded list
            excluded_drivers = booking.get('excluded_drivers', [])
            if driver_id not in excluded_drivers:
                excluded_drivers.append(driver_id)
            
            # Get old booking data for audit
            old_booking_data = dict(booking)
            
            # Update booking status to pending for reassignment
            update_data = {
                'status': 'pending',  # Reset to pending for reassignment
                'driver_id': None,  # Remove current driver
                'driver_name': None,
                'driver_assigned_at': None,
                'cancel_reason': reason,
                'last_cancelled_by': 'driver',
                'last_cancelled_at': datetime.now().isoformat(),
                'excluded_drivers': excluded_drivers,
                'updated_at': datetime.now().isoformat()
            }
            
            update = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for driver cancellation
            if hasattr(update, 'data') and update.data:
                try:
                    username, role = self._get_user_info(driver_id)
                    _log_audit(
                        user_id=driver_id,
                        username=username,
                        role=role,
                        action='CANCEL_BOOKING_DRIVER',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=update.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")
            
            updated_booking = update.data[0] if hasattr(update, 'data') and update.data else booking
            
            # Create driver cancellation report for admin using enhanced reporting
            try:
                driver_name = booking.get('driver_name', 'Unknown Driver')
                package_name = booking.get('package_name', 'Tour Package')
                customer_name = booking.get('customer_name', 'Tourist')
                
                # Create detailed description with all relevant information
                detailed_description = f"""Driver Cancellation Report
                
Driver: {driver_name} (ID: {driver_id})
Customer: {customer_name}
Package: {package_name}
Booking Reference: {booking.get('booking_reference', 'N/A')}
Booking Date: {booking.get('booking_date', 'N/A')}
Total Amount: ₱{booking.get('total_amount', 0):,.2f}

Cancellation Reason: {reason or 'No reason provided'}

This booking has been reassigned to other available drivers and the customer has been notified."""
                
                report_data = {
                    'report_type': 'driver_cancellation',
                    'title': f'Driver Cancellation - {package_name}',
                    'description': detailed_description,
                    'reporter_id': driver_id,
                    'reporter_type': 'driver',
                    'related_booking_id': booking_id,
                    'related_user_id': booking.get('customer_id'),
                    'status': 'pending',
                    'priority': 'medium',
                    'created_at': datetime.now().isoformat()
                }
                
                print(f"[REPORT] Creating report with data: {report_data}")
                report_result = supabase.table('reports').insert(report_data).execute()
                
                if hasattr(report_result, 'data') and report_result.data:
                    report_id = report_result.data[0]['id']
                    print(f"[REPORT] ✅ Successfully created driver cancellation report {report_id} for booking {booking_id}")
                    print(f"[REPORT] Report title: {report_data['title']}")
                    print(f"[REPORT] Report should now be visible in web admin panel")
                else:
                    print(f"[REPORT] ❌ Failed to create report - no data returned")
                    print(f"[REPORT] Response: {report_result}")
                
            except Exception as e:
                print(f"[REPORT] ❌ Failed to create cancellation report: {e}")
                print(f"[REPORT] Error type: {type(e).__name__}")
                import traceback
                traceback.print_exc()
                # Continue execution even if report creation fails
                pass
            
            # Notify admin of driver cancellation with enhanced details
            try:
                admin_response = supabase.table('users').select('id').eq('role', 'admin').execute()
                admin_ids = [admin['id'] for admin in admin_response.data] if admin_response.data else []
                
                if admin_ids:
                    notification_data = {
                        'title': 'Driver Cancellation Report 🚫',
                        'message': f'Driver {booking.get("driver_name", "Unknown")} cancelled {booking.get("package_name", "booking")} for {booking.get("customer_name", "tourist")}. Reason: {reason or "No reason provided"}. Check reports page for details.',
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
                        print(f"[NOTIFICATION] Notified {len(admin_ids)} admins of driver cancellation")
                        
            except Exception as e:
                print(f"[NOTIFICATION] Failed to notify admin of driver cancellation: {e}")
            
            # Broadcast booking to all available drivers (reassignment)
            try:
                broadcast_result = self._notify_drivers_of_new_booking(updated_booking)
                print(f"[REASSIGNMENT] Broadcast result: {broadcast_result}")
            except Exception as e:
                print(f"[REASSIGNMENT] Failed to broadcast booking: {e}")
            
            # Notify tourist of driver cancellation and reassignment
            try:
                customer_id = booking.get('customer_id')
                if customer_id:
                    notification = supabase.table('notifications').insert({
                        'title': 'Driver Changed - Reassigning 🔄',
                        'message': f"Your driver cancelled due to: {reason or 'unforeseen circumstances'}. We're finding you a new driver. You'll be notified once a new driver accepts your booking.",
                        'type': 'booking',
                        'created_at': datetime.now().isoformat()
                    }).execute()
                    
                    if notification.data:
                        notification_id = notification.data[0]['id']
                        supabase.table('notification_recipients').insert({
                            'notification_id': notification_id,
                            'user_id': customer_id,
                            'role': 'tourist',
                            'delivery_status': 'sent'
                        }).execute()
                        print(f"[NOTIFICATION] Notified tourist of reassignment")
                        
            except Exception as e:
                print(f"[NOTIFICATION] Failed to notify tourist: {e}")
            
            # Record cancellation for admin review but don't affect metrics yet
            # Metrics will only be recorded if admin marks cancellation as unjustified
            try:
                from api.driver_metrics import record_driver_cancellation_for_review
                record_driver_cancellation_for_review(driver_id=driver_id, booking_id=booking_id, reason=reason)
                print(f"[METRICS] Recorded cancellation for admin review: driver={driver_id}, booking={booking_id}")
            except Exception as metrics_error:
                print(f"[METRICS] Failed to record cancellation for review: {metrics_error}")
                import traceback
                traceback.print_exc()
            
            suspension = None  # No automatic suspension until admin review

            # Don't create refund for driver cancellation since booking is reassigned
            reverse_info = {'ok': True, 'reassigned': True}
            
            payload = {
                'success': True,
                'data': updated_booking,
                'reversal': reverse_info,
                'message': 'Booking cancelled and reassigned to available drivers. Tourist and admin have been notified.',
                'reassignment_status': 'broadcasted'
            }
            
            if suspension and suspension.get('success'):
                payload['driver_suspended'] = True
                payload['suspension'] = suspension
            else:
                payload['driver_suspended'] = False
                
            return Response(payload)
            
        except Exception as e:
            print(f'Error driver cancelling tour booking: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='customer/(?P<customer_id>[^/.]+)')
    def get_customer_bookings(self, request, customer_id=None):
        """Get all tour bookings for a specific customer"""
        try:
            # Get query parameters for filtering
            if hasattr(request, 'query_params'):
                status_filter = request.query_params.get('status')
                date_from = request.query_params.get('date_from')
                date_to = request.query_params.get('date_to')
                limit = request.query_params.get('limit')
            else:
                status_filter = request.GET.get('status')
                date_from = request.GET.get('date_from')
                date_to = request.GET.get('date_to')
                limit = request.GET.get('limit')
            
            # Build query for bookings
            query = supabase.table('bookings').select('*').eq('customer_id', customer_id).order('created_at', desc=True)
            
            # Apply filters
            if status_filter:
                query = query.eq('status', status_filter)
            if date_from:
                query = query.gte('booking_date', date_from)
            if date_to:
                query = query.lte('booking_date', date_to)
            if limit:
                try:
                    limit = int(limit)
                    query = query.limit(limit)
                except ValueError:
                    pass
            
            response = query.execute()
            bookings = response.data if hasattr(response, 'data') else []
            
            # Process bookings for better display
            processed_bookings = []
            total_spent = 0
            status_counts = {}
            
            for booking in bookings:
                # Format dates
                if booking.get('booking_date'):
                    try:
                        booking_date = datetime.fromisoformat(booking['booking_date'].split('T')[0])
                        booking['booking_date_formatted'] = booking_date.strftime('%B %d, %Y')
                    except:
                        booking['booking_date_formatted'] = booking['booking_date']
                
                # Format total amount
                if booking.get('total_amount'):
                    booking['total_amount_formatted'] = f"₱{booking['total_amount']:,.2f}"
                    if booking.get('status') == 'completed':
                        total_spent += booking['total_amount']
                
                # Count statuses
                booking_status = booking.get('status', 'unknown')
                status_counts[booking_status] = status_counts.get(booking_status, 0) + 1
                
                # Add summary
                booking['summary'] = f"{booking.get('package_name', 'Tour Package')} - {booking.get('number_of_pax', 0)} pax"
                
                # Add cancellation info for active bookings
                if booking.get('status') not in ['completed', 'cancelled']:
                    try:
                        booking_date_str = str(booking.get('booking_date', '')).split('T')[0]
                        booking_date_obj = datetime.fromisoformat(booking_date_str).date()
                        days_until_booking = (booking_date_obj - date.today()).days
                        
                        booking['can_cancel'] = True
                        booking['days_until_booking'] = days_until_booking
                        
                        # No cancellation fee for tourists
                        booking['cancellation_fee_percentage'] = 0
                    except Exception:
                        booking['can_cancel'] = True
                        booking['cancellation_fee_percentage'] = 0
                else:
                    booking['can_cancel'] = False
                    booking['cancellation_fee_percentage'] = None
                
                processed_bookings.append(booking)
            
            # Get customer info
            customer_name, customer_email = self._get_customer_info(customer_id)
            
            return Response({
                'success': True,
                'data': {
                    'bookings': processed_bookings,
                    'customer_info': {
                        'id': customer_id,
                        'name': customer_name,
                        'email': customer_email
                    },
                    'statistics': {
                        'total_bookings': len(processed_bookings),
                        'status_counts': status_counts,
                        'total_spent': total_spent,
                        'total_spent_formatted': f"₱{total_spent:,.2f}"
                    }
                },
                'count': len(processed_bookings)
            })
            
        except Exception as e:
            print(f'Error fetching customer tour bookings: {str(e)}')
            from rest_framework import status as http_status
            return Response({
                'success': False,
                'error': 'Failed to fetch customer tour bookings',
                'data': []
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='driver/(?P<driver_id>[^/.]+)')
    def get_driver_bookings(self, request, driver_id=None):
        """Get all tour bookings assigned to a specific driver"""
        try:
            # Validate driver_id
            if not driver_id:
                return Response({
                    'success': False,
                    'error': 'Driver ID is required',
                    'data': []
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get query parameters for filtering
            try:
                if hasattr(request, 'query_params'):
                    status_filter = request.query_params.get('status')
                    date_from = request.query_params.get('date_from')
                    date_to = request.query_params.get('date_to')
                else:
                    status_filter = request.GET.get('status')
                    date_from = request.GET.get('date_from')
                    date_to = request.GET.get('date_to')
            except Exception as param_error:
                print(f'Error parsing query parameters: {param_error}')
                status_filter = None
                date_from = None
                date_to = None
            
            # Ensure connection is healthy before proceeding
            if not ensure_healthy_connection():
                logger.warning(f"Connection unhealthy for driver bookings query: {driver_id}")
                return Response({
                    'success': False,
                    'error': 'Service temporarily unavailable. Please try again.',
                    'data': []
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            # Build query for bookings with enhanced error handling
            def query_func():
                query = supabase.table('bookings').select('*').eq('driver_id', driver_id)
                
                # Apply filters safely
                if status_filter:
                    query = query.eq('status', status_filter)
                if date_from:
                    query = query.gte('booking_date', date_from)
                if date_to:
                    query = query.lte('booking_date', date_to)
                
                return query.order('created_at', desc=True).execute()
            
            try:
                response = execute_with_retry(query_func, max_retries=5)  # More retries for driver queries
                bookings = response.data if hasattr(response, 'data') and response.data else []
            except Exception as db_error:
                print(f'Database query error for driver {driver_id}: {db_error}')
                print(f'Error type: {type(db_error).__name__}')
                print(f'Full traceback: {traceback.format_exc()}')
                return Response({
                    'success': False,
                    'error': 'Database connection error',
                    'data': []
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Process bookings for better display with safe error handling
            processed_bookings = []
            total_earnings = 0
            status_counts = {}
            
            # Handle case where bookings might be None or have error
            if not bookings or (hasattr(bookings, 'error') and bookings.error):
                bookings = []
            
            for booking in bookings:
                try:
                    # Format dates safely
                    if booking.get('booking_date'):
                        try:
                            booking_date = datetime.fromisoformat(str(booking['booking_date']).split('T')[0])
                            booking['booking_date_formatted'] = booking_date.strftime('%B %d, %Y')
                        except Exception:
                            booking['booking_date_formatted'] = str(booking.get('booking_date', 'N/A'))
                    
                    # Format total amount and calculate earnings safely
                    if booking.get('total_amount'):
                        try:
                            amount = float(booking['total_amount'])
                            booking['total_amount_formatted'] = f"₱{amount:,.2f}"
                            if booking.get('status') == 'completed':
                                driver_earning = float(_quantize_money(Decimal(str(amount)) * DRIVER_PERCENTAGE))
                                total_earnings += driver_earning
                                booking['driver_earnings'] = driver_earning
                                booking['driver_earnings_formatted'] = f"₱{driver_earning:,.2f}"
                        except Exception as calc_error:
                            print(f'Error calculating earnings for booking {booking.get("id")}: {calc_error}')
                            booking['total_amount_formatted'] = '₱0.00'
                    
                    # Count statuses safely
                    booking_status = str(booking.get('status', 'unknown'))
                    status_counts[booking_status] = status_counts.get(booking_status, 0) + 1
                    
                    # Add summary safely
                    package_name = str(booking.get('package_name', 'Tour Package'))
                    pax_count = booking.get('number_of_pax', 0)
                    booking['summary'] = f"{package_name} - {pax_count} pax"
                    
                    processed_bookings.append(booking)
                except Exception as process_error:
                    print(f'Error processing booking {booking.get("id", "unknown")}: {process_error}')
                    # Skip this booking but continue with others
                    continue
            
            # Get driver name safely
            driver_name = 'Unknown'
            try:
                if processed_bookings:
                    driver_name = str(processed_bookings[0].get('driver_name', 'Unknown'))
                else:
                    # Try to get driver name from users table
                    user_response = supabase.table('users').select('name').eq('id', driver_id).single().execute()
                    if user_response.data:
                        driver_name = user_response.data.get('name', 'Unknown')
            except Exception as name_error:
                print(f'Error getting driver name: {name_error}')
                driver_name = 'Unknown'
            
            return Response({
                'success': True,
                'data': {
                    'bookings': processed_bookings,
                    'driver_info': {
                        'id': driver_id,
                        'name': driver_name
                    },
                    'statistics': {
                        'total_bookings': len(processed_bookings),
                        'status_counts': status_counts,
                        'total_earnings': total_earnings,
                        'total_earnings_formatted': f"₱{total_earnings:,.2f}",
                        'driver_percentage': float(get_driver_percentage() * 100)
                    }
                },
                'count': len(processed_bookings)
            })
            
        except Exception as e:
            print(f'Unexpected error in get_driver_bookings for driver {driver_id}: {str(e)}')
            print(f'Error traceback: {traceback.format_exc()}')
            return Response({
                'success': False,
                'error': 'Failed to fetch driver tour bookings',
                'data': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='auto-cancel-unpaid')
    def auto_cancel_unpaid_bookings(self, request):
        """Endpoint to trigger automatic cancellation of unpaid bookings (can be called by cron job)"""
        try:
            result = self._check_and_cancel_unpaid_bookings()
            return Response(result)
        except Exception as e:
            print(f'Error in auto-cancel endpoint: {str(e)}')
            return Response({
                'success': False,
                'error': 'Failed to process auto-cancellation',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _check_and_timeout_pending_bookings(self):
        """Check for bookings that have been pending for more than 6 hours without driver acceptance"""
        try:
            # Calculate 6 hours ago
            six_hours_ago = timezone.now() - timedelta(hours=6)
            
            # Find bookings that are still pending and created more than 6 hours ago
            query = supabase.table('bookings').select('*').eq('status', 'pending')
            response = query.execute()
            
            bookings_to_timeout = []
            if hasattr(response, 'data') and response.data:
                for booking in response.data:
                    created_at = booking.get('created_at')
                    if created_at:
                        try:
                            created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            if created_time.replace(tzinfo=timezone.utc) < six_hours_ago:
                                bookings_to_timeout.append(booking)
                        except Exception as e:
                            print(f"Error parsing created_at for booking {booking.get('id')}: {e}")
            
            timed_out_count = 0
            for booking in bookings_to_timeout:
                try:
                    # Update booking status to suggest rebooking
                    # Get old booking data for audit
                    old_booking_data = dict(booking)
                    
                    update_data = {
                        'status': 'no_driver_available',
                        'timeout_reason': 'No driver accepted within 6 hours',
                        'timed_out_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    
                    result = supabase.table('bookings').update(update_data).eq('id', booking['id']).execute()
                    
                    # Log audit trail for booking timeout
                    if hasattr(result, 'data') and result.data:
                        try:
                            _log_audit(
                                user_id=None,
                                username='System',
                                role='system',
                                action='TIMEOUT_BOOKING',
                                entity_name='bookings',
                                entity_id=booking['id'],
                                old_data=old_booking_data,
                                new_data=result.data[0],
                                request=None
                            )
                        except Exception as audit_error:
                            print(f"Audit log error: {audit_error}")
                    
                    # Notify customer with rebooking options
                    try:
                        customer_id = booking.get('customer_id')
                        if customer_id:
                            package_name = booking.get('package_name', 'tour package')
                            booking_date = booking.get('booking_date', 'your selected date')
                            
                            notification_data = {
                                'title': 'No Driver Available - Rebook Suggested 📅',
                                'message': f'Unfortunately, no driver accepted your {package_name} booking for {booking_date}. We suggest rebooking for another date when more drivers are available.',
                                'type': 'booking_timeout',
                                'created_at': datetime.now().isoformat()
                            }
                            
                            notification = supabase.table('notifications').insert(notification_data).execute()
                            
                            if notification.data:
                                notification_id = notification.data[0]['id']
                                supabase.table('notification_recipients').insert({
                                    'notification_id': notification_id,
                                    'user_id': customer_id,
                                    'role': 'tourist',
                                    'delivery_status': 'sent'
                                }).execute()
                    except Exception as e:
                        print(f"Failed to notify customer of timeout: {e}")
                    
                    timed_out_count += 1
                    print(f"Timed out booking {booking['id']} - no driver acceptance within 6 hours")
                    
                except Exception as e:
                    print(f"Error timing out booking {booking.get('id')}: {e}")
            
            return {
                'success': True,
                'message': f'Processed {timed_out_count} timed out bookings',
                'timed_out_count': timed_out_count
            }
            
        except Exception as e:
            print(f"Error in timeout check: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    @action(detail=False, methods=['post'], url_path='check-timeouts')
    def check_booking_timeouts(self, request):
        """Endpoint to check for booking timeouts (can be called by cron job)"""
        try:
            result = self._check_and_timeout_pending_bookings()
            return Response(result)
        except Exception as e:
            print(f'Error in timeout check endpoint: {str(e)}')
            return Response({
                'success': False,
                'error': 'Failed to process timeout check',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='rebook/(?P<booking_id>[^/.]+)')
    def rebook_timeout_booking(self, request, booking_id=None):
        """Rebook a timed out booking with new date"""
        try:
            data = request.data if hasattr(request, 'data') else request.POST.dict()
            
            new_date = data.get('new_date')
            new_time = data.get('new_time')
            customer_id = data.get('customer_id')
            
            if not all([new_date, customer_id]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: new_date, customer_id'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get original booking
            booking_response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            if not (hasattr(booking_response, 'data') and booking_response.data):
                return Response({
                    'success': False,
                    'error': 'Booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            original_booking = booking_response.data[0]
            
            # Verify customer owns the booking
            if original_booking.get('customer_id') != customer_id:
                return Response({
                    'success': False,
                    'error': 'Unauthorized'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check if booking can be rebooked
            if original_booking.get('status') != 'no_driver_available':
                return Response({
                    'success': False,
                    'error': 'Only timed out bookings can be rebooked'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get old booking data for audit
            old_booking_data = dict(original_booking)
            
            # Update booking with new date and reset to pending
            update_data = {
                'booking_date': new_date,
                'pickup_time': new_time or original_booking.get('pickup_time', '09:00:00'),
                'status': 'pending',
                'rebooked_at': datetime.now().isoformat(),
                'rebook_count': (original_booking.get('rebook_count', 0) + 1),
                'updated_at': datetime.now().isoformat(),
                # Clear timeout fields
                'timeout_reason': None,
                'timed_out_at': None
            }
            
            result = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for rebooking
            if hasattr(result, 'data') and result.data:
                try:
                    username, role = self._get_user_info(customer_id)
                    _log_audit(
                        user_id=customer_id,
                        username=username,
                        role=role,
                        action='REBOOK_TIMEOUT',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=result.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")
            
            if hasattr(result, 'data') and result.data:
                # Notify drivers of the rebooked booking
                self._notify_drivers_of_new_booking(result.data[0])
                
                return Response({
                    'success': True,
                    'data': result.data[0],
                    'message': 'Booking successfully rebooked. Drivers will be notified of your new booking.'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to rebook'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            print(f'Error rebooking: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='cancel-timeout/(?P<booking_id>[^/.]+)')
    def cancel_timeout_booking(self, request, booking_id=None):
        """Cancel a timed out booking instead of rebooking"""
        try:
            data = request.data if hasattr(request, 'data') else request.POST.dict()
            
            customer_id = data.get('customer_id')
            reason = data.get('reason', 'No driver available - customer cancelled')
            
            if not customer_id:
                return Response({
                    'success': False,
                    'error': 'Missing required field: customer_id'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get booking
            booking_response = supabase.table('bookings').select('*').eq('id', booking_id).execute()
            if not (hasattr(booking_response, 'data') and booking_response.data):
                return Response({
                    'success': False,
                    'error': 'Booking not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            booking = booking_response.data[0]
            
            # Verify customer owns the booking
            if booking.get('customer_id') != customer_id:
                return Response({
                    'success': False,
                    'error': 'Unauthorized'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Check if booking can be cancelled
            if booking.get('status') not in ['no_driver_available', 'pending']:
                return Response({
                    'success': False,
                    'error': 'Booking cannot be cancelled'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get old booking data for audit
            old_booking_data = dict(booking)
            
            # Cancel the booking
            update_data = {
                'status': 'cancelled',
                'cancel_reason': reason,
                'cancelled_by': 'customer',
                'cancelled_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            result = supabase.table('bookings').update(update_data).eq('id', booking_id).execute()
            
            # Log audit trail for timeout cancellation
            if hasattr(result, 'data') and result.data:
                try:
                    username, role = self._get_user_info(customer_id)
                    _log_audit(
                        user_id=customer_id,
                        username=username,
                        role=role,
                        action='CANCEL_TIMEOUT_BOOKING',
                        entity_name='bookings',
                        entity_id=booking_id,
                        old_data=old_booking_data,
                        new_data=result.data[0],
                        request=request
                    )
                except Exception as audit_error:
                    print(f"Audit log error: {audit_error}")
            
            if hasattr(result, 'data') and result.data:
                # Create refund if needed
                self._reverse_earnings_and_create_refund(booking, reason=reason, cancelled_by='customer')
                
                return Response({
                    'success': True,
                    'data': result.data[0],
                    'message': 'Booking cancelled successfully. Full refund will be processed if payment was made.'
                })
            else:
                return Response({
                    'success': False,
                    'error': 'Failed to cancel booking'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            print(f'Error cancelling timeout booking: {str(e)}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



    @action(detail=False, methods=['get'], url_path='stats')
    def get_booking_stats(self, request):
        """Get tour booking statistics"""
        try:
            # Get total bookings
            total_response = supabase.table('bookings').select('id').execute()
            total_bookings = len(total_response.data) if hasattr(total_response, 'data') and total_response.data else 0
            
            # Get bookings by status
            status_response = supabase.table('bookings').select('status').execute()
            status_counts = {}
            if hasattr(status_response, 'data'):
                for booking in status_response.data:
                    booking_status = booking.get('status', 'unknown')
                    status_counts[booking_status] = status_counts.get(booking_status, 0) + 1
            
            # Get today's bookings
            today = date.today().isoformat()
            today_response = supabase.table('bookings').select('id').eq('booking_date', today).execute()
            today_bookings = len(today_response.data) if hasattr(today_response, 'data') and today_response.data else 0
            
            # Get this month's bookings
            first_day = date.today().replace(day=1).isoformat()
            month_response = supabase.table('bookings').select('id').gte('booking_date', first_day).execute()
            month_bookings = len(month_response.data) if hasattr(month_response, 'data') and month_response.data else 0
            
            # Get cancellation stats
            cancelled_response = supabase.table('bookings').select('cancelled_by').eq('status', 'cancelled').execute()
            cancellation_stats = {'customer': 0, 'driver': 0, 'admin': 0}
            if hasattr(cancelled_response, 'data'):
                for booking in cancelled_response.data:
                    cancelled_by = booking.get('cancelled_by', 'unknown')
                    if cancelled_by in cancellation_stats:
                        cancellation_stats[cancelled_by] += 1
            
            stats = {
                'total_bookings': total_bookings,
                'status_counts': status_counts,
                'today_bookings': today_bookings,
                'month_bookings': month_bookings,
                'cancellation_stats': cancellation_stats,
                'booking_type': 'tour_package'
            }
            
            return Response({
                'success': True,
                'data': stats
            })
            
        except Exception as e:
            print(f'Error fetching tour booking stats: {str(e)}')
            from rest_framework import status as http_status
            return Response({
                'success': False,
                'error': 'Failed to fetch tour booking statistics',
                'data': {}
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
