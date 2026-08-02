from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .forms import ComplaintForm
from .models import Complaint, WardOfficial


# ==================================================
# HOME PAGE
# ==================================================
def home(request):
    return render(request, "complaint/home.html")


# ==================================================
# COMPLAINT REGISTRATION
# ==================================================
def complaint_register(request):

    if request.method == "POST":

        form = ComplaintForm(request.POST, request.FILES)

        if form.is_valid():

            complaint = form.save()

            return render(
                request,
                "complaint/success.html",
                {
                    "complaint": complaint
                }
            )

        else:

            print("\n========== FORM ERRORS ==========")
            print(form.errors)
            print("=================================\n")

    else:

        form = ComplaintForm()

    return render(
        request,
        "complaint/complaint_register.html",
        {
            "form": form
        }
    )

def complaint_track(request):

    complaint = None
    error = None

    if request.method == "POST":

        complaint_id = request.POST.get("complaint_id")

        try:

           complaint = Complaint.objects.get(
    complaint_id=complaint_id
)

        except Complaint.DoesNotExist:

            error = "यो गुनासो फेला परेन।"

    return render(
        request,
        "complaint/complaint_track.html",
        {
            "complaint": complaint,
            "error": error,
        }
    )

# ==================================================
# WARD LOGIN
# ==================================================
def ward_login(request):

    # Already logged in
    if request.session.get("ward_id"):
        return redirect("ward_dashboard")

    if request.method == "POST":

        username = request.POST.get("username")
        password = request.POST.get("password")

        try:

            ward = WardOfficial.objects.get(
                username=username,
                password=password
            )

            # Store logged in ward
            request.session["ward_id"] = ward.id

            return redirect("ward_dashboard")

        except WardOfficial.DoesNotExist:

            return render(
                request,
                "complaint/ward_login.html",
                {
                    "error": "Username वा Password मिलेन।"
                }
            )

    return render(
        request,
        "complaint/ward_login.html"
    )


# ==================================================
# WARD DASHBOARD
# ==================================================
def ward_dashboard(request):

    ward_id = request.session.get("ward_id")

    # Login required
    if not ward_id:
        return redirect("ward_login")

    ward = get_object_or_404(
        WardOfficial,
        id=ward_id
    )

    complaints = Complaint.objects.filter(
        ward=ward.ward_number
    ).order_by("-created_at")

    total = complaints.count()

    pending = complaints.filter(
        status="Pending"
    ).count()

    in_progress = complaints.filter(
        status="In Progress"
    ).count()

    resolved = complaints.filter(
        status="Resolved"
    ).count()

    today = complaints.filter(
        created_at__date=timezone.now().date()
    ).count()

    context = {

        "ward": ward,

        "complaints": complaints,

        "total": total,

        "pending": pending,

        "in_progress": in_progress,

        "resolved": resolved,

        "today": today,

    }

    return render(
        request,
        "complaint/ward_dashboard.html",
        context
    )


# ==================================================
# LOGOUT
# ==================================================
def ward_logout(request):

    request.session.flush()

    return redirect("home")


# ==================================================
# COMPLAINT DETAIL
# ==================================================
def complaint_detail(request, pk):

    # Login required
    if not request.session.get("ward_id"):
        return redirect("ward_login")

    complaint = get_object_or_404(
        Complaint,
        pk=pk
    )

    return render(
        request,
        "complaint/complaint_detail.html",
        {
            "complaint": complaint
        }
    )


# ==================================================
# UPDATE STATUS
# ==================================================
def update_status(request, pk):

    # Login required
    if not request.session.get("ward_id"):
        return redirect("ward_login")

    complaint = get_object_or_404(
        Complaint,
        pk=pk
    )

    if request.method == "POST":

        complaint.status = request.POST.get("status")

        complaint.reply = request.POST.get("reply")

        complaint.save()

        return redirect(
            "complaint_detail",
            pk=pk
        )

        return redirect(
            "complaint_detail",
            pk=pk
        )

    return render(
        request,
        "complaint/update_status.html",
        {
            "complaint": complaint
        }
    )