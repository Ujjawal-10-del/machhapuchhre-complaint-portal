from django import forms
from .models import Complaint


class ComplaintForm(forms.ModelForm):

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

}

        widgets = {

            "citizen_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "पूरा नाम"
            }),

            "phone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "९८XXXXXXXX"
            }),

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
                "placeholder": "गुनासोको विस्तृत विवरण"
            }),

            "image": forms.ClearableFileInput(attrs={
                "class": "form-control"
            }),
        }