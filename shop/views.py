from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404, RetrieveAPIView
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
        try:
            participation = Participation.objects.select_for_update().get(id=pk)
        except Participation.DoesNotExist:
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

        participations = Participation.objects.select_for_update().filter(user=user, payment_state="PENDING")
        if not participations.exists():
            return Response({"detail": "No pending participations found."},
                            status=status.HTTP_400_BAD_REQUEST)

        for participation in participations:
            presentation = participation.presentation

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

        total_price = sum(
            p.presentation.cost
            for p in participations
        )
        accessories = Accessory.objects.filter(id__in=accessory_ids)
        # TODO: Check for inactive accessories and return if any isn't active

        if total_price == 0:
            for accessory in accessories.all():
                user.accessories.add(accessory)
            participations.update(payment_state="COMPLETED")
            return Response(None, status=status.HTTP_204_NO_CONTENT)

        total_price += sum(accessory.price for accessory in accessories)

        coupon = None
        if coupon_code:
            coupon = Coupon.objects.select_for_update().filter(name=coupon_code, count__gt=0).first()
            if not coupon:
                return Response({"detail": "کد تخفیف نامعتبر!"},
                                status=status.HTTP_400_BAD_REQUEST)
            discount = (coupon.percentage / 100) * total_price
            total_price -= discount

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
            payment.save()

            participations.update(payment_state="PENDING")

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

    @extend_schema(request=PaymentVerifySerializer, responses={200: 'detail, ref_id, card_pan, amount'})
    @action(methods=['post'], detail=False, permission_classes=[])
    @transaction.atomic
    def verify(self, request):
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        authority = serializer.validated_data['authority']

        payment = get_object_or_404(Payment.objects.select_for_update(), authority=authority)

        if payment.payment_state == "COMPLETED":
            return Response({"detail": "Payment has already been verified."},
                            status=status.HTTP_200_OK)

        zarrinpal = ZarrinPal()
        zarrinpal_response = zarrinpal.verify_payment(
            authority=authority,
            amount=payment.total_price
        )

        if zarrinpal_response['status'] == 'success':
            payment.ref_id = zarrinpal_response['ref_id']
            payment.card_pan = zarrinpal_response['card_pan']
            payment.payment_state = "COMPLETED"
            payment.verified_date = timezone.now()
            payment.save()

            if payment.is_competition_payment:
                payment.user.is_signed_up_for_competition = True
                payment.user.save()
            else:
                payment.participations.update(payment_state="COMPLETED")
                if payment.coupon:
                    payment.coupon.count -= 1
                    payment.coupon.save()

                for accessory in payment.accessories.all():
                    payment.user.accessories.add(accessory)

            return Response({
                "detail": "Payment verified successfully.",
                "ref_id": payment.ref_id,
                "card_pan": payment.card_pan,
                "amount": payment.total_price,
            }, status=status.HTTP_200_OK)
        else:
            payment.payment_state = "FAILED"
            payment.save()

            return Response({
                "detail": "Payment verification failed.",
                "error": zarrinpal_response.get('error')
            }, status=status.HTTP_400_BAD_REQUEST)

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