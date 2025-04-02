from django.contrib import admin
from django.http import JsonResponse
from django.template.defaultfilters import title

from accounts.sms import SMS_EXECUTOR, send_sms
from shop.models import Presenter, Presentation, Participation, Coupon, Payment, PresentationTag

admin.site.register(Presenter)
admin.site.register(Participation)
admin.site.register(Payment)
admin.site.register(PresentationTag)

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('name', 'used')

    def used(self, obj):
        return Payment.objects.filter(payment_state="COMPLETED",coupon=obj).count()

@admin.register(Presentation)
class PresentationAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'capacity', 'get_remained_capacity', 'start')
    actions = ('send_registration_sms', 'export_registrations')

    class Meta:
        model = Presentation
        fields = '__all__'

    @admin.action(description='Send registration sms')
    def send_registration_sms(self, request, obj):
        for presentation in obj:
            mobiles = {
                str(participation.user.phone_number)
                for participation in Participation.objects.filter(
                    payment_state="COMPLETED",
                )
            }

            message_text = (
                f"Dear User, this is a friendly reminder to join us for the upcoming presentation '{presentation.en_title}'. "
                f"We look forward to your participation! Date: {presentation.start}"
            )

            if mobiles:
                SMS_EXECUTOR.submit(send_sms, list(mobiles), message_text)


    @admin.action(description='Export registrations')
    def export_registrations(self, request, queryset):
        data = {}

        for presentation in queryset:
            data[presentation.en_title] = {}
            for participation in Participation.objects.filter(payment_state="COMPLETED"):
                user = participation.user
                data[presentation.en_title][user.phone_number] = {
                    'name': user.first_name + " " + user.last_name,
                    'email': user.email,
                }

        return JsonResponse(data)

