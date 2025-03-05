from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Presentation, Participation, Payment, Coupon
from .payments import ZarrinPal
from .serializers import PresentationSerializer, ParticipationSerializer, PayAllSerializer, PaymentVerifySerializer


class PresentationViewSet(viewsets.ViewSet):
    serializer_class = PresentationSerializer

    @action(detail=False, methods=['get'], serializer_class=PresentationSerializer)
    def all(self, request):
        presentations = Presentation.objects.all()
        serializer = PresentationSerializer(presentations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated],
            serializer_class=ParticipationSerializer)
    def cart(self, request):
        participations = Participation.objects.filter(user=request.user)
        serializer = ParticipationSerializer(participations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    @transaction.atomic
    def participate(self, request):
        try:
            serializer = ParticipationSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            presentation_id = serializer.data['presentation_id']
            has_accessories = serializer.data['has_accessories']

            presentation = Presentation.objects.select_for_update().get(id=presentation_id)
        except Presentation.DoesNotExist:
            return Response({'error': 'No presentation found.'}, status=status.HTTP_400_BAD_REQUEST)

        if Participation.objects.filter(user=request.user, presentation=presentation).exists():
            return Response({'detail': 'Already participating in this presentation.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if not presentation.is_registration_active:
            return Response({'detail': 'Registration is closed for this presentation.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if presentation.get_remained_capacity() <= 0:
            return Response({'detail': 'No remaining capacity for this presentation.'},
                            status=status.HTTP_400_BAD_REQUEST)

        participation = Participation.objects.create(
            user=request.user,
            presentation=presentation,
            payment_state='PENDING',
            has_accessories=has_accessories,
        )

        return Response(ParticipationSerializer(participation).data, status=status.HTTP_201_CREATED)


class PaymentViewSet(viewsets.ViewSet):
    @action(methods=['post'], detail=False, permission_classes=[IsAuthenticated], serializer_class=PayAllSerializer)
    @transaction.atomic
    def pay_all(self, request):
        user = request.user
        serializer = PayAllSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        coupon_code = serializer.validated_data.get('coupon', None)

        participations = Participation.objects.select_for_update().filter(user=user, payment_state="PENDING")
        if not participations.exists():
            return Response({"detail": "No pending participations found."},
                            status=status.HTTP_400_BAD_REQUEST)

        total_price = sum(
            p.presentation.cost + (p.presentation.accessories_cost if p.has_accessories else 0)
            for p in participations
        )

        coupon = None
        if coupon_code:
            coupon = Coupon.objects.select_for_update().filter(name=coupon_code, count__gt=0).first()
            if not coupon:
                return Response({"detail": "Invalid or expired coupon code."},
                                status=status.HTTP_400_BAD_REQUEST)
            discount = (coupon.percentage / 100) * total_price
            total_price -= discount

        payment = Payment.objects.create(
            user=user,
            total_price=total_price,
            coupon=coupon,
        )
        payment.participations = participations

        zarrinpal = ZarrinPal()
        zarrinpal_response = zarrinpal.create_payment(
            amount=total_price,
            mobile=user.phone_number,
            email=user.email
        )

        if zarrinpal_response['status'] == 'success':
            authority = zarrinpal_response['authority']
            payment.authority = authority

            pay_link = zarrinpal.generate_response(authority)
            payment.pay_link = pay_link
            payment.save()

            participations.update(payment_state="PENDING")
            if coupon:
                coupon.count -= 1
                coupon.save()

            return Response({
                "payment_url": pay_link,
                "authority": authority
            }, status=status.HTTP_200_OK)
        else:
            payment.payment_state = "FAILED"
            payment.save()
            return Response({
                "detail": "Payment initiation failed.",
                "error": zarrinpal_response.get('error')
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    @action(methods=['post'], detail=False, permission_classes=[IsAuthenticated],
            serializer_class=PaymentVerifySerializer)
    @transaction.atomic
    def verify(self, request):
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        authority = serializer.validated_data['authority']

        payment = get_object_or_404(Payment.objects.select_for_update(), authority=authority, user=request.user)

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

            payment.participations.update(payment_state="COMPLETED")

            return Response({
                "detail": "Payment verified successfully.",
                "ref_id": payment.ref_id,
                "card_pan": payment.card_pan,
                "amount": payment.total_price,
            }, status=status.HTTP_200_OK)
        else:
            payment.payment_state = "FAILED"
            payment.save()

            payment.participations.update(payment_state="PENDING")

            return Response({
                "detail": "Payment verification failed.",
                "error": zarrinpal_response.get('error')
            }, status=status.HTTP_400_BAD_REQUEST)