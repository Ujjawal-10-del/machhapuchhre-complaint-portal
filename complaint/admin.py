from django.contrib import admin
from .models import WardOfficial, Complaint


@admin.register(WardOfficial)
class WardOfficialAdmin(admin.ModelAdmin):
    list_display = (
        "ward_number",
        "full_name",
        "username",
    )

    search_fields = (
        "full_name",
        "username",
    )

    list_filter = (
        "ward_number",
    )


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = (
        "complaint_id",
        "citizen_name",
        "ward",
        "category",
        "priority",
        "status",
        "created_at",
    )

    search_fields = (
        "citizen_name",
        "phone",
        "subject",
    )

    list_filter = (
        "ward",
        "category",
        "status",
    )

    ordering = (
        "-created_at",
    )