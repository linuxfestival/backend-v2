from django.contrib.auth.password_validation import validate_password
from .models import User, Staff, FAQ
from rest_framework import serializers


class UserPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'avatar', 'email']

class UserRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        instance = self.Meta.model(**validated_data)
        if password is not None:
            instance.set_password(password)
        instance.is_active = True
        instance.save()
        return instance

class StaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = Staff
        fields = '__all__'

class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ['question', 'answer']


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True, validators=[validate_password])
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
