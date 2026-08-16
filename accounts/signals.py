from allauth.account.models import EmailAddress
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User, canonicalize_email


@receiver(post_save, sender=User)
def ensure_primary_email_address(sender, instance, created, raw=False, **kwargs):
    if raw or not created:
        return
    email = canonicalize_email(instance.email)
    address, address_created = EmailAddress.objects.get_or_create(
        email=email,
        defaults={"user": instance, "primary": True, "verified": False},
    )
    if not address_created and address.user_id != instance.pk:
        raise ValueError("이 이메일은 다른 사용자에게 연결되어 있습니다.")
    EmailAddress.objects.filter(user=instance).exclude(pk=address.pk).delete()
    if not address.primary:
        address.primary = True
        address.save(update_fields=["primary"])


@receiver(user_logged_in)
def snapshot_auth_session_version(sender, request, user, **kwargs):
    request.session["auth_session_version"] = user.auth_session_version
