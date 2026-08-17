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
    )
    def test_incomplete_oauth_fails_closed(self):
        from accounts.checks import production_security_checks

        error_ids = {error.id for error in production_security_checks(None)}

        self.assertTrue({"accounts.E007", "accounts.E008"} <= error_ids)

    @override_settings(
        DEBUG=False,
        SECRET_KEY="a" * 60,
        ALLOWED_HOSTS=["ax.example.com"],
        SECURE_SSL_REDIRECT=True,
        HTTPS_READY=True,
        SECURE_HSTS_SECONDS=31_536_000,
        TRUST_PROXY_HEADERS=False,
        GOOGLE_OAUTH_REQUESTED=False,
        KAKAO_OAUTH_REQUESTED=False,
    )
    def test_deploy_checks_pass_without_any_mail_configuration(self):
        """메일을 보내지 않는 구성이므로 SMTP 설정이 없어도 배포 검사를 막지 않는다."""
        from accounts.checks import production_security_checks

        self.assertEqual(production_security_checks(None), [])
