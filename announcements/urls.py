from django.urls import path
from . import views

urlpatterns = [
    path('', views.announcements_page, name='announcements'),
    path('send/', views.send_announcement, name='send_announcement'),
]