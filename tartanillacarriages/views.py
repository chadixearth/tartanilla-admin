from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from accounts.views import admin_authenticated
from rest_framework.test import APIRequestFactory
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import api_view, permission_classes

# Create your views here.
@never_cache
@admin_authenticated
def list_of_tartanillas(request):
    """List all tartanilla carriages"""
    try:
        from api.tartanilla import get_all_tartanilla_carriages
        carriages = get_all_tartanilla_carriages()
        
        # Debug: Print carriage data
        print(f"[DEBUG] Found {len(carriages)} carriages")
        for i, carriage in enumerate(carriages[:2]):  # Print first 2 for debugging
            print(f"[DEBUG] Carriage {i+1}: {carriage.get('plate_number')}")
            print(f"  - Owner ID: {carriage.get('assigned_owner_id')}")
            print(f"  - Owner Data: {carriage.get('assigned_owner')}")
            print(f"  - Driver ID: {carriage.get('assigned_driver_id')}")
            print(f"  - Driver Data: {carriage.get('assigned_driver')}")
            print(f"  - Eligibility: {carriage.get('eligibility')}")
        
        return render(request, 'tartanillacarriages/listofcarriages.html', {
            'carriages': carriages,
            'is_owner_specific': False,
            'owner': None
        })
    except Exception as e:
        print(f"Error in list_of_tartanillas: {str(e)}")
        import traceback
        traceback.print_exc()
        return render(request, 'tartanillacarriages/listofcarriages.html', {
            'carriages': [],
            'is_owner_specific': False,
            'owner': None,
            'error': str(e)
        })

@never_cache
@admin_authenticated
def list_of_carriages(request, tartanilla_id=None):
    """List carriages with optional owner filtering"""
    try:
        from api.tartanilla import (
            get_all_tartanilla_carriages,
            get_tartanilla_carriages_by_owner,
            get_user_by_id
        )
        
        # Check if this is an owner-specific view
        owner_id = request.GET.get('owner_id')
        is_owner_specific = bool(owner_id)
        
        if is_owner_specific:
            # Get carriages for specific owner
            carriages = get_tartanilla_carriages_by_owner(owner_id)
            # Get owner info
            owner = get_user_by_id(owner_id)
        else:
            # Get all carriages
            carriages = get_all_tartanilla_carriages()
            owner = None
        
        return render(request, 'tartanillacarriages/listofcarriages.html', {
            'carriages': carriages,
            'is_owner_specific': is_owner_specific,
            'owner': owner
        })
        
    except Exception as e:
        print(f"Error in list_of_carriages: {str(e)}")
        return render(request, 'tartanillacarriages/listofcarriages.html', {
            'carriages': [],
            'is_owner_specific': False,
            'owner': None,
            'error': str(e)
        })

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def get_assigned_tartanillas(request):
    """API endpoint to get assigned tartanillas for a driver"""
    try:
        driver_id = request.GET.get('driver_id')
        
        if not driver_id:
            return JsonResponse({
                'success': False,
                'error': 'driver_id parameter is required'
            }, status=400)
        
        from api.tartanilla import get_tartanilla_carriages_by_driver
        
        # Get assigned tartanillas for the driver
        try:
            carriages = get_tartanilla_carriages_by_driver(driver_id)
            return JsonResponse({
                'success': True,
                'data': carriages
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Error fetching assigned tartanillas: {str(e)}'
            }, status=500)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)
