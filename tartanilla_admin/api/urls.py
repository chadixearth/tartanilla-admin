from rest_framework.routers import DefaultRouter
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

# Example ViewSet
class StatusViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=['get'])
    def ping(self, request):
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)

router = DefaultRouter()
router.register(r'status', StatusViewSet, basename='status')

urlpatterns = [
    path('', include(router.urls)),
] 