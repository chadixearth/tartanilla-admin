from django.urls import path
from .views import ChatSupportView

urlpatterns = [
    path('', ChatSupportView.as_view(), name='chat_support'),
]