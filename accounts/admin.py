from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Staff


class UserAdmin(admin.ModelAdmin):
    ordering = ['date_joined']
    list_display = ['phone_number', 'first_name', 'last_name', 'email', 'is_staff', 'is_active']
    list_filter = ['is_staff', 'is_active', 'date_joined']
    search_fields = ['phone_number', 'first_name', 'last_name', 'email']
    filter_horizontal = ('groups', 'user_permissions')

admin.site.register(User, UserAdmin)

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    pass