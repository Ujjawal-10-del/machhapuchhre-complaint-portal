import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import CitizenProfileForm, ComplaintForm
from .models import (
    Citizen,
    Complaint,
    OTPCode,
    Upvote,
    WardOfficial,
    CATEGORY_CHOICES,
    STATUS_CHOICES,
    WARD_CHOICES,
)
from .notifications import (
    notify_login_code,
    notify_registered,
    notify_status_change,
)
from .sms import normalize_phone


# ==================================================
# HELPERS
# ==================================================
def paginate(request, queryset, per_page=12):
    """Return one page of a queryset plus the querystring that preserves filters.

    The querystring keeps every parameter except "page", so paging through
    filtered results does not silently drop the filters.
    """

    paginator = Paginator(queryset, per_page)

    page_obj = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    querystring = params.urlencode()

    return page_obj, (querystring + "&" if querystring else "")


def get_logged_in_ward(request):
    """Return the WardOfficial for this request, or None.

    Backed by Django's auth system. A signed-in user without a linked ward
    profile -- the admin superuser, for instance -- is deliberately not a ward
    official and gets None.
    """

    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return None

    return WardOfficial.objects.filter(user=user).first()


def get_complaint_for_ward(ward, pk):
    """Fetch a complaint, but only if it belongs to this official's ward.

    Without the ward filter an official could reach any other ward's complaint
    just by editing the pk in the URL.
    """

    return get_object_or_404(
        Complaint,
        pk=pk,
        ward=ward.ward_number
    )


# ==================================================
# HOME PAGE
# ==================================================
def home(request):
    return render(
        request,
        "complaint/home.html",
        {
            "active_nav": "home"
        }
    )


# ==================================================
# COMPLAINT REGISTRATION
# ==================================================
def complaint_register(request):

    if request.method == "POST":

        form = ComplaintForm(request.POST, request.FILES)

        if form.is_valid():

            complaint = form.save()

            # Text the tracking ID over: it is otherwise shown only once.
            # send_sms swallows its own errors, so registration cannot fail
            # just because the gateway is down.
            sms = notify_registered(complaint)

            return render(
                request,
                "complaint/success.html",
                {
                    "complaint": complaint,
                    "sms_sent": sms.success,
                }
            )

    else:

        # A signed-in citizen already told us who they are at signup, so do not
        # make them retype it. Anyone not signed in fills the form as before.
        citizen = get_logged_in_citizen(request)

        initial = {}

        if citizen:
            initial = {
                "citizen_name": citizen.name,
                "phone": citizen.phone,
                "address": citizen.address,
                "ward": citizen.ward,
            }

        form = ComplaintForm(initial=initial)

    return render(
        request,
        "complaint/complaint_register.html",
        {
            "form": form,
            "prefilled": bool(get_logged_in_citizen(request)),
            "active_nav": "register",
        }
    )


# ==================================================
# COMPLAINT TRACKING
# ==================================================
def complaint_track(request):

    complaint = None
    error = None

    if request.method == "POST":

        complaint_id = (request.POST.get("complaint_id") or "").strip()

        complaint = Complaint.objects.filter(
            complaint_id__iexact=complaint_id
        ).first()

        if complaint is None:
            error = "यो गुनासो फेला परेन।"

    return render(
        request,
        "complaint/complaint_track.html",
        {
            "complaint": complaint,
            "error": error,
            "active_nav": "track",
        }
    )


# ==================================================
# PUBLIC COMPLAINT BOARD
# ==================================================
def public_complaint_queryset():
    """Complaints the public is allowed to see, with their upvote totals.

    Counted rather than kept in a column on Complaint, so the number can never
    drift away from the rows it is derived from.
    """

    return Complaint.objects.filter(
        is_public=True,
        hidden_by_office=False
    ).annotate(
        upvote_count=Count("upvotes")
    )


def hash_ip(request):
    """Salted hash of the caller's address, for auditing only.

    Never compared against other visitors: carrier-grade NAT means many
    unrelated people share one address here, so blocking on it would silence
    entire villages.
    """

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")

    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else request.META.get("REMOTE_ADDR", "")
    )

    if not ip:
        return ""

    salted = f"{settings.SECRET_KEY}:{ip}".encode("utf-8")

    return hashlib.sha256(salted).hexdigest()


def upvotes_by_visitor(request):
    """Upvotes attributable to whoever is making this request.

    Matches the citizen account when signed in as well as the browser session,
    so the button reflects reality on a second device instead of inviting a
    press that would silently withdraw an existing vote.
    """

    session_key = request.session.session_key

    citizen = get_logged_in_citizen(request)

    if not session_key and not citizen:
        return Upvote.objects.none()

    match = Q(pk__in=[])

    if session_key:
        match = match | Q(session_key=session_key)

    if citizen:
        match = match | Q(citizen=citizen)

    return Upvote.objects.filter(match)


def public_complaints(request):
    """The public board: every complaint citizens agreed to publish."""

    complaints = public_complaint_queryset()

    query = (request.GET.get("q") or "").strip()

    category = request.GET.get("category") or ""

    ward = request.GET.get("ward") or ""

    sort = request.GET.get("sort") or "popular"

    if query:
        complaints = complaints.filter(
            Q(subject__icontains=query) | Q(description__icontains=query)
        )

    if category:
        complaints = complaints.filter(category=category)

    if ward.isdigit():
        complaints = complaints.filter(ward=int(ward))

    if sort == "recent":
        complaints = complaints.order_by("-created_at")
    else:
        complaints = complaints.order_by("-upvote_count", "-created_at")

    page_obj, querystring = paginate(request, complaints)

    # The paginator has already counted the set; counting again is a wasted
    # query over the same rows.
    total_public = page_obj.paginator.count

    # Only the complaints actually on screen need an "already backed" check.
    upvoted_ids = set(
        upvotes_by_visitor(request)
        .filter(complaint__in=list(page_obj.object_list))
        .values_list("complaint_id", flat=True)
    )

    return render(
        request,
        "complaint/public_complaints.html",
        {
            "complaints": page_obj.object_list,
            "page_obj": page_obj,
            "querystring": querystring,
            "upvoted_ids": upvoted_ids,
            "query": query,
            "selected_category": category,
            "selected_ward": ward,
            "sort": sort,
            "categories": CATEGORY_CHOICES,
            "wards": WARD_CHOICES,
            "total_public": total_public,
            "active_nav": "public",
        }
    )


def public_complaint_detail(request, pk):
    """One complaint on the public board.

    Deliberately renders a hand-picked set of fields. Phone and address are
    never among them, whatever the citizen chose about their name.
    """

    complaint = get_object_or_404(public_complaint_queryset(), pk=pk)

    already_upvoted = upvotes_by_visitor(request).filter(
        complaint=complaint
    ).exists()

    return render(
        request,
        "complaint/public_complaint_detail.html",
        {
            "complaint": complaint,
            "already_upvoted": already_upvoted,
            "active_nav": "public",
        }
    )


def upvote_complaint(request, pk):
    """Register a "me too" against a public complaint."""

    if request.method != "POST":
        return redirect("public_complaints")

    complaint = get_object_or_404(public_complaint_queryset(), pk=pk)

    # Anonymous visitors have no session until something is written to one.
    if not request.session.session_key:
        request.session.create()

    session_key = request.session.session_key

    citizen = get_logged_in_citizen(request)

    # Match on the account when there is one, so signing in on a second device
    # cannot add a second vote, and falls back to the session otherwise.
    match = Q(session_key=session_key)

    if citizen:
        match = match | Q(citizen=citizen)

    existing = Upvote.objects.filter(complaint=complaint).filter(match).first()

    if existing:
        # Second press means "take it back".
        existing.delete()

    else:

        try:

            Upvote.objects.create(
                complaint=complaint,
                session_key=session_key,
                citizen=citizen,
                ip_hash=hash_ip(request),
            )

        except IntegrityError:
            # Double-submitted; the unique constraint already did its job.
            pass

    next_url = request.POST.get("next")

    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)

    return redirect("public_complaint_detail", pk=pk)


# ==================================================
# PUBLIC WARD RANKING
# ==================================================
def ward_ranking(request):
    """Public league table of the 9 wards, ranked by share of complaints resolved.

    Percentage alone rewards low-volume wards, so total volume is carried
    alongside it and is used to break ties. Wards with no complaints cannot be
    scored at all and are listed separately rather than shown as 0% or 100%.
    """

    resolution_time = ExpressionWrapper(
        F("resolved_at") - F("created_at"),
        output_field=DurationField()
    )

    # One grouped query for every per-ward number on the page.
    rows = Complaint.objects.values("ward").annotate(

        total=Count("id"),

        pending=Count("id", filter=Q(status="Pending")),

        in_progress=Count("id", filter=Q(status="In Progress")),

        resolved=Count("id", filter=Q(status="Resolved")),

        # How many of those resolutions the citizen actually agreed with. This
        # is the number that is hard to fake.
        confirmed=Count(
            "id",
            filter=Q(status="Resolved", citizen_confirmed=True)
        ),

        disputed=Count("id", filter=Q(citizen_confirmed=False)),

        avg_resolution=Avg(
            resolution_time,
            filter=Q(status="Resolved", resolved_at__isnull=False)
        ),

    )

    stats_by_ward = {row["ward"]: row for row in rows}

    # Ward offices are keyed by number, not a foreign key, so map them by hand.
    # First record wins if a ward somehow has more than one official.
    names_by_ward = {}

    for official in WardOfficial.objects.all().order_by("id"):
        names_by_ward.setdefault(official.ward_number, official.full_name)

    wards = []

    for number, label in WARD_CHOICES:

        stats = stats_by_ward.get(number, {})

        total = stats.get("total", 0)
        resolved = stats.get("resolved", 0)

        avg_resolution = stats.get("avg_resolution")

        wards.append({

            "number": number,

            "label": label,

            "office": names_by_ward.get(number, ""),

            "total": total,

            "pending": stats.get("pending", 0),

            "in_progress": stats.get("in_progress", 0),

            "resolved": resolved,

            "confirmed": stats.get("confirmed", 0),

            "disputed": stats.get("disputed", 0),

            # None (not 0) when there is nothing to score, so the template can
            # show "—" instead of implying the ward performed badly.
            "rate": (resolved / total * 100) if total else None,

            "avg_days": (
                avg_resolution.total_seconds() / 86400
                if avg_resolution else None
            ),

        })

    ranked = [w for w in wards if w["total"] > 0]
    unranked = [w for w in wards if w["total"] == 0]

    # Higher rate first; more complaints handled breaks a tie.
    ranked.sort(key=lambda w: (-w["rate"], -w["total"], w["number"]))

    for position, ward in enumerate(ranked, start=1):
        ward["rank"] = position

    totals = {
        "total": sum(w["total"] for w in wards),
        "pending": sum(w["pending"] for w in wards),
        "in_progress": sum(w["in_progress"] for w in wards),
        "resolved": sum(w["resolved"] for w in wards),
        "confirmed": sum(w["confirmed"] for w in wards),
        "disputed": sum(w["disputed"] for w in wards),
    }

    totals["rate"] = (
        totals["resolved"] / totals["total"] * 100
        if totals["total"] else None
    )

    return render(
        request,
        "complaint/ward_ranking.html",
        {
            "ranked": ranked,
            "unranked": unranked,
            "totals": totals,
            "active_nav": "ranking",
        }
    )


# ==================================================
# CITIZEN LOGIN (OPTIONAL, PHONE + OTP)
# ==================================================
def get_logged_in_citizen(request):
    """Return the signed-in Citizen, or None. Never required to use the site."""

    citizen_id = request.session.get("citizen_id")

    if not citizen_id:
        return None

    return Citizen.objects.filter(id=citizen_id).first()


def start_otp(request, template, mode):
    """Shared first step for signing in and signing up: text a code.

    Signing up is open to any valid mobile number, so two independent caps
    guard the SMS bill: one per number, and one per source address to stop
    someone cycling through numbers they do not own.
    """

    if get_logged_in_citizen(request):
        return redirect("my_complaints")

    context = {"active_nav": "citizen", "mode": mode}

    if request.method != "POST":
        return render(request, template, context)

    phone = normalize_phone(request.POST.get("phone"))

    if not phone:

        context["error"] = "सही मोबाइल नम्बर लेख्नुहोस् (जस्तै: ९८XXXXXXXX)।"

        return render(request, template, context)

    number_key = "otp-requests:%s" % phone
    number_limit = getattr(settings, "OTP_REQUEST_LIMIT", 3)
    number_window = getattr(settings, "OTP_REQUEST_WINDOW", 900)

    source_key = "otp-source:%s" % hash_ip(request)
    source_limit = getattr(settings, "OTP_IP_REQUEST_LIMIT", 10)
    source_window = getattr(settings, "OTP_IP_REQUEST_WINDOW", 3600)

    number_used = cache.get(number_key, 0)
    source_used = cache.get(source_key, 0)

    if number_used >= number_limit or source_used >= source_limit:

        context["error"] = (
            "धेरै पटक कोड मागियो। केही समयपछि प्रयास गर्नुहोस्।"
        )

        return render(request, template, context, status=429)

    ttl = getattr(settings, "OTP_TTL_SECONDS", 300)

    code = "%06d" % secrets.randbelow(1000000)

    otp = OTPCode(
        phone=phone,
        expires_at=timezone.now() + timedelta(seconds=ttl),
        ip_hash=hash_ip(request),
    )

    otp.set_code(code)
    otp.save()

    # Any earlier code for this number is now void, so a stale SMS cannot be
    # replayed.
    OTPCode.objects.filter(phone=phone).exclude(pk=otp.pk).update(used=True)

    cache.set(number_key, number_used + 1, number_window)
    cache.set(source_key, source_used + 1, source_window)

    notify_login_code(phone, code, ttl // 60)

    request.session["otp_phone"] = phone

    return redirect("citizen_verify")


def citizen_login(request):
    """Sign in to an existing account, or create one on the spot."""

    return start_otp(request, "complaint/citizen_login.html", "login")


def citizen_signup(request):
    """Same machinery as login, presented for someone with no account yet."""

    return start_otp(request, "complaint/citizen_signup.html", "signup")


def citizen_verify(request):
    """Step two: check the code and sign the citizen in."""

    phone = request.session.get("otp_phone")

    if not phone:
        return redirect("citizen_login")

    error = None

    if request.method == "POST":

        otp = OTPCode.objects.filter(phone=phone).first()

        if otp is None or not otp.is_live:
            error = "कोडको म्याद सकियो। नयाँ कोड माग्नुहोस्।"

        elif otp.check_code((request.POST.get("code") or "").strip()):

            otp.used = True
            otp.save(update_fields=["used"])

            citizen, _ = Citizen.objects.get_or_create(phone=phone)

            # Seed the profile from their most recent complaint so someone who
            # has filed before does not retype what the portal already knows.
            latest = Complaint.objects.filter(phone=phone).first()

            if latest:

                if not citizen.name:
                    citizen.name = latest.citizen_name

                if not citizen.address:
                    citizen.address = latest.address

                if not citizen.ward:
                    citizen.ward = latest.ward

            citizen.last_login_at = timezone.now()
            citizen.save()

            request.session.cycle_key()

            request.session["citizen_id"] = citizen.id

            request.session.pop("otp_phone", None)

            # Only interrupt with the details form when the portal genuinely
            # does not know who they are. Someone whose past complaints already
            # filled the profile goes straight to their history.
            if not citizen.profile_complete:
                return redirect("citizen_profile")

            return redirect("my_complaints")

        else:

            otp.attempts += 1
            otp.save(update_fields=["attempts"])

            remaining = (
                getattr(settings, "OTP_MAX_ATTEMPTS", 5) - otp.attempts
            )

            error = (
                "कोड मिलेन। %d प्रयास बाँकी।" % remaining
                if remaining > 0
                else "धेरै पटक गलत भयो। नयाँ कोड माग्नुहोस्।"
            )

    return render(
        request,
        "complaint/citizen_verify.html",
        {
            "phone": phone,
            "error": error,
            "active_nav": "citizen",
        }
    )


def citizen_profile(request):
    """Fill in or update the account's details.

    The phone number is not editable: it is what the account is identified by,
    and changing it would silently detach every complaint filed under it.
    """

    citizen = get_logged_in_citizen(request)

    if not citizen:
        return redirect("citizen_login")

    saved = False

    if request.method == "POST":

        form = CitizenProfileForm(request.POST, instance=citizen)

        if form.is_valid():

            form.save()

            # Stays on the page and confirms, rather than redirecting: editing
            # a profile is usually followed by another small correction.
            saved = True

    else:
        form = CitizenProfileForm(instance=citizen)

    return render(
        request,
        "complaint/citizen_profile.html",
        {
            "citizen": citizen,
            "form": form,
            "saved": saved,
            "active_nav": "citizen",
        }
    )


def citizen_logout(request):

    request.session.pop("citizen_id", None)
    request.session.pop("otp_phone", None)

    return redirect("home")


def my_complaints(request):
    """Every complaint filed from the signed-in citizen's number."""

    citizen = get_logged_in_citizen(request)

    if not citizen:
        return redirect("citizen_login")

    # Ordered explicitly: annotate() adds a GROUP BY, after which Django no
    # longer treats Meta.ordering as a guarantee, and unordered pagination can
    # repeat or skip rows between pages.
    complaints = citizen.complaints.annotate(
        upvote_count=Count("upvotes")
    ).order_by("-created_at")

    counts = citizen.complaints.aggregate(
        total=Count("id"),
        open=Count("id", filter=~Q(status="Resolved")),
        resolved=Count("id", filter=Q(status="Resolved")),
        awaiting=Count(
            "id",
            filter=Q(status="Resolved", citizen_confirmed__isnull=True)
        ),
    )

    page_obj, querystring = paginate(request, complaints)

    return render(
        request,
        "complaint/my_complaints.html",
        {
            "citizen": citizen,
            "complaints": page_obj.object_list,
            "page_obj": page_obj,
            "querystring": querystring,
            "counts": counts,
            "active_nav": "citizen",
        }
    )


# ==================================================
# CITIZEN CONFIRMATION
# ==================================================
def confirm_resolution(request):
    """Let the citizen accept or reject a ward's claim that the work is done.

    Keyed on the complaint ID rather than the primary key: that string is what
    was texted to the citizen, so knowing it stands in for authentication on a
    portal where citizens have no accounts.
    """

    if request.method != "POST":
        return redirect("complaint_track")

    complaint_id = (request.POST.get("complaint_id") or "").strip()

    complaint = Complaint.objects.filter(
        complaint_id__iexact=complaint_id
    ).first()

    if complaint is None:

        return render(
            request,
            "complaint/complaint_track.html",
            {
                "error": "यो गुनासो फेला परेन।",
                "active_nav": "track",
            }
        )

    answer = request.POST.get("answer")

    message = None
    error = None

    if not complaint.awaiting_confirmation:

        # Already answered, or never resolved in the first place.
        error = "यो गुनासोमा अहिले पुष्टि गर्न मिल्दैन।"

    elif answer == "yes":

        complaint.citizen_confirmed = True
        complaint.confirmed_at = timezone.now()

        complaint.save(update_fields=["citizen_confirmed", "confirmed_at"])

        message = "धन्यवाद! तपाईंको पुष्टि दर्ता भयो।"

    elif answer == "no":

        # Reopening is the point: a disputed complaint goes back to the ward's
        # queue and stops counting as resolved on the public ranking.
        complaint.citizen_confirmed = False
        complaint.confirmed_at = timezone.now()
        complaint.dispute_reason = (request.POST.get("reason") or "").strip()
        complaint.status = "In Progress"
        complaint.resolved_at = None

        complaint.save(update_fields=[
            "citizen_confirmed",
            "confirmed_at",
            "dispute_reason",
            "status",
            "resolved_at",
        ])

        message = (
            "तपाईंको जवाफ दर्ता भयो। गुनासो पुनः वडा कार्यालयमा पठाइएको छ।"
        )

    else:
        error = "कृपया 'हो' वा 'होइन' छान्नुहोस्।"

    return render(
        request,
        "complaint/complaint_track.html",
        {
            "complaint": complaint,
            "message": message,
            "error": error,
            "active_nav": "track",
        }
    )


# ==================================================
# WARD LOGIN
# ==================================================
def login_attempt_key(request, username):
    """Throttle bucket for one account seen from one address.

    Keyed on both, never on the address alone: Nepali networks put whole
    offices behind a single address, so an IP-only counter would let one
    person's mistyped password lock out everyone around them.
    """

    return "login-attempts:%s:%s" % (hash_ip(request), (username or "").lower())


def ward_login(request):

    # Already logged in
    if get_logged_in_ward(request):
        return redirect("ward_dashboard")

    limit = getattr(settings, "LOGIN_ATTEMPT_LIMIT", 10)
    window = getattr(settings, "LOGIN_ATTEMPT_WINDOW", 900)

    if request.method == "POST":

        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        cache_key = login_attempt_key(request, username)

        # Ward passwords are short and guessable, and this form is on the open
        # internet, so unlimited guessing cannot be allowed.
        attempts = cache.get(cache_key, 0)

        if attempts >= limit:

            return render(
                request,
                "complaint/ward_login.html",
                {
                    "error": (
                        "धेरै पटक गलत प्रयास भयो। "
                        "%d मिनेटपछि फेरि प्रयास गर्नुहोस्।" % (window // 60)
                    )
                },
                status=429,
            )

        user = authenticate(request, username=username, password=password)

        # Authenticating is not enough: the account must actually belong to a
        # ward office. The admin superuser has no business here.
        official = (
            WardOfficial.objects.filter(user=user).first() if user else None
        )

        if official:

            cache.delete(cache_key)

            # login() cycles the session key for us, guarding against fixation.
            django_login(request, user)

            return redirect("ward_dashboard")

        # set() rather than incr() so the first failure creates the entry and
        # starts the expiry clock.
        cache.set(cache_key, attempts + 1, window)

        return render(
            request,
            "complaint/ward_login.html",
            {
                "error": "Username वा Password मिलेन।",
                "attempts_left": max(0, limit - attempts - 1),
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

    ward = get_logged_in_ward(request)

    # Login required
    if not ward:
        return redirect("ward_login")

    complaints = Complaint.objects.filter(
        ward=ward.ward_number
    )

    # Tiles always describe the whole ward, so they stay meaningful while the
    # table below is filtered. One grouped query rather than five round trips.
    counts = complaints.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status="Pending")),
        in_progress=Count("id", filter=Q(status="In Progress")),
        resolved=Count("id", filter=Q(status="Resolved")),
        today=Count("id", filter=Q(created_at__date=timezone.localdate())),
    )

    query = (request.GET.get("q") or "").strip()

    status = request.GET.get("status") or ""

    category = request.GET.get("category") or ""

    if query:
        complaints = complaints.filter(
            Q(subject__icontains=query)
            | Q(description__icontains=query)
            | Q(citizen_name__icontains=query)
            | Q(complaint_id__icontains=query)
        )

    if status in dict(STATUS_CHOICES):
        complaints = complaints.filter(status=status)

    if category in dict(CATEGORY_CHOICES):
        complaints = complaints.filter(category=category)

    page_obj, querystring = paginate(request, complaints, per_page=20)

    # Reuse the paginator's count rather than issuing a second identical one.
    filtered_count = page_obj.paginator.count

    context = {

        "ward": ward,

        "complaints": page_obj.object_list,

        "page_obj": page_obj,

        "querystring": querystring,

        "query": query,

        "selected_status": status,

        "selected_category": category,

        "statuses": STATUS_CHOICES,

        "categories": CATEGORY_CHOICES,

        "filtered_count": filtered_count,

        "is_filtered": bool(query or status or category),

        **counts,

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

    # logout() flushes the whole session, which would also sign out a citizen
    # who happens to be using the same browser. Their login is unrelated, so
    # carry it across.
    citizen_id = request.session.get("citizen_id")

    django_logout(request)

    if citizen_id:
        request.session["citizen_id"] = citizen_id

    return redirect("home")


# ==================================================
# COMPLAINT DETAIL
# ==================================================
def complaint_detail(request, pk):

    ward = get_logged_in_ward(request)

    # Login required
    if not ward:
        return redirect("ward_login")

    complaint = get_complaint_for_ward(ward, pk)

    return render(
        request,
        "complaint/complaint_detail.html",
        {
            "ward": ward,
            "complaint": complaint,
        }
    )


# ==================================================
# UPDATE STATUS
# ==================================================
def update_status(request, pk):

    ward = get_logged_in_ward(request)

    # Login required
    if not ward:
        return redirect("ward_login")

    complaint = get_complaint_for_ward(ward, pk)

    error = None

    if request.method == "POST":

        status = request.POST.get("status")

        valid_statuses = [choice[0] for choice in STATUS_CHOICES]

        if status in valid_statuses:

            # Captured before the change so the citizen is only texted when the
            # status genuinely moved, not every time a reply is edited.
            status_changed = complaint.status != status

            complaint.status = status

            complaint.reply = (request.POST.get("reply") or "").strip()

            # Stamp the first time it lands on Resolved, and clear the stamp if
            # the complaint is reopened, so resolution time stays truthful.
            if status == "Resolved":

                if not complaint.resolved_at:
                    complaint.resolved_at = timezone.now()

                # A complaint the citizen previously rejected has been worked on
                # again, so their old "no" is stale. Clear it and ask afresh,
                # otherwise a genuine fix could never be confirmed.
                if status_changed and complaint.citizen_confirmed is False:
                    complaint.citizen_confirmed = None
                    complaint.confirmed_at = None
                    complaint.dispute_reason = ""

            else:
                complaint.resolved_at = None

            complaint.save()

            if status_changed:
                notify_status_change(complaint)

            return redirect(
                "complaint_detail",
                pk=pk
            )

        error = "अमान्य स्थिति चयन गरियो।"

    return render(
        request,
        "complaint/update_status.html",
        {
            "ward": ward,
            "complaint": complaint,
            "error": error,
        }
    )


# ==================================================
# MODERATION
# ==================================================
def toggle_visibility(request, pk):
    """Let a ward office pull one of its complaints off the public board.

    Public free text will eventually contain abuse, a named accusation or a
    phone number someone typed into the description. Without this the only
    remedy would be deleting the complaint outright.
    """

    ward = get_logged_in_ward(request)

    if not ward:
        return redirect("ward_login")

    complaint = get_complaint_for_ward(ward, pk)

    if request.method == "POST":

        complaint.hidden_by_office = not complaint.hidden_by_office

        complaint.hidden_reason = (
            (request.POST.get("reason") or "").strip()
            if complaint.hidden_by_office
            else ""
        )

        complaint.save(update_fields=["hidden_by_office", "hidden_reason"])

    return redirect("complaint_detail", pk=pk)
