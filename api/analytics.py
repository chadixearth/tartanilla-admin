# api/analytics.py

from tartanilla_admin.supabase import supabase, execute_with_retry
from datetime import datetime, timedelta, timezone, date
from collections import defaultdict, OrderedDict
from rest_framework.permissions import AllowAny
from rest_framework import viewsets

PAGE_SIZE = 1000


class AnalyticsViewSet(viewsets.ViewSet):
    """
    Analytics helpers.
    """
    permission_classes = [AllowAny]

    # -------------------- Helpers --------------------
    @staticmethod
    def _parse_date_range(start_str, end_str):
        try:
            start = datetime.fromisoformat(start_str) if start_str else None
        except Exception:
            start = None
        try:
            end = datetime.fromisoformat(end_str) if end_str else None
        except Exception:
            end = None
        return start, end

    @staticmethod
    def _completed_bookings_filter(q, start=None, end=None):
        q = q.eq('status', 'completed')
        if start:
            q = q.gte('booking_date', start.date().isoformat() if isinstance(start, datetime) else start.isoformat())
        if end:
            q = q.lte('booking_date', end.date().isoformat() if isinstance(end, datetime) else end.isoformat())
        return q

    @staticmethod
    def _monday_of(d: date) -> date:
        """Return Monday of the week for given date (Mon=0)."""
        return d - timedelta(days=d.weekday())

    # -------------------- KPIs --------------------
    @staticmethod
    def get_total_revenue(start_date=None, end_date=None):
        from datetime import date, datetime, timedelta, timezone, time
        from collections import defaultdict

        def _first_of_month(d: date): return date(d.year, d.month, 1)
        def _last_of_month(d: date):
            if d.month == 12: return date(d.year, 12, 31)
            return date(d.year, d.month + 1, 1) - timedelta(days=1)

        today = datetime.now(timezone.utc).date()

        # Resolve window (defaults to current month)
        start_d = datetime.fromisoformat(start_date).date() if start_date else None
        end_d   = datetime.fromisoformat(end_date).date()   if end_date   else None
        if not start_d and not end_d:
            start_d, end_d = _first_of_month(today), _last_of_month(today)
        elif start_d and not end_d:
            end_d = _last_of_month(start_d)
        elif end_d and not start_d:
            start_d = _first_of_month(end_d)
        if not start_d or not end_d:
            return 0.0

        # Inclusive start, exclusive end (avoid lte-midnight edge cases)
        start_ts      = datetime.combine(start_d, time.min, tzinfo=timezone.utc)
        end_exclusive = datetime.combine(end_d + timedelta(days=1), time.min, tzinfo=timezone.utc)

        # Pull rows in window
        rows, offset = [], 0
        STATUSES = ['pending', 'finalized', 'reversed']
        while True:
            def q():
                return (
                    supabase.table('earnings')
                    .select('id, booking_id, amount, status, earning_date')
                    .in_('status', STATUSES)
                    .gte('earning_date', start_ts.isoformat())
                    .lt('earning_date', end_exclusive.isoformat())
                    .range(offset, offset + PAGE_SIZE - 1)
                    .execute()
                )
            resp = execute_with_retry(q)
            chunk = resp.data or []
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        # ✅ Keep ONLY rows that came from bookings (booking_id present)
        rows = [r for r in rows if r.get('booking_id')]

        # Group strictly by booking_id and take the latest record per booking
        buckets = defaultdict(list)
        for r in rows:
            buckets[r['booking_id']].append(r)

        total = 0.0
        for _, items in buckets.items():
            latest = max(items, key=lambda x: x.get('earning_date') or '')
            st = (latest.get('status') or '').strip().lower()
            try:
                amt = float(latest.get('amount') or 0)
            except (TypeError, ValueError):
                amt = 0.0

            # Latest status wins:
            # - pending/finalized => add
            # - reversed          => contribute 0
            if st in ('pending', 'finalized'):
                total += amt

        return round(total, 2)




    @staticmethod
    def get_completed_bookings_count(start_date=None, end_date=None):
        start, end = AnalyticsViewSet._parse_date_range(start_date, end_date)

        def query():
            q = supabase.table('bookings').select('id', count='exact')
            q = AnalyticsViewSet._completed_bookings_filter(q, start, end)
            return q.execute()

        resp = execute_with_retry(query)
        return getattr(resp, 'count', None) or len(resp.data or [])

    @staticmethod
    def get_weekly_top_drivers(limit=5):
        """
        Top drivers by total share_amount from payout_earnings.

        Notes:
        - Uses payout_earnings (not bookings/earnings).
        - Groups by driver_id and prefers driver_name (X-axis label).
        - If driver_name is missing/blank, falls back to 'Driver {id}'.
        - No date filter here because payout_earnings schema provided has no timestamp column.
          If your payouts table has created_at/released_at and you want a true "weekly" window,
          we can join via payout_id and filter on that timestamp.
        """
        PAGE = PAGE_SIZE
        offset = 0
        sums_by_driver = defaultdict(float)
        name_by_driver = {}

        while True:
            def q():
                # pull only what we need, paginate to be safe
                return (supabase.table('payout_earnings')
                        .select('driver_id, driver_name, share_amount, status')
                        .range(offset, offset + PAGE - 1)
                        .execute())
            resp = execute_with_retry(q)
            rows = resp.data or []
            if not rows:
                break

            for r in rows:
                did = r.get('driver_id')
                if not did:
                    continue
                try:
                    amt = float(r.get('share_amount') or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                sums_by_driver[did] += amt

                # prefer first non-empty driver_name for label
                dn = (r.get('driver_name') or '').strip()
                if dn and did not in name_by_driver:
                    name_by_driver[did] = dn

            if len(rows) < PAGE:
                break
            offset += PAGE

        # Build sorted top list
        ordered = sorted(sums_by_driver.items(), key=lambda kv: kv[1], reverse=True)
        top = ordered[:limit] if (limit and limit > 0) else ordered

        result = []
        for did, total in top:
            label = name_by_driver.get(did) or f'Driver {did}'
            result.append({
                'driver_id': did,
                'name': label,                 # <- frontend reads this for X-axis
                'amount': round(total, 2),     # <- y-axis value
            })
        return result

    @staticmethod
    def get_ratings_distribution():
        """
        Distribution of driver ratings from published driver reviews.
        Returns { labels: ['5★','4★','3★','2★','1★'], counts: [n5,n4,n3,n2,n1], groups: [...] }
        """
        try:
            def q():
                return (supabase.table('driver_reviews')
                        .select('rating, driver_id')
                        .execute())
            resp = execute_with_retry(q)
            rows = resp.data or []
            
            counts = [0, 0, 0, 0, 0]  # indexes 0..4 represent 5..1
            drivers_by_rating = {5: set(), 4: set(), 3: set(), 2: set(), 1: set()}
            
            for r in rows:
                try:
                    rating = int(r.get('rating') or 0)
                except (TypeError, ValueError):
                    rating = 0
                if 1 <= rating <= 5:
                    idx = 5 - rating
                    counts[idx] += 1
                    driver_id = r.get('driver_id')
                    if driver_id:
                        drivers_by_rating[rating].add(str(driver_id))
            
            # Get driver names
            all_driver_ids = list(set().union(*drivers_by_rating.values()))
            name_by_id = {}
            
            if all_driver_ids:
                def q_users():
                    return (supabase.table('users')
                            .select('id, name, email')
                            .in_('id', all_driver_ids)
                            .execute())
                try:
                    users_resp = execute_with_retry(q_users)
                    for u in (users_resp.data or []):
                        uid = str(u.get('id'))
                        label = (u.get('name') or u.get('email') or '').strip()
                        if label and uid:
                            name_by_id[uid] = label
                except Exception:
                    pass
            
            # Build groups for tooltip
            groups = []
            for rating in (5, 4, 3, 2, 1):
                driver_names = [name_by_id.get(did, f'Driver {did}') for did in sorted(drivers_by_rating[rating])]
                driver_names.sort(key=lambda s: s.lower())
                groups.append({
                    'rating': rating,
                    'label': f'{rating}★',
                    'count': counts[5 - rating],
                    'drivers': driver_names
                })
            
            return {'labels': ['5★', '4★', '3★', '2★', '1★'], 'counts': counts, 'groups': groups}
        except Exception as e:
            print(f"DEBUG: Error in get_ratings_distribution: {e}")
            return {'labels': ['5★', '4★', '3★', '2★', '1★'], 'counts': [0, 0, 0, 0, 0], 'groups': []}

    @staticmethod
    def _driver_ratings_map():
        """
        Build a map of driver_id -> {'avg_rating': float, 'rating_count': int}
        from driver reviews.
        """
        try:
            def q():
                return (supabase.table('driver_reviews')
                        .select('driver_id, rating')
                        .execute())
            resp = execute_with_retry(q)
            rows = resp.data or []
            
            sums = defaultdict(float)
            counts = defaultdict(int)
            for r in rows:
                did = r.get('driver_id')
                if not did:
                    continue
                try:
                    rating = float(r.get('rating') or 0)
                except (TypeError, ValueError):
                    rating = 0.0
                if rating <= 0:
                    continue
                sums[did] += rating
                counts[did] += 1
            result = {}
            for did, cnt in counts.items():
                avg = round(sums.get(did, 0.0) / cnt, 2) if cnt else 0.0
                result[did] = {'avg_rating': avg, 'rating_count': cnt}
            return result
        except Exception:
            return {}

    @staticmethod
    def get_driver_performance(limit=None):
        """
        Build per-driver metrics from the bookings table.

        Metrics:
        - completed_rides: COUNT(*) where status='completed'
        - earnings: SUM(total_amount) where status='completed'
        - acceptance_pct: accepted / (accepted + rejected)
                accepted := driver_id is set AND driver_assigned_at IS NOT NULL
                rejected := status='rejected' AND driver_id is set
        - cancellations:
                driver_cancel_pct   := cancelled_by='driver'   / accepted
                customer_cancel_pct := cancelled_by='customer' / accepted
        Notes:
        - Percentages are 0 when denominator is 0.
        - Results are sorted by earnings desc, then completed_rides desc.
        """
        from math import isfinite

        # Pull all relevant booking rows (paginated)
        offset = 0
        PAGE = PAGE_SIZE
        rows = []
        while True:
            def q():
                return (supabase.table('bookings')
                        .select('driver_id, driver_name, status, total_amount, driver_assigned_at, cancelled_by')
                        .range(offset, offset + PAGE - 1)
                        .execute())
            resp = execute_with_retry(q)
            chunk = resp.data or []
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < PAGE:
                break
            offset += PAGE

        # Aggregate
        by_driver = defaultdict(lambda: {
            'accepted': 0,
            'rejected': 0,
            'completed_rides': 0,
            'earnings': 0.0,
            'driver_cancel': 0,
            'customer_cancel': 0,
            'label': None,
        })

        for r in rows:
            did = r.get('driver_id')
            if not did:
                continue

            rec = by_driver[did]
            # label (prefer bookings.driver_name fallback to "Driver {id}")
            nm = (r.get('driver_name') or '').strip()
            if nm:
                rec['label'] = nm

            status = (r.get('status') or '').strip().lower()
            try:
                amt = float(r.get('total_amount') or 0)
            except (TypeError, ValueError):
                amt = 0.0

            # Completed rides & earnings
            if status == 'completed':
                rec['completed_rides'] += 1
                rec['earnings'] += amt

            # Accepted (driver tapped accept => driver_assigned_at present)
            if r.get('driver_assigned_at') is not None:
                rec['accepted'] += 1

            # Rejected
            if status == 'rejected':
                rec['rejected'] += 1

            # Cancellations by source
            if status == 'cancelled':
                cb = (r.get('cancelled_by') or '').strip().lower()
                if cb == 'driver':
                    rec['driver_cancel'] += 1
                elif cb == 'customer':
                    rec['customer_cancel'] += 1

        # Fetch missing names from users for nicer labels
        driver_ids = list(by_driver.keys())
        if driver_ids:
            def q_users():
                return (supabase.table('users')
                        .select('id,name,email')
                        .in_('id', driver_ids)
                        .execute())
            users_resp = execute_with_retry(q_users)
            for u in (users_resp.data or []):
                label = (u.get('name') or u.get('email') or '').strip()
                if label:
                    if by_driver[u['id']]['label'] in (None, ''):
                        by_driver[u['id']]['label'] = label

        # Build rows
        def pct(num, den):
            if not den:
                return 0.0
            try:
                v = (float(num) / float(den)) * 100.0
                return round(v, 2) if isfinite(v) else 0.0
            except Exception:
                return 0.0

        results = []
        for did, agg in by_driver.items():
            accepted = agg['accepted']
            rejected = agg['rejected']
            denom_acc = accepted + rejected
            
            acceptance_pct = pct(accepted, denom_acc)
            driver_cancel_pct = pct(agg['driver_cancel'], accepted)
            customer_cancel_pct = pct(agg['customer_cancel'], accepted)
            
            results.append({
                'driver_id': did,
                'driver_name': agg['label'] or f'Driver {did}',
                'completed_rides': int(agg['completed_rides']),
                'earnings': round(agg['earnings'], 2),
                'acceptance_pct': acceptance_pct,             # e.g., 83.33
                'driver_cancel_pct': driver_cancel_pct,       # e.g., 5.0
                'customer_cancel_pct': customer_cancel_pct,   # e.g., 10.0
            })

        # Merge in ratings per driver
        try:
            rating_map = AnalyticsViewSet._driver_ratings_map()
            if rating_map:
                for row in results:
                    stats = rating_map.get(row['driver_id'])
                    if stats:
                        row['avg_rating'] = stats.get('avg_rating', 0.0)
                        row['rating_count'] = stats.get('rating_count', 0)
                    else:
                        row['avg_rating'] = 0.0
                        row['rating_count'] = 0
            else:
                for row in results:
                    row['avg_rating'] = 0.0
                    row['rating_count'] = 0
        except Exception:
            for row in results:
                row['avg_rating'] = 0.0
                row['rating_count'] = 0
        
        # Sort & limit
        results.sort(key=lambda x: (x['earnings'], x['completed_rides']), reverse=True)
        return results[:limit] if (limit and limit > 0) else results



    # -------------------- Revenue by Package --------------------
    @staticmethod
    def get_revenue_by_package_monthly(months=6, top=10):
        """
        Monthly Top-N packages by revenue from completed bookings.
        Returns { months: [YYYY-MM...], datasets: [ { package_id, package_name, data: [...] } ] }
        """
        today = datetime.now(timezone.utc).date()
        end_month = date(today.year, today.month, 1)
        # go back N-1 months
        y, m = end_month.year, end_month.month - (months - 1)
        while m <= 0:
            m += 12
            y -= 1
        start_month = date(y, m, 1)

        # fetch bookings
        def q():
            return (supabase.table("bookings")
                    .select("package_id, package_name, total_amount, booking_date, status")
                    .eq("status", "completed")
                    .gte("booking_date", start_month.isoformat())
                    .lte("booking_date", today.isoformat())
                    .execute())
        resp = execute_with_retry(q)
        rows = resp.data or []

        # bucket by month + package
        sums = defaultdict(float)
        pkg_names = {}
        months_labels = []
        y, m = start_month.year, start_month.month
        while True:
            months_labels.append(f"{y:04d}-{m:02d}")
            if y == end_month.year and m == end_month.month:
                break
            m += 1
            if m == 13:
                m = 1
                y += 1

        all_pkg_ids = set()
        for r in rows:
            pid = r.get("package_id")
            if not pid:
                continue
            all_pkg_ids.add(pid)
            try:
                bdate = r.get("booking_date")
                if isinstance(bdate, str):
                    bdate = datetime.fromisoformat(bdate).date()
            except Exception:
                continue
            key = f"{bdate.year:04d}-{bdate.month:02d}"
            try:
                amt = float(r.get("total_amount") or 0)
            except:
                amt = 0
            sums[(pid, key)] += amt

        # Fetch ALL names from tourpackages table ONLY
        pkg_names = {}
        if all_pkg_ids:
            def q_packages():
                return (supabase.table('tourpackages')
                        .select('id,package_name')
                        .in_('id', list(all_pkg_ids))
                        .execute())
            pk_resp = execute_with_retry(q_packages)
            for p in (pk_resp.data or []):
                pid = p.get('id')
                label = (p.get('package_name') or '').strip()
                if pid:
                    pkg_names[pid] = label if label else f'Package {pid}'

        # order top packages by total revenue
        pkg_totals = defaultdict(float)
        for (pid, _), val in sums.items():
            pkg_totals[pid] += val
        top_ids = [pid for pid, _ in sorted(pkg_totals.items(), key=lambda x: x[1], reverse=True)[:top]]

        datasets = []
        for pid in top_ids:
            row = [round(sums.get((pid, m), 0.0), 2) for m in months_labels]
            datasets.append({
                "package_id": pid,
                "package_name": pkg_names.get(pid, f"(Unknown {pid})"),
                "data": row
            })

        return {"months": months_labels, "datasets": datasets}


    @staticmethod
    def get_revenue_by_package_weekly(weeks=8):
        """
        Weekly rollup (Mon-Sun window) of completed bookings' total_amount per package_id.

        Output shape:
        {
          'weeks': ['2025-07-07','2025-07-14', ...],   # ISO date of Monday for each week (ascending)
          'datasets': [
            { 'package_id': '...', 'package_name': '...', 'data': [w1_amt, w2_amt, ...] },
            ...
          ]
        }
        """
        # Build week range: last `weeks` complete weeks ending with current week
        today = datetime.now(timezone.utc).date()
        this_monday = AnalyticsViewSet._monday_of(today)
        first_monday = this_monday - timedelta(weeks=weeks-1)

        # Fetch completed bookings within range
        def q_bookings():
            return (supabase.table('bookings')
                    .select('package_id, package_name, total_amount, status, booking_date')
                    .eq('status', 'completed')
                    .gte('booking_date', first_monday.isoformat())
                    .lte('booking_date', (this_monday + timedelta(days=6)).isoformat())  # include full current week
                    .execute())

        resp = execute_with_retry(q_bookings)
        rows = resp.data or []

        # Prepare week buckets (Ordered for stable labels)
        week_starts = []
        ws = first_monday
        for _ in range(weeks):
            week_starts.append(ws)
            ws = ws + timedelta(weeks=1)

        # Aggregate: (week_start, package_id) -> sum
        sums = defaultdict(float)
        all_pkg_ids = set()
        for r in rows:
            pid = r.get('package_id')
            if not pid:
                continue
            all_pkg_ids.add(pid)
            # parse date
            try:
                bdate = r.get('booking_date')
                if isinstance(bdate, str):
                    bdate = datetime.fromisoformat(bdate).date()
                elif isinstance(bdate, datetime):
                    bdate = bdate.date()
                if not isinstance(bdate, date):
                    continue
            except Exception:
                continue

            wk = AnalyticsViewSet._monday_of(bdate)
            if wk < first_monday or wk > this_monday:
                continue

            try:
                amt = float(r.get('total_amount') or 0)
            except (TypeError, ValueError):
                amt = 0.0

            sums[(wk, pid)] += amt

        # Fetch ALL names from tourpackages table ONLY
        pkg_names = {}
        if all_pkg_ids:
            def q_packages():
                return (supabase.table('tourpackages')
                        .select('id,package_name')
                        .in_('id', list(all_pkg_ids))
                        .execute())
            pk_resp = execute_with_retry(q_packages)
            for p in (pk_resp.data or []):
                pid = p.get('id')
                label = (p.get('package_name') or '').strip()
                if pid:
                    pkg_names[pid] = label if label else f'Package {pid}'

        # Build datasets in package order by total sum desc
        pkg_totals = defaultdict(float)
        for (wk, pid), val in sums.items():
            pkg_totals[pid] += val
        ordered_pkg_ids = [pid for pid, _ in sorted(pkg_totals.items(), key=lambda x: x[1], reverse=True)]

        weeks_labels = [ws.isoformat() for ws in week_starts]
        datasets = []
        for pid in ordered_pkg_ids:
            row = []
            for wk in week_starts:
                row.append(round(sums.get((wk, pid), 0.0), 2))
            datasets.append({
                'package_id': pid,
                'package_name': pkg_names.get(pid, f'(Unknown package {pid})'),
                'data': row
            })

        return {'weeks': weeks_labels, 'datasets': datasets}
    
    @staticmethod
    def get_revenue_by_package_daily(days=7):
        """
        Daily rollup of completed bookings' total_amount per package_id
        for the last `days` (inclusive of today).
        Returns:
        {
        'days': ['YYYY-MM-DD', ...],  # ascending
        'datasets': [
            {'package_id':'...', 'package_name':'...', 'data':[d1_amt, d2_amt, ...]}
        ]
        }
        """
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days-1)

        def q_bookings():
            return (supabase.table('bookings')
                    .select('package_id, package_name, total_amount, status, booking_date')
                    .eq('status', 'completed')
                    .gte('booking_date', start.isoformat())
                    .lte('booking_date', today.isoformat())
                    .execute())

        resp = execute_with_retry(q_bookings)
        rows = resp.data or []

        # Prepare date buckets
        day_labels = []
        d = start
        while d <= today:
            day_labels.append(d.isoformat())
            d += timedelta(days=1)

        sums = defaultdict(float)   # (day_iso, package_id) -> amount
        all_pkg_ids = set()

        for r in rows:
            pid = r.get('package_id')
            if not pid: continue
            all_pkg_ids.add(pid)
            bdate = r.get('booking_date')
            try:
                if isinstance(bdate, str):
                    bdate = datetime.fromisoformat(bdate).date()
                elif isinstance(bdate, datetime):
                    bdate = bdate.date()
            except Exception:
                continue
            key = bdate.isoformat()
            try:
                amt = float(r.get('total_amount') or 0)
            except (TypeError, ValueError):
                amt = 0.0
            sums[(key, pid)] += amt

        # Fetch ALL names from tourpackages table ONLY
        pkg_names = {}
        if all_pkg_ids:
            def q_packages():
                return (supabase.table('tourpackages')
                        .select('id,package_name')
                        .in_('id', list(all_pkg_ids))
                        .execute())
            pk_resp = execute_with_retry(q_packages)
            for p in (pk_resp.data or []):
                pid = p.get('id')
                label = (p.get('package_name') or '').strip()
                if pid:
                    pkg_names[pid] = label if label else f'Package {pid}'

        # Order packages by total
        pkg_totals = defaultdict(float)
        for (day, pid), val in sums.items():
            pkg_totals[pid] += val
        ordered_pkg_ids = [pid for pid, _ in sorted(pkg_totals.items(), key=lambda x: x[1], reverse=True)]

        datasets = []
        for pid in ordered_pkg_ids:
            row = [round(sums.get((day, pid), 0.0), 2) for day in day_labels]
            datasets.append({
                'package_id': pid,
                'package_name': pkg_names.get(pid, f'(Unknown package {pid})'),
                'data': row
            })

        return {'days': day_labels, 'datasets': datasets}



    @staticmethod
    def get_revenue_trend_monthly(months=6, start_date=None, end_date=None):
        """
        Monthly revenue from COMPLETED bookings:
          SUM(bookings.total_amount) grouped by month over the last `months`.
        Returns:
          {
            "months": ["2025-03", "2025-04", ...],
            "amounts": [12345.67, 890.0, ...]
          }
        """
        # Build month window
        today = datetime.now(timezone.utc).date()
        # end bound (inclusive) = end of current month or end_date if given
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                end_d = end_dt.date()
            except Exception:
                end_d = today
        else:
            end_d = today
        end_month_start = date(end_d.year, end_d.month, 1)

        # start bound (inclusive) = first day of first month in window or start_date if given
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                start_d = start_dt.date()
            except Exception:
                start_d = end_month_start
        else:
            # months back (include current month)
            m = months - 1 if months and months > 0 else 5
            # find first month start m months ago
            y = end_month_start.year
            mo = end_month_start.month - m
            while mo <= 0:
                mo += 12
                y -= 1
            start_d = date(y, mo, 1)

        # Fetch all completed bookings between start and end (end of last month window)
        # We'll include entire end month (till last day)
        def _last_day_of_month(d: date) -> date:
            if d.month == 12:
                return date(d.year, 12, 31)
            nxt = date(d.year, d.month + 1, 1)
            return nxt - timedelta(days=1)

        end_inclusive = _last_day_of_month(end_month_start)

        total_by_month = defaultdict(float)
        offset = 0
        while True:
            def q():
                q = (supabase.table('bookings')
                     .select('total_amount, status, booking_date')
                     .eq('status', 'completed')
                     .gte('booking_date', start_d.isoformat())
                     .lte('booking_date', end_inclusive.isoformat())
                     .range(offset, offset + PAGE_SIZE - 1))
                return q.execute()

            resp = execute_with_retry(q)
            rows = resp.data or []
            if not rows:
                break

            for r in rows:
                bdate = r.get('booking_date')
                try:
                    if isinstance(bdate, str):
                        bdate = datetime.fromisoformat(bdate).date()
                    elif isinstance(bdate, datetime):
                        bdate = bdate.date()
                    if not isinstance(bdate, date):
                        continue
                except Exception:
                    continue

                key = f"{bdate.year:04d}-{bdate.month:02d}"  # YYYY-MM
                try:
                    amt = float(r.get('total_amount') or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                total_by_month[key] += amt

            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        # Build ordered labels from start_d to end_month_start
        labels = []
        y, mo = start_d.year, start_d.month
        end_y, end_mo = end_month_start.year, end_month_start.month
        while True:
            labels.append(f"{y:04d}-{mo:02d}")
            if y == end_y and mo == end_mo:
                break
            mo += 1
            if mo == 13:
                mo = 1
                y += 1

        amounts = [round(total_by_month.get(lbl, 0.0), 2) for lbl in labels]
        return {"months": labels, "amounts": amounts}
    
    @staticmethod
    def get_highest_rated_driver(min_reviews: int = 1):
        """
        Returns the highest-rated driver AGGREGATED BY NAME.
        We first compute avg/count per driver_id from published reviews,
        then resolve each driver's display name (users.name/email fallback),
        then aggregate sums/counts per driver_name and choose the best.

        Output (id kept for back-compat but may be None):
        { 'driver_id': <representative id or None>,
        'name': 'Jane D.',
        'avg_rating': 4.92,
        'rating_count': 37 }
        or None if no qualifying names.
        """
        # Per-driver stats from reviews
        id_stats = AnalyticsViewSet._driver_ratings_map() or {}
        if not id_stats:
            return None

        driver_ids = list(id_stats.keys())

        # Resolve display names
        name_by_id = {}
        if driver_ids:
            def q_users():
                return (supabase.table('users')
                        .select('id,name,first_name,last_name,email')
                        .in_('id', driver_ids)
                        .execute())
            try:
                users_resp = execute_with_retry(q_users)
                for u in (users_resp.data or []):
                    uid = u.get('id')
                    label = (u.get('name') or '').strip()
                    if not label:
                        first = (u.get('first_name') or '').strip()
                        last = (u.get('last_name') or '').strip()
                        if first and last:
                            label = f"{first} {last}"
                        elif first:
                            label = first
                        elif last:
                            label = last
                    if not label:
                        label = (u.get('email') or '').strip()
                    if label and uid:
                        name_by_id[uid] = label
            except Exception:
                # fallback: leave missing, we’ll generate a label
                pass

        # Aggregate stats by display name
        from collections import defaultdict
        sums_by_name = defaultdict(float)   # total stars sum
        cnt_by_name  = defaultdict(int)     # total review count
        rep_id_by_name = {}                 # keep one representative id (optional/back-compat)

        for did, stats in id_stats.items():
            # Ensure we always get a proper name, never just an ID
            raw_name = name_by_id.get(did, '').strip()
            if not raw_name:
                # Try to get name from users table if not found
                try:
                    def q_single_user():
                        return (supabase.table('users')
                                .select('id,name,email')
                                .eq('id', did)
                                .execute())
                    user_resp = execute_with_retry(q_single_user)
                    if user_resp.data:
                        user = user_resp.data[0]
                        raw_name = (user.get('name') or user.get('email') or '').strip()
                except Exception:
                    pass
            
            # Final fallback to a readable name format
            name = raw_name if raw_name else f"Driver {did}"
            
            avg = float(stats.get('avg_rating', 0.0) or 0.0)
            cnt = int(stats.get('rating_count', 0) or 0)
            if cnt <= 0:
                continue
            # Convert avg+count back to sum of stars, then aggregate by name
            sums_by_name[name] += avg * cnt
            cnt_by_name[name]  += cnt
            rep_id_by_name.setdefault(name, did)

        # Filter by min_reviews at the NAME level
        candidates = []
        for name, total_cnt in cnt_by_name.items():
            if total_cnt >= int(min_reviews):
                total_sum = sums_by_name[name]
                avg_name = total_sum / total_cnt if total_cnt else 0.0
                candidates.append((name, avg_name, total_cnt))

        if not candidates:
            return None

        # Sort: avg desc, then count desc, then name asc
        candidates.sort(key=lambda t: (t[1], t[2], t[0].lower()), reverse=True)
        best_name, best_avg, best_cnt = candidates[0]
        rep_id = rep_id_by_name.get(best_name)  # may be None

        result = {
            'driver_id': rep_id,  # kept for compatibility; not used by your UI
            'name': best_name,
            'avg_rating': round(float(best_avg or 0.0), 2),
            'rating_count': int(best_cnt or 0),
        }
        print(f"DEBUG: get_highest_rated_driver returning: {result}")
        return result
    

    # @staticmethod
    # def get_package_ratings_pie(top: int = 12, only_published: bool = True):
    #     """
    #     Returns package review counts with proper names.
    #     {
    #     labels:   [<package_name>...],
    #     counts:   [<review_count>...],
    #     packages: [{id, name, count}]
    #     }
    #     """
    #     from collections import defaultdict

    #     # 1) Gather reviews (prefer package_reviews, fallback to booking_reviews)
    #     source_rows = []
    #     for table in ('package_reviews', 'booking_reviews'):
    #         try:
    #             offset = 0
    #             while True:
    #                 def q():
    #                     sel = 'package_id, rating, is_published'
    #                     qb = supabase.table(table).select(sel).range(offset, offset + PAGE_SIZE - 1)
    #                     if only_published:
    #                         qb = qb.eq('is_published', True)
    #                     return qb.execute()
    #                 resp = execute_with_retry(q)
    #                 chunk = resp.data or []
    #                 if not chunk:
    #                     break
    #                 source_rows.extend(chunk)
    #                 if len(chunk) < PAGE_SIZE:
    #                     break
    #                 offset += PAGE_SIZE
    #             if source_rows:
    #                 break
    #         except Exception:
    #             continue

    #     if not source_rows:
    #         return {'labels': [], 'counts': [], 'packages': []}

    #     # 2) Count by package_id
    #     counts_by_pkg = defaultdict(int)
    #     for r in source_rows:
    #         pid = r.get('package_id')
    #         if pid:
    #             counts_by_pkg[str(pid)] += 1   # normalize to str keys

    #     if not counts_by_pkg:
    #         return {'labels': [], 'counts': [], 'packages': []}

    #     # 3) Order by count desc and trim to TOP N
    #     ordered = sorted(counts_by_pkg.items(), key=lambda kv: kv[1], reverse=True)
    #     if top and top > 0:
    #         ordered = ordered[:top]
    #     top_pkg_ids = [pid for pid, _ in ordered]

    #     # 4) Resolve names
    #     name_by_id = {}

    #     # 4a) Try tourpackages first
    #     try:
    #         pk_resp = execute_with_retry(lambda:
    #             supabase.table('tourpackages')
    #                     .select('id, package_name, name, title')
    #                     .in_('id', top_pkg_ids)
    #                     .execute()
    #         )
    #         for p in (pk_resp.data or []):
    #             pid = str(p.get('id'))
    #             label = (p.get('package_name') or p.get('package_name') or p.get('title') or '').strip()
    #             if pid and label:
    #                 name_by_id[pid] = label
    #     except Exception:
    #         pass

    #     # 4b) Fallback: pull any recent booking rows and use bookings.package_name
    #     missing = [pid for pid in top_pkg_ids if pid not in name_by_id]
    #     if missing:
    #         try:
    #             bk_resp = execute_with_retry(lambda:
    #                 supabase.table('bookings')
    #                         .select('package_id, package_name')
    #                         .in_('package_id', missing)
    #                         .execute()
    #             )
    #             for b in (bk_resp.data or []):
    #                 pid = str(b.get('package_id'))
    #                 label = (b.get('package_name') or '').strip()
    #                 if pid and label and pid not in name_by_id:
    #                     name_by_id[pid] = label
    #         except Exception:
    #             pass

    #     # 5) Build final payload with NAMES (fallback only if truly unknown)
    #     packages, labels, counts = [], [], []
    #     for pid, cnt in ordered:
    #         label = name_by_id.get(pid) or f'Package {pid}'
    #         packages.append({'id': pid, 'name': label, 'count': int(cnt)})
    #         labels.append(label)
    #         counts.append(int(cnt))

    #     return {'labels': labels, 'counts': counts, 'packages': packages}

    @staticmethod
    def get_package_ratings_pie(top: int = 12, only_published: bool = True):
        """
        Pie grouped by star rating. Legend shows "5★…1★".
        Hover tooltips can list package names via `groups[*].packages`.

        Returns:
        {
        "labels": ["5★","4★","3★","2★","1★"],
        "counts": [n5, n4, n3, n2, n1],
        "groups": [
            {"rating": 5, "label": "5★", "count": n5, "packages": ["Tour A","Tour B", ...]},
            ... for 4..1 ...
        ]
        }
        """
        from collections import defaultdict

        # ---------- 1) Gather reviews (prefer package_reviews, fallback to booking_reviews)
        source_rows = []
        for table in ('package_reviews', 'booking_reviews'):
            try:
                print(f"DEBUG: Trying table {table}")
                offset = 0
                while True:
                    def q():
                        sel = 'package_id, rating, is_published'
                        qb = supabase.table(table).select(sel).range(offset, offset + PAGE_SIZE - 1)
                        if only_published:
                            qb = qb.eq('is_published', True)
                        return qb.execute()
                    resp = execute_with_retry(q)
                    chunk = resp.data or []
                    print(f"DEBUG: Table {table}, offset {offset}, got {len(chunk)} rows")
                    if not chunk:
                        break
                    source_rows.extend(chunk)
                    if len(chunk) < PAGE_SIZE:
                        break
                    offset += PAGE_SIZE
                if source_rows:
                    print(f"DEBUG: Found {len(source_rows)} total rows in {table}")
                    break
            except Exception as e:
                print(f"DEBUG: Error with table {table}: {e}")
                continue

        print(f"DEBUG: Final source_rows count: {len(source_rows)}")
        
        # If no published reviews found, try without is_published filter
        if not source_rows and only_published:
            print("DEBUG: No published reviews found, trying without is_published filter")
            for table in ('package_reviews', 'booking_reviews'):
                try:
                    print(f"DEBUG: Trying table {table} without is_published filter")
                    offset = 0
                    while True:
                        def q():
                            sel = 'package_id, rating'
                            qb = supabase.table(table).select(sel).range(offset, offset + PAGE_SIZE - 1)
                            return qb.execute()
                        resp = execute_with_retry(q)
                        chunk = resp.data or []
                        print(f"DEBUG: Table {table}, offset {offset}, got {len(chunk)} rows (no filter)")
                        if not chunk:
                            break
                        source_rows.extend(chunk)
                        if len(chunk) < PAGE_SIZE:
                            break
                        offset += PAGE_SIZE
                    if source_rows:
                        print(f"DEBUG: Found {len(source_rows)} total rows in {table} (no filter)")
                        break
                except Exception as e:
                    print(f"DEBUG: Error with table {table} (no filter): {e}")
                    continue
        
        if not source_rows:
            return {"labels": [], "counts": [], "groups": []}

        # ---------- 2) Count by rating & collect package IDs per rating
        counts_by_rating = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
        ids_by_rating = {5: set(), 4: set(), 3: set(), 2: set(), 1: set()}

        for r in source_rows:
            try:
                rating = int(r.get('rating') or 0)
            except (TypeError, ValueError):
                rating = 0
            if rating not in counts_by_rating:
                continue
            pid = r.get('package_id')
            if pid:
                pid = str(pid)
                ids_by_rating[rating].add(pid)
            counts_by_rating[rating] += 1

        # If everything is zero, just return empties
        if sum(counts_by_rating.values()) == 0:
            return {"labels": [], "counts": [], "groups": []}

        # ---------- 3) Resolve package names for all involved package_ids
        all_pkg_ids = sorted(set().union(*ids_by_rating.values()))
        name_by_id = {}

        # 3a) tourpackages
        try:
            if all_pkg_ids:
                pk_resp = execute_with_retry(lambda:
                    supabase.table('tourpackages')
                            .select('id, package_name, name, title')
                            .in_('id', all_pkg_ids)
                            .execute()
                )
                for p in (pk_resp.data or []):
                    pid = str(p.get('id'))
                    label = (p.get('package_name') or p.get('package_name') or p.get('title') or '').strip()
                    if pid and label:
                        name_by_id[pid] = label
        except Exception:
            pass

        # 3b) fallback to bookings.package_name for any missing
        missing = [pid for pid in all_pkg_ids if pid not in name_by_id]
        if missing:
            try:
                bk_resp = execute_with_retry(lambda:
                    supabase.table('bookings')
                            .select('package_id, package_name')
                            .in_('package_id', missing)
                            .execute()
                )
                for b in (bk_resp.data or []):
                    pid = str(b.get('package_id'))
                    label = (b.get('package_name') or '').strip()
                    if pid and label and pid not in name_by_id:
                        name_by_id[pid] = label
            except Exception:
                pass

        # ---------- 4) Build groups for 5..1 stars
        labels = ['5★', '4★', '3★', '2★', '1★']
        counts = [counts_by_rating[5], counts_by_rating[4], counts_by_rating[3], counts_by_rating[2], counts_by_rating[1]]

        groups = []
        for rating in (5, 4, 3, 2, 1):
            pkg_names = [name_by_id.get(pid, f'Package {pid}') for pid in sorted(ids_by_rating[rating])]
            # Optional: sort names alphabetically
            pkg_names.sort(key=lambda s: s.lower())
            groups.append({
                "rating": rating,
                "label": f"{rating}★",
                "count": counts_by_rating[rating],
                "packages": pkg_names
            })

        return {"labels": labels, "counts": counts, "groups": groups}
    


    @staticmethod
    def get_active_drivers_count() -> int:
        """
        role='driver' AND status ILIKE 'active'
        AND (suspended_until IS NULL OR suspended_until <= now)
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        def q():
            return (
                supabase
                .table('users')
                .select('id', count='exact')
                .eq('role', 'driver')                 # only drivers
                .ilike('status', 'active')            # 'Active' / 'active' / etc.
                .or_(f'suspended_until.is.null,suspended_until.lte.{now_iso}')  # not suspended now
                .execute()
            )

        resp = execute_with_retry(q)
        return getattr(resp, 'count', None) or len(resp.data or [])



