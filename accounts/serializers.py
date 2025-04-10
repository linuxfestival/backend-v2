from django.contrib.auth.password_validation import validate_password
from rest_framework.exceptions import ValidationError
from rest_framework.fields import SerializerMethodField
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, Staff, FAQ, Accessory
from rest_framework import serializers

class AccessorySerializer(serializers.ModelSerializer):
    class Meta:
        fields = '__all__'
        model = Accessory

class UserPublicSerializer(serializers.ModelSerializer):
    accessories = AccessorySerializer(many=True, read_only=True)
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'avatar', 'email', 'accessories', 'is_signed_up_for_competition']

class ResetPasswordByAdminSerializer(serializers.Serializer):
    phone_number = serializers.CharField()



class UserRegistrationSerializer(serializers.ModelSerializer):
    tokens = SerializerMethodField(read_only=True)
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'password', 'tokens']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        instance = self.Meta.model(**validated_data)
        if password is not None:
            instance.set_password(password)
        else:
            raise serializers.ValidationError("Invalid password.")
        instance.is_active = True
        instance.save()
        return instance

    def get_tokens(self, obj):
        refresh = RefreshToken.for_user(obj)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }

    def validate_password(self, value):
        try:
            validate_password(value, self.instance)
        except ValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value


class StaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = Staff
        fields = '__all__'


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ['question', 'answer']


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])


class SendVerificationSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)

    def validate(self, data):
        phone_number = data.get("phone_number")
        try:
            User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid phone number.")

        return data


class ActivateUserSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)
    code = serializers.CharField(max_length=6)

    def validate(self, data):
        phone_number = data.get("phone_number")
        try:
            User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid phone number.")

        return data


