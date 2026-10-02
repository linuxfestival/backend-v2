from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Accessory, FAQ, ReferralSource, Staff, User


class AccessorySerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"
        model = Accessory


class UserPublicSerializer(serializers.ModelSerializer):
    accessories = AccessorySerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            "first_name", "last_name", "avatar", "email", "phone_number",
            "accessories", "is_signed_up_for_competition", "is_first_login",
            "heard_about_us", "university", "hamkaran_announcement_consent",
        ]
        read_only_fields = ["email", "phone_number", "is_first_login"]


class ResetPasswordByAdminSerializer(serializers.Serializer):
    phone_number = serializers.CharField()


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone_number", "password"]

    def validate_email(self, value):
        return value.strip().lower()

    def create(self, validated_data):
        return User.objects.create_user(
            **validated_data,
            is_active=not settings.EMAIL_VERIFICATION_ENABLED,
        )


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    default_error_messages = {
        "no_active_account": "No active account found with the given credentials."
    }

    def validate(self, attrs):
        email = attrs.get(self.username_field, "").strip().lower()
        attrs[self.username_field] = email
        user = User.objects.filter(email__iexact=email).first()

        if user and not user.is_active and user.check_password(attrs.get("password", "")):
            if settings.EMAIL_VERIFICATION_ENABLED:
                raise AuthenticationFailed({
                    "detail": "Email verification is required.",
                    "verification_required": True,
                    "email": user.email,
                })
            user.is_active = True
            user.save(update_fields=["is_active"])

        data = super().validate(attrs)
        data.update({
            "email": self.user.email,
            "phone_number": self.user.phone_number,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "is_first_login": self.user.is_first_login,
        })
        return data


class SendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class ActivateUserSerializer(SendVerificationSerializer):
    code = serializers.RegexField(r"^\d{6}$")


class PasswordResetRequestSerializer(SendVerificationSerializer):
    pass


class PasswordResetConfirmSerializer(ActivateUserSerializer):
    new_password = serializers.CharField(write_only=True, validators=[validate_password])


class OnboardingSerializer(serializers.ModelSerializer):
    heard_about_us = serializers.ChoiceField(choices=ReferralSource.choices)

    class Meta:
        model = User
        fields = [
            "is_first_login", "heard_about_us", "university",
            "hamkaran_announcement_consent",
        ]
        read_only_fields = ["is_first_login"]
        extra_kwargs = {
            "university": {"allow_blank": True, "allow_null": True, "required": False},
            "hamkaran_announcement_consent": {"required": False},
        }

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        instance.is_first_login = False
        instance.save(update_fields=["is_first_login"])
        return instance


class StaffSerializer(serializers.ModelSerializer):
    class Meta:
        model = Staff
        fields = "__all__"


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ["question", "answer"]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, validators=[validate_password])


def tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}
