from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class HomePageTests(SimpleTestCase):
    def test_home_page_sends_anonymous_user_to_login(self):
        response = self.client.get(reverse("home"))

        self.assertRedirects(response, reverse("accounts:login"))


class ProductionCheckTests(SimpleTestCase):
    @override_settings(
        DEBUG=False,
        SECRET_KEY="unsafe",
        ALLOWED_HOSTS=["*"],
        SECURE_SSL_REDIRECT=False,
        HTTPS_READY=False,
        SECURE_HSTS_SECONDS=0,
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
    )
    def test_insecure_production_settings_fail_closed(self):
        from accounts.checks import production_security_checks

        error_ids = {error.id for error in production_security_checks(None)}

        self.assertTrue({"accounts.E002", "accounts.E003", "accounts.E004"} <= error_ids)

    @override_settings(
        DEBUG=False,
        GOOGLE_OAUTH_REQUESTED=True,
        GOOGLE_OAUTH_ENABLED=False,
        KAKAO_OAUTH_REQUESTED=True,
        KAKAO_OAUTH_ENABLED=False,
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.invalid",
        DEFAULT_FROM_EMAIL="AX Console <no-reply@service.test>",
        EMAIL_USE_TLS=True,
        EMAIL_USE_SSL=True,
    )
    def test_incomplete_oauth_and_conflicting_smtp_tls_fail_closed(self):
        from accounts.checks import production_security_checks

        error_ids = {error.id for error in production_security_checks(None)}

        self.assertTrue({"accounts.E007", "accounts.E008", "accounts.E013"} <= error_ids)
