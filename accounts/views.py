from django.contrib.auth.models import AnonymousUser
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission

from . import serializers
from .models import User
from rest_framework.response import Response
from .sms import SMS_EXECUTOR, send_sms


class IsSamePerson(BasePermission):
    message = 'You are not the owner of this account.'

    def has_permission(self, request, view):
        return request.user and not isinstance(request.user, AnonymousUser)

    def has_object_permission(self, request, view, obj):
        try:
            return request.user and not isinstance(request.user, AnonymousUser) and request.user.pk == obj.pk
        except AttributeError:
            return False


class UserViewSet(mixins.UpdateModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
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
                return Response({"message": "Old password is incorrect"}, status=status.HTTP_400_BAD_REQUEST)
            request.user.set_password(serializer.validated_data["new_password"])
            request.user.save()
            return Response({"message": "Password updated successfully"}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
                return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)
            user.generate_activation_code()

            mobiles = [user.phone_number, ]
            SMS_EXECUTOR.submit(send_sms, list(mobiles), f"Your Verification code is sent {user.activation_code}.")

            return Response({"message": "Verification code sent to your phone."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.ActivateUserSerializer)
    def activate(self, request):
        serializer = serializers.ActivateUserSerializer(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']

            try:
                user = User.objects.get(phone_number=phone_number)
            except User.DoesNotExist:
                return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

            if user.activation_code != serializer.validated_data["activation_code"]:
                return Response({"message": "Invalid activation code"}, status=status.HTTP_400_BAD_REQUEST)

            user.is_active = True
            user.save()
            return Response({"message": "Phone number verified successfully."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
