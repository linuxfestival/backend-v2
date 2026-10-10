from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from colorfield.fields import ColorField
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.conf import settings
from django.utils import timezone
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


class Bundle(models.Model):
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    presentations = models.ManyToManyField(Presentation, related_name='bundles')
    tags = models.ManyToManyField(PresentationTag, related_name='bundles', blank=True)
    is_active = models.BooleanField(default=True)

    def availability(self):
        items = list(self.presentations.all())
        if not self.is_active:
            return 0, 'inactive'
        if len(items) < 2:
            return 0, 'insufficient_presentations'
        if any(item.start <= timezone.now() for item in items):
            return 0, 'started'
        if any(not item.is_registration_active for item in items):
            return 0, 'registration_closed'
        remaining = min(item.get_remained_capacity() for item in items)
        return remaining, None if remaining else 'sold_out'

    def __str__(self):
        return self.name


class BundleSelection(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bundle_selections')
    bundle = models.ForeignKey(Bundle, on_delete=models.PROTECT, related_name='selections')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'bundle'], name='unique_user_bundle')]


class Participation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='participations')
    presentation = models.ForeignKey(Presentation, on_delete=models.CASCADE, related_name='participations')
    payment_state = models.CharField(choices=PAYMENT_STATES, default="PENDING", max_length=10)
    bundle_selection = models.ForeignKey(
        BundleSelection, null=True, blank=True, on_delete=models.RESTRICT,
        related_name='participations',
    )
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
    minimum_items = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text=(
            'Minimum number of standalone presentations/workshops in the cart. Counts '
            'pending standalone presentations, including those outside the coupon scope. '
            'Accessories, bundle members, and previously purchased items do not count.'
        ),
    )
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
    bundle_snapshot = models.JSONField(default=list, blank=True)

    def is_pending_expired(self, at=None):
        """Return whether a started gateway payment needs reconciliation."""
        if self.payment_state != "PENDING" or not self.authority:
            return False
        at = at or timezone.now()
        expires_at = self.created_date + timedelta(
            seconds=settings.PAYMENT_PENDING_TTL_SECONDS,
        )
        return expires_at <= at

    def __str__(self):
        return f'Payment {self.pk} - {self.user.phone_number} - {self.total_price}'


MAX_PROPOSAL_SLIDE_SIZE = 20 * 1024 * 1024


def validate_proposal_slide_size(value):
    if value.size > MAX_PROPOSAL_SLIDE_SIZE:
        raise ValidationError('Slides must be 20 MB or smaller.')


def validate_proposal_slide_content(value):
    """Reject files whose contents do not match their allowed extension."""
    suffix = Path(value.name).suffix.lower()
    try:
        value.seek(0)
        header = value.read(8)
        if suffix == '.pdf':
            valid = header.startswith(b'%PDF-')
        elif suffix == '.ppt':
            valid = header == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
        elif suffix == '.pptx':
            value.seek(0)
            try:
                with ZipFile(value) as archive:
                    names = set(archive.namelist())
                    valid = {
                        '[Content_Types].xml',
                        'ppt/presentation.xml',
                    }.issubset(names)
            except (BadZipFile, OSError):
                valid = False
        else:
            valid = False
    finally:
        value.seek(0)

    if not valid:
        raise ValidationError('The uploaded file content does not match its extension.')


class PresentationProposal(models.Model):
    full_name = models.CharField(max_length=255)
    biography = models.TextField()
    organization = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=32)
    topic = models.CharField(max_length=255)
    abstract = models.TextField()
    slides = models.FileField(
        upload_to='presentation_proposals/',
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['pdf', 'ppt', 'pptx']),
            validate_proposal_slide_size,
            validate_proposal_slide_content,
        ],
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.full_name} - {self.topic}'
