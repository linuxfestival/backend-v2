from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PresentationViewSet, PaymentViewSet

router = DefaultRouter()
router.register(r'presentations', PresentationViewSet, basename='presentation')
router.register(r'payments', PaymentViewSet, basename='payment')

urlpatterns = [
    path('', include(router.urls)),
]
