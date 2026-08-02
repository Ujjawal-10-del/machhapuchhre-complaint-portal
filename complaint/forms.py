from django import forms
from django.conf import settings

from .models import Citizen, Complaint
from .sms import normalize_phone


class CitizenProfileForm(forms.ModelForm):
    """Details on a citizen account.

    Phone is excluded on purpose: it identifies the account and links it to
    every complaint filed under it, so it must not be edited here.
    """

    class Meta:
        model = Citizen

        fields = ["name", "address", "ward"]

        labels = {
            "name": "पूरा नाम",
            "address": "ठेगाना",
            "ward": "वडा नम्बर",
        }

        widgets = {

            "name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "पूरा नाम",
            }),

            "address": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "टोल / गाउँ",
            }),

            "ward": forms.Select(attrs={
                "class": "form-select",
            }),
        }

    def clean_name(self):

        name = (self.cleaned_data.get("name") or "").strip()

        if not name:
            raise forms.ValidationError("नाम अनिवार्य छ।")

        return name


class ComplaintForm(forms.ModelForm):

    # Declared explicitly rather than left to the model field: Complaint.phone
    # allows 15 characters, and ModelForm would render maxlength="15" from it,
    # overriding the widget attribute below.
    #
    # No max_length here on purpose. The browser is capped at 10 digits, but the
    # server stays lenient so a number pasted as "981 419 8452" is normalised by
    # clean_phone instead of being rejected for being 12 characters long.
    phone = forms.CharField(
        label="मोबाइल नम्बर",
        error_messages={
            "required": "मोबाइल नम्बर अनिवार्य छ।",
        },
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "९८XXXXXXXX",
            "maxlength": "10",
            "minlength": "10",
            "pattern": "9[78][0-9]{8}",
            "inputmode": "numeric",
            "autocomplete": "tel",
            "title": "१० अंकको मोबाइल नम्बर लेख्नुहोस् (९८ वा ९७ बाट सुरु हुने)।",
        }),
    )

    def clean_phone(self):
        """Store the number in a shape the SMS gateway will accept.

        The citizen is notified on this number, so an unusable one means they
        silently never hear back about their complaint.
        """

        raw = self.cleaned_data.get("phone")

        normalized = normalize_phone(raw)

        if not normalized:
            raise forms.ValidationError(
                "सही मोबाइल नम्बर लेख्नुहोस् (जस्तै: ९८XXXXXXXX)।"
            )

        return normalized

    def clean_description(self):
        """Cap the description on the server.

        The textarea carries a maxlength, but that only binds a browser. A
        direct POST could otherwise store a description of any size.
        """

        description = (self.cleaned_data.get("description") or "").strip()

        limit = getattr(settings, "MAX_DESCRIPTION_LENGTH", 2000)

        if len(description) > limit:
            raise forms.ValidationError(
                "गुनासो विवरण %d अक्षरभन्दा लामो हुन सक्दैन।" % limit
            )

        return description

    def clean_image(self):
        """Reject photos too large to be worth storing.

        Django streams an upload of any size to disk without complaint, so
        without this one request could fill the server's disk.
        """

        image = self.cleaned_data.get("image")

        # Unchanged or absent uploads have no size to check.
        if not image or not hasattr(image, "size"):
            return image

        limit = getattr(settings, "MAX_UPLOAD_SIZE", 5 * 1024 * 1024)

        if image.size > limit:
            raise forms.ValidationError(
                "फोटो %d MB भन्दा सानो हुनुपर्छ।" % (limit // (1024 * 1024))
            )

        return image

    class Meta:
        model = Complaint

        fields = [
            "citizen_name",
            "phone",
            "address",
            "ward",
            "category",
            "priority",
            "subject",
            "description",
            "image",
            "is_public",
            "show_name",
        ]
        labels = {

    "citizen_name": "नागरिकको नाम",

    "phone": "फोन नम्बर",

    "address": "ठेगाना",

    "ward": "वडा नम्बर",

    "category": "समस्या प्रकार",

    "priority": "प्राथमिकता",

    "subject": "गुनासोको शीर्षक",

    "description": "गुनासो विवरण",

    "image": "फोटो",

    "is_public": "सार्वजनिक सूचीमा देखाउने",

    "show_name": "मेरो नाम पनि देखाउने",

}

        widgets = {

            "citizen_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "पूरा नाम"
            }),

            # "phone" is declared as an explicit field above, so a widget here
            # would be ignored.

            "address": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "टोल / गाउँ / वडा"
            }),

            "ward": forms.Select(
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
                ],
                attrs={
                    "class": "form-select"
                }
            ),

            "category": forms.Select(attrs={
                "class": "form-select"
            }),

            "priority": forms.Select(attrs={
                "class": "form-select"
            }),

            "subject": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "गुनासोको शीर्षक"
            }),

            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "गुनासोको विस्तृत विवरण",
                "maxlength": str(settings.MAX_DESCRIPTION_LENGTH),
            }),

            # accept limits the file picker; clean_image enforces the real cap.
            "image": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),

            # Ticked by default: the board only works if complaints reach it.
            "is_public": forms.CheckboxInput(attrs={
                "class": "form-check-input"
            }),

            # Unticked by default. Publishing someone's name has to be a
            # deliberate choice, never something that happens by not noticing.
            "show_name": forms.CheckboxInput(attrs={
                "class": "form-check-input"
            }),
        }