from django.urls import path
from . import views

urlpatterns = [

    # ---------------- HOME ----------------
    path(
        "",
        views.home,
        name="home"
    ),

    # ---------------- COMPLAINT register ----------------
    path(
        "complaint/register/",
        views.complaint_register,
        name="complaint_register"
    ),
    # ---------------- COMPLAINT TRACK ----------------
    path(
    "complaint/track/",
    views.complaint_track,
    name="complaint_track"
    ),
    # ---------------- WARD LOGIN ----------------
    path(
        "ward/login/",
        views.ward_login,
        name="ward_login"
    ),

    # ---------------- WARD DASHBOARD ----------------
    path(
        "ward/dashboard/",
        views.ward_dashboard,
        name="ward_dashboard"
    ),

    # ---------------- LOGOUT ----------------
    path(
        "ward/logout/",
        views.ward_logout,
        name="ward_logout"
    ),

    # ---------------- COMPLAINT DETAIL ----------------
    path(
        "complaint/<int:pk>/",
        views.complaint_detail,
        name="complaint_detail"
    ),

    # ---------------- UPDATE STATUS ----------------
    path(
        "complaint/<int:pk>/update/",
        views.update_status,
        name="update_status"
    ),

]
