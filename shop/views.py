from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from accounts.models import Accessory
from .models import Presentation, Participation, Payment, Coupon, Presenter
from .payments import ZarrinPal
from .serializers import PresentationSerializer, ParticipationSerializer, PayAllSerializer, PaymentVerifySerializer, \
    CartSerializer, PaymentListSerializer, CouponSerializer, PresenterSerializer


class PresentationViewSet(RetrieveAPIView, viewsets.ViewSet):
    queryset = Presentation.objects.all()
    serializer_class = PresentationSerializer

    @extend_schema(responses={200: PresentationSerializer(many=True)})
    @action(detail=False, methods=['get'], permission_classes=[AllowAny], )
    def all(self, request):
        presentations = Presentation.objects.all()
        serializer = PresentationSerializer(presentations, many=True)
        return Response(serializer.data)

    @extend_schema(responses={200: CartSerializer(many=True)})
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def cart(self, request):
        participations = Participation.objects.filter(user=request.user)
        serializer = CartSerializer(participations, many=True)
        return Response(serializer.data)

    @extend_schema(responses={201: "detail"})
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    @transaction.atomic
    def add_participation(self, request, pk=None):
        try:
            presentation = Presentation.objects.select_for_update().get(id=pk)
        except Presentation.DoesNotExist:
            return Response({'error': 'No presentation found.'}, status=status.HTTP_400_BAD_REQUEST)

        if Participation.objects.filter(user=request.user, presentation=presentation).exists():
            return Response({'detail': 'Already participating in this presentation.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if not presentation.is_registration_active:
            return Response({'detail': 'Registration is closed for this presentation.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if presentation.get_remained_capacity() < 1:
            return Response(
                {'detail': f'No remaining capacity for presentation {presentation.en_title}.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if presentation.start <= timezone.now():
            return Response(
                {'detail': f'Presentation {presentation.en_title} has already started.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        participation = Participation.objects.create(
            user=request.user,
            presentation=presentation,
            payment_state='PENDING',
        )

        return Response({"detail": "Participation created successfully."}, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: "detail"})
    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    @transaction.atomic
    def remove_participation(self, request, pk=None):
        # The route is nested under presentations, while an older frontend
        # sent the participation id. Accept both during the migration period.
        participation = Participation.objects.select_for_update().filter(
            presentation_id=pk,
            user=request.user,
        ).first()
        if participation is None:
            participation = Participation.objects.select_for_update().filter(
                id=pk,
                user=request.user,
            ).first()
        if participation is None:
            return Response({'detail': 'Participation not found or you do not have permission to remove it.'},
                            status=status.HTTP_404_NOT_FOUND)

        presentation = participation.presentation
        if presentation.start <= timezone.now():
            return Response(
                {'detail': f'Cannot remove participation; presentation {presentation.en_title} has already started.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if participation.payment_state == "COMPLETED":
            return Response(
                {'detail': f'Cannot remove participation; presentation {presentation.en_title} has already completed.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if participation.payments.filter(
            payment_state="PENDING",
            authority__isnull=False,
        ).exists():
            return Response(
                {'detail': 'Cannot remove participation while its payment is in progress.'},
                status=status.HTTP_409_CONFLICT,
            )

        participation.delete()

        return Response({'detail': 'Participation removed successfully.'}, status=status.HTTP_200_OK)


class PresenterViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Presenter.objects.all()
    serializer_class = PresenterSerializer

class PaymentViewSet(viewsets.ViewSet):
    @extend_schema(request=PayAllSerializer, responses={200: 'payment_url, authority'})
    @action(methods=['post'], detail=False, permission_classes=[IsAuthenticated])
    @transaction.atomic
    def pay_all(self, request):
        user = request.user
        serializer = PayAllSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        coupon_code = serializer.validated_data.get('coupon', None)
        accessory_ids = serializer.validated_data.get('accessories', [])

        participation_queryset = Participation.objects.select_for_update().filter(
            user=user,
            payment_state="PENDING",
        ).select_related("presentation")
        participations = list(participation_queryset)
        if not participations:
            return Response({"detail": "No pending participations found."},
                            status=status.HTTP_400_BAD_REQUEST)

        requested_accessory_ids = set(accessory_ids)
        requested_participation_ids = {item.pk for item in participations}
        # PostgreSQL does not allow SELECT DISTINCT together with FOR UPDATE.
        # Resolve distinct ids in a subquery, then lock the payment rows in the
        # outer query so concurrent checkout retries remain idempotent.
        pending_payment_ids = Payment.objects.filter(
            user=user,
            payment_state="PENDING",
            is_competition_payment=False,
            authority__isnull=False,
            participations__in=participations,
        ).values_list("pk", flat=True).distinct()
        pending_payments = list(
            Payment.objects.select_for_update()
            .filter(pk__in=pending_payment_ids)
            .prefetch_related("participations", "accessories")
            .order_by("-created_date")
        )
        for pending_payment in pending_payments:
            same_checkout = (
                {item.pk for item in pending_payment.participations.all()}
                == requested_participation_ids
                and {item.pk for item in pending_payment.accessories.all()}
                == requested_accessory_ids
                and pending_payment.coupon_id == (coupon_code or None)
            )
            if same_checkout:
                return Response({
                    "payment_url": pending_payment.pay_link,
                    "authority": pending_payment.authority,
                }, status=status.HTTP_200_OK)
        if pending_payments:
            return Response(
                {"detail": "A payment is already in progress for an item in this cart."},
                status=status.HTTP_409_CONFLICT,
            )

        presentation_ids = {item.presentation_id for item in participations}
        locked_presentations = {
            item.pk: item
            for item in Presentation.objects.select_for_update().filter(pk__in=presentation_ids)
        }

        for participation in participations:
            presentation = locked_presentations[participation.presentation_id]

            if presentation.start <= timezone.now():
                return Response(
                    {'detail': f'Presentation {presentation.en_title} has already started.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not presentation.is_registration_active:
                return Response({'detail': 'Registration is closed for this presentation.'},
                                status=status.HTTP_400_BAD_REQUEST)

            if presentation.get_remained_capacity() < 1:
                return Response(
                    {'detail': f'No remaining capacity for presentation {presentation.en_title}.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        accessories = list(Accessory.objects.filter(
            id__in=requested_accessory_ids,
            is_active=True,
        ))
        if len(accessories) != len(requested_accessory_ids):
            return Response(
                {"detail": "One or more accessories are invalid or inactive."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        presentation_total = sum(
            (participation.presentation.cost for participation in participations),
            Decimal("0"),
        )
        accessory_total = sum((accessory.price for accessory in accessories), Decimal("0"))
        total_price = presentation_total + accessory_total

        coupon = None
        if coupon_code:
            coupon = Coupon.objects.select_for_update().filter(name=coupon_code, count__gt=0).first()
            if not coupon:
                return Response({"detail": "کد تخفیف نامعتبر!"},
                                status=status.HTTP_400_BAD_REQUEST)
            discount = (Decimal(coupon.percentage) / Decimal("100")) * total_price
            total_price -= discount

        total_price = max(total_price, Decimal("0")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if total_price == 0:
            user.accessories.add(*accessories)
            participation_queryset.update(payment_state="COMPLETED")
            if coupon:
                coupon.count -= 1
                coupon.save(update_fields=["count"])
            return Response(None, status=status.HTTP_204_NO_CONTENT)

        payment = Payment.objects.create(
            user=user,
            total_price=total_price,
            coupon=coupon,
        )
        payment.participations.set(participations)
        payment.accessories.set(accessories)

        zarrinpal = ZarrinPal()
        zarrinpal_response = zarrinpal.create_payment(
            amount=total_price,
            mobile=user.phone_number,
            email=user.email
        )

        if zarrinpal_response['status'] == 'success':
            authority = zarrinpal_response['authority']
            payment.authority = authority
            payment.pay_link = zarrinpal_response['link']
            payment.save(update_fields=["authority", "pay_link"])

            return Response({
                "payment_url": payment.pay_link,
                "authority": authority
            }, status=status.HTTP_200_OK)
        else:
            payment.payment_state = "FAILED"
            payment.save(update_fields=["payment_state"])
            return Response({
                "detail": "Payment initiation failed.",
                "error": zarrinpal_response.get('error')
            }, status=status.HTTP_502_BAD_GATEWAY)

    @staticmethod
    def _verify_authority(authority):
        try:
            payment = Payment.objects.select_related("user", "coupon").get(authority=authority)
        except Payment.DoesNotExist:
            return None, {"detail": "Payment not found."}, status.HTTP_404_NOT_FOUND

        if payment.payment_state == "COMPLETED":
            return payment, {
                "status": "success",
                "detail": "Payment has already been verified.",
                "ref_id": payment.ref_id,
                "card_pan": payment.card_pan,
                "amount": payment.total_price,
            }, status.HTTP_200_OK

        zarrinpal_response = ZarrinPal().verify_payment(
            authority=authority,
            amount=payment.total_price,
        )
        if zarrinpal_response["status"] != "success":
            # A transport/configuration failure is retryable. Only persist FAILED
            # when the provider explicitly rejects the verification.
            if zarrinpal_response["status"] == "failed":
                Payment.objects.filter(pk=payment.pk).update(payment_state="FAILED")
            response_status = (
                status.HTTP_400_BAD_REQUEST
                if zarrinpal_response["status"] == "failed"
                else status.HTTP_502_BAD_GATEWAY
            )
            return payment, {
                "status": zarrinpal_response["status"],
                "detail": "Payment verification failed.",
                "error": zarrinpal_response.get("error"),
            }, response_status

        with transaction.atomic():
            # PostgreSQL cannot lock the nullable side of the outer join that
            # select_related("coupon") creates. Lock only the payment row; the
            # coupon is fetched and locked separately below when one exists.
            payment = Payment.objects.select_for_update().select_related("user").get(pk=payment.pk)
            if payment.payment_state != "COMPLETED":
                payment.ref_id = zarrinpal_response["ref_id"]
                payment.card_pan = zarrinpal_response["card_pan"]
                payment.payment_state = "COMPLETED"
                payment.verified_date = timezone.now()
                payment.save(update_fields=[
                    "ref_id", "card_pan", "payment_state", "verified_date",
                ])

                if payment.is_competition_payment:
                    payment.user.is_signed_up_for_competition = True
                    payment.user.save(update_fields=["is_signed_up_for_competition"])
                else:
                    payment.participations.update(payment_state="COMPLETED")
                    if payment.coupon_id:
                        coupon = Coupon.objects.select_for_update().get(pk=payment.coupon_id)
                        if coupon.count > 0:
                            coupon.count -= 1
                            coupon.save(update_fields=["count"])
                    payment.user.accessories.add(*payment.accessories.all())

        return payment, {
            "status": "success",
            "detail": "Payment verified successfully.",
            "ref_id": payment.ref_id,
            "card_pan": payment.card_pan,
            "amount": payment.total_price,
        }, status.HTTP_200_OK

    @extend_schema(request=PaymentVerifySerializer, responses={200: 'detail, ref_id, card_pan, amount'})
    @action(methods=['post'], detail=False, permission_classes=[])
    def verify(self, request):
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        authority = serializer.validated_data['authority']

        _payment, payload, response_status = self._verify_authority(authority)
        return Response(payload, status=response_status)

    @extend_schema(responses={302: None})
    @action(methods=['get'], detail=False, permission_classes=[], url_path='provider-callback')
    def provider_callback(self, request):
        authority = request.query_params.get("Authority")
        gateway_status = request.query_params.get("Status")
        payment = None
        response_status = status.HTTP_400_BAD_REQUEST
        if authority:
            payment, _payload, response_status = self._verify_authority(authority)

        # If the gateway reported success but our verification request had a
        # temporary transport/provider failure, preserve OK so the frontend
        # performs its own verification retry. It only displays success after
        # that API call succeeds. Explicit provider rejection remains NOK.
        retryable_verification = (
            gateway_status == "OK"
            and response_status == status.HTTP_502_BAD_GATEWAY
        )
        query = {
            "Authority": authority or "",
            "Status": "OK" if (
                response_status == status.HTTP_200_OK or retryable_verification
            ) else "NOK",
        }
        if payment and payment.ref_id:
            query["RefID"] = payment.ref_id
        separator = "&" if "?" in settings.PAYMENT_RETURN_URL else "?"
        return redirect(f"{settings.PAYMENT_RETURN_URL}{separator}{urlencode(query)}")

    @extend_schema(responses={200: PaymentListSerializer(many=True)})
    @action(methods=['get'], detail=False, permission_classes=[IsAuthenticated])
    @transaction.atomic
    def get_list(self, request):
        payments = Payment.objects.filter(user=request.user)
        serializer = PaymentListSerializer(payments, many=True)
        return Response(serializer.data)

class CouponViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CouponSerializer
    queryset = Coupon.objects.all()
