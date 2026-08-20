import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.template.loader import get_template
from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

from deploy.render_production_env import render


class HomePageTests(SimpleTestCase):
    def test_home_page_sends_anonymous_user_to_login(self):
        response = self.client.get(reverse("home"))

        self.assertRedirects(response, reverse("accounts:login"))


class ErrorPageTests(SimpleTestCase):
    @override_settings(DEBUG=False)
    def test_unknown_address_renders_error_page(self):
        """DEBUG=False일 때만 오류 템플릿이 쓰이므로 그 조건에서 확인한다."""
        response = self.client.get("/definitely-not-a-real-page/")

        self.assertContains(response, "페이지를 찾을 수 없습니다", status_code=404)

    def test_csrf_failure_renders_error_page(self):
        """만료된 폼을 제출했을 때 Django 기본 영문 화면 대신 우리 화면이 나와야 한다."""
        strict_client = Client(enforce_csrf_checks=True)

        response = strict_client.post(reverse("accounts:login"), {"email": "", "password": ""})

        self.assertContains(response, "보안 확인에 실패했습니다", status_code=403)

    def test_error_templates_render_without_request_context(self):
        """500 화면은 요청 객체 없이 그려진다 - user·messages에 기대면 여기서 깨진다."""
        headings = {
            "400.html": "잘못된 요청입니다",
            "403.html": "접근 권한이 없습니다",
            "404.html": "페이지를 찾을 수 없습니다",
            "500.html": "서버에 문제가 생겼습니다",
            "403_csrf.html": "보안 확인에 실패했습니다",
        }

        for template_name, heading in headings.items():
            with self.subTest(template=template_name):
                self.assertIn(heading, get_template(template_name).render())


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

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            self.assertEqual(production_security_checks(None), [])

    def test_unwritable_media_root_fails_closed(self):
        """업로드 경로가 없으면 프로필 사진 저장이 500이 되므로 배포 전에 막는다."""
        from accounts.checks import production_security_checks

        with tempfile.TemporaryDirectory() as parent:
            with self.settings(MEDIA_ROOT=str(Path(parent) / "missing-media")):
                error_ids = {error.id for error in production_security_checks(None)}

        self.assertIn("accounts.E009", error_ids)


class ProductionEnvironmentRenderTests(SimpleTestCase):
    def test_renders_google_oauth_secrets_without_logging_them(self):
        template = "\n".join(
            (
                "DJANGO_SECRET_KEY=placeholder",
                "POSTGRES_PASSWORD=placeholder",
                "DJANGO_EMAIL_HOST_PASSWORD=placeholder",
                "GOOGLE_OAUTH_CLIENT_ID=",
                "GOOGLE_OAUTH_CLIENT_SECRET=",
                "KAKAO_OAUTH_CLIENT_ID=",
                "KAKAO_OAUTH_CLIENT_SECRET=",
            )
        )
        secrets = {
            "DJANGO_SECRET_KEY": "d" * 64,
            "POSTGRES_PASSWORD": "p" * 48,
            "DJANGO_EMAIL_HOST_PASSWORD": "e" * 32,
            "GOOGLE_OAUTH_CLIENT_ID": f"{'1' * 24}.apps.googleusercontent.com",
            "GOOGLE_OAUTH_CLIENT_SECRET": "oauth-secret-with_symbols-123",
            "KAKAO_OAUTH_CLIENT_ID": "a" * 32,
            "KAKAO_OAUTH_CLIENT_SECRET": "kakao-login-secret-with-symbols",
        }

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, secrets, clear=False),
        ):
            template_path = Path(directory) / "template.env"
            output_path = Path(directory) / "production.env"
            template_path.write_text(template, encoding="utf-8")

            render(template_path, output_path)

            rendered = output_path.read_text(encoding="utf-8")
            self.assertIn(f"GOOGLE_OAUTH_CLIENT_ID={secrets['GOOGLE_OAUTH_CLIENT_ID']}", rendered)
            self.assertIn(
                f"GOOGLE_OAUTH_CLIENT_SECRET={secrets['GOOGLE_OAUTH_CLIENT_SECRET']}", rendered
            )
            self.assertIn(f"KAKAO_OAUTH_CLIENT_ID={secrets['KAKAO_OAUTH_CLIENT_ID']}", rendered)
            self.assertIn(
                f"KAKAO_OAUTH_CLIENT_SECRET={secrets['KAKAO_OAUTH_CLIENT_SECRET']}", rendered
            )
            self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)

    def test_rejects_oauth_secret_with_newline(self):
        secrets = {
            "DJANGO_SECRET_KEY": "d" * 64,
            "POSTGRES_PASSWORD": "p" * 48,
            "DJANGO_EMAIL_HOST_PASSWORD": "e" * 32,
            "GOOGLE_OAUTH_CLIENT_ID": f"{'1' * 24}.apps.googleusercontent.com",
            "GOOGLE_OAUTH_CLIENT_SECRET": "valid-prefix-with-newline\nINJECTED=True",
            "KAKAO_OAUTH_CLIENT_ID": "a" * 32,
            "KAKAO_OAUTH_CLIENT_SECRET": "kakao-login-secret-with-symbols",
        }

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, secrets, clear=False),
        ):
            template_path = Path(directory) / "template.env"
            output_path = Path(directory) / "production.env"
            template_path.write_text("GOOGLE_OAUTH_CLIENT_SECRET=\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                render(template_path, output_path)
