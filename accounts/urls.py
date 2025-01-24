from django.urls import path
from rest_framework import routers

from . import views
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, token_blacklist

from .views import ActivateUserView, SendVerificationView

app_name = 'accounts'
router = routers.DefaultRouter()
router.register('users', views.UserViewSet, 'users')

urlpatterns = [
                  # flush expired tokens on a daily basis.
                  path('token/', TokenObtainPairView.as_view(), name='token'),
                  path('token/refresh/', TokenRefreshView.as_view(), name='refresh_token'),
                  path('token/blacklist/', token_blacklist, name='blacklist_token'),

                  path('users/send-verification/', SendVerificationView.as_view(), name='send_verification'),
                  path('users/activate/', ActivateUserView.as_view(), name='activate_user'),
              ] + router.urls