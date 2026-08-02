import re

from django.contrib import admin

from .models import WardOfficial, Complaint, SMSLog, Upvote, Citizen, OTPCode


@admin.register(WardOfficial)
class WardOfficialAdmin(admin.ModelAdmin):
    """Ward profile. Credentials live on the linked Django user.

    Passwords are set through the standard Users admin, which already applies
    AUTH_PASSWORD_VALIDATORS, hashes on save and never shows a password back.
    """

    list_display = (
        "ward_number",
        "full_name",
        "username",
        "is_active",
    )

    search_fields = (
        "full_name",
        "user__username",
    )

    list_filter = (
        "ward_number",
    )

    autocomplete_fields = ("user",)

    @admin.display(description="Username", ordering="user__username")
    def username(self, official):
        return official.user.username

    @admin.display(description="Active", boolean=True)
    def is_active(self, official):
        return official.user.is_active

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")


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
        "is_public",
        "hidden_by_office",
    )

    ordering = (
        "-created_at",
    )

    actions = ["hide_from_public", "restore_to_public"]

    @admin.action(description="Hide selected complaints from the public board")
    def hide_from_public(self, request, queryset):

        updated = queryset.update(hidden_by_office=True)

        self.message_user(request, f"{updated} complaint(s) hidden.")

    @admin.action(description="Restore selected complaints to the public board")
    def restore_to_public(self, request, queryset):

        updated = queryset.update(hidden_by_office=False, hidden_reason="")

        self.message_user(request, f"{updated} complaint(s) restored.")


@admin.register(Citizen)
class CitizenAdmin(admin.ModelAdmin):
    list_display = (
        "phone",
        "name",
        "created_at",
        "last_login_at",
    )

    search_fields = (
        "phone",
        "name",
    )

    readonly_fields = (
        "created_at",
        "last_login_at",
    )


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = (
        "phone",
        "created_at",
        "expires_at",
        "attempts",
        "used",
    )

    list_filter = (
        "used",
    )

    search_fields = (
        "phone",
    )

    # Login codes are a security record. code_hash is deliberately not listed:
    # nothing in the admin should make guessing a live code easier.
    readonly_fields = (
        "phone",
        "expires_at",
        "attempts",
        "used",
        "ip_hash",
        "created_at",
    )

    exclude = ("code_hash",)

    def has_add_permission(self, request):
        return False


@admin.register(Upvote)
class UpvoteAdmin(admin.ModelAdmin):
    list_display = (
        "complaint",
        "session_key",
        "created_at",
    )

    readonly_fields = (
        "complaint",
        "session_key",
        "ip_hash",
        "created_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    """Every SMS the portal tried to send.

    While the console backend is in use nothing reaches a real handset, so the
    login code shown here is how a citizen account can be tested. With DEBUG
    off the code is redacted before it is ever written to this table.
    """

    list_display = (
        "created_at",
        "phone",
        "purpose",
        "login_code",
        "message",
        "success",
    )

    list_filter = (
        "purpose",
        "success",
    )

    search_fields = (
        "phone",
        "message",
    )

    @admin.display(description="Login code")
    def login_code(self, log):

        if log.purpose != "login_code":
            return "—"

        found = re.search(r"\d{6}", log.message or "")

        return found.group(0) if found else "— (redacted)"

    # Delivery history is a record of what happened, not something to edit.
    readonly_fields = (
        "complaint",
        "phone",
        "message",
        "purpose",
        "success",
        "provider_response",
        "created_at",
    )

    def has_add_permission(self, request):
        return False