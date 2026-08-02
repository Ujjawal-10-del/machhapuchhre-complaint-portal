"""Tests for the parts of the portal that are expensive or risky to get wrong.

Focused on three things: money (SMS is billed per message), privacy (one ward
must not read another's complaints), and the public ranking arithmetic.
"""

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Citizen, Complaint, OTPCode, SMSLog, WardOfficial
from .sms import (
    BaseSMSBackend,
    SMSError,
    count_segments,
    normalize_phone,
    send_sms,
)


class ExplodingBackend(BaseSMSBackend):
    """Stands in for a gateway that is down."""

    def send(self, phone, message):
        raise SMSError("gateway unreachable")


class CrashingBackend(BaseSMSBackend):
    """Stands in for a buggy backend that raises something unexpected."""

    def send(self, phone, message):
        raise ValueError("bug inside the backend")


BROKEN = "complaint.tests.ExplodingBackend"
CRASHING = "complaint.tests.CrashingBackend"


# ==================================================
# PHONE NUMBERS
# ==================================================

class NormalizePhoneTests(TestCase):

    def test_accepts_the_shapes_people_actually_type(self):

        for raw in [
            "9814198452",
            "981 4198452",
            "981-419-8452",
            "+9779814198452",
            "+977 981-419-8452",
            "9779814198452",
            "09814198452",
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_phone(raw), "9814198452")

    def test_rejects_numbers_that_cannot_receive_sms(self):

        for raw in [
            "9192892839273",   # too long, already in the live database
            "1234567890",      # right length, wrong prefix
            "9614198452",      # 96 is not a mobile prefix
            "98141984",        # too short
            "asdf",
            "",
            None,
        ]:
            with self.subTest(raw=raw):
                self.assertIsNone(normalize_phone(raw))


class SegmentCountTests(TestCase):

    def test_latin_text_uses_160_character_segments(self):

        self.assertEqual(count_segments("a" * 160), 1)
        self.assertEqual(count_segments("a" * 161), 2)

    def test_devanagari_forces_70_character_segments(self):

        self.assertEqual(count_segments("क" * 70), 1)
        self.assertEqual(count_segments("क" * 71), 2)

    def test_every_citizen_message_fits_one_segment(self):
        """Guards the SMS bill: a stray word here doubles the cost."""

        from .notifications import (
            build_registration_message,
            build_status_message,
        )

        complaint = Complaint(
            complaint_id="MC-12345678",
            status="In Progress",
        )

        self.assertEqual(count_segments(build_registration_message(complaint)), 1)

        for status in ["Pending", "In Progress", "Resolved"]:
            with self.subTest(status=status):
                complaint.status = status
                self.assertEqual(count_segments(build_status_message(complaint)), 1)


# ==================================================
# SMS DELIVERY
# ==================================================

class SendSMSTests(TestCase):

    def test_records_a_successful_send(self):

        log = send_sms("9814198452", "hello", purpose="registration")

        self.assertTrue(log.success)
        self.assertEqual(log.phone, "9814198452")

    def test_unusable_number_is_skipped_not_sent(self):

        log = send_sms("9192892839273", "hello")

        self.assertFalse(log.success)
        self.assertIn("not a valid", log.provider_response)

    @override_settings(SMS_ENABLED=False)
    def test_master_switch_stops_sending(self):

        log = send_sms("9814198452", "hello")

        self.assertFalse(log.success)
        self.assertIn("SMS_ENABLED", log.provider_response)

    @override_settings(SMS_BACKEND=BROKEN)
    def test_gateway_failure_is_logged_not_raised(self):

        log = send_sms("9814198452", "hello")

        self.assertFalse(log.success)
        self.assertIn("gateway unreachable", log.provider_response)

    @override_settings(SMS_BACKEND=CRASHING)
    def test_unexpected_backend_bug_is_contained(self):

        log = send_sms("9814198452", "hello")

        self.assertFalse(log.success)
        self.assertIn("bug inside the backend", log.provider_response)


# ==================================================
# CITIZEN FLOW
# ==================================================

class RegistrationTests(TestCase):

    def form_data(self, **overrides):

        data = {
            "citizen_name": "Test Citizen",
            "phone": "981 419 8452",
            "address": "Somewhere",
            "ward": 3,
            "category": "Road",
            "priority": "Low",
            "subject": "Pothole",
            "description": "There is a pothole.",
        }

        data.update(overrides)

        return data

    def test_registration_stores_a_normalized_phone(self):

        self.client.post("/complaint/register/", self.form_data())

        complaint = Complaint.objects.get(subject="Pothole")

        self.assertEqual(complaint.phone, "9814198452")

    def test_registration_texts_the_tracking_id(self):

        self.client.post("/complaint/register/", self.form_data())

        complaint = Complaint.objects.get(subject="Pothole")
        log = complaint.sms_logs.get(purpose="registration")

        self.assertTrue(log.success)
        self.assertIn(complaint.complaint_id, log.message)

    def test_unusable_phone_is_rejected_before_saving(self):

        response = self.client.post(
            "/complaint/register/",
            self.form_data(phone="9192892839273")
        )

        self.assertFalse(Complaint.objects.filter(subject="Pothole").exists())
        self.assertIn("phone", response.context["form"].errors)

    def test_phone_must_be_exactly_ten_digits(self):

        for phone, why in [
            ("981419845", "nine digits"),
            ("98141984521", "eleven digits"),
            ("9192892839273", "thirteen digits"),
            ("", "empty"),
        ]:
            with self.subTest(why=why):

                response = self.client.post(
                    "/complaint/register/",
                    self.form_data(phone=phone)
                )

                self.assertIn("phone", response.context["form"].errors)
                self.assertFalse(
                    Complaint.objects.filter(subject="Pothole").exists()
                )

    def test_phone_input_is_capped_at_ten_in_the_browser(self):
        """The rendered field must stop over-long input before submit."""

        html = self.client.get("/complaint/register/").content.decode()

        self.assertIn('maxlength="10"', html)
        self.assertIn('pattern="9[78][0-9]{8}"', html)

    @override_settings(SMS_BACKEND=BROKEN)
    def test_registration_succeeds_even_when_sms_fails(self):
        """A dead gateway must never cost a citizen their complaint."""

        response = self.client.post("/complaint/register/", self.form_data())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Complaint.objects.filter(subject="Pothole").exists())
        self.assertFalse(response.context["sms_sent"])


# ==================================================
# WARD FLOW
# ==================================================

class WardWorkflowTests(TestCase):

    def setUp(self):

        cache.clear()

        self.ward3 = WardOfficial.create_official(


            ward_number=3,


            full_name="Ghachok",


            username="ward3",


            password="secret3",


        )

        self.ward7 = WardOfficial.create_official(


            ward_number=7,


            full_name="Dhampus",


            username="ward7",


            password="secret7",


        )

        self.mine = Complaint.objects.create(
            citizen_name="A", phone="9814198452", ward=3,
            category="Road", subject="Mine", description="d",
        )

        self.theirs = Complaint.objects.create(
            citizen_name="B", phone="9814198452", ward=7,
            category="Road", subject="Theirs", description="d",
        )

        self.client.post(
            "/ward/login/",
            {"username": "ward3", "password": "secret3"}
        )

    def test_password_is_stored_hashed(self):

        self.assertNotEqual(self.ward3.user.password, "secret3")
        self.assertTrue(self.ward3.check_password("secret3"))
        self.assertFalse(self.ward3.check_password("wrong"))

    def test_can_open_own_complaint(self):

        response = self.client.get("/complaint/%d/" % self.mine.pk)

        self.assertEqual(response.status_code, 200)

    def test_cannot_open_another_wards_complaint(self):

        response = self.client.get("/complaint/%d/" % self.theirs.pk)

        self.assertEqual(response.status_code, 404)

    def test_cannot_update_another_wards_complaint(self):

        self.client.post(
            "/complaint/%d/update/" % self.theirs.pk,
            {"status": "Resolved", "reply": "x"}
        )

        self.theirs.refresh_from_db()

        self.assertEqual(self.theirs.status, "Pending")

    def test_invalid_status_is_rejected(self):

        self.client.post(
            "/complaint/%d/update/" % self.mine.pk,
            {"status": "Hacked", "reply": "x"}
        )

        self.mine.refresh_from_db()

        self.assertEqual(self.mine.status, "Pending")

    def test_status_change_texts_the_citizen_once(self):

        self.client.post(
            "/complaint/%d/update/" % self.mine.pk,
            {"status": "In Progress", "reply": "working"}
        )

        self.assertEqual(
            self.mine.sms_logs.filter(purpose="status_change").count(), 1
        )

    def test_editing_only_the_reply_does_not_text_again(self):
        """Otherwise every typo correction bills the municipality again."""

        url = "/complaint/%d/update/" % self.mine.pk

        self.client.post(url, {"status": "In Progress", "reply": "first"})
        self.client.post(url, {"status": "In Progress", "reply": "corrected"})

        self.assertEqual(
            self.mine.sms_logs.filter(purpose="status_change").count(), 1
        )

    def test_resolved_at_is_stamped_and_cleared(self):

        url = "/complaint/%d/update/" % self.mine.pk

        self.client.post(url, {"status": "Resolved", "reply": "done"})
        self.mine.refresh_from_db()
        self.assertIsNotNone(self.mine.resolved_at)

        self.client.post(url, {"status": "Pending", "reply": "reopened"})
        self.mine.refresh_from_db()
        self.assertIsNone(self.mine.resolved_at)

    def test_dashboard_counts_are_one_aggregate_query(self):
        """Stat tiles must not cost one COUNT round trip each."""

        for _ in range(20):
            Complaint.objects.create(
                citizen_name="A", phone="9814198452", ward=3,
                category="Road", subject="s", description="d",
            )

        # session + auth user + ward profile + one aggregate
        # + paginator count + the page slice.
        with self.assertNumQueries(6):
            self.client.get("/ward/dashboard/")

    @override_settings(SMS_BACKEND=BROKEN)
    def test_status_update_survives_a_dead_gateway(self):

        response = self.client.post(
            "/complaint/%d/update/" % self.mine.pk,
            {"status": "Resolved", "reply": "done"}
        )

        self.mine.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.mine.status, "Resolved")
        self.assertTrue(self.mine.sms_logs.filter(success=False).exists())


# ==================================================
# PUBLIC TRACKING
# ==================================================

class TrackingPrivacyTests(TestCase):

    def test_full_phone_number_is_never_shown(self):
        """The tracking page needs no login, so the raw number must not leak."""

        complaint = Complaint.objects.create(
            citizen_name="A", phone="9814198452", ward=3,
            category="Road", subject="s", description="d",
        )

        response = self.client.post(
            "/complaint/track/",
            {"complaint_id": complaint.complaint_id}
        )

        self.assertNotContains(response, "9814198452")


# ==================================================
# INPUT LIMITS AND ABUSE
# ==================================================

class InputLimitTests(TestCase):

    def form_data(self, **overrides):

        data = {
            "citizen_name": "A",
            "phone": "9814198452",
            "address": "a",
            "ward": 1,
            "category": "Road",
            "priority": "Low",
            "subject": "s",
            "description": "d",
            "is_public": True,
        }

        data.update(overrides)

        return data

    def test_oversized_description_is_rejected(self):
        """maxlength on a textarea only binds a browser, not a direct POST."""

        response = self.client.post(
            "/complaint/register/",
            self.form_data(description="क" * 200000)
        )

        self.assertIn("description", response.context["form"].errors)
        self.assertEqual(Complaint.objects.count(), 0)

    def test_description_at_the_limit_is_accepted(self):

        limit = settings.MAX_DESCRIPTION_LENGTH

        self.client.post(
            "/complaint/register/",
            self.form_data(description="क" * limit)
        )

        self.assertEqual(Complaint.objects.count(), 1)

    def test_oversized_image_is_rejected(self):

        from django.core.files.uploadedfile import SimpleUploadedFile

        oversized = SimpleUploadedFile(
            "big.jpg",
            b"\xff\xd8\xff" + b"0" * (settings.MAX_UPLOAD_SIZE + 1024),
            content_type="image/jpeg",
        )

        response = self.client.post(
            "/complaint/register/",
            self.form_data(image=oversized)
        )

        self.assertIn("image", response.context["form"].errors)
        self.assertEqual(Complaint.objects.count(), 0)


class LoginThrottleTests(TestCase):

    def setUp(self):

        cache.clear()

        self.ward = WardOfficial.create_official(


            ward_number=1,


            full_name="Test",


            username="ward1",


            password="correct-horse-battery",


        )

    def test_repeated_failures_are_eventually_locked_out(self):

        limit = settings.LOGIN_ATTEMPT_LIMIT

        for _ in range(limit):
            self.client.post(
                "/ward/login/",
                {"username": "ward1", "password": "wrong"}
            )

        response = self.client.post(
            "/ward/login/",
            {"username": "ward1", "password": "wrong"}
        )

        self.assertEqual(response.status_code, 429)

    def test_lockout_blocks_even_the_correct_password(self):
        """Otherwise an attacker who guesses right on attempt 50 still wins."""

        for _ in range(settings.LOGIN_ATTEMPT_LIMIT):
            self.client.post(
                "/ward/login/",
                {"username": "ward1", "password": "wrong"}
            )

        response = self.client.post(
            "/ward/login/",
            {"username": "ward1", "password": "correct-horse-battery"}
        )

        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_successful_login_clears_the_counter(self):

        for _ in range(3):
            self.client.post(
                "/ward/login/",
                {"username": "ward1", "password": "wrong"}
            )

        self.client.post(
            "/ward/login/",
            {"username": "ward1", "password": "correct-horse-battery"}
        )

        self.assertIn("_auth_user_id", self.client.session)

        from django.core.cache import cache
        from .views import login_attempt_key

        request = self.client.request().wsgi_request

        self.assertIsNone(cache.get(login_attempt_key(request, "ward1")))

    def test_locking_one_account_does_not_lock_another(self):
        """Everyone in a ward office shares one public address."""

        other = WardOfficial.create_official(
            ward_number=2,
            full_name="Other",
            username="ward2",
            password="another-good-password",
        )

        for _ in range(settings.LOGIN_ATTEMPT_LIMIT + 2):
            self.client.post(
                "/ward/login/",
                {"username": "ward1", "password": "wrong"}
            )

        response = self.client.post(
            "/ward/login/",
            {"username": "ward2", "password": "another-good-password"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)


class WardPasswordStrengthTests(TestCase):
    """Ward credentials now live on a Django user, so the project's
    AUTH_PASSWORD_VALIDATORS apply to them automatically."""

    def test_a_weak_password_is_refused(self):

        from django.contrib.auth.forms import UserCreationForm

        form = UserCreationForm(data={
            "username": "ward1",
            "password1": "ward@1",
            "password2": "ward@1",
        })

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_a_strong_password_is_accepted_and_hashed(self):

        official = WardOfficial.create_official(
            ward_number=1,
            full_name="Test",
            username="ward1",
            password="correct-horse-battery-staple",
        )

        self.assertNotEqual(
            official.user.password, "correct-horse-battery-staple"
        )
        self.assertTrue(official.check_password("correct-horse-battery-staple"))

    def test_the_validators_are_actually_configured(self):

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validate_password("ward@1")


# ==================================================
# CITIZEN LOGIN (OPTIONAL, PHONE + OTP)
# ==================================================

# Login codes are only kept in the SMS log while DEBUG is on, so that the
# Django admin can show them when no real gateway is connected. The test runner
# forces DEBUG off, so these classes turn it back on to read the code the way a
# developer would.
@override_settings(DEBUG=True)
class CitizenLoginTests(TestCase):

    PHONE = "9814198452"

    def setUp(self):

        cache.clear()

        self.mine = Complaint.objects.create(
            citizen_name="Sita", phone=self.PHONE, ward=3,
            category="Road", subject="Mine", description="d",
        )

        self.someone_else = Complaint.objects.create(
            citizen_name="Ram", phone="9800000001", ward=3,
            category="Road", subject="Theirs", description="d",
        )

    def request_code(self, phone=None):
        return self.client.post(
            "/citizen/login/",
            {"phone": phone or self.PHONE}
        )

    def latest_code(self):
        """Read the code out of the SMS log, the way the citizen reads the SMS."""

        import re

        log = SMSLog.objects.filter(purpose="login_code").first()

        return re.search(r"\d{6}", log.message).group(0)

    # ---------- the optional part ----------

    def test_filing_a_complaint_still_needs_no_account(self):

        response = self.client.post("/complaint/register/", {
            "citizen_name": "Anon", "phone": "9800000002", "address": "a",
            "ward": 1, "category": "Road", "priority": "Low",
            "subject": "No account", "description": "d",
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Complaint.objects.filter(subject="No account").exists())

    def test_tracking_still_needs_no_account(self):

        response = self.client.post(
            "/complaint/track/",
            {"complaint_id": self.mine.complaint_id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["complaint"])

    # ---------- happy path ----------

    def test_a_code_is_texted_and_login_succeeds(self):

        self.request_code()

        self.assertEqual(SMSLog.objects.filter(purpose="login_code").count(), 1)

        response = self.client.post(
            "/citizen/verify/",
            {"code": self.latest_code()}
        )

        self.assertRedirects(response, "/citizen/complaints/")
        self.assertTrue(Citizen.objects.filter(phone=self.PHONE).exists())

    def test_the_code_is_not_stored_in_plain_text(self):

        self.request_code()

        code = self.latest_code()
        otp = OTPCode.objects.get()

        self.assertNotIn(code, otp.code_hash)
        self.assertTrue(otp.check_code(code))

    # ---------- abuse ----------

    def test_a_number_with_no_complaints_can_still_sign_up(self):
        """Signup is open by design; the throttles are what guard the SMS bill.

        See CitizenSignupTests for the per-number and per-source caps.
        """

        self.request_code(phone="9809999999")

        self.assertEqual(SMSLog.objects.filter(purpose="login_code").count(), 1)
        self.assertTrue(OTPCode.objects.filter(phone="9809999999").exists())

    def test_code_requests_are_rate_limited(self):

        limit = settings.OTP_REQUEST_LIMIT

        for _ in range(limit):
            self.request_code()

        response = self.request_code()

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            SMSLog.objects.filter(purpose="login_code").count(), limit
        )

    def test_a_wrong_code_does_not_log_anyone_in(self):

        self.request_code()

        self.client.post("/citizen/verify/", {"code": "000000"})

        self.assertIsNone(self.client.session.get("citizen_id"))

    def test_guessing_burns_the_code(self):

        self.request_code()

        real = self.latest_code()

        for _ in range(settings.OTP_MAX_ATTEMPTS):
            self.client.post("/citizen/verify/", {"code": "000000"})

        # Even the correct code is now dead.
        self.client.post("/citizen/verify/", {"code": real})

        self.assertIsNone(self.client.session.get("citizen_id"))

    def test_an_expired_code_is_rejected(self):

        self.request_code()

        code = self.latest_code()

        otp = OTPCode.objects.get()
        otp.expires_at = timezone.now() - timedelta(seconds=1)
        otp.save()

        self.client.post("/citizen/verify/", {"code": code})

        self.assertIsNone(self.client.session.get("citizen_id"))

    def test_a_code_cannot_be_used_twice(self):

        self.request_code()

        code = self.latest_code()

        self.client.post("/citizen/verify/", {"code": code})
        self.client.get("/citizen/logout/")

        second = self.client.post("/citizen/verify/", {"code": code})

        self.assertIsNone(self.client.session.get("citizen_id"))
        self.assertEqual(second.status_code, 302)

    def test_requesting_a_new_code_voids_the_old_one(self):

        self.request_code()
        first = self.latest_code()

        self.request_code()

        self.client.post("/citizen/verify/", {"code": first})

        self.assertIsNone(self.client.session.get("citizen_id"))

    # ---------- my complaints ----------

    def test_my_complaints_requires_signing_in(self):

        response = self.client.get("/citizen/complaints/")

        self.assertRedirects(response, "/citizen/login/")

    def test_my_complaints_shows_only_that_citizens_complaints(self):

        self.request_code()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})

        response = self.client.get("/citizen/complaints/")

        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")

    def test_my_complaints_includes_private_ones(self):
        """The owner should see a complaint they kept off the public board."""

        self.mine.is_public = False
        self.mine.save()

        self.request_code()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})

        response = self.client.get("/citizen/complaints/")

        self.assertContains(response, "Mine")


# Login codes are only kept in the SMS log while DEBUG is on, so that the
# Django admin can show them when no real gateway is connected. The test runner
# forces DEBUG off, so these classes turn it back on to read the code the way a
# developer would.
@override_settings(DEBUG=True)
class CitizenSignupTests(TestCase):

    NEW_PHONE = "9807654321"

    def setUp(self):
        cache.clear()

    def latest_code(self):

        import re

        log = SMSLog.objects.filter(purpose="login_code").first()

        return re.search(r"\d{6}", log.message).group(0)

    def signup(self, phone=None):
        return self.client.post(
            "/citizen/signup/",
            {"phone": phone or self.NEW_PHONE}
        )

    def test_a_brand_new_number_can_open_an_account(self):
        """Signup must work before the person has ever filed anything."""

        self.signup()

        self.assertEqual(SMSLog.objects.filter(purpose="login_code").count(), 1)

        response = self.client.post(
            "/citizen/verify/",
            {"code": self.latest_code()}
        )

        self.assertTrue(Citizen.objects.filter(phone=self.NEW_PHONE).exists())
        self.assertRedirects(response, "/citizen/profile/")

    def test_a_new_account_is_sent_to_fill_in_details(self):

        self.signup()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})

        citizen = Citizen.objects.get(phone=self.NEW_PHONE)

        self.assertFalse(citizen.profile_complete)

    def test_details_can_be_saved_and_edited(self):

        self.signup()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})

        self.client.post("/citizen/profile/", {
            "name": "Sita Gurung",
            "address": "Ghachok-4",
            "ward": 3,
        })

        citizen = Citizen.objects.get(phone=self.NEW_PHONE)

        self.assertEqual(citizen.name, "Sita Gurung")
        self.assertEqual(citizen.ward, 3)
        self.assertTrue(citizen.profile_complete)

    def test_a_name_is_required(self):

        self.signup()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})

        response = self.client.post("/citizen/profile/", {
            "name": "   ",
            "address": "x",
            "ward": 3,
        })

        self.assertIn("name", response.context["form"].errors)

    def test_the_phone_number_cannot_be_edited(self):
        """It identifies the account; changing it would orphan the history."""

        self.signup()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})

        self.client.post("/citizen/profile/", {
            "name": "Sita",
            "ward": 3,
            "phone": "9800000009",
        })

        citizen = Citizen.objects.get()

        self.assertEqual(citizen.phone, self.NEW_PHONE)

    def test_profile_requires_signing_in(self):

        response = self.client.get("/citizen/profile/")

        self.assertRedirects(response, "/citizen/login/")

    # ---------- the form autofill the whole account is for ----------

    def test_the_complaint_form_is_prefilled_for_a_signed_in_citizen(self):

        self.signup()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})
        self.client.post("/citizen/profile/", {
            "name": "Sita Gurung",
            "address": "Ghachok-4",
            "ward": 3,
        })

        response = self.client.get("/complaint/register/")

        initial = response.context["form"].initial

        self.assertEqual(initial["citizen_name"], "Sita Gurung")
        self.assertEqual(initial["phone"], self.NEW_PHONE)
        self.assertEqual(initial["address"], "Ghachok-4")
        self.assertEqual(initial["ward"], 3)
        self.assertTrue(response.context["prefilled"])

    def test_the_form_is_empty_for_someone_not_signed_in(self):

        response = self.client.get("/complaint/register/")

        self.assertEqual(response.context["form"].initial, {})
        self.assertFalse(response.context["prefilled"])

    def test_signing_in_later_picks_up_details_from_past_complaints(self):
        """Someone who filed anonymously first should not retype everything."""

        Complaint.objects.create(
            citizen_name="Ram Bahadur", phone=self.NEW_PHONE,
            address="Lahachok-2", ward=4,
            category="Road", subject="s", description="d",
        )

        self.signup()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})

        citizen = Citizen.objects.get(phone=self.NEW_PHONE)

        self.assertEqual(citizen.name, "Ram Bahadur")
        self.assertEqual(citizen.address, "Lahachok-2")
        self.assertEqual(citizen.ward, 4)

    def test_history_shows_complaints_filed_before_the_account_existed(self):

        Complaint.objects.create(
            citizen_name="Ram", phone=self.NEW_PHONE, ward=4,
            category="Road", subject="Filed anonymously", description="d",
        )

        self.signup()
        self.client.post("/citizen/verify/", {"code": self.latest_code()})

        response = self.client.get("/citizen/complaints/")

        self.assertContains(response, "Filed anonymously")

    # ---------- abuse, now that signup is open ----------

    def test_one_source_cannot_cycle_through_many_numbers(self):
        """Opening signup removed the old guard; this replaces it."""

        limit = settings.OTP_IP_REQUEST_LIMIT

        for i in range(limit):
            self.signup(phone="98000000%02d" % i)

        response = self.signup(phone="9800000099")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            SMSLog.objects.filter(purpose="login_code").count(), limit
        )

    def test_one_number_still_cannot_be_spammed(self):

        limit = settings.OTP_REQUEST_LIMIT

        for _ in range(limit):
            self.signup()

        response = self.signup()

        self.assertEqual(response.status_code, 429)

    def test_an_invalid_number_never_triggers_an_sms(self):

        self.signup(phone="123")

        self.assertEqual(SMSLog.objects.count(), 0)


class LoginCodeVisibilityTests(TestCase):
    """The admin shows login codes only while there is no real SMS gateway."""

    @override_settings(DEBUG=True)
    def test_the_code_is_readable_in_development(self):
        """This is what makes testing possible with the console backend."""

        from .notifications import notify_login_code

        notify_login_code("9814198452", "123456", 5)

        log = SMSLog.objects.get(purpose="login_code")

        self.assertIn("123456", log.message)

    @override_settings(DEBUG=False)
    def test_the_code_is_redacted_in_production(self):
        """A live code sitting in the database is a way in to any account."""

        from .notifications import notify_login_code

        notify_login_code("9814198452", "123456", 5)

        log = SMSLog.objects.get(purpose="login_code")

        self.assertNotIn("123456", log.message)
        self.assertIn("******", log.message)

    @override_settings(DEBUG=False)
    def test_redacting_the_log_does_not_change_what_was_sent(self):
        """The citizen must still receive a usable code."""

        from .notifications import build_otp_message

        self.assertIn("123456", build_otp_message("123456", 5))


class CitizenUpvoteTests(TestCase):

    PHONE = "9814198452"

    def setUp(self):

        cache.clear()

        self.complaint = Complaint.objects.create(
            citizen_name="A", phone=self.PHONE, ward=3,
            category="Road", subject="Pothole", description="d",
        )

        self.url = "/complaints/public/%d/upvote/" % self.complaint.pk

        self.citizen = Citizen.objects.create(phone=self.PHONE)

    def sign_in(self, client):
        session = client.session
        session["citizen_id"] = self.citizen.id
        session.save()

    def test_a_signed_in_citizen_cannot_stack_votes_from_two_devices(self):
        """Session-only deduplication would have counted this twice."""

        from django.test import Client

        phone_browser, laptop = Client(), Client()

        self.sign_in(phone_browser)
        self.sign_in(laptop)

        phone_browser.post(self.url)
        laptop.post(self.url)

        self.assertLessEqual(self.complaint.upvotes.count(), 1)

    def test_the_second_device_knows_the_vote_is_already_cast(self):
        """Otherwise the button invites a press that silently withdraws it."""

        from django.test import Client

        phone_browser, laptop = Client(), Client()

        self.sign_in(phone_browser)
        self.sign_in(laptop)

        phone_browser.post(self.url)

        response = laptop.get(
            "/complaints/public/%d/" % self.complaint.pk
        )

        self.assertTrue(response.context["already_upvoted"])

    def test_anonymous_visitors_can_still_upvote(self):

        self.client.post(self.url)

        self.assertEqual(self.complaint.upvotes.count(), 1)
        self.assertIsNone(self.complaint.upvotes.first().citizen)


# ==================================================
# CITIZEN CONFIRMATION
# ==================================================

class ConfirmationTests(TestCase):

    def setUp(self):

        cache.clear()

        self.ward3 = WardOfficial.create_official(


            ward_number=3,


            full_name="Ghachok",


            username="ward3",


            password="secret3",


        )

        self.complaint = Complaint.objects.create(
            citizen_name="A", phone="9814198452", ward=3,
            category="Road", subject="Pothole", description="d",
            status="Resolved", resolved_at=timezone.now(),
        )

    def confirm(self, answer, reason="", complaint_id=None):

        return self.client.post("/complaint/confirm/", {
            "complaint_id": complaint_id or self.complaint.complaint_id,
            "answer": answer,
            "reason": reason,
        })

    def test_citizen_can_confirm_the_work_is_done(self):

        self.confirm("yes")

        self.complaint.refresh_from_db()

        self.assertIs(self.complaint.citizen_confirmed, True)
        self.assertIsNotNone(self.complaint.confirmed_at)
        self.assertEqual(self.complaint.status, "Resolved")

    def test_disputing_reopens_the_complaint(self):

        self.confirm("no", reason="still broken")

        self.complaint.refresh_from_db()

        self.assertIs(self.complaint.citizen_confirmed, False)
        self.assertEqual(self.complaint.dispute_reason, "still broken")
        self.assertEqual(self.complaint.status, "In Progress")
        self.assertIsNone(self.complaint.resolved_at)

    def test_confirmation_requires_the_complaint_id(self):
        """The ID is the only credential a citizen has; a wrong one must fail."""

        response = self.confirm("yes", complaint_id="MC-DOESNOTEXIST")

        self.complaint.refresh_from_db()

        self.assertIsNone(self.complaint.citizen_confirmed)
        self.assertIsNotNone(response.context["error"])

    def test_cannot_confirm_a_complaint_that_is_not_resolved(self):

        self.complaint.status = "Pending"
        self.complaint.save()

        self.confirm("yes")

        self.complaint.refresh_from_db()

        self.assertIsNone(self.complaint.citizen_confirmed)

    def test_cannot_answer_twice(self):

        self.confirm("yes")
        self.confirm("no", reason="changed my mind")

        self.complaint.refresh_from_db()

        self.assertIs(self.complaint.citizen_confirmed, True)
        self.assertEqual(self.complaint.status, "Resolved")

    def test_get_requests_change_nothing(self):

        self.client.get("/complaint/confirm/")

        self.complaint.refresh_from_db()

        self.assertIsNone(self.complaint.citizen_confirmed)

    def test_reresolving_a_disputed_complaint_asks_again(self):
        """A stale "no" must not block confirming a genuine later fix."""

        self.confirm("no", reason="still broken")

        self.client.post(
            "/ward/login/",
            {"username": "ward3", "password": "secret3"}
        )

        self.client.post(
            "/complaint/%d/update/" % self.complaint.pk,
            {"status": "Resolved", "reply": "fixed properly this time"}
        )

        self.complaint.refresh_from_db()

        self.assertIsNone(self.complaint.citizen_confirmed)
        self.assertEqual(self.complaint.dispute_reason, "")
        self.assertTrue(self.complaint.awaiting_confirmation)

    def test_tracking_page_offers_the_choice_while_awaiting(self):

        response = self.client.post(
            "/complaint/track/",
            {"complaint_id": self.complaint.complaint_id}
        )

        self.assertContains(response, "/complaint/confirm/")
        self.assertContains(response, 'value="yes"')
        self.assertContains(response, 'value="no"')

    def test_tracking_page_hides_the_choice_once_answered(self):

        self.confirm("yes")

        response = self.client.post(
            "/complaint/track/",
            {"complaint_id": self.complaint.complaint_id}
        )

        self.assertNotContains(response, "/complaint/confirm/")

    def test_resolved_sms_asks_for_confirmation(self):

        from .notifications import build_status_message

        message = build_status_message(self.complaint)

        self.assertIn("पुष्टि", message)
        self.assertEqual(count_segments(message), 1)

    def test_ranking_reports_confirmed_and_disputed_separately(self):

        self.confirm("yes")

        Complaint.objects.create(
            citizen_name="B", phone="9814198452", ward=3,
            category="Road", subject="Other", description="d",
            status="Resolved", resolved_at=timezone.now(),
        )

        response = self.client.get("/wards/ranking/")

        ward3 = [w for w in response.context["ranked"] if w["number"] == 3][0]

        self.assertEqual(ward3["resolved"], 2)
        self.assertEqual(ward3["confirmed"], 1)
        self.assertEqual(ward3["disputed"], 0)

    def test_disputed_work_stops_counting_as_resolved(self):
        """The accountability payoff: a disputed fix leaves the resolved count."""

        before = self.client.get("/wards/ranking/")
        ward3_before = [
            w for w in before.context["ranked"] if w["number"] == 3
        ][0]

        self.confirm("no", reason="not fixed")

        after = self.client.get("/wards/ranking/")
        ward3_after = [
            w for w in after.context["ranked"] if w["number"] == 3
        ][0]

        self.assertEqual(ward3_before["resolved"], 1)
        self.assertEqual(ward3_after["resolved"], 0)
        self.assertEqual(ward3_after["disputed"], 1)
        self.assertEqual(ward3_after["rate"], 0)


# ==================================================
# PUBLIC BOARD
# ==================================================

class PublicBoardPrivacyTests(TestCase):

    def setUp(self):

        self.complaint = Complaint.objects.create(
            citizen_name="Sita Gurung",
            phone="9814198452",
            address="Ghachok-4",
            ward=3,
            category="Road",
            subject="Broken road",
            description="The road is broken.",
        )

    def test_phone_and_address_never_appear_on_the_list(self):

        response = self.client.get("/complaints/public/")

        self.assertNotContains(response, "9814198452")
        self.assertNotContains(response, "Ghachok-4")

    def test_phone_and_address_never_appear_on_the_detail_page(self):

        response = self.client.get(
            "/complaints/public/%d/" % self.complaint.pk
        )

        self.assertNotContains(response, "9814198452")
        self.assertNotContains(response, "Ghachok-4")

    def test_name_is_hidden_unless_the_citizen_opted_in(self):

        response = self.client.get("/complaints/public/")

        self.assertNotContains(response, "Sita Gurung")
        self.assertContains(response, "अज्ञात नागरिक")

    def test_name_is_shown_when_the_citizen_opted_in(self):

        self.complaint.show_name = True
        self.complaint.save()

        response = self.client.get("/complaints/public/")

        self.assertContains(response, "Sita Gurung")

    def test_existing_complaints_default_to_public_and_anonymous(self):
        """Matches the decision taken for the rows filed before this feature."""

        self.assertTrue(self.complaint.is_public)
        self.assertFalse(self.complaint.show_name)
        self.assertEqual(self.complaint.public_author, "अज्ञात नागरिक")

    def test_citizen_can_keep_a_complaint_off_the_board(self):

        self.complaint.is_public = False
        self.complaint.save()

        listing = self.client.get("/complaints/public/")
        detail = self.client.get("/complaints/public/%d/" % self.complaint.pk)

        self.assertNotContains(listing, "Broken road")
        self.assertEqual(detail.status_code, 404)


class UpvoteTests(TestCase):

    def setUp(self):

        self.complaint = Complaint.objects.create(
            citizen_name="A", phone="9814198452", ward=3,
            category="Road", subject="Pothole", description="d",
        )

        self.url = "/complaints/public/%d/upvote/" % self.complaint.pk

    def test_a_visitor_can_upvote(self):

        self.client.post(self.url)

        self.assertEqual(self.complaint.upvotes.count(), 1)

    def test_the_same_visitor_cannot_stack_upvotes(self):

        self.client.post(self.url)
        self.client.post(self.url)
        self.client.post(self.url)

        # Second press removes it, third adds it back: never more than one.
        self.assertEqual(self.complaint.upvotes.count(), 1)

    def test_pressing_again_withdraws_support(self):

        self.client.post(self.url)
        self.client.post(self.url)

        self.assertEqual(self.complaint.upvotes.count(), 0)

    def test_different_visitors_each_count(self):

        from django.test import Client

        Client().post(self.url)
        Client().post(self.url)

        self.assertEqual(self.complaint.upvotes.count(), 2)

    def test_get_requests_do_not_change_anything(self):
        """A crawler following links must not be able to vote."""

        self.client.get(self.url)

        self.assertEqual(self.complaint.upvotes.count(), 0)

    def test_cannot_upvote_a_hidden_complaint(self):

        self.complaint.hidden_by_office = True
        self.complaint.save()

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.complaint.upvotes.count(), 0)

    def test_redirect_target_cannot_be_an_external_site(self):

        response = self.client.post(
            self.url,
            {"next": "https://evil.example.com/"}
        )

        self.assertNotIn("evil.example.com", response["Location"])

    def test_popular_sort_puts_the_most_backed_first(self):

        from django.test import Client

        quiet = Complaint.objects.create(
            citizen_name="B", phone="9814198452", ward=3,
            category="Road", subject="Quiet", description="d",
        )

        Client().post(self.url)
        Client().post(self.url.replace(str(self.complaint.pk), str(quiet.pk)))
        Client().post(self.url)

        response = self.client.get("/complaints/public/?sort=popular")

        subjects = [c.subject for c in response.context["complaints"]]

        self.assertEqual(subjects[0], "Pothole")


class ModerationTests(TestCase):

    def setUp(self):

        cache.clear()

        self.ward3 = WardOfficial.create_official(


            ward_number=3,


            full_name="Ghachok",


            username="ward3",


            password="secret3",


        )

        self.complaint = Complaint.objects.create(
            citizen_name="A", phone="9814198452", ward=3,
            category="Road", subject="Offensive", description="d",
        )

        self.client.post(
            "/ward/login/",
            {"username": "ward3", "password": "secret3"}
        )

    def test_office_can_hide_a_complaint_from_the_board(self):

        self.client.post(
            "/complaint/%d/visibility/" % self.complaint.pk,
            {"reason": "personal attack"}
        )

        self.complaint.refresh_from_db()

        self.assertTrue(self.complaint.hidden_by_office)
        self.assertEqual(self.complaint.hidden_reason, "personal attack")

        listing = self.client.get("/complaints/public/")
        self.assertNotContains(listing, "Offensive")

    def test_hiding_is_reversible(self):

        url = "/complaint/%d/visibility/" % self.complaint.pk

        self.client.post(url, {"reason": "mistake"})
        self.client.post(url)

        self.complaint.refresh_from_db()

        self.assertFalse(self.complaint.hidden_by_office)
        self.assertEqual(self.complaint.hidden_reason, "")

    def test_an_office_cannot_moderate_another_wards_complaint(self):

        other = Complaint.objects.create(
            citizen_name="B", phone="9814198452", ward=7,
            category="Road", subject="Other ward", description="d",
        )

        response = self.client.post(
            "/complaint/%d/visibility/" % other.pk,
            {"reason": "meddling"}
        )

        other.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertFalse(other.hidden_by_office)

    def test_anonymous_visitors_cannot_moderate(self):

        self.client.logout()
        self.client.cookies.clear()

        self.client.post(
            "/complaint/%d/visibility/" % self.complaint.pk,
            {"reason": "nope"}
        )

        self.complaint.refresh_from_db()

        self.assertFalse(self.complaint.hidden_by_office)


# ==================================================
# PAGINATION AND FILTERING
# ==================================================

class PaginationTests(TestCase):

    def setUp(self):

        cache.clear()

        for i in range(30):
            Complaint.objects.create(
                citizen_name="A", phone="9814198452", ward=3,
                category="Road", subject="Complaint %02d" % i,
                description="d",
            )

    def test_public_board_does_not_dump_every_complaint(self):

        response = self.client.get("/complaints/public/")

        self.assertEqual(len(response.context["complaints"]), 12)
        self.assertEqual(response.context["page_obj"].paginator.count, 30)
        self.assertEqual(response.context["total_public"], 30)

    def test_later_pages_hold_the_remainder(self):

        page3 = self.client.get("/complaints/public/?page=3")

        self.assertEqual(len(page3.context["complaints"]), 6)
        self.assertFalse(page3.context["page_obj"].has_next())

    def test_pages_do_not_overlap(self):

        first = {
            c.pk for c in
            self.client.get("/complaints/public/?page=1").context["complaints"]
        }
        second = {
            c.pk for c in
            self.client.get("/complaints/public/?page=2").context["complaints"]
        }

        self.assertEqual(first & second, set())

    def test_a_nonsense_page_number_does_not_error(self):

        for value in ["0", "-1", "999", "abc", ""]:
            with self.subTest(page=value):
                response = self.client.get("/complaints/public/?page=%s" % value)
                self.assertEqual(response.status_code, 200)

    def test_filters_survive_paging(self):
        """Page 2 of a filtered search must stay filtered."""

        Complaint.objects.create(
            citizen_name="A", phone="9814198452", ward=7,
            category="Water", subject="Different ward", description="d",
        )

        response = self.client.get("/complaints/public/?ward=3&sort=recent")

        querystring = response.context["querystring"]

        self.assertIn("ward=3", querystring)
        self.assertIn("sort=recent", querystring)
        self.assertNotIn("page=", querystring)

        page2 = self.client.get("/complaints/public/?ward=3&sort=recent&page=2")

        self.assertTrue(
            all(c.ward == 3 for c in page2.context["complaints"])
        )

    def test_public_board_query_count_does_not_grow_with_data(self):
        """Paging must not reintroduce a per-row query."""

        with self.assertNumQueries(2):
            self.client.get("/complaints/public/")

        for i in range(60):
            Complaint.objects.create(
                citizen_name="A", phone="9814198452", ward=5,
                category="Road", subject="More %02d" % i, description="d",
            )

        with self.assertNumQueries(2):
            self.client.get("/complaints/public/")


class WardDashboardFilterTests(TestCase):

    def setUp(self):

        cache.clear()

        self.ward3 = WardOfficial.create_official(


            ward_number=3,


            full_name="Ghachok",


            username="ward3",


            password="a-good-long-password",


        )

        for i in range(25):
            Complaint.objects.create(
                citizen_name="Sita" if i % 2 else "Ram",
                phone="9814198452", ward=3,
                category="Water" if i % 3 else "Road",
                subject="Issue %02d" % i, description="d",
                status="Resolved" if i % 5 == 0 else "Pending",
            )

        self.client.post(
            "/ward/login/",
            {"username": "ward3", "password": "a-good-long-password"}
        )

    def test_dashboard_is_paginated(self):

        response = self.client.get("/ward/dashboard/")

        self.assertEqual(len(response.context["complaints"]), 20)
        self.assertEqual(response.context["page_obj"].paginator.count, 25)

    def test_tiles_describe_the_whole_ward_not_the_filter(self):
        """A filtered table must not make the ward look smaller than it is."""

        response = self.client.get("/ward/dashboard/?status=Resolved")

        self.assertEqual(response.context["total"], 25)
        self.assertEqual(response.context["filtered_count"], 5)

    def test_search_matches_name_and_subject(self):

        by_subject = self.client.get("/ward/dashboard/?q=Issue 03")
        by_name = self.client.get("/ward/dashboard/?q=Sita")

        self.assertEqual(by_subject.context["filtered_count"], 1)
        self.assertGreater(by_name.context["filtered_count"], 0)

    def test_search_matches_the_tracking_id(self):

        complaint = Complaint.objects.filter(ward=3).first()

        response = self.client.get(
            "/ward/dashboard/?q=%s" % complaint.complaint_id
        )

        self.assertEqual(response.context["filtered_count"], 1)

    def test_category_filter_applies(self):

        response = self.client.get("/ward/dashboard/?category=Road")

        self.assertTrue(
            all(c.category == "Road" for c in response.context["complaints"])
        )

    def test_a_bogus_filter_value_is_ignored_not_applied(self):

        response = self.client.get(
            "/ward/dashboard/?status=Hacked&category=Nonsense"
        )

        self.assertEqual(response.context["filtered_count"], 25)

    def test_filtering_never_reaches_another_ward(self):

        Complaint.objects.create(
            citizen_name="Other", phone="9814198452", ward=7,
            category="Road", subject="Issue 99", description="d",
        )

        response = self.client.get("/ward/dashboard/?q=Issue 99")

        self.assertEqual(response.context["filtered_count"], 0)


# ==================================================
# PUBLIC RANKING
# ==================================================

class WardRankingTests(TestCase):

    def make(self, ward, status, resolved_days_ago=None):

        complaint = Complaint.objects.create(
            citizen_name="A", phone="9814198452", ward=ward,
            category="Road", subject="s", description="d", status=status,
        )

        if resolved_days_ago is not None:

            now = timezone.now()

            Complaint.objects.filter(pk=complaint.pk).update(
                created_at=now - timedelta(days=resolved_days_ago),
                resolved_at=now,
            )

        return complaint

    def test_rate_volume_and_average_time(self):

        self.make(1, "Resolved", resolved_days_ago=2)
        self.make(1, "Resolved", resolved_days_ago=4)
        self.make(1, "Pending")

        response = self.client.get("/wards/ranking/")

        ward1 = [w for w in response.context["ranked"] if w["number"] == 1][0]

        self.assertEqual(ward1["total"], 3)
        self.assertEqual(ward1["resolved"], 2)
        self.assertAlmostEqual(ward1["rate"], 66.666, places=2)
        self.assertAlmostEqual(ward1["avg_days"], 3.0, places=2)

    def test_wards_without_complaints_are_unranked_not_zero(self):

        self.make(1, "Pending")

        response = self.client.get("/wards/ranking/")

        self.assertEqual(len(response.context["unranked"]), 8)
        self.assertIsNone(response.context["unranked"][0]["rate"])

    def test_equal_rates_are_broken_by_volume(self):

        self.make(1, "Pending")
        self.make(2, "Pending")
        self.make(2, "Pending")

        response = self.client.get("/wards/ranking/")

        order = [w["number"] for w in response.context["ranked"]]

        # Both sit at 0%; the ward carrying more complaints ranks higher.
        self.assertEqual(order, [2, 1])

    def test_totals_match_the_complaint_table(self):

        self.make(1, "Resolved")
        self.make(2, "Pending")
        self.make(3, "In Progress")

        totals = self.client.get("/wards/ranking/").context["totals"]

        self.assertEqual(totals["total"], Complaint.objects.count())
        self.assertEqual(totals["resolved"], 1)
        self.assertAlmostEqual(totals["rate"], 100 / 3, places=2)

    def test_page_stays_at_two_queries_regardless_of_volume(self):

        for ward in range(1, 10):
            for _ in range(3):
                self.make(ward, "Resolved")

        with self.assertNumQueries(2):
            self.client.get("/wards/ranking/")
