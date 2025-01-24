from django.contrib.auth.models import AnonymousUser
from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, BasePermission

from . import serializers
from .models import User

from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import SendVerificationSerializer, ActivateUserSerializer
from .sms import SMSThread


class IsSamePerson(BasePermission):
    message = 'You are not the owner of this account.'

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

    def get_permissions(self):
        if self.request.method == 'GET':
            self.permission_classes = [AllowAny]
        else:
            self.permission_classes = [IsSamePerson]
        return [permission() for permission in self.permission_classes]

    @action(methods=['POST'], detail=False, permission_classes=[IsSamePerson])
    def change_password(self, request):
        user = request.user
        self.check_object_permissions(request, user)

        serializer = serializers.ChangePasswordSerializer(data=request.data)

        if serializer.is_valid() and user:
            old_password = serializer.data.get("old_password")
            if not user.check_password(old_password):
                return Response({"message": "Old password is wrong"}, status=status.HTTP_400_BAD_REQUEST)

            user.set_password(serializer.data.get("new_password"))
            user.save()
            return Response(status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['POST'], detail=False, permission_classes=[])
    def signup(self, request):
        serializer = serializers.UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SendVerificationView(APIView):
    serializer_class = SendVerificationSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            user = User.objects.get(phone_number=phone_number)
            user.generate_activation_code()

            mobiles = [user.phone_number,]
            SMSThread(f"Your Verification code is sent {user.activation_code}.", list(mobiles)).start()

            return Response({"message": "Verification code sent to your phone."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ActivateUserView(APIView):
    serializer_class =  ActivateUserSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            phone_number = serializer.validated_data['phone_number']
            user = User.objects.get(phone_number=phone_number)
            user.is_active = True
            user.save()
            return Response({"message": "Phone number verified successfully."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)