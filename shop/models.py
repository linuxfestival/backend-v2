from django.db import models
from django.conf import settings
from rest_framework.exceptions import ValidationError

from accounts.models import Accessory

PAYMENT_STATES = [
    ('COMPLETED', 'COMPLETED'),
    ('PENDING', 'PENDING'),
    ('FAILED', 'FAILED')
]

SERVICE_TYPE = [
    ('WORKSHOP', 'WORKSHOP'),
    ('TALK', 'TALK'),
]


class Presenter(models.Model):
    first_name = models.CharField(max_length=30, blank=False)
    last_name = models.CharField(max_length=30, blank=False)

    email = models.EmailField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    avatar = models.ImageField(null=True, blank=True)

    class Meta:
        unique_together = ('first_name', 'last_name')

    def __str__(self):
        return f'{self.last_name} {self.first_name}'


class Presentation(models.Model):
    presenters = models.ManyToManyField(Presenter, related_name='presentations')
    service_type = models.CharField(choices=SERVICE_TYPE, blank=False, max_length=30)

    title = models.CharField(max_length=100)
    start = models.DateTimeField(blank=False)
    end = models.DateTimeField(blank=False)

    description = models.TextField(blank=False)
    capacity = models.IntegerField(blank=False)
    is_registration_active = models.BooleanField(default=True)
    presentation_link = models.URLField(blank=True)
    cost = models.FloatField(blank=False)


    def clean(self):
        if self.cost < 0:
            raise ValidationError("Cost cannot be negative.")
        if self.start >= self.end:
            raise ValidationError("End time must be after start time.")

    def get_remained_capacity(self):
        return self.capacity - Participation.objects.filter(presentation=self, payment_state="COMPLETED").count()


    def participations(self):
        return Participation.objects.filter(presentation=self)

    def __str__(self):
        return self.title


class Participation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='participations')
    presentation = models.ForeignKey(Presentation, on_delete=models.CASCADE, related_name='participations')
    payment_state = models.CharField(choices=PAYMENT_STATES, default="PENDING", max_length=10)

    def __str__(self):
        return f'{self.user.phone_number} - {self.presentation.title}'


class Coupon(models.Model):
    name = models.CharField(max_length=50, primary_key=True, help_text="Don't use / in the name.")
    count = models.PositiveIntegerField()
    percentage = models.IntegerField(default=0.0, help_text='Enter a number between 0 to 100.')

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
    total_price = models.FloatField(blank=False)
    participations = models.ManyToManyField(Participation, related_name='payments')
    payment_state = models.CharField(choices=PAYMENT_STATES, default="PENDING", max_length=10)

    authority = models.CharField(null=True, max_length=100)
    pay_link = models.URLField(null=True)
    ref_id = models.CharField(null=True, max_length=100)
    card_pan = models.TextField(null=True)

    created_date = models.DateTimeField(auto_now_add=True)
    verified_date = models.DateTimeField(null=True, blank=True)
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, default=None, null=True, blank=True)
    accessories = models.ManyToManyField(Accessory, "payment_accessories")

    def __str__(self):
        return f'Payment {self.pk} - {self.user.phone_number} - {self.total_price}'
