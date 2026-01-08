from django.urls import path
from . import views

urlpatterns = [
    path('list-of-tartanillas/', views.list_of_tartanillas, name='list_of_tartanillas'),
    path('list-of-carriages/', views.list_of_carriages, name='list_of_carriages'),
    path('list-of-carriages/<uuid:tartanilla_id>/', views.list_of_carriages, name='list_of_carriages_detail'),
    path('api/assigned/', views.get_assigned_tartanillas, name='get_assigned_tartanillas'),
]