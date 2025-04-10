import secrets

import pyotp
from django.utils.timezone import now

from django.contrib.auth.models import AnonymousUser
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission

from . import serializers
from .models import User, Staff, FAQ, Accessory
from rest_framework.response import Response

from .serializers import FAQSerializer, AccessorySerializer
from .sms import SMS_EXECUTOR, send_sms, OTP_VALIDITY_PERIOD, OTP_RESEND_DELAY


class IsSamePerson(BasePermission):
    message = 'You are not the owner of this account.'

    def has_permission(self, request, view):
        return request.user and not isinstance(request.user, AnonymousUser)

    def has_object_permission(self, request, view, obj):
        try:
            return request.user and not isinstance(request.user, AnonymousUser) and request.user.pk == obj.pk
        except AttributeError:
            return False


class StaffViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Staff.objects.all()
    serializer_class = serializers.StaffSerializer


class UserViewSet(mixins.UpdateModelMixin, mixins.RetrieveModelMixin,
                  viewsets.GenericViewSet):
    queryset = User.objects.all()
    serializer_class = serializers.UserPublicSerializer
    lookup_field = 'phone_number'
    permission_classes = [IsSamePerson]

    @action(methods=['POST'], detail=False, permission_classes=[IsSamePerson],
            serializer_class=serializers.ChangePasswordSerializer)
    def change_password(self, request):
        serializer = serializers.ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            if not request.user.check_password(serializer.validated_data["old_password"]):
                return Response({"detail": "Old password is incorrect"}, status=status.HTTP_400_BAD_REQUEST)
            request.user.set_password(serializer.validated_data["new_password"])
            request.user.save()
            return Response({"detail": "Password updated successfully"}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['POST'], detail=False, permission_classes=[IsSamePerson],
            serializer_class=None)
    def competition_signup(self, request):
        user = request.user
        if user.is_signed_up_for_competition:
            return Response({"detail": "User's already registered for the upcoming competition", "suggestion": "kys"}, status=status.HTTP_400_BAD_REQUEST)
        user.is_signed_up_for_competition = True
        user.save()
        return Response({"detail": "Donezo"})

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.UserRegistrationSerializer)
    def signup(self, request):
        serializer = serializers.UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(is_active=False)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.SendVerificationSerializer)
    def verify(self, request):
        serializer = serializers.SendVerificationSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']

            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

            if user.last_otp_sent and (now() - user.last_otp_sent).seconds < OTP_RESEND_DELAY:
                return Response({"detail": "Please wait before requesting another OTP."},
                                status=status.HTTP_429_TOO_MANY_REQUESTS)

            secret_key = pyotp.random_base32()
            user.otp_code = secret_key
            user.last_otp_sent = now()
            user.save()

            totp = pyotp.TOTP(secret_key, interval=OTP_VALIDITY_PERIOD)
            otp = totp.now()

            mobiles = [user.phone_number, ]
            SMS_EXECUTOR.submit(send_sms, mobiles, f"Your verification code is {otp}.")

            return Response({"detail": "Verification code sent to your phone."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.ActivateUserSerializer)
    def activate(self, request):
        serializer = serializers.ActivateUserSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            otp = serializer.validated_data["code"]

            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

            if not user.otp_code:
                return Response({"detail": "No OTP generated for this user."}, status=status.HTTP_400_BAD_REQUEST)

            totp = pyotp.TOTP(user.otp_code, interval=OTP_VALIDITY_PERIOD)
            if not totp.verify(otp):
                return Response({"detail": "Invalid or expired activation code"}, status=status.HTTP_400_BAD_REQUEST)

            user.is_active = True
            user.otp_code = ""
            user.save()

            return Response({"detail": "Phone number verified successfully."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.ForgotPasswordSerializer)
    def forgot_password(self, request):
        serializer = serializers.ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

            new_password = secrets.token_urlsafe(8)
            user.set_password(new_password)
            user.save()

            message_text = f"رمز عبور جدید شما: {new_password}. لطفاً پس از ورود، آن را تغییر دهید."
            SMS_EXECUTOR.submit(send_sms, [user.phone_number], message_text)

            return Response({"detail": "password change"},
                            status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class FAQViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = FAQ.objects.all()
    serializer_class = FAQSerializer


class AccessoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Accessory.objects.all()
    serializer_class = AccessorySerializer
