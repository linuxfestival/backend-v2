from collections import defaultdict
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny

from django.db import transaction
from rest_framework.response import Response
from django.utils import timezone
from .models import Presentation, Participation, Payment, Coupon
from .payping import PayPingRequest, PAYPING_STATUS_OK, generatePayPingLink
from .serializers import PresentationSerializer, ParticipationSerializer, PaymentSerializer


class PresentationViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['get'], )
    def all(self, request):
        presentations = Presentation.objects.all()
        serializer = PresentationSerializer(presentations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def cart(self, request):
        participations = Participation.objects.filter(user=request.user)
        serializer = ParticipationSerializer(participations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def participate(self, request):
        presentation_id = request.data.get('id')
        try:
            presentation = Presentation.objects.get(id=presentation_id)
        except Presentation.DoesNotExist:
            return Response({'detail': 'Presentation not found.'}, status=status.HTTP_404_NOT_FOUND)

        if Participation.objects.filter(user=request.user, presentation=presentation).exists():
            return Response({'detail': 'Already participating in this presentation.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if not presentation.is_registration_active:
            return Response({'detail': 'Registration is closed for this presentation.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if presentation.get_remained_capacity() <= 0:
            return Response({'detail': 'No remaining capacity for this presentation.'},
                            status=status.HTTP_400_BAD_REQUEST)

        participation = Participation.objects.create(user=request.user, presentation=presentation,
                                                     payment_state='PENDING')
        return Response(ParticipationSerializer(participation).data, status=status.HTTP_201_CREATED)


class PaymentViewSet(viewsets.ViewSet):

    @action(methods=['POST'], detail=False, permission_classes=[IsAuthenticated])
    def payment(self, request):
        data = defaultdict(lambda: None, request.data)
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
        coupon_code = data.get('coupon')

        if coupon_code:
            try:
                coupon = Coupon.objects.get(name=coupon_code)
                if coupon.count > 0:
                    discount = total_price * (coupon.percentage / 100)
                    total_price -= discount
                    coupon.count -= 1
                    coupon.save()
                else:
                    return Response(
                        {'detail': 'Coupon is out of stock.'},
                        status=status.HTTP_406_NOT_ACCEPTABLE
                    )
            except Coupon.DoesNotExist:
                return Response(
                    {'detail': 'Invalid coupon code.'},
                    status=status.HTTP_406_NOT_ACCEPTABLE
                )

        if total_price <= 0:
            participations.update(payment_state='COMPLETED')
            return Response({'detail': 'Total price is zero, automatically verified.'}, status=status.HTTP_200_OK)

        total_price = max(total_price, 0)

        # Start transaction to ensure consistency
        with transaction.atomic():
            payment = Payment.objects.create(
                total_price=total_price,
                user=user,
                coupon=coupon
            )

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
                    coupon.count += 1
                    coupon.save()
                return Response({'detail': 'Error creating payment link.'}, status=status.HTTP_400_BAD_REQUEST)

            code = response['code']
            payment.payment_link = generatePayPingLink(code)
            payment.save()

        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(methods=['POST'], detail=False, permission_classes=[AllowAny])
    def verify(self, request):
        ref_id = request.data.get('refid')
        payment_id = request.data.get('clientrefid')

        if not ref_id or not payment_id:
            return Response({'detail': 'Missing reference ID or client reference ID. Please provide valid information.'},
                            status=status.HTTP_400_BAD_REQUEST)

        payment = Payment.objects.filter(id=payment_id).first()
        if not payment:
            return Response({'detail': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)

        payping = PayPingRequest()
        verification_response = payping.verify_payment(ref_id, payment.total_price)

        if verification_response.get('status') != 200:
            if payment.coupon:
                coupon = payment.coupon
                coupon.count += 1
                coupon.save()
            payment.payment_state = 'FAILED'
            payment.original_data = verification_response
            payment.save()
            return Response({'detail': 'Payment verification failed.'}, status=status.HTTP_400_BAD_REQUEST)

        payment.payment_state = 'COMPLETED'
        payment.paymentID = ref_id
        payment.hashed_card_number = verification_response['cardHashPan']
        payment.trackID = ref_id
        payment.verified_date = timezone.now()
        payment.save()

        participations = Participation.objects.filter(user=payment.user, payment_state='PENDING')
        for participation in participations:
            participation.payment_state = 'COMPLETED'
            participation.save()

        return Response({'detail': 'Payment successfully verified.'}, status=status.HTTP_200_OK)
