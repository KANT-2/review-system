import random
import sys
from datetime import timedelta

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from accounts.models import EmailVerificationCode, canonicalize_email

# Windows 콘솔 인코딩(cp949)의 이모지 출력 시 UnicodeEncodeError 방어
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _safe_send_mail(msg):
    """콘솔 인코딩 에러를 안전하게 예방하며 메일을 발송합니다."""
    try:
        return msg.send(fail_silently=False)
    except UnicodeEncodeError:
        return msg.send(fail_silently=True)
    except Exception:
        return msg.send(fail_silently=True)


def generate_random_6digit_code():
    """6자리 무작위 숫자 난수 생성"""
    return str(random.randint(100000, 999999))


def send_email_verification_code(email, purpose):
    """
    6자리 본인 인증 코드를 생성하여 지정된 이메일로 HTML 메일을 발송합니다.
    유효기간은 5분입니다.
    """
    clean_email = canonicalize_email(email)
    code = generate_random_6digit_code()
    expires_at = timezone.now() + timedelta(minutes=5)

    # 기존 미인증 코드 덮어쓰기 또는 새로 저장
    verification = EmailVerificationCode.objects.create(
        email=clean_email,
        code=code,
        purpose=purpose,
        is_verified=False,
        expires_at=expires_at,
    )

    purpose_text_map = {
        EmailVerificationCode.Purpose.SIGNUP: "회원가입 본인 인증",
        EmailVerificationCode.Purpose.PASSWORD_RESET: "비밀번호 재설정 본인 인증",
    }
    purpose_text = purpose_text_map.get(purpose, "본인 인증")

    subject = f"[AX 평가 시스템] {purpose_text} 인증코드: [{code}]"

    html_content = render_to_string(
        "emails/verification_code.html",
        {
            "title": subject,
            "purpose_text": purpose_text,
            "code": code,
        },
    )
    text_content = strip_tags(html_content)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,  # DEFAULT_FROM_EMAIL 사용
        to=[clean_email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send()

    return verification


def verify_email_code(email, code, purpose):
    """
    입력된 6자리 인증코드가 5분 이내의 올바른 코드인지 검증합니다.
    성공 시 is_verified를 True로 변경하고 True를 반환합니다.
    """
    clean_email = canonicalize_email(email)
    now = timezone.now()

    verification = (
        EmailVerificationCode.objects.filter(
            email=clean_email,
            code=str(code).strip(),
            purpose=purpose,
            is_verified=False,
            expires_at__gte=now,
        )
        .order_by("-created_at")
        .first()
    )

    if not verification:
        return False

    verification.is_verified = True
    verification.save(update_fields=["is_verified"])
    return True


def check_email_is_verified(email, purpose):
    """
    최근 30분 내에 해당 이메일이 해당 목적(SIGNUP/PASSWORD_RESET)으로 성공적으로 인증 완료되었는지 확인합니다.
    """
    clean_email = canonicalize_email(email)
    valid_threshold = timezone.now() - timedelta(minutes=30)

    return EmailVerificationCode.objects.filter(
        email=clean_email,
        purpose=purpose,
        is_verified=True,
        created_at__gte=valid_threshold,
    ).exists()


def send_tutor_announcement_email(
    subject, message, recipient_emails, dashboard_url="http://127.0.0.1:8000/"
):
    """
    튜터/관리자가 지정된 수강생/조 수신자 목록에게 커스텀 공지 메일을 발송합니다.
    """
    clean_emails = [canonicalize_email(e) for e in recipient_emails if e]
    if not clean_emails:
        return 0

    full_subject = f"[AX 평가 공지] {subject}"
    html_content = render_to_string(
        "emails/custom_announcement.html",
        {
            "subject": subject,
            "message": message,
            "dashboard_url": dashboard_url,
        },
    )
    text_content = strip_tags(html_content)

    msg = EmailMultiAlternatives(
        subject=full_subject,
        body=text_content,
        from_email=None,
        bcc=clean_emails,  # Bcc로 안전하게 발송
    )
    msg.attach_alternative(html_content, "text/html")
    return _safe_send_mail(msg)


def send_round_started_email(
    evaluation_round, recipient_emails, evaluation_url="http://127.0.0.1:8000/"
):
    """
    평가 회차가 '진행 중'으로 변경되었을 때 대상 수강생들에게 개시 알림 메일을 발송합니다.
    """
    clean_emails = [canonicalize_email(e) for e in recipient_emails if e]
    if not clean_emails:
        return 0

    subject = f"[AX 평가 시작] '{evaluation_round.title}' 회차 평가가 개시되었습니다!"
    html_content = render_to_string(
        "emails/round_started.html",
        {
            "round_title": evaluation_round.title,
            "assignment_name": evaluation_round.title,
            "evaluation_url": evaluation_url,
        },
    )
    text_content = strip_tags(html_content)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,
        bcc=clean_emails,
    )
    msg.attach_alternative(html_content, "text/html")
    return _safe_send_mail(msg)


def send_results_released_email(
    evaluation_round, recipient_emails, result_url="http://127.0.0.1:8000/"
):
    """
    평가 성적/피드백이 '공개' 상태로 변경되었을 때 수강생들에게 알림 메일을 발송합니다.
    """
    clean_emails = [canonicalize_email(e) for e in recipient_emails if e]
    if not clean_emails:
        return 0

    subject = f"[AX 성적 공개] '{evaluation_round.title}' 최종 성적 및 피드백이 공개되었습니다!"
    html_content = render_to_string(
        "emails/results_released.html",
        {
            "round_title": evaluation_round.title,
            "result_url": result_url,
        },
    )
    text_content = strip_tags(html_content)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,
        bcc=clean_emails,
    )
    msg.attach_alternative(html_content, "text/html")
    return _safe_send_mail(msg)


def send_submission_reminder_email(
    evaluation_round, student_name, student_email, evaluation_url="http://127.0.0.1:8000/"
):
    """
    특정 미제출 수강생에게 제출 독촉 알림 메일을 발송합니다.
    """
    clean_email = canonicalize_email(student_email)
    subject = f"[AX 평가 안내] '{evaluation_round.title}' 평가 제출 안내"
    html_content = render_to_string(
        "emails/submission_reminder.html",
        {
            "student_name": student_name,
            "round_title": evaluation_round.title,
            "evaluation_url": evaluation_url,
        },
    )
    text_content = strip_tags(html_content)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=None,
        to=[clean_email],
    )
    msg.attach_alternative(html_content, "text/html")
    return _safe_send_mail(msg)
