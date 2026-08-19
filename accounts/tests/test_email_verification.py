from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from accounts.email_services import (
    check_email_is_verified,
    send_email_verification_code,
    verify_email_code,
)
from accounts.models import EmailVerificationCode


class EmailVerificationServiceTestCase(TestCase):
    def test_send_email_verification_code_creates_record_and_sends_email(self):
        email = "teststudent@example.com"
        purpose = EmailVerificationCode.Purpose.SIGNUP

        verification = send_email_verification_code(email, purpose)

        self.assertIsNotNone(verification)
        self.assertEqual(verification.email, email)
        self.assertEqual(len(verification.code), 6)
        self.assertFalse(verification.is_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(verification.code, mail.outbox[0].subject)

    def test_verify_email_code_success(self):
        email = "student2@example.com"
        purpose = EmailVerificationCode.Purpose.PASSWORD_RESET

        verification = send_email_verification_code(email, purpose)
        code = verification.code

        success = verify_email_code(email, code, purpose)
        self.assertTrue(success)

        verification.refresh_from_db()
        self.assertTrue(verification.is_verified)
        self.assertTrue(check_email_is_verified(email, purpose))

    def test_verify_email_code_expired_fails(self):
        email = "expiredstudent@example.com"
        purpose = EmailVerificationCode.Purpose.SIGNUP

        verification = send_email_verification_code(email, purpose)
        verification.expires_at = timezone.now() - timedelta(minutes=1)
        verification.save()

        success = verify_email_code(email, verification.code, purpose)
        self.assertFalse(success)
