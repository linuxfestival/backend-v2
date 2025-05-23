"""
Django settings for backend project.

Generated by 'django-admin startproject' using Django 5.0.7.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.0/ref/settings/
"""
from datetime import timedelta
from pathlib import Path

import os
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("SECRET_KEY", default="key34572dfg57ll90xdvs234ghh$")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", default="False") == "True"

# Custom
AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = 'accounts:token'

STATIC_ROOT = BASE_DIR / 'static'
STATIC_URL = '/static/'

MEDIA_ROOT = BASE_DIR / 'media'
MEDIA_URL = 'media/'

ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = ['https://localhost', 'https://127.0.0.1']
CORS_ORIGIN_ALLOW_ALL = True
USE_X_FORWARDED_HOST = True

SMS_KEY = os.getenv("SMS_KEY", default="key")
SMS_LINE_NUMBER = os.getenv("SMS_LINE_NUMBER", default="300")

PAYMENT_API_KEY = os.getenv("PAYMENT_API_KEY", default="auth")
PAYMENT_CALLBACK_URL = os.getenv("PAYMENT_CALLBACK_URL", default="callback")

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PARSER_CLASSES': (
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DATETIME_FORMAT': "%Y-%m-%dT%H:%M:%S.%f%z",
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'UPDATE_LAST_LOGIN': True,
}

# Application definition

INSTALLED_APPS = [
    # Custom
    'accounts',
    'shop',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'drf_spectacular_sidecar',
    'corsheaders',
    'tinymce',
    'colorfield',

    # Default: required for admin site
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

SPECTACULAR_SETTINGS = {
    'TITLE': 'Your Project API',
    'DESCRIPTION': 'Your project description',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
}

MIDDLEWARE = [
    # Custom
    'corsheaders.middleware.CorsMiddleware',

    # Default
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME', 'test'),
        'USER': os.getenv('DB_USER', 'asdf'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'asdf'),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '3306'),
    },
}

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates']
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'

# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Tehran'

USE_I18N = True

USE_TZ = True

LIARA_ENDPOINT = os.getenv("BUCKET_ENDPOINT", default="BUCKET_ENDPOINT_DEFAULT")
LIARA_BUCKET_NAME = os.getenv("BUCKET_NAME", default="BUCKET_NAME_DEFAULT")
LIARA_ACCESS_KEY = os.getenv("BUCKET_ACCESS_KEY", default="BUCKET_ACCESS_KEY_DEFAULT")
LIARA_SECRET_KEY = os.getenv("BUCKET_SECRET_KEY", default="BUCKET_SECRET_KEY_DEFAULT")

# S3 Settings Based on AWS (optional)
AWS_ACCESS_KEY_ID = LIARA_ACCESS_KEY
AWS_SECRET_ACCESS_KEY = LIARA_SECRET_KEY
AWS_STORAGE_BUCKET_NAME = LIARA_BUCKET_NAME
AWS_S3_ENDPOINT_URL = LIARA_ENDPOINT
AWS_S3_REGION_NAME = 'us-east-1'
# Django-storages configuration
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

AWS_QUERYSTRING_AUTH = False

TINYMCE_DEFAULT_CONFIG = {
    "height": 500,
    "menubar": "edit view insert format tools table",
    "plugins": "textcolor colorpicker",
    "toolbar": "undo redo | bold italic underline | forecolor backcolor | alignleft aligncenter alignright alignjustify",
    "skin": "oxide-dark",
    "content_css": "dark",
}
