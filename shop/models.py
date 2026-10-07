from colorfield.fields import ColorField
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from tinymce.models import HTMLField

from accounts.models import Accessory

PAYMENT_STATES = [
    ('COMPLETED', 'COMPLETED'),
    ('PENDING', 'PENDING'),
    ('FAILED', 'FAILED')
]

SERVICE_TYPE = [
    ('WORKSHOP', 'WORKSHOP'),
    ('TALK', 'TALK'),
    ('PACKAGE', 'PACKAGE'),
]


class Presenter(models.Model):
    first_name = models.CharField(max_length=30, blank=False)
    last_name = models.CharField(max_length=30, blank=False)

    email = models.EmailField(blank=True, null=True)
    description = HTMLField()
    avatar = models.ImageField(null=True, blank=True)

    linkedin = models.URLField(blank=True)

    class Meta:
        unique_together = ('first_name', 'last_name')

    def __str__(self):
        return f'{self.last_name} {self.first_name}'

class PresentationTag(models.Model):
    en_name = models.CharField(max_length=63)
    fa_name = models.CharField(max_length=63)
    color = ColorField(default="#FA175C")

    def __str__(self):
        return f"{self.fa_name} / {self.en_name}"


class Presentation(models.Model):
    presenters = models.ManyToManyField(Presenter, related_name='presentations')
    service_type = models.CharField(choices=SERVICE_TYPE, blank=False, max_length=30)

    en_title = models.CharField(max_length=100)
    fa_title = models.CharField(max_length=100)
    start = models.DateTimeField(blank=False)
    end = models.DateTimeField(blank=False)

    en_description = HTMLField()
    fa_description = HTMLField()
    capacity = models.PositiveIntegerField(blank=False)
    is_registration_active = models.BooleanField(default=True)
    presentation_link = models.URLField(blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, blank=False)

    morkopoloyor = models.URLField(blank=True)

    tags = models.ManyToManyField(PresentationTag, "presentation_tag", blank=True)


    def clean(self):
        if self.cost < 0:
            raise ValidationError("Cost cannot be negative.")
        if self.start >= self.end:
            raise ValidationError("End time must be after start time.")

    def get_remained_capacity(self):
        # A started gateway payment reserves its seat until it is completed or
        # explicitly fails. This prevents two users from paying for the final
        # seat at the same time.
        committed = Participation.objects.filter(
            presentation=self,
            is_capacity_exempt=False,
        ).filter(
            models.Q(payment_state="COMPLETED")
            | models.Q(
                payment_state="PENDING",
                payments__payment_state="PENDING",
                payments__authority__isnull=False,
            )
        ).distinct().count()
        return max(self.capacity - committed, 0)


    def participations(self):
        return Participation.objects.filter(presentation=self)

    def __str__(self):
        return self.en_title


class Participation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='participations')
    presentation = models.ForeignKey(Presentation, on_delete=models.CASCADE, related_name='participations')
    payment_state = models.CharField(choices=PAYMENT_STATES, default="PENDING", max_length=10)
    is_capacity_exempt = models.BooleanField(
        default=False,
        help_text="Completed registrations with this flag do not reduce remaining capacity.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "presentation"],
                name="unique_user_presentation",
            ),
        ]

    def __str__(self):
        return f'{self.user.phone_number} - {self.presentation.en_title}'


class Coupon(models.Model):
    name = models.CharField(max_length=50, primary_key=True, help_text="Don't use / in the name.")
    count = models.PositiveIntegerField()
    percentage = models.IntegerField(default=0.0, help_text='Enter a number between 0 to 100.')
    eligible_presentations = models.ManyToManyField(
        Presentation,
        blank=True,
        related_name="coupons",
        help_text="Leave empty to apply this coupon to the whole cart.",
    )
    preserve_capacity = models.BooleanField(
        default=False,
        help_text=(
            "When enabled, registrations discounted by this coupon do not reduce "
            "the selected presentations' remaining capacity."
        ),
    )

    def __str__(self):
        return self.name

    def clean(self):
        if self.percentage < 0 or self.percentage > 100:
            raise ValidationError("Enter a number between 0 to 100.")
        if self.count < 0:
            raise ValidationError("Coupon count cannot be negative.")

    def is_valid(self):
        return self.count > 0


class Payment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payments')
    total_price = models.DecimalField(max_digits=12, decimal_places=2, blank=False)
    participations = models.ManyToManyField(Participation, related_name='payments')
    payment_state = models.CharField(choices=PAYMENT_STATES, default="PENDING", max_length=10)

    authority = models.CharField(null=True, unique=True, max_length=100)
    pay_link = models.URLField(null=True)
    ref_id = models.CharField(null=True, max_length=100)
    card_pan = models.TextField(null=True)

    created_date = models.DateTimeField(auto_now_add=True)
    verified_date = models.DateTimeField(null=True, blank=True)
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, default=None, null=True, blank=True)
    coupon_participations = models.ManyToManyField(
        Participation,
        blank=True,
        related_name="coupon_payments",
        help_text="Snapshot of participations to which this payment's coupon applied.",
    )
    coupon_preserves_capacity = models.BooleanField(
        default=False,
        help_text="Snapshot of the coupon's capacity behavior when checkout started.",
    )
    accessories = models.ManyToManyField(Accessory, "payment_accessories")
    is_competition_payment = models.BooleanField(default=False)

    def __str__(self):
        return f'Payment {self.pk} - {self.user.phone_number} - {self.total_price}'
