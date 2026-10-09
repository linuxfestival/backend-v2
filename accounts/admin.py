from pathlib import Path

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Accessory, FAQ, Resume, Staff, User


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


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ["user", "original_filename", "updated_at"]
    search_fields = ["user__email", "user__phone_number", "original_filename"]
    readonly_fields = [
        "user", "original_filename", "uploaded_at", "updated_at", "download_link",
    ]
    fields = readonly_fields

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/download/",
                self.admin_site.admin_view(self.download),
                name="accounts_resume_download",
            ),
        ]
        return custom_urls + super().get_urls()

    def download(self, request, object_id):
        resume = self.get_object(request, object_id)
        if resume is None or not resume.file:
            raise Http404("Resume file was not found.")
        if not self.has_view_or_change_permission(request, resume):
            raise PermissionDenied
        return FileResponse(
            resume.file.open("rb"),
            as_attachment=True,
            filename=Path(resume.original_filename).name,
            content_type="application/pdf",
        )

    @admin.display(description="Resume")
    def download_link(self, obj):
        if not obj or not obj.file:
            return "No resume uploaded"
        url = reverse("admin:accounts_resume_download", args=[obj.pk])
        return format_html('<a href="{}">Download resume</a>', url)
