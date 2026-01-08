from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from accounts.views import admin_authenticated
from tartanilla_admin.supabase import supabase
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import json
import base64
from datetime import datetime
import requests
from django.conf import settings
from rest_framework.test import APIRequestFactory
import traceback
from core.view_utils import OptimizedViewMixin, cached_view, OptimizedJSONResponseMixin
from core.cache_utils import CacheManager
from core.database_utils import DatabaseManager, DataProcessor
from core.jwt_auth import get_token_from_request, verify_token

API_BASE = '/api/tourpackage/'

# Render create package page
@never_cache
@admin_authenticated
def create_package_page(request):
    return render(request, 'tourpackage/createpackage.html')

# Render step-by-step create package page
@never_cache
@admin_authenticated
def create_package_steps(request):
    return render(request, 'tourpackage/create_package_steps.html')

# Optimized view packages page using centralized utilities
class TourPackageListView(OptimizedViewMixin):
    TABLE_NAME = 'tourpackages'
    MODULE_NAME = 'tourpackage'
    DATE_FIELDS = ['expiration_date', 'created_at', 'updated_at']
    JSON_FIELDS = ['available_days', 'photos']
    TEMPLATE_NAME = 'tourpackage/viewtourpackage.html'
    CACHE_TIMEOUT = 'short'

@cached_view('tourpackage', 'view_packages', 'medium')
@never_cache
@admin_authenticated
def view_packages(request):
    """Render view packages page with centralized optimization and pagination"""
    view_helper = TourPackageListView()
    
    # Get page number from request
    page = request.GET.get('page', 1)
    try:
        page = int(page)
    except ValueError:
        page = 1
    
    # Get filter parameter
    filter_param = request.GET.get('filter', 'all')
    
    # Set items per page
    items_per_page = 10
    
    # Get all packages
    all_packages = DatabaseManager.get_all(
        table=view_helper.TABLE_NAME,
        order_by='-created_at'
    )
    
    # Process data with error handling for malformed fields
    try:
        all_packages = view_helper.process_data(all_packages)
    except Exception as e:
        print(f"Error processing package data: {e}")
        # Continue with unprocessed data if processing fails
        pass
    
    # Apply filtering
    filtered_packages = []
    print(f"Total packages before filtering: {len(all_packages)}")
    for package in all_packages:
        print(f"Processing package: {package.get('package_name', 'Unknown')} (ID: {package.get('id', 'Unknown')})")
        # Check if package has expiration date
        has_expiration = package.get('expiration_date') not in [None, '', 'No expiration']
        
        # Check if package is expired
        is_expired = False
        if has_expiration:
            try:
                exp_date_str = package.get('expiration_date')
                if exp_date_str:
                    # Try multiple date formats
                    try:
                        expiration_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
                    except ValueError:
                        try:
                            expiration_date = datetime.strptime(exp_date_str, '%b %d, %Y').date()
                        except ValueError:
                            # If all parsing fails, assume not expired
                            expiration_date = datetime.now().date() + datetime.timedelta(days=1)
                    is_expired = expiration_date < datetime.now().date()
            except (ValueError, TypeError, AttributeError):
                is_expired = False
        
        # Check if package is active
        is_active = package.get('is_active') == True
        
        # Apply filter
        print(f"  - has_expiration: {has_expiration}, is_expired: {is_expired}, is_active: {is_active}")
        if filter_param == 'active' and is_active and not is_expired:
            filtered_packages.append(package)
            print(f"  - Added to filtered (active)")
        elif filter_param == 'expired' and is_expired:
            filtered_packages.append(package)
            print(f"  - Added to filtered (expired)")
        elif filter_param == 'no-expiration' and not has_expiration:
            filtered_packages.append(package)
            print(f"  - Added to filtered (no-expiration)")
        elif filter_param == 'all':
            filtered_packages.append(package)
            print(f"  - Added to filtered (all)")
        else:
            print(f"  - Filtered out (filter: {filter_param})")
    
    print(f"Total packages after filtering: {len(filtered_packages)}")
    
    # Calculate total pages
    total_items = len(filtered_packages)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    
    # Ensure page is within valid range
    if page < 1:
        page = 1
    if page > total_pages and total_pages > 0:
        page = total_pages
    
    # Calculate start and end indices for current page
    start_idx = (page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    
    # Get packages for current page
    current_page_packages = filtered_packages[start_idx:end_idx] if filtered_packages else []

    # Enrich with review stats (average rating and count) for displayed packages
    try:
        package_ids = [p.get('id') for p in current_page_packages if p.get('id')]
        review_stats_map = {}
        if package_ids:
            # Fetch published reviews for these packages in one query
            reviews = DatabaseManager.get_all(
                table='package_reviews',
                columns='package_id, rating, is_published',
                filters={'package_id': package_ids, 'is_published': True}
            )
            # Aggregate ratings per package
            sums = {}
            counts = {}
            for r in reviews or []:
                pid = r.get('package_id')
                try:
                    rating_val = float(r.get('rating') or 0)
                except (TypeError, ValueError):
                    rating_val = 0.0
                if not pid or rating_val <= 0:
                    continue
                sums[pid] = sums.get(pid, 0.0) + rating_val
                counts[pid] = counts.get(pid, 0) + 1
            # Build stats map
            for pid, cnt in counts.items():
                avg = round(sums.get(pid, 0.0) / cnt, 1) if cnt else 0.0
                review_stats_map[pid] = {'average_rating': avg, 'review_count': cnt}
        # Attach to each package
        for p in current_page_packages:
            pid = p.get('id')
            stats = review_stats_map.get(pid, {'average_rating': 0.0, 'review_count': 0})
            p['average_rating'] = stats['average_rating']
            p['review_count'] = stats['review_count']
    except Exception as e:
        # Fail-safe: do not block page if review stats fail
        for p in current_page_packages:
            p.setdefault('average_rating', 0.0)
            p.setdefault('review_count', 0)
    
    # Prepare context
    context = {
        'tourpackages': current_page_packages,
        'total_items': total_items,
        'current_page': page,
        'total_pages': total_pages,
        'page_range': range(1, total_pages + 1),
        'showing_start': start_idx + 1 if current_page_packages else 0,
        'showing_end': end_idx,
        'has_previous': page > 1,
        'has_next': page < total_pages,
        'previous_page': page - 1,
        'next_page': page + 1,
        'current_filter': filter_param
    }
    
    return render(request, view_helper.TEMPLATE_NAME, context)

@never_cache
@admin_authenticated
def edit_package(request, package_id):
    """Render edit package page with current package data as placeholders"""
    if request.method == 'POST':
        # Handle form submission by calling the API
        try:
            from api.tourpackage import TourPackageViewSet
            from rest_framework.test import APIRequestFactory
            
            factory = APIRequestFactory()
            api_request = factory.put(f'/api/tourpackage/{package_id}/', request.POST, format='json')
            api_request.user = request.user
            api_request.data = request.POST
            
            viewset = TourPackageViewSet()
            api_response = viewset.update(api_request, pk=package_id)
            
            if hasattr(api_response, 'data') and api_response.data.get('success'):
                return JsonResponse({'success': True, 'message': 'Package updated successfully'})
            else:
                error_msg = api_response.data.get('error', 'Update failed') if hasattr(api_response, 'data') else 'Update failed'
                return JsonResponse({'success': False, 'error': error_msg})
                
        except Exception as e:
            import json
            error_msg = str(e).replace('"', '\"').replace("'", "\'")  # Escape quotes
            return JsonResponse({'success': False, 'error': error_msg})
    
    try:
        # Fetch the package data from the database
        response = supabase.table('tourpackages').select('*').eq('id', package_id).single().execute()
        
        if not (hasattr(response, 'data') and response.data):
            # Package not found, redirect to view page
            return redirect('tourpackage:view')
        
        package = response.data
        
        # Process the package data for template display
        # Handle JSON fields
        if package.get('available_days'):
            if isinstance(package['available_days'], str):
                try:
                    package['available_days'] = json.loads(package['available_days'])
                except (json.JSONDecodeError, TypeError):
                    package['available_days'] = []
        else:
            package['available_days'] = []
        
        if package.get('photos'):
            if isinstance(package['photos'], str):
                try:
                    package['photos'] = json.loads(package['photos'])
                except (json.JSONDecodeError, TypeError):
                    package['photos'] = []
        else:
            package['photos'] = []
        
        # Handle date fields
        if package.get('expiration_date'):
            try:
                # Convert date to proper format if needed
                from datetime import datetime
                if isinstance(package['expiration_date'], str):
                    # Try to parse and reformat the date
                    date_obj = datetime.fromisoformat(package['expiration_date'].replace('Z', '+00:00'))
                    package['expiration_date'] = date_obj.strftime('%Y-%m-%d')
            except (ValueError, TypeError):
                package['expiration_date'] = None
        
        # Ensure numeric fields are properly formatted
        package['duration_hours'] = package.get('duration_hours') or ''
        package['duration_minutes'] = package.get('duration_minutes') or ''
        package['price'] = package.get('price') or ''
        package['max_pax'] = package.get('max_pax') or ''
        package['pickup_lat'] = package.get('pickup_lat') or ''
        package['pickup_lng'] = package.get('pickup_lng') or ''
        package['dropoff_lat'] = package.get('dropoff_lat') or ''
        package['dropoff_lng'] = package.get('dropoff_lng') or ''
        
        # Handle pickup time field
        package['pickup_time'] = package.get('pickup_time') or ''
        
        # Ensure text fields are not None
        package['package_name'] = package.get('package_name') or ''
        package['description'] = package.get('description') or ''
        package['pickup_location'] = package.get('pickup_location') or ''
        package['destination'] = package.get('destination') or ''
        package['route'] = package.get('route') or ''
        
        context = {
            'package': package
        }
        
        return render(request, 'tourpackage/edittourpackage.html', context)
        
    except Exception as e:
        print(f'Error loading package for edit: {str(e)}')
        traceback.print_exc()
        return redirect('tourpackage:view')

# Render bookings page with API integration and pagination
@never_cache
@admin_authenticated
def view_bookings(request):
    try:
        # Get page number from request
        page = request.GET.get('page', 1)
        try:
            page = int(page)
        except ValueError:
            page = 1
        
        # Set items per page to 6
        items_per_page = 6
        
        # Use the TourBookingViewSet to get bookings
        from api.booking import TourBookingViewSet
        viewset = TourBookingViewSet()
        viewset.request = request
        api_response = viewset.list(request)
        
        # Check if the response is a proper DRF Response
        if hasattr(api_response, 'data'):
            all_bookings = api_response.data.get('data', [])
            error = api_response.data.get('error')
        else:
            # Fallback if response is not as expected
            all_bookings = []
            error = 'Invalid API response'
            
        # Process bookings for display
        for booking in all_bookings:
            # Format dates for display
            if booking.get('booking_date'):
                try:
                    booking_date = datetime.fromisoformat(booking['booking_date'].split('T')[0])
                    booking['booking_date_formatted'] = booking_date.strftime('%Y-%m-%d')
                except:
                    booking['booking_date_formatted'] = booking['booking_date']
            
            if booking.get('created_at'):
                try:
                    created_date = datetime.fromisoformat(booking['created_at'].split('T')[0])
                    booking['created_date_formatted'] = created_date.strftime('%Y-%m-%d')
                except:
                    booking['created_date_formatted'] = booking['created_at']
            
            # Set default values for missing fields
            booking['payment_status'] = booking.get('payment_status', 'Pending')
            # Format booking_date for display
            if booking.get('booking_date'):
                try:
                    booking_date = datetime.fromisoformat(booking['booking_date'].split('T')[0])
                    booking['scheduled_tour_date'] = booking_date.strftime('%Y-%m-%d')
                except:
                    booking['scheduled_tour_date'] = booking.get('booking_date', 'TBD')
            else:
                booking['scheduled_tour_date'] = 'TBD'
        
        # Calculate pagination
        total_items = len(all_bookings)
        total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
        
        # Ensure page is within valid range
        if page < 1:
            page = 1
        if page > total_pages and total_pages > 0:
            page = total_pages
        
        # Calculate start and end indices for current page
        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_items)
        
        # Get bookings for current page
        current_page_bookings = all_bookings[start_idx:end_idx] if all_bookings else []
        
        # Create pagination context
        context = {
            'bookings': current_page_bookings,
            'error': error,
            'total_items': total_items,
            'current_page': page,
            'total_pages': total_pages,
            'page_range': range(1, total_pages + 1),
            'showing_start': start_idx + 1 if current_page_bookings else 0,
            'showing_end': end_idx,
            'has_previous': page > 1,
            'has_next': page < total_pages,
            'previous_page': page - 1,
            'next_page': page + 1,
        }
            
        return render(request, 'tourpackage/listofbookings.html', context)
    except Exception as e:
        print(f'Error in view_bookings: {str(e)}')
        # Fallback to direct database call if API fails
        try:
            response = supabase.table('bookings').select('*').order('created_at', desc=True).execute()
            all_bookings = response.data if hasattr(response, 'data') else []
            
            # Process bookings for display
            for booking in all_bookings:
                if booking.get('booking_date'):
                    try:
                        booking_date = datetime.fromisoformat(booking['booking_date'].split('T')[0])
                        booking['booking_date_formatted'] = booking_date.strftime('%Y-%m-%d')
                    except:
                        booking['booking_date_formatted'] = booking['booking_date']
                
                if booking.get('created_at'):
                    try:
                        created_date = datetime.fromisoformat(booking['created_at'].split('T')[0])
                        booking['created_date_formatted'] = created_date.strftime('%Y-%m-%d')
                    except:
                        booking['created_date_formatted'] = booking['created_at']
                
                booking['payment_status'] = booking.get('payment_status', 'Pending')
                booking['scheduled_tour_date'] = booking.get('booking_date_formatted', 'TBD')
            
            # Get page number from request
            page = request.GET.get('page', 1)
            try:
                page = int(page)
            except ValueError:
                page = 1
            
            # Set items per page to 6
            items_per_page = 6
            
            # Calculate pagination
            total_items = len(all_bookings)
            total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
            
            # Ensure page is within valid range
            if page < 1:
                page = 1
            if page > total_pages and total_pages > 0:
                page = total_pages
            
            # Calculate start and end indices for current page
            start_idx = (page - 1) * items_per_page
            end_idx = min(start_idx + items_per_page, total_items)
            
            # Get bookings for current page
            current_page_bookings = all_bookings[start_idx:end_idx] if all_bookings else []
            
            # Create pagination context
            context = {
                'bookings': current_page_bookings,
                'error': None,
                'total_items': total_items,
                'current_page': page,
                'total_pages': total_pages,
                'page_range': range(1, total_pages + 1),
                'showing_start': start_idx + 1 if current_page_bookings else 0,
                'showing_end': end_idx,
                'has_previous': page > 1,
                'has_next': page < total_pages,
                'previous_page': page - 1,
                'next_page': page + 1,
            }
            
            return render(request, 'tourpackage/listofbookings.html', context)
        except Exception as fallback_error:
            print(f'Fallback error: {str(fallback_error)}')
            return render(request, 'tourpackage/listofbookings.html', {
                'bookings': [], 
                'error': 'Failed to load bookings',
                'total_items': 0,
                'current_page': 1,
                'total_pages': 1,
                'has_previous': False,
                'has_next': False,
            })

# API endpoint to update booking status
@csrf_exempt
@require_http_methods(["POST"])
def update_booking_status(request):
    try:
        try:
            data = json.loads(request.body)
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Invalid JSON: {str(e)}'}, status=400)

        booking_id = data.get('booking_id')
        new_status = data.get('status')

        if not booking_id or not new_status:
            return JsonResponse({'success': False, 'error': 'Missing booking_id or status'}, status=400)

        # Only admin-driven simple transitions are supported here.
        # For now, support admin decline -> cancelled. Other flows use dedicated endpoints.
        if new_status.lower() == 'cancelled':
            # Ensure booking exists
            booking_res = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
            booking = booking_res.data if hasattr(booking_res, 'data') else None
            if not booking:
                return JsonResponse({'success': False, 'error': 'Booking not found'}, status=404)

            update = supabase.table('bookings').update({
                'status': 'cancelled',
                'cancel_reason': data.get('reason', 'Declined by admin'),
                'cancelled_by': 'admin',
                'cancelled_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }).eq('id', booking_id).execute()

            if hasattr(update, 'data') and update.data:
                return JsonResponse({'success': True, 'message': 'Booking declined successfully'})
            return JsonResponse({'success': False, 'error': 'Failed to decline booking'}, status=500)

        return JsonResponse({'success': False, 'error': 'Unsupported status change. Use the appropriate action endpoint.'}, status=400)

    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@never_cache
@admin_authenticated
def view_booking_detail(request):
    """View detailed information about a specific booking"""
    try:
        booking_id = request.GET.get('booking_id')
        if not booking_id:
            return JsonResponse({'error': 'Missing booking_id'}, status=400)
        
        # Fetch booking details
        booking_response = supabase.table('bookings').select('*').eq('id', booking_id).single().execute()
        booking = booking_response.data if hasattr(booking_response, 'data') and booking_response.data else None
        
        if not booking:
            return render(request, 'tourpackage/booking_detail.html', {'error': 'Booking not found'})
        
        # Fetch related tour package
        package = None
        if booking.get('package_id'):
            try:
                package_response = supabase.table('tourpackages').select('*').eq('id', booking['package_id']).single().execute()
                package = package_response.data if hasattr(package_response, 'data') and package_response.data else None
            except:
                pass
        
        # Fetch tourist details
        tourist = None
        if booking.get('tourist_id'):
            try:
                tourist_response = supabase.table('users').select('*').eq('id', booking['tourist_id']).single().execute()
                tourist = tourist_response.data if hasattr(tourist_response, 'data') and tourist_response.data else None
            except:
                pass
        
        # Fetch driver details
        driver = None
        if booking.get('driver_id'):
            try:
                driver_response = supabase.table('users').select('*').eq('id', booking['driver_id']).single().execute()
                driver = driver_response.data if hasattr(driver_response, 'data') and driver_response.data else None
            except:
                pass
        
        context = {
            'booking': booking,
            'package': package,
            'tourist': tourist,
            'driver': driver
        }
        
        return render(request, 'tourpackage/booking_detail.html', context)
        
    except Exception as e:
        print(f'Error viewing booking detail: {str(e)}')
        return render(request, 'tourpackage/booking_detail.html', {'error': str(e)})

# DEPRECATED: Admin approval is no longer required - bookings go directly to drivers
@csrf_exempt
@require_http_methods(["POST"])
def admin_approve_booking(request):
    """
    DEPRECATED: This endpoint is kept for backward compatibility.
    New bookings are automatically set to 'waiting_for_driver' status.
    Admin approval is no longer required in the booking flow.
    """
    try:
        data = json.loads(request.body)
        booking_id = data.get('booking_id')
        
        if not booking_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing booking_id'
            }, status=400)
        
        # For backward compatibility, we still call the deprecated method
        # This handles any legacy bookings that might still be pending
        from api.booking import TourBookingViewSet
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        api_request = factory.post(f'/api/tour-booking/admin-approve/{booking_id}/', {}, format='json')
        api_request.user = request.user

        viewset = TourBookingViewSet()
        viewset.request = api_request
        api_response = viewset.admin_approve_booking(api_request, booking_id=booking_id)
        
        if hasattr(api_response, 'data'):
            response_data = api_response.data
            if response_data.get('success'):
                return JsonResponse({
                    'success': True,
                    'message': 'Booking processed (admin approval no longer required)'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': response_data.get('error', 'Failed to process booking')
                }, status=400)
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to process booking'
            }, status=500)
            
    except Exception as e:
        print(f'Error in deprecated admin approval endpoint: {str(e)}')
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
