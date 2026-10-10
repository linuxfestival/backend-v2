from decimal import Decimal

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from .models import Bundle, BundleSelection, Participation, Payment, Presentation
from .serializers import PresentationSerializer, PresentationTagSerializer


class BundleSerializer(serializers.ModelSerializer):
    presentations = PresentationSerializer(many=True, read_only=True)
    tags = PresentationTagSerializer(many=True, read_only=True)
    original_price = serializers.SerializerMethodField()
    remaining_capacity = serializers.SerializerMethodField()
    is_available = serializers.SerializerMethodField()
    unavailable_reason = serializers.SerializerMethodField()

    class Meta:
        model = Bundle
        fields = ['id', 'name', 'description', 'price', 'original_price', 'tags',
                  'presentations', 'is_active', 'remaining_capacity', 'is_available', 'unavailable_reason']

    def get_original_price(self, obj) -> str:
        return str(sum((item.cost for item in obj.presentations.all()), Decimal('0')))

    def _availability(self, obj):
        if not hasattr(self, '_availability_cache'):
            self._availability_cache = {}
        if obj.pk not in self._availability_cache:
            self._availability_cache[obj.pk] = obj.availability()
        return self._availability_cache[obj.pk]

    def get_remaining_capacity(self, obj) -> int:
        return self._availability(obj)[0]

    def get_is_available(self, obj) -> bool:
        return self._availability(obj)[1] is None

    def get_unavailable_reason(self, obj) -> str | None:
        return self._availability(obj)[1]


class BundleCartSerializer(serializers.ModelSerializer):
    bundle = BundleSerializer(read_only=True)
    participation_ids = serializers.SerializerMethodField()

    class Meta:
        model = BundleSelection
        fields = ['id', 'bundle', 'participation_ids']

    def get_participation_ids(self, obj) -> list[int]:
        return list(obj.participations.values_list('pk', flat=True))


class BundleViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Bundle.objects.prefetch_related('presentations__presenters', 'presentations__tags', 'tags').order_by('pk')
    serializer_class = BundleSerializer
    permission_classes = [AllowAny]

    @extend_schema(responses={200: BundleCartSerializer(many=True)})
    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def cart(self, request):
        selections = BundleSelection.objects.filter(
            user=request.user, participations__payment_state='PENDING',
        ).distinct().select_related('bundle').prefetch_related('participations')
        return Response(BundleCartSerializer(selections, many=True).data)

    @extend_schema(request=None, responses={201: BundleCartSerializer})
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    @transaction.atomic
    def add_to_cart(self, request, pk=None):
        User.objects.select_for_update().get(pk=request.user.pk)
        bundle = Bundle.objects.select_for_update().get(pk=self.get_object().pk)
        if BundleSelection.objects.filter(user=request.user, bundle=bundle).exists():
            return Response({'detail': 'This bundle is already in your cart or purchased.',
                             'code': 'bundle_overlap'}, status=409)
        # All cart mutations and checkout serialize on the user row. Lock
        # presentation rows in the same order as checkout for seat availability.
        ids = list(bundle.presentations.values_list('pk', flat=True))
        list(Presentation.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
        remaining, reason = bundle.availability()
        if reason:
            return Response({'detail': 'Bundle is unavailable.', 'code': reason}, status=400)
        existing = list(Participation.objects.select_for_update().filter(
            user=request.user, presentation_id__in=ids,
        ))
        purchased = [item.presentation_id for item in existing if item.payment_state == 'COMPLETED']
        if purchased:
            return Response({'detail': 'You already purchased an included presentation.',
                             'code': 'already_purchased', 'presentation_ids': purchased}, status=409)
        if any(item.bundle_selection_id for item in existing):
            return Response({'detail': 'This bundle overlaps a bundle already in your cart.',
                             'code': 'bundle_overlap'}, status=409)
        if Payment.objects.filter(
            participations__in=existing, payment_state='PENDING', authority__isnull=False,
        ).exists():
            return Response({'detail': 'Payment is in progress for an included item.',
                             'code': 'active_payment'}, status=409)
        selection = BundleSelection.objects.create(user=request.user, bundle=bundle)
        existing_ids = {item.presentation_id for item in existing}
        Participation.objects.filter(pk__in=[item.pk for item in existing]).update(
            bundle_selection=selection, payment_state='PENDING', is_capacity_exempt=False,
        )
        Participation.objects.bulk_create([
            Participation(user=request.user, presentation_id=item_id, bundle_selection=selection)
            for item_id in ids if item_id not in existing_ids
        ])
        return Response(BundleCartSerializer(selection).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None})
    @action(detail=True, methods=['delete'], permission_classes=[IsAuthenticated])
    def remove_from_cart(self, request, pk=None):
        selection = BundleSelection.objects.filter(user=request.user, bundle_id=pk).first()
        if selection is None:
            return Response({'detail': 'Bundle not found in your cart.'}, status=404)
        if selection.participations.filter(payment_state='COMPLETED').exists():
            return Response({'detail': 'A purchased bundle cannot be removed.'}, status=409)
        payments = Payment.objects.filter(
            participations__bundle_selection=selection, payment_state='PENDING',
            authority__isnull=False,
        ).distinct().order_by('created_date')
        # Match individual cart removal: reconcile expired provider payments
        # before releasing seats, never discard an unverified successful payment.
        from .views import PaymentViewSet
        for payment in payments:
            if not payment.is_pending_expired():
                return Response({'detail': 'Payment is still in progress.', 'code': 'active_payment'}, status=409)
            _, _, response_status = PaymentViewSet._verify_authority(payment.authority)
            if response_status == status.HTTP_200_OK:
                return Response({'detail': 'Payment confirmed; bundle cannot be removed.'}, status=409)
            if response_status == status.HTTP_502_BAD_GATEWAY:
                return Response({'detail': 'Payment provider unavailable. Try again shortly.'}, status=503)
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            selection = BundleSelection.objects.filter(pk=selection.pk, user=request.user).first()
            if selection is None:
                return Response(status=204)
            items = list(selection.participations.select_for_update())
            if any(item.payment_state == 'COMPLETED' for item in items) or Payment.objects.filter(
                participations__in=items, payment_state='PENDING', authority__isnull=False,
            ).exists():
                return Response({'detail': 'A payment is in progress or completed.'}, status=409)
            selection.participations.all().delete()
            selection.delete()
        return Response(status=204)
