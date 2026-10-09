import logging
import secrets
import string

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import viewsets, mixins, status
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.views import TokenObtainPairView

from shop.models import Payment
from shop.payments import ZarrinPal
from . import serializers
from .emailing import OTPError, OTPThrottled, send_otp, validate_otp
from .models import OTPPurpose, User, Staff, FAQ, Accessory, Resume
from rest_framework.response import Response

from .serializers import FAQSerializer, AccessorySerializer, ResetPasswordByAdminSerializer


logger = logging.getLogger(__name__)


class ResumeUploadThrottle(UserRateThrottle):
    scope = "resume_upload"


@extend_schema_view(
    get=extend_schema(
        responses={
            200: serializers.ResumeSerializer,
            404: OpenApiResponse(description="No resume has been submitted."),
        },
    ),
    post=extend_schema(
        request=serializers.ResumeUploadSerializer,
        responses={
            200: serializers.ResumeMutationResponseSerializer,
            201: serializers.ResumeMutationResponseSerializer,
            400: OpenApiResponse(description="The uploaded file failed validation."),
            429: OpenApiResponse(description="The per-user upload rate limit was exceeded."),
        },
    ),
    delete=extend_schema(responses={204: None, 404: OpenApiResponse(description="No resume found.")}),
)
class ResumeUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_throttles(self):
        if self.request.method == "POST":
            return [ResumeUploadThrottle()]
        return []

    def get(self, request):
        resume = Resume.objects.filter(user=request.user).first()
        if resume is None:
            return Response(
                {"detail": "No resume has been submitted."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(serializers.ResumeSerializer(resume).data)

    def post(self, request):
        with transaction.atomic():
            # Locking the user serializes two simultaneous uploads even when a
            # resume row does not exist yet.
            user = User.objects.select_for_update().get(pk=request.user.pk)
            resume = Resume.objects.filter(user=user).first()
            created = resume is None
            upload = serializers.ResumeUploadSerializer(
                resume,
                data=request.data,
                context={"request": request},
            )
            upload.is_valid(raise_exception=True)
            resume = upload.save(user=user)

        return Response(
            {
                "detail": "Resume uploaded successfully." if created else "Resume replaced successfully.",
                "resume": serializers.ResumeSerializer(resume).data,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request):
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request.user.pk)
            resume = Resume.objects.filter(user=user).first()
            if resume is None:
                return Response(
                    {"detail": "No resume has been submitted."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            resume.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = serializers.EmailTokenObtainPairSerializer


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

    @action(methods=['POST'], detail=False, permission_classes=[IsAdminUser],
            serializer_class=ResetPasswordByAdminSerializer)
    def reset_password_by_admin(self,request):
        serializer = serializers.ResetPasswordByAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data['phone_number']

        try:
            user = User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        new_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        user.set_password(new_password)
        user.save()

        return Response({
            'detail': 'Password has been reset.',
            'new_password': new_password
        }, status=status.HTTP_200_OK)


    @action(methods=['POST'], detail=False, permission_classes=[IsSamePerson],
            serializer_class=None)
    @transaction.atomic
    def competition_signup(self, request):
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if user.is_signed_up_for_competition:
            return Response({"detail": "شما برای مسابقه قبلا ثبت نام کردید!"},
                            status=status.HTTP_400_BAD_REQUEST)

        # TODO: Move this shit to db
        if User.objects.filter(is_signed_up_for_competition=True).count() >= 50:
            return Response({"detail": "ظرفیت مسابقه پر شده است!"}, status=status.HTTP_400_BAD_REQUEST)

        pending_payment = Payment.objects.select_for_update().filter(
            user=user,
            is_competition_payment=True,
            payment_state="PENDING",
            authority__isnull=False,
        ).order_by("-created_date").first()
        if pending_payment:
            return Response({
                "payment_url": pending_payment.pay_link,
                "authority": pending_payment.authority,
            }, status=status.HTTP_200_OK)

        # TODO: Duplicated code
        zarrinpal = ZarrinPal()

        # TODO: Move total price to env variables or even better, admin panel
        # Also TODO: Don't be lazy
        price = 50_000
        zarrinpal_response = zarrinpal.create_payment(
            amount=price,
            mobile=user.phone_number,
            email=user.email
        )

        payment = Payment.objects.create(
            user=user,
            total_price=price,
            is_competition_payment=True
        )

        if zarrinpal_response['status'] == 'success':
            authority = zarrinpal_response['authority']
            payment.authority = authority
            payment.pay_link = zarrinpal_response['link']
            payment.save()

            return Response({
                "payment_url": payment.pay_link,
                "authority": authority
            }, status=status.HTTP_200_OK)
        else:
            payment.payment_state = "FAILED"
            payment.save()
            return Response({
                "detail": "Payment initiation failed.",
                "error": zarrinpal_response.get('error')
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.UserRegistrationSerializer)
    def signup(self, request):
        existing = None
        email = str(request.data.get("email", "")).strip().lower()
        if settings.EMAIL_VERIFICATION_ENABLED and email:
            existing = User.objects.filter(email__iexact=email, is_active=False).first()

        serializer = serializers.UserRegistrationSerializer(
            existing, data=request.data
        ) if existing else serializers.UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if existing and serializer.validated_data["phone_number"] != existing.phone_number:
            raise ValidationError({"email": ["This email address has already been reserved."]})
        user = serializer.save()

        response = {
            **serializer.data,
            "verification_required": settings.EMAIL_VERIFICATION_ENABLED,
            "is_first_login": user.is_first_login,
        }
        if settings.EMAIL_VERIFICATION_ENABLED:
            try:
                send_otp(user, OTPPurpose.EMAIL_VERIFICATION)
            except OTPThrottled as error:
                # A valid code was sent recently. Returning success lets the
                # client continue to the verification form on signup retry.
                response["detail"] = str(error)
                return Response(response, status=status.HTTP_200_OK)
            except Exception:
                logger.exception("Unable to send signup verification email to user %s", user.pk)
                return Response({
                    "detail": "Account created, but the verification email could not be sent. Try resending it.",
                    "verification_required": True,
                    "email": user.email,
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        else:
            response["tokens"] = serializers.tokens_for_user(user)

        return Response(
            response,
            status=status.HTTP_200_OK if existing else status.HTTP_201_CREATED,
        )

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.SendVerificationSerializer)
    def resend_activation(self, request):
        serializer = serializers.SendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not settings.EMAIL_VERIFICATION_ENABLED:
            return Response({"detail": "Email verification is disabled."})

        user = User.objects.filter(email__iexact=serializer.validated_data["email"]).first()
        if not user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.is_active:
            return Response({"detail": "This email is already verified."})

        try:
            send_otp(user, OTPPurpose.EMAIL_VERIFICATION)
        except OTPThrottled as error:
            return Response({"detail": str(error)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except Exception:
            logger.exception("Unable to resend verification email to user %s", user.pk)
            return Response({"detail": "The verification email could not be sent."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"detail": "Verification code sent to your email."})

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.SendVerificationSerializer,
            url_path="verify")
    def verify(self, request):
        """Backward-compatible alias for the old resend endpoint."""
        return self.resend_activation(request)

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.ActivateUserSerializer)
    def activate(self, request):
        serializer = serializers.ActivateUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data["email"]).first()
        if not user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if user.is_active:
            return Response({"detail": "This email is already verified."})

        try:
            validate_otp(user, serializer.validated_data["code"], OTPPurpose.EMAIL_VERIFICATION)
        except OTPError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        user.is_active = True
        user.save(update_fields=["is_active"])
        return Response({
            "detail": "Email verified successfully.",
            "tokens": serializers.tokens_for_user(user),
            "phone_number": user.phone_number,
            "is_first_login": user.is_first_login,
        })

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.PasswordResetRequestSerializer)
    def password_reset_request(self, request):
        serializer = serializers.PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=serializer.validated_data["email"], is_active=True
        ).first()
        if user:
            try:
                send_otp(user, OTPPurpose.PASSWORD_RESET)
            except OTPThrottled as error:
                return Response({"detail": str(error)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            except Exception:
                logger.exception("Unable to send password reset email to user %s", user.pk)
        return Response({
            "detail": "If an active account exists for this email, a reset code has been sent."
        })

    @action(methods=['POST'], detail=False, permission_classes=[],
            serializer_class=serializers.PasswordResetConfirmSerializer)
    def password_reset_confirm(self, request):
        serializer = serializers.PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=serializer.validated_data["email"], is_active=True
        ).first()
        if not user:
            return Response({"detail": "Invalid email or code."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_otp(user, serializer.validated_data["code"], OTPPurpose.PASSWORD_RESET)
        except OTPError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)
        return Response({"detail": "Password updated successfully."})

    @action(methods=['GET', 'POST'], detail=False, permission_classes=[IsSamePerson],
            serializer_class=serializers.OnboardingSerializer)
    def onboarding(self, request):
        if request.method == "GET":
            return Response(serializers.OnboardingSerializer(request.user).data)

        serializer = serializers.OnboardingSerializer(
            request.user, data=request.data, partial=False
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class FAQViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = FAQ.objects.all()
    serializer_class = FAQSerializer


class AccessoryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Accessory.objects.all()
    serializer_class = AccessorySerializer
