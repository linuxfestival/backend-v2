from functools import wraps

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from .models import Payment, CouponRedemption


def record_coupon_redemption(coupon, user, participations, payment=None):
    items = list(participations)
    data = {
        'coupon': coupon, 'coupon_code': coupon.pk, 'user': user,
        'snapshot': {
            'percentage': payment.checkout_snapshot.get('coupon_percentage', coupon.percentage) if payment else coupon.percentage,
            'preserve_capacity': payment.coupon_preserves_capacity if payment else coupon.preserve_capacity,
            'discounted_presentations': [
                {'id': item.presentation_id, 'name': item.presentation.en_title} for item in items
            ],
        },
    }
    if payment:
        redemption, created = CouponRedemption.objects.get_or_create(payment=payment, defaults=data)
    else:
        redemption = CouponRedemption.objects.create(**data)
        created = True
    if created:
        redemption.participations.set(items)
    return redemption


def atomic_cart_change(view):
    """Serialize edits/checkout/settlement and roll back unsuccessful changes."""
    @wraps(view)
    def wrapped(self, request, *args, **kwargs):
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            response = view(self, request, *args, **kwargs)
            if response.status_code >= 400:
                transaction.set_rollback(True)
            return response
    return wrapped


def snapshot_payment(payment):
    return {
        'amount': str(payment.total_price),
        'coupon': payment.coupon_id,
        'coupon_percentage': payment.coupon.percentage if payment.coupon_id else None,
        'bundles': payment.bundle_snapshot,
        'presentations': [
            {'id': item.presentation_id, 'name': item.presentation.en_title,
             'participation_id': item.pk, 'cost': str(item.presentation.cost)}
            for item in payment.participations.select_related('presentation').order_by('pk')
        ],
        'accessories': [
            {'id': item.pk, 'name': item.name, 'price': str(item.price)}
            for item in payment.accessories.order_by('pk')
        ],
    }


def supersede_pending_payments(user, reason):
    """Caller must hold the user lock; keep authorities for later reconciliation."""
    for payment in Payment.objects.select_for_update().filter(
        user=user, payment_state__in=['PENDING', 'FAILED'], is_competition_payment=False,
        authority__isnull=False, superseded_at__isnull=True,
    ).order_by('pk'):
        if not payment.checkout_snapshot:
            payment.checkout_snapshot = snapshot_payment(payment)
        payment.superseded_at = timezone.now()
        payment.superseded_reason = reason
        payment.save(update_fields=['superseded_at', 'superseded_reason', 'checkout_snapshot'])
