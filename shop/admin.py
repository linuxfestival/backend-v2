import asyncio

from django.contrib import admin
from django.http import JsonResponse
import time
from accounts.sms import send_sms
from shop.models import Presenter, Presentation, Participation, Coupon, Payment, PresentationTag

admin.site.register(Presenter)
admin.site.register(PresentationTag)

def chunk_list(lst, chunk_size):
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    search_fields = ['user__phone_number']

@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    search_fields = ['user__phone_number']
    list_display = ['__str__','payment_state', 'presentation__cost']


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('name', 'used')

    def used(self, obj):
        return Payment.objects.filter(payment_state="COMPLETED", coupon=obj).count()


@admin.register(Presentation)
class PresentationAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'capacity', 'get_remained_capacity', 'get_presenters')
    actions = ('send_registration_sms', 'export_registrations')

    class Meta:
        model = Presentation
        fields = '__all__'

    def get_presenters(self, obj):
        return ", ".join([str(presenter) for presenter in obj.presenters.all()])

    get_presenters.short_description = 'Presenters'

    @admin.action(description='Send registration sms')
    def send_registration_sms(self, request, obj):
        for presentation in obj:
            mobiles = {
                str(participation.user.phone_number)
                for participation in Participation.objects.filter(
                    payment_state="COMPLETED", presentation=presentation
                )
            }

            message_text = (
                f"""سلام دوست عزیز! 😊 یه یادآوری دوستانه برات داریم برای شرکت در جلسه ارائه {presentation.en_title}. "
                تاریخ:{presentation.start}
                Linux Fest 🐧✨"""
            )

            if mobiles:
                mobiles_list = list(mobiles)
                for chunk in chunk_list(mobiles_list, 90):
                    asyncio.run(send_sms(chunk, str(message_text)))
                    time.sleep(10)

            return JsonResponse({"message": "SMS tried, check logs."})

    @admin.action(description='Export registrations')
    def export_registrations(self, request, queryset):
        data = {}

        for presentation in queryset:
            data[presentation.en_title] = {}
            for participation in Participation.objects.filter(payment_state="COMPLETED", presentation=presentation):
                user = participation.user
                data[presentation.en_title][user.phone_number] = {
                    'name': user.first_name + " " + user.last_name,
                    'email': user.email,
                }

        return JsonResponse(data)
