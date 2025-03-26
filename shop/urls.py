from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PresentationViewSet, PaymentViewSet, CouponViewSet

router = DefaultRouter()
router.register(r'presentations', PresentationViewSet, basename='presentation')
router.register(r'payments', PaymentViewSet, basename='payment')
router.register(r'coupon', CouponViewSet, basename='coupon')

urlpatterns = [
    path('', include(router.urls)),
]
