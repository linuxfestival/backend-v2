from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import Presentation, Participation, Payment, Coupon
from .payping import PayPingRequest, PAYPING_STATUS_OK, generatePayPingLink
from .serializers import PresentationSerializer, ParticipationSerializer, PayAllSerializer, PaymentVerifySerializer, \
    PaymentSerializer


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

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def participate(self, request, pk=None):
        with transaction.atomic():
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

            if presentation.get_remained_capacity() <= 0:
                return Response({'detail': 'No remaining capacity for this presentation.'},
                                status=status.HTTP_400_BAD_REQUEST)

            participation = Participation.objects.create(
                user=request.user,
                presentation=presentation,
                payment_state='PENDING'
            )

            return Response(ParticipationSerializer(participation).data, status=status.HTTP_201_CREATED)


class PaymentViewSet(viewsets.ViewSet):
    serializer_class = PayAllSerializer

    @action(methods=['post'], detail=False, permission_classes=[IsAuthenticated], serializer_class=PayAllSerializer)
    def pay_all(self, request):
        serializer = PayAllSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        participations = Participation.objects.filter(user=user, payment_state='PENDING')

        if not participations.exists():
            return Response({'detail': 'No pending participations found.'}, status=status.HTTP_400_BAD_REQUEST)

        total_price = 0
        for participation in participations:
            presentation = participation.presentation
            if presentation.get_remained_capacity() <= 0:
                return Response(
                    {'detail': f'Presentation "{presentation.title}" is full. Please remove it to proceed.'},
                    status=status.HTTP_406_NOT_ACCEPTABLE
                )

            if not presentation.is_registration_active:
                return Response(
                    {'detail': f'Registration for "{presentation.title}" is closed. Please remove it to proceed.'},
                    status=status.HTTP_406_NOT_ACCEPTABLE
                )

            total_price += presentation.cost

        coupon = None
        coupon_code = serializer.validated_data.get('coupon')
        if coupon_code:
            coupon = Coupon.objects.filter(name=coupon_code).first()
            if not coupon:
                return Response({'detail': 'Invalid coupon code.'}, status=status.HTTP_406_NOT_ACCEPTABLE)

            if coupon.count <= 0:
                return Response({'detail': 'Coupon is out of stock.'}, status=status.HTTP_406_NOT_ACCEPTABLE)

            discount = total_price * (coupon.percentage / 100)
            total_price -= discount
            coupon.count -= 1
            coupon.save()

        if total_price <= 0:
            participations.update(payment_state='COMPLETED')
            return Response({'detail': 'Total price is zero, automatically verified.'}, status=status.HTTP_200_OK)

        with transaction.atomic():
            payment = Payment.objects.create(
                total_price=total_price,
                user=user,
                coupon=coupon,
            )
            for participation in participations:
                payment.participations.add(participation)
            payment.save()

            payping = PayPingRequest()
            response = payping.create_payment(
                order_id=payment.pk,
                amount=total_price,
                name=user.get_full_name(),
                phone=user.phone_number,
                email=user.email,
            )

            if response.get('status') != PAYPING_STATUS_OK:
                payment.delete()
                if coupon:
                    Coupon.objects.filter(id=coupon.id).update(count=F('count') + 1)
                return Response({'error': 'Error creating payment link.'}, status=status.HTTP_400_BAD_REQUEST)

            payment.payment_link = generatePayPingLink(response['code'])
            payment.save()

        return Response({PaymentSerializer(payment).data}, status=status.HTTP_201_CREATED)

    @action(methods=['post'], detail=False, permission_classes=[AllowAny], serializer_class=PaymentVerifySerializer)
    def verify(self, request):
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ref_id = serializer.validated_data['refid']
        payment_id = serializer.validated_data['clientrefid']

        with transaction.atomic():
            try:
                payment = Payment.objects.select_for_update().get(id=payment_id)
            except Payment.DoesNotExist:
                return Response({'error': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)

            payping = PayPingRequest()
            verification_response = payping.verify_payment(ref_id, payment.total_price)

            if verification_response.get('status') != 200:
                if payment.coupon:
                    Coupon.objects.filter(id=payment.coupon.id).update(count=F('count') + 1)
                payment.payment_state = 'FAILED'
                payment.original_data = verification_response
                payment.save()
                return Response({'detail': 'Payment verification failed.'}, status=status.HTTP_400_BAD_REQUEST)

            payment.payment_state = 'COMPLETED'
            payment.paymentID = ref_id
            payment.hashed_card_number = verification_response.get('cardHashPan', 'Unknown')
            payment.trackID = ref_id
            payment.verified_date = timezone.now()
            payment.participations.update(payment_state='COMPLETED')
            payment.save()

            return Response({'detail': 'Payment successfully verified.'}, status=status.HTTP_200_OK)
