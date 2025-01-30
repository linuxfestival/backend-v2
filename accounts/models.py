from django.core.validators import RegexValidator
from django.utils import timezone
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin, AbstractUser

from django.db import models
from rest_framework.exceptions import ValidationError


def validate_avatar(value):
    if value and value.size > 2000000:
        raise ValidationError("Avatar image must be up to 2MB.")
    return value


class PhoneValidator(RegexValidator):
    regex = r'^(\+98|0)?9\d{9}$'
    message = "Phone number must be entered in the format: '+98----------' or '09---------'."


class UserManager(BaseUserManager):
    def create_user(self, phone_number, password, first_name, last_name, email, **other_fields):
        if not email:
            raise ValueError('You must provide an email address.')

        if not phone_number:
            raise ValueError('You must provide a phone number.')

        if not first_name:
            raise ValueError('You must provide a first name.')

        if not last_name:
            raise ValueError('You must provide a last name.')

        email = self.normalize_email(email)
        user = self.model(email=email, first_name=first_name, last_name=last_name,
                          phone_number=phone_number, **other_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, phone_number, password, first_name, last_name, email, **other_fields):
        other_fields.setdefault('is_staff', True)
        other_fields.setdefault('is_superuser', True)
        other_fields.setdefault('is_active', True)

        if other_fields.get('is_staff') is not True:
            raise ValueError('Superuser must be assigned to is_staff=True.')

        if other_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must be assigned to is_superuser=True.')

        return self.create_user(phone_number, password, first_name, last_name, email, **other_fields)


class User(AbstractBaseUser, PermissionsMixin):
    phone_number = models.CharField(validators=[PhoneValidator()],
                                    max_length=32, blank=False, null=False, unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)

    date_joined = models.DateTimeField(default=timezone.now)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    avatar = models.ImageField(blank=True, null=True)
    activation_code = models.CharField(max_length=64, blank=True, null=True)
    last_login = models.DateTimeField(blank=True, null=True)

    objects = UserManager()
    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'email']

    def get_full_name(self):
        return self.first_name + ' ' + self.last_name

    def generate_activation_code(self):
        self.activation_code = str(uuid.uuid4().int)[:6]
        self.save()

    def __str__(self):
        return self.phone_number

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        super(User, self).save(*args, **kwargs)