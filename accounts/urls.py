from django.urls import path
from rest_framework import routers

from . import views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, token_blacklist

app_name = 'accounts'
router = routers.DefaultRouter()
router.register('users', views.UserViewSet, 'users')
router.register('staff', views.StaffViewSet, 'staff')
router.register('faq', views.FAQViewSet, 'faq')

urlpatterns = [
                  # flush expired tokens on a daily basis.
                  path('token/access/', TokenObtainPairView.as_view(), name='token'),
                  path('token/refresh/', TokenRefreshView.as_view(), name='refresh_token'),
                  path('token/blacklist/', token_blacklist, name='blacklist_token'),
              ] + router.urls
