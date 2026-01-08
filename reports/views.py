from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods
from tartanilla_admin.supabase import supabase
from datetime import datetime
import json

def admin_authenticated(view_func):
    """Decorator to check admin authentication"""
    from functools import wraps
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.COOKIES.get('admin_authenticated') != '1':
            return redirect('/accounts/login/')
        
        # Get user info from cookies
        user_id = request.COOKIES.get('admin_user_id')
        user_email = request.COOKIES.get('admin_email')
        
        # Set user information on request object
        request.user = type('AdminUser', (), {
            'is_authenticated': True,
            'is_active': True,
            'id': user_id,
            'pk': user_id,
            'email': user_email,
            '__str__': lambda self: self.email
        })
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@admin_authenticated
def reports_list(request):
    """Display all reports in the admin interface"""
    try:
        # Get reports from Supabase
        response = supabase.table('reports').select('*').order('created_at', desc=True).execute()
        all_reports = response.data if hasattr(response, 'data') else []
        
        # Apply filters
        status_filter = request.GET.get('status')
        type_filter = request.GET.get('type')
        
        filtered_reports = all_reports
        if status_filter:
            filtered_reports = [r for r in filtered_reports if r.get('status') == status_filter]
        if type_filter:
            filtered_reports = [r for r in filtered_reports if r.get('report_type') == type_filter]
        
        # Get statistics
        stats = {
            'total': len(all_reports),
            'pending': len([r for r in all_reports if r.get('status') == 'pending']),
            'investigating': len([r for r in all_reports if r.get('status') == 'investigating']),
            'resolved': len([r for r in all_reports if r.get('status') == 'resolved']),
            'by_type': {}
        }
        
        for report in all_reports:
            report_type = report.get('report_type', 'unknown')
            stats['by_type'][report_type] = stats['by_type'].get(report_type, 0) + 1
        
        # Pagination - 5 reports per page
        paginator = Paginator(filtered_reports, 5)
        page_number = request.GET.get('page')
        reports = paginator.get_page(page_number)
        
        context = {
            'reports': reports,
            'stats': stats,
            'status_filter': status_filter,
            'type_filter': type_filter,
            'user': request.COOKIES.get('admin_email')
        }
        
        return render(request, 'reports/reports_list.html', context)
        
    except Exception as e:
        print(f"Error fetching reports: {e}")
        return render(request, 'reports/reports_list.html', {
            'reports': [],
            'stats': {'total': 0, 'pending': 0, 'investigating': 0, 'resolved': 0, 'by_type': {}},
            'error': 'Failed to load reports',
            'user': request.COOKIES.get('admin_email')
        })

@admin_authenticated
def report_detail(request, report_id):
    """Display detailed view of a specific report"""
    try:
        # Get report details
        response = supabase.table('reports').select('*').eq('id', report_id).single().execute()
        report = response.data if hasattr(response, 'data') and response.data else None
        
        if not report:
            return render(request, 'reports/report_detail.html', {
                'error': 'Report not found'
            })
        
        # Get related booking if exists
        booking = None
        if report.get('related_booking_id'):
            try:
                booking_response = supabase.table('bookings').select('*').eq('id', report['related_booking_id']).single().execute()
                booking = booking_response.data if hasattr(booking_response, 'data') and booking_response.data else None
            except:
                pass
        
        # Get related user if exists
        related_user = None
        if report.get('related_user_id'):
            try:
                user_response = supabase.table('users').select('*').eq('id', report['related_user_id']).single().execute()
                related_user = user_response.data if hasattr(user_response, 'data') and user_response.data else None
            except:
                pass
        
        # Get post media for goods & services violations
        post_media = None
        if 'goods' in report.get('report_type', '').lower() and 'services' in report.get('report_type', '').lower():
            try:
                post_id = report.get('related_booking_id')
                print(f"Fetching media for post_id: {post_id}")
                post_response = supabase.table('goods_services_profiles').select('media').eq('id', post_id).single().execute()
                print(f"Post response: {post_response}")
                if hasattr(post_response, 'data') and post_response.data:
                    media = post_response.data.get('media', [])
                    print(f"Media data: {media}")
                    if isinstance(media, str):
                        try:
                            post_media = json.loads(media)
                        except:
                            post_media = [media] if media else []
                    else:
                        post_media = media
                    print(f"Final post_media: {post_media}")
            except Exception as e:
                print(f"Error fetching post media: {e}")
        
        # Handle POST request for status updates
        if request.method == 'POST':
            try:
                new_status = request.POST.get('status')
                admin_notes = request.POST.get('admin_notes', '')
                
                update_data = {
                    'status': new_status,
                    'admin_notes': admin_notes,
                    'updated_at': datetime.now().isoformat()
                }
                
                if new_status == 'resolved':
                    update_data['resolved_at'] = datetime.now().isoformat()
                    # You can add admin_id here if you have session management
                
                supabase.table('reports').update(update_data).eq('id', report_id).execute()
                
                return JsonResponse({
                    'success': True,
                    'message': 'Report status updated successfully'
                })
                
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })
        
        print(f"Report type: '{report.get('report_type')}', Status: '{report.get('status')}', Post media count: {len(post_media) if post_media else 0}")
        
        context = {
            'report': report,
            'booking': booking,
            'related_user': related_user,
            'post_media': post_media,
            'user': request.COOKIES.get('admin_email')
        }
        
        return render(request, 'reports/report_detail.html', context)
        
    except Exception as e:
        print(f"Error fetching report details: {e}")
        return render(request, 'reports/report_detail.html', {
            'error': 'Failed to load report details',
            'user': request.COOKIES.get('admin_email')
        })

@require_http_methods(["GET"])
def reports_pending_count(request):
    """API endpoint to get pending reports count"""
    try:
        response = supabase.table('reports').select('id').eq('status', 'pending').execute()
        pending_reports = response.data if hasattr(response, 'data') else []
        count = len(pending_reports)
        
        return JsonResponse({'count': count})
    except Exception as e:
        print(f"Error fetching pending reports count: {e}")
        return JsonResponse({'count': 0, 'error': str(e)})