from django.db import models
import uuid


class WardOfficial(models.Model):

    ward_number = models.IntegerField(
        choices=[
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
    )

    full_name = models.CharField(max_length=100)

    username = models.CharField(
        max_length=50,
        unique=True
    )

    password = models.CharField(max_length=128)

    def __str__(self):
        return f"वडा {self.ward_number} - {self.full_name}"


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


from django.db import models
import uuid


class WardOfficial(models.Model):

    ward_number = models.IntegerField(
        choices=[
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
    )

    full_name = models.CharField(max_length=100)

    username = models.CharField(
        max_length=50,
        unique=True
    )

    password = models.CharField(max_length=128)

    def __str__(self):
        return f"वडा {self.ward_number} - {self.full_name}"


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

    ward = models.IntegerField()

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

    def save(self, *args, **kwargs):

        if not self.complaint_id:
            self.complaint_id = "MC-" + uuid.uuid4().hex[:8].upper()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.complaint_id} - {self.subject}"