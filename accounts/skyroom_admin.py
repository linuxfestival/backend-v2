from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured
from django.template.response import TemplateResponse

from .models import SkyroomEmail, User
from .skyroom import export_users, queue_credential_emails


class SkyroomAdminPermissions:
    def has_export_skyroom_permission(self, request):
        return request.user.has_perm('accounts.export_skyroom_credentials')

    def has_email_skyroom_permission(self, request):
        return request.user.has_perm('accounts.email_skyroom_credentials')


class SkyroomUserActions(SkyroomAdminPermissions):
    @admin.action(description='Export Skyroom credentials (Excel)', permissions=['export_skyroom'])
    def export_skyroom_credentials(self, request, queryset):
        try:
            return export_users(queryset)
        except ImproperlyConfigured as error:
            self.message_user(request, str(error), level=messages.ERROR)


class SkyroomPresentationActions(SkyroomAdminPermissions):
    def skyroom_users(self, queryset):
        ids = list(queryset.filter(is_skyroom=True).values_list('pk', flat=True))
        users = User.objects.filter(participations__payment_state='COMPLETED',
                                    participations__presentation_id__in=ids).distinct()
        return ids, users

    @admin.action(description='Export participants’ Skyroom credentials (Excel)', permissions=['export_skyroom'])
    def export_skyroom_credentials(self, request, queryset):
        ids, users = self.skyroom_users(queryset)
        if not ids:
            self.message_user(request, 'Select a presentation with Skyroom enabled.', level=messages.WARNING)
            return
        try:
            return export_users(users, ids)
        except ImproperlyConfigured as error:
            self.message_user(request, str(error), level=messages.ERROR)

    @admin.action(description='Email Skyroom credentials to participants', permissions=['email_skyroom'])
    def email_skyroom_credentials(self, request, queryset):
        ids, users = self.skyroom_users(queryset)
        if not ids:
            self.message_user(request, 'Select a presentation with Skyroom enabled.', level=messages.WARNING)
            return
        if request.POST.get('confirm') == 'yes':
            try:
                count = queue_credential_emails(users, ids)
            except ImproperlyConfigured as error:
                self.message_user(request, str(error), level=messages.ERROR)
                return
            self.message_user(request, f'Queued {count} Skyroom credential emails. Check Skyroom emails for delivery status.')
            return
        return TemplateResponse(request, 'admin/skyroom_email_confirmation.html', {
            **self.admin_site.each_context(request), 'title': 'Confirm Skyroom credential emails',
            'opts': self.model._meta, 'presentations': queryset.filter(pk__in=ids),
            'recipient_count': users.count(), 'selected_ids': list(queryset.values_list('pk', flat=True)),
            'select_across': request.POST.get('select_across', '0'),
        })


@admin.register(SkyroomEmail)
class SkyroomEmailAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'status', 'attempts', 'created_at', 'sent_at', 'last_error')
    list_filter = ('status', 'created_at')
    search_fields = ('recipient', 'credential__username')
    readonly_fields = ('credential', 'recipient', 'presentations', 'status', 'attempts',
                       'available_at', 'created_at', 'sent_at', 'last_error')
    actions = ['retry_failed']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_email_skyroom_permission(self, request):
        return request.user.has_perm('accounts.email_skyroom_credentials')

    @admin.action(description='Retry failed Skyroom emails', permissions=['email_skyroom'])
    def retry_failed(self, request, queryset):
        from django.utils import timezone
        count = queryset.filter(status='FAILED').update(status='PENDING', attempts=0, last_error='', available_at=timezone.now())
        self.message_user(request, f'Requeued {count} failed emails.')
