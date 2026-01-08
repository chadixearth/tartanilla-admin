from django.urls import path
# from .views import LoginView, LogoutView
from . import views

urlpatterns = [
    path('chat/', views.chat_view, name='chat_view'),  
    # path('test-404/', views.test_404, name='test_404'),  # for testing
]