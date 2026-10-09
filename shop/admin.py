from pathlib import Path

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.http import FileResponse, Http404, JsonResponse
from django.template.defaultfilters import title
from django.urls import path, reverse
from django.utils.html import format_html

from accounts.sms import SMS_EXECUTOR, send_sms
from shop.models import (
    Presenter,
    Presentation,
    Participation,
    Coupon,
    Payment,
    PresentationTag,
    PresentationProposal,
)

admin.site.register(Presenter)


@admin.register(PresentationTag)
class PresentationTagAdmin(admin.ModelAdmin):
    list_display = ('en_name', 'fa_name', 'color')
    search_fields = ('en_name', 'fa_name')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    change_list_template = 'admin/shop/payment/change_list.html'
    list_display = (
        'id',
        'user',
        'total_price',
        'payment_state',
        'ref_id',
        'created_date',
        'verified_date',
    )
    list_filter = ('payment_state', 'created_date', 'verified_date')
    search_fields = (
        'user__phone_number',
        'user__email',
        'authority',
        'ref_id',
    )
    date_hierarchy = 'created_date'

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        context = getattr(response, 'context_data', None)
        if context and 'cl' in context:
            # Use the changelist queryset so date filters and searches are
            # reflected in the figures shown to an administrator.
            context['completed_payment_summary'] = context['cl'].queryset.filter(
                payment_state='COMPLETED',
            ).aggregate(
                count=Count('pk'),
                total=Sum('total_price', default=0),
            )
        return response

@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    search_fields = ['user__phone_number']
    list_display = ['__str__', 'payment_state', 'is_capacity_exempt', 'presentation__cost']
    list_filter = ['payment_state', 'is_capacity_exempt']


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('name', 'percentage', 'count', 'preserve_capacity', 'used')
    filter_horizontal = ('eligible_presentations',)

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
                    presentation=presentation,
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
            for participation in Participation.objects.filter(
                presentation=presentation,
                payment_state="COMPLETED",
            ):
                user = participation.user
                data[presentation.en_title][user.phone_number] = {
                    'name': user.first_name + " " + user.last_name,
                    'email': user.email,
                }

        return JsonResponse(data)


@admin.register(PresentationProposal)
class PresentationProposalAdmin(admin.ModelAdmin):
    list_display = ('submitted_at', 'full_name', 'topic', 'phone_number')
    list_filter = ('submitted_at',)
    search_fields = ('full_name', 'organization', 'phone_number', 'topic')
    readonly_fields = (
        'full_name',
        'biography',
        'organization',
        'phone_number',
        'topic',
        'abstract',
        'submitted_at',
        'slides_download_link',
    )
    fields = readonly_fields

    def get_urls(self):
        custom_urls = [
            path(
                '<path:object_id>/download-slides/',
                self.admin_site.admin_view(self.download_slides),
                name='shop_presentationproposal_download',
            ),
        ]
        return custom_urls + super().get_urls()

    def download_slides(self, request, object_id):
        proposal = self.get_object(request, object_id)
        if proposal is None or not proposal.slides:
            raise Http404('Proposal slides were not found.')
        if not self.has_view_or_change_permission(request, proposal):
            raise PermissionDenied
        return FileResponse(
            proposal.slides.open('rb'),
            as_attachment=True,
            filename=Path(proposal.slides.name).name,
        )

    @admin.display(description='Slides')
    def slides_download_link(self, obj):
        if not obj or not obj.slides:
            return 'No slides uploaded'
        download_url = reverse(
            'admin:shop_presentationproposal_download',
            args=[obj.pk],
        )
        return format_html('<a href="{}">Download slides</a>', download_url)
