from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PresentationViewSet,
    PaymentViewSet,
    CouponViewSet,
    PresenterViewSet,
    PresentationProposalCreateView,
)

router = DefaultRouter()
router.register(r'presentations', PresentationViewSet, basename='presentation')
router.register(r'payments', PaymentViewSet, basename='payment')
router.register(r'coupon', CouponViewSet, basename='coupon')
router.register(r'presenter', PresenterViewSet, basename='presenter')

urlpatterns = [
    path(
        'presentation-proposals/',
        PresentationProposalCreateView.as_view(),
        name='presentation-proposal-create',
    ),
    path('', include(router.urls)),
]
