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
    # ---------------- CITIZEN LOGIN (OPTIONAL) ----------------
    path(
        "citizen/login/",
        views.citizen_login,
        name="citizen_login"
    ),

    path(
        "citizen/signup/",
        views.citizen_signup,
        name="citizen_signup"
    ),

    path(
        "citizen/verify/",
        views.citizen_verify,
        name="citizen_verify"
    ),

    path(
        "citizen/profile/",
        views.citizen_profile,
        name="citizen_profile"
    ),

    path(
        "citizen/logout/",
        views.citizen_logout,
        name="citizen_logout"
    ),

    path(
        "citizen/complaints/",
        views.my_complaints,
        name="my_complaints"
    ),

    # ---------------- CITIZEN CONFIRMATION ----------------
    path(
        "complaint/confirm/",
        views.confirm_resolution,
        name="confirm_resolution"
    ),

    # ---------------- PUBLIC COMPLAINT BOARD ----------------
    path(
        "complaints/public/",
        views.public_complaints,
        name="public_complaints"
    ),

    path(
        "complaints/public/<int:pk>/",
        views.public_complaint_detail,
        name="public_complaint_detail"
    ),

    path(
        "complaints/public/<int:pk>/upvote/",
        views.upvote_complaint,
        name="upvote_complaint"
    ),

    # ---------------- PUBLIC WARD RANKING ----------------
    path(
        "wards/ranking/",
        views.ward_ranking,
        name="ward_ranking"
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

    # ---------------- MODERATION ----------------
    path(
        "complaint/<int:pk>/visibility/",
        views.toggle_visibility,
        name="toggle_visibility"
    ),

]
