from .models import User, Staff, FAQ, Accessory
from django.contrib import admin


class UserAdmin(admin.ModelAdmin):
    ordering = ['date_joined']
    list_display = ['phone_number', 'first_name', 'last_name', 'email', 'is_staff', 'is_active', 'participation_presentations']
    list_filter = ['is_staff', 'is_active', 'date_joined']
    search_fields = ['phone_number', 'first_name', 'last_name', 'email']
    filter_horizontal = ('groups', 'user_permissions')

    def participation_presentations(self, obj):
        thing = [p.presentation.en_title for p in obj.participations.all()]
        return f"(count: {len(thing)}) {', '.join(thing)}"

    participation_presentations.short_description = "Participations"

    @admin.action(description='Update passwords to @{user.email[:4]}Aa')
    def update_password(self, request, queryset):
        for user in queryset:
            new_password = f"@{user.email[:4]}Aa"
            user.set_password(new_password)
            user.save()

    actions = ['update_password']


admin.site.register(User, UserAdmin)
admin.site.register(FAQ)

@admin.register(Accessory)
class AccessoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'get_bought_count']

    def get_bought_count(self, obj):
        return obj.accessories.count()

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    pass