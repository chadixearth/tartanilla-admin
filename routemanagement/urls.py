from django.urls import path
# from .views import LoginView, LogoutView
from . import views
from . import raw_views

urlpatterns = [
    # Main route management page
    path("", views.route_management, name="route_management"),
    
    # Debug endpoint
    path("debug/", views.debug_info, name="debug_info"),
    
    # Fix JSON data endpoint
    path("fix_json_data/", views.fix_json_data, name="fix_json_data"),
    
    # Test JSON endpoint
    path("test_json/", views.test_json, name="test_json"),
    
    # Test roads endpoint
    path("test_roads/", views.test_roads, name="test_roads"),
    
    # Get points by type endpoint
    path("points_by_type/", views.get_points_by_type, name="get_points_by_type"),
    
    # AJAX endpoints for saving data
    path("save_point/", views.save_point, name="save_point"),
    path("save_road/", views.save_road, name="save_road"),
    path("save_ridehailing/", views.save_ridehailing, name="save_ridehailing"),
    
    # AJAX endpoints for loading data
    path("get_items/", views.get_items, name="get_items"),
    path("raw_json/", raw_views.raw_json, name="raw_json"),
    path("get_map_configuration/", views.get_map_configuration, name="get_map_configuration"),
    
    # AJAX endpoints for updating data
    path("update_point/<int:point_id>/", views.update_point, name="update_point"),
    path("update_road/<int:road_id>/", views.update_road, name="update_road"),
    
    # AJAX endpoints for deleting data
    path("delete_point/<int:point_id>/", views.delete_point, name="delete_point"),
    path("delete_road/<int:road_id>/", views.delete_road, name="delete_road"),
    
    # Map configuration
    path("save_map_configuration/", views.save_map_configuration, name="save_map_configuration"),
]