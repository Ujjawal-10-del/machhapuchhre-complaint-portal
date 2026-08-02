from django.conf import settings
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.db import models
import uuid


WARD_CHOICES = [
    (1, "वडा नं. १"),
    (2, "वडा नं. २"),
    (3, "वडा नं. ३"),
    (4, "वडा नं. ४"),
    (5, "वडा नं. ५"),
    (6, "वडा नं. ६"),
    (7, "वडा नं. ७"),
    (8, "वडा नं. ८"),
    (9, "वडा नं. ९"),
]

STATUS_CHOICES = [
    ("Pending", "Pending"),
    ("In Progress", "In Progress"),
    ("Resolved", "Resolved"),
]

CATEGORY_CHOICES = [
    ("Road", "Road"),
    ("Water", "Water"),
    ("Electricity", "Electricity"),
    ("Sanitation", "Sanitation"),
    ("Education", "Education"),
    ("Health", "Health"),
    ("Agriculture", "Agriculture"),
    ("Other", "Other"),
]

PRIORITY_CHOICES = [
    ("Low", "Low"),
    ("Medium", "Medium"),
    ("High", "High"),
]


class WardOfficial(models.Model):

    # Authentication is delegated to Django's own user system rather than
    # hand-rolled on a password column: session handling, hashing and the
    # password validators all come for free and are far better tested.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ward_official",
    )

    ward_number = models.IntegerField(choices=WARD_CHOICES)

    full_name = models.CharField(max_length=100)

    @classmethod
    def create_official(cls, ward_number, full_name, username, password):
        """Create the account and its ward profile together."""

        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username=username,
            password=password,
        )

        return cls.objects.create(
            user=user,
            ward_number=ward_number,
            full_name=full_name,
        )

    @property
    def username(self):
        return self.user.username

    def set_password(self, raw_password):
        self.user.set_password(raw_password)
        self.user.save(update_fields=["password"])

    def check_password(self, raw_password):
        if not raw_password:
            return False

        return self.user.check_password(raw_password)

    def __str__(self):
        return f"वडा {self.ward_number} - {self.full_name}"


class Complaint(models.Model):

    complaint_id = models.CharField(
        max_length=20,
        unique=True,
        blank=True
    )

    citizen_name = models.CharField(max_length=100)

    phone = models.CharField(max_length=15)

    address = models.CharField(
        max_length=200,
        blank=True
    )

    ward = models.IntegerField(choices=WARD_CHOICES)

    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES
    )

    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default="Medium"
    )

    subject = models.CharField(max_length=200)

    description = models.TextField()

    image = models.ImageField(
        upload_to="complaints/",
        blank=True,
        null=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    reply = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    # Set the moment status first becomes "Resolved"; cleared if it is reopened.
    # Needed to report how long a ward actually takes to close a complaint.
    resolved_at = models.DateTimeField(
        blank=True,
        null=True
    )

    # ---------- citizen confirmation ----------

    # None  = the citizen has not responded yet
    # True  = they agree the problem is fixed
    # False = they say it is not, and the complaint was reopened
    #
    # Without this, "Resolved" is only ever the ward office's own claim, and the
    # public ranking rewards that claim.
    citizen_confirmed = models.BooleanField(
        null=True,
        blank=True,
        default=None
    )

    confirmed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    dispute_reason = models.TextField(
        blank=True
    )

    @property
    def awaiting_confirmation(self):
        return self.status == "Resolved" and self.citizen_confirmed is None

    # ---------- public visibility ----------

    # Whether the complaint appears on the public board at all. Default True so
    # the board is useful, but the citizen can opt out for a sensitive matter.
    is_public = models.BooleanField(default=True)

    # Names are opt-in and default to off. Complaints filed before the public
    # board existed therefore appear anonymously, which is the only honest
    # option for text submitted with no notice that it might be published.
    show_name = models.BooleanField(default=False)

    # Moderation takedown, controlled by the ward office. Kept separate from
    # is_public so an office hiding something never silently overwrites what
    # the citizen chose.
    hidden_by_office = models.BooleanField(default=False)

    hidden_reason = models.CharField(
        max_length=200,
        blank=True
    )

    @property
    def is_visible_publicly(self):
        return self.is_public and not self.hidden_by_office

    @property
    def public_author(self):
        """Name to show on the public board, or the anonymous label."""

        if self.show_name and self.citizen_name:
            return self.citizen_name

        return "अज्ञात नागरिक"

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):

        if not self.complaint_id:
            self.complaint_id = "MC-" + uuid.uuid4().hex[:8].upper()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.complaint_id} - {self.subject}"


class Citizen(models.Model):
    """An optional account, identified only by a mobile number.

    Filing a complaint never requires one. An account exists purely so someone
    can find their earlier complaints again without the tracking ID -- there is
    no password, because a village portal cannot expect people to keep one.
    """

    phone = models.CharField(
        max_length=10,
        unique=True
    )

    name = models.CharField(
        max_length=100,
        blank=True
    )

    address = models.CharField(
        max_length=200,
        blank=True
    )

    ward = models.IntegerField(
        choices=WARD_CHOICES,
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    last_login_at = models.DateTimeField(
        blank=True,
        null=True
    )

    @property
    def complaints(self):
        return Complaint.objects.filter(phone=self.phone)

    @property
    def profile_complete(self):
        """Enough detail to prefill a complaint form."""

        return bool(self.name and self.ward)

    def __str__(self):
        return self.phone


class OTPCode(models.Model):
    """A short-lived login code sent by SMS.

    The code is stored hashed. It only ever needs to be compared, never read
    back, so a leaked database should not hand over live login codes.
    """

    phone = models.CharField(max_length=10)

    code_hash = models.CharField(max_length=128)

    expires_at = models.DateTimeField()

    attempts = models.PositiveIntegerField(default=0)

    used = models.BooleanField(default=False)

    ip_hash = models.CharField(
        max_length=64,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def set_code(self, raw_code):
        self.code_hash = make_password(raw_code)

    def check_code(self, raw_code):
        return check_password(raw_code or "", self.code_hash)

    @property
    def is_live(self):
        """Still usable: unused, unexpired, and not guessed at too many times."""

        from django.conf import settings
        from django.utils import timezone

        max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)

        return (
            not self.used
            and self.attempts < max_attempts
            and timezone.now() < self.expires_at
        )

    def __str__(self):
        return f"OTP for {self.phone}"


class Upvote(models.Model):
    """One "me too" from a visitor on a public complaint.

    Citizens have no accounts, so this is deduplicated by session. That is
    bypassable with a fresh browser session and deliberately so: it is a
    priority signal, not a vote in an election. The IP is stored only as a
    salted hash for later auditing -- never as a block, because Nepali mobile
    networks put whole neighbourhoods behind one address.
    """

    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.CASCADE,
        related_name="upvotes"
    )

    session_key = models.CharField(max_length=40)

    # Set when the visitor happened to be signed in. Session keys change; a
    # citizen account does not, so this makes the count exact for the people
    # who have one, without requiring anyone to sign in to vote.
    citizen = models.ForeignKey(
        "Citizen",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="upvotes"
    )

    ip_hash = models.CharField(
        max_length=64,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Database-level guarantees, so a double-submit cannot double-count.
        constraints = [
            models.UniqueConstraint(
                fields=["complaint", "session_key"],
                name="unique_upvote_per_session"
            ),
            models.UniqueConstraint(
                fields=["complaint", "citizen"],
                condition=models.Q(citizen__isnull=False),
                name="unique_upvote_per_citizen"
            ),
        ]

    def __str__(self):
        return f"upvote on {self.complaint.complaint_id}"


SMS_PURPOSE_CHOICES = [
    ("registration", "Registration"),
    ("status_change", "Status change"),
    ("login_code", "Login code"),
]


class SMSLog(models.Model):
    """One row per SMS attempt, successful or not.

    Messages cost money and citizens will ask whether they were notified, so
    every attempt is recorded rather than only the failures.
    """

    complaint = models.ForeignKey(
        Complaint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sms_logs"
    )

    phone = models.CharField(max_length=20)

    message = models.TextField()

    purpose = models.CharField(
        max_length=30,
        choices=SMS_PURPOSE_CHOICES,
        blank=True
    )

    success = models.BooleanField(default=False)

    provider_response = models.CharField(
        max_length=500,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        state = "sent" if self.success else "failed"

        return f"{self.phone} - {self.purpose} ({state})"
