from pathlib import Path

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum, Q
from django.http import FileResponse, Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.template.defaultfilters import title
from django.urls import path, reverse
from django.utils.html import format_html

from accounts.sms import SMS_EXECUTOR, send_sms
from accounts.skyroom_admin import SkyroomPresentationActions
from accounts.skyroom import export_users
from accounts.models import User
from shop.models import (
    Presenter,
    Presentation,
    Participation,
    Coupon,
    Payment,
    PresentationTag,
    PresentationProposal,
    Bundle,
    CouponRedemption,
    PresentationReminder,
)
from shop.reminders import confirmation_token, queue_reminders, reminder_batch, reminder_content, reminder_recipients

admin.site.register(Presenter)


class BundleAdminForm(forms.ModelForm):
    class Meta:
        model = Bundle
        fields = '__all__'

    def clean_presentations(self):
        items = self.cleaned_data['presentations']
        if items.count() < 2:
            raise forms.ValidationError('A bundle must contain at least two presentations/workshops.')
        return items


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    form = BundleAdminForm
    list_display = ('name', 'price', 'is_active', 'remaining_capacity')
    list_filter = ('is_active', 'tags')
    search_fields = ('name',)
    filter_horizontal = ('presentations', 'tags')

    @admin.display(description='Remaining capacity')
    def remaining_capacity(self, obj):
        return obj.availability()[0]


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
        'superseded_at',
        'requires_manual_review',
        'review_resolved',
    )
    list_filter = ('requires_manual_review', 'review_resolved', 'superseded_at', 'payment_state', 'created_date', 'verified_date')
    readonly_fields = ('superseded_at', 'superseded_reason', 'checkout_snapshot',
                       'requires_manual_review', 'last_reconciled_at')
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
    list_display = ('name', 'percentage', 'count', 'minimum_items', 'preserve_capacity', 'used', 'discounted_registrations')
    filter_horizontal = ('eligible_presentations',)

    @admin.display(description='Redeemed orders (recorded)')
    def used(self, obj):
        return obj.redemptions.count() + Payment.objects.filter(
            payment_state='COMPLETED', coupon=obj, requires_manual_review=False,
            coupon_redemption__isnull=True,
        ).count()

    @admin.display(description='Discounted registrations (recorded)')
    def discounted_registrations(self, obj):
        return Participation.objects.filter(payment_state='COMPLETED').filter(
            Q(coupon_redemptions__coupon=obj)
            | Q(coupon_payments__coupon=obj, coupon_payments__payment_state='COMPLETED',
                coupon_payments__requires_manual_review=False),
        ).distinct().count()


@admin.register(CouponRedemption)
class CouponRedemptionAdmin(admin.ModelAdmin):
    list_display = ('coupon_code', 'user', 'payment', 'created_at')
    list_filter = ('coupon_code', 'created_at')
    search_fields = ('coupon_code', 'user__email', 'user__phone_number')
    readonly_fields = ('coupon', 'coupon_code', 'user', 'payment', 'participations', 'created_at', 'snapshot')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Presentation)
class PresentationAdmin(SkyroomPresentationActions, admin.ModelAdmin):
    change_form_template = 'admin/shop/presentation/change_form.html'
    list_display = ('__str__', 'capacity', 'completed_registrations', 'capacity_exempt_registrations', 'display_remaining', 'checkout_remaining', 'get_presenters')
    actions = ('send_registration_sms', 'export_registrations', 'export_skyroom_credentials', 'email_skyroom_credentials')

    def get_urls(self):
        return [path(
            '<path:object_id>/notify-participants/',
            self.admin_site.admin_view(self.notify_participants),
            name='shop_presentation_notify_participants',
        ), path(
            '<path:object_id>/export-skyroom/',
            self.admin_site.admin_view(self.download_participants_excel),
            name='shop_presentation_export_skyroom',
        )] + super().get_urls()

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        context = dict(extra_context or {})
        if object_id:
            obj = self.get_object(request, object_id)
            if obj and self.has_view_or_change_permission(request, obj) and self.has_export_skyroom_permission(request):
                context['participants_excel_url'] = reverse('admin:shop_presentation_export_skyroom', args=[obj.pk])
            if obj and self.has_view_or_change_permission(request, obj) and self.has_send_reminders_permission(request):
                context['notify_participants_url'] = reverse('admin:shop_presentation_notify_participants', args=[obj.pk])
        return super().changeform_view(request, object_id, form_url, context)

    def has_send_reminders_permission(self, request):
        return request.user.has_perm('shop.send_presentation_reminders')

    def notify_participants(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            raise Http404('Presentation not found.')
        if not self.has_view_or_change_permission(request, obj) or not self.has_send_reminders_permission(request):
            raise PermissionDenied
        if request.method not in ('GET', 'POST'):
            return HttpResponseNotAllowed(['GET', 'POST'])
        error = None
        if request.method == 'POST':
            try:
                if request.POST.get('confirm') != 'yes':
                    raise ValueError('Please confirm the reminder emails.')
                batch_id = reminder_batch(request.POST.get('confirmation_token', ''), obj)
            except ValueError as failure:
                error = str(failure)
            else:
                count = queue_reminders(obj, batch_id, request.user)
                self.message_user(request, f'Queued {count} reminder emails. A repeated confirmation does not queue duplicates.', messages.SUCCESS)
                return redirect(reverse('admin:shop_presentation_change', args=[obj.pk]))
        subject, body = reminder_content(obj, 'شرکت‌کننده گرامی')
        return TemplateResponse(request, 'admin/shop/presentation/reminder_confirmation.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Send presentation reminder emails', 'presentation': obj,
            'recipient_count': reminder_recipients(obj).count(), 'confirmation_token': confirmation_token(obj),
            'email_subject': subject, 'email_body': body, 'error': error,
            'cancel_url': reverse('admin:shop_presentation_change', args=[obj.pk]),
            'delivery_url': reverse('admin:shop_presentationreminder_changelist') + f'?presentation__id__exact={obj.pk}',
        }, status=400 if error else 200)

    def download_participants_excel(self, request, object_id):
        from django.core.exceptions import ImproperlyConfigured
        obj = self.get_object(request, object_id)
        if obj is None:
            raise Http404('Presentation not found.')
        if not self.has_view_or_change_permission(request, obj) or not self.has_export_skyroom_permission(request):
            raise PermissionDenied
        users = User.objects.filter(participations__presentation=obj,
                                    participations__payment_state='COMPLETED').distinct()
        try:
            return export_users(users, [obj.pk], include_non_skyroom=True)
        except ImproperlyConfigured as error:
            from django.contrib import messages
            self.message_user(request, str(error), level=messages.ERROR)
            return redirect(reverse('admin:shop_presentation_change', args=[obj.pk]))

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            registered_count=Count('participations', filter=Q(participations__payment_state='COMPLETED'), distinct=True),
            exempt_count=Count('participations', filter=Q(participations__payment_state='COMPLETED', participations__is_capacity_exempt=True), distinct=True),
        )

    @admin.display(description='Completed registrations', ordering='registered_count')
    def completed_registrations(self, obj):
        return obj.registered_count

    @admin.display(description='Capacity-exempt registrations', ordering='exempt_count')
    def capacity_exempt_registrations(self, obj):
        return obj.exempt_count

    @admin.display(description='Remaining (all registrations)')
    def display_remaining(self, obj):
        return obj.get_display_remained_capacity()

    @admin.display(description='Checkout capacity (excludes exempt)')
    def checkout_remaining(self, obj):
        return obj.get_remained_capacity()

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


@admin.register(PresentationReminder)
class PresentationReminderAdmin(admin.ModelAdmin):
    list_display = ('presentation', 'recipient', 'status', 'attempts', 'created_at', 'sent_at', 'last_error', 'queued_by')
    list_filter = ('status', 'presentation', 'created_at')
    list_select_related = ('presentation', 'queued_by')
    search_fields = ('recipient', 'presentation__en_title', 'presentation__fa_title')
    readonly_fields = ('presentation', 'user', 'queued_by', 'batch_id', 'recipient', 'status',
                       'attempts', 'created_at', 'available_at', 'sent_at', 'last_error')
    actions = ['retry_failed']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_send_reminders_permission(self, request):
        return request.user.has_perm('shop.send_presentation_reminders')

    @admin.action(description='Retry failed reminder emails', permissions=['send_reminders'])
    def retry_failed(self, request, queryset):
        from django.utils import timezone
        count = queryset.filter(status='FAILED').update(status='PENDING', attempts=0, last_error='', available_at=timezone.now())
        self.message_user(request, f'Requeued {count} reminder emails.')


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
