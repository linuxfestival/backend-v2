from django.contrib import admin
from accounts.sms import SMS_EXECUTOR, send_sms
from shop.models import Presenter, Presentation, Participation, Coupon, Payment


admin.site.register(Presenter)
admin.site.register(Participation)
admin.site.register(Coupon)
admin.site.register(Payment)

@admin.register(Presentation)
class PresentationAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'capacity', 'get_remained_capacity', 'start')
    actions = ('send_registration_sms',)

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
                f"Dear User, this is a friendly reminder to join us for the upcoming presentation '{presentation.title}'. "
                f"We look forward to your participation! Date: {presentation.start}"
            )

            if mobiles:
                SMS_EXECUTOR.submit(send_sms, list(mobiles), message_text)
