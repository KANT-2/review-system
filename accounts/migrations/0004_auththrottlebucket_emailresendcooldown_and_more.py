import django.db.models.functions.text
from django.db import migrations, models


def _canonical(email):
    return (email or "").strip().lower()


def _provider_proves_email(social_account, email):
    data = social_account.extra_data or {}
    if social_account.provider == "google":
        verified = data.get("email_verified") is True or data.get("verified_email") is True
        return verified and _canonical(data.get("email")) == email
    if social_account.provider == "kakao":
        account = data.get("kakao_account", {})
        verified = (
            account.get("has_email") is True
            and account.get("email_needs_agreement") is False
            and account.get("is_email_valid") is True
            and account.get("is_email_verified") is True
        )
        return verified and _canonical(account.get("email")) == email
    return False


def preflight_and_sync_auth_data(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    WhitelistEmail = apps.get_model("accounts", "WhitelistEmail")
    EmailAddress = apps.get_model("account", "EmailAddress")
    SocialAccount = apps.get_model("socialaccount", "SocialAccount")

    privileged_whitelist_ids = list(
        WhitelistEmail.objects.exclude(role="student").values_list("pk", flat=True)
    )
    inconsistent_user_ids = list(
        User.objects.exclude(
            models.Q(is_staff=True, role="admin")
            | (models.Q(is_staff=False) & ~models.Q(role="admin"))
        ).values_list("pk", flat=True)
    )
    inconsistent_superuser_ids = list(
        User.objects.filter(is_superuser=True)
        .exclude(is_staff=True, role="admin", approval_status="approved")
        .values_list("pk", flat=True)
    )
    if privileged_whitelist_ids or inconsistent_user_ids or inconsistent_superuser_ids:
        raise RuntimeError(
            "Authentication preflight requires explicit remediation: "
            f"privileged_whitelist_ids={privileged_whitelist_ids}, "
            f"inconsistent_user_ids={inconsistent_user_ids}, "
            f"inconsistent_superuser_ids={inconsistent_superuser_ids}"
        )

    user_emails = {}
    for user_id, email in User.objects.values_list("pk", "email"):
        canonical = _canonical(email)
        if canonical in user_emails:
            raise RuntimeError(
                f"Case-insensitive user email collision IDs: {user_emails[canonical]}, {user_id}"
            )
        user_emails[canonical] = user_id

    whitelist_emails = {}
    for whitelist_id, email in WhitelistEmail.objects.values_list("pk", "email"):
        canonical = _canonical(email)
        if canonical in whitelist_emails:
            raise RuntimeError(
                "Case-insensitive whitelist email collision IDs: "
                f"{whitelist_emails[canonical]}, {whitelist_id}"
            )
        whitelist_emails[canonical] = whitelist_id
        WhitelistEmail.objects.filter(pk=whitelist_id).update(email=canonical)

    for user in User.objects.order_by("pk"):
        canonical = _canonical(user.email)
        addresses = list(EmailAddress.objects.filter(user_id=user.pk).order_by("pk"))
        if len(addresses) > 1:
            raise RuntimeError(f"User ID {user.pk} has multiple email-address rows")
        if addresses and _canonical(addresses[0].email) != canonical:
            raise RuntimeError(f"User ID {user.pk} has a mismatched primary email-address row")
        address = addresses[0] if addresses else EmailAddress(user_id=user.pk, email=canonical)
        social_accounts = SocialAccount.objects.filter(user_id=user.pk)
        provider_evidence = any(
            _provider_proves_email(social_account, canonical) for social_account in social_accounts
        )
        address.email = canonical
        address.primary = True
        address.verified = bool(address.verified and provider_evidence)
        address.save()
        User.objects.filter(pk=user.pk).update(
            email=canonical,
            must_rotate_password=not user.password.startswith("!"),
        )


def create_primary_email_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION accounts_validate_primary_email()
        RETURNS trigger AS $$
        DECLARE
            target_user_id bigint;
            user_email text;
            primary_count integer;
            primary_email text;
        BEGIN
            IF TG_TABLE_NAME = 'accounts_user' THEN
                target_user_id := COALESCE(NEW.id, OLD.id);
            ELSE
                target_user_id := COALESCE(NEW.user_id, OLD.user_id);
            END IF;

            SELECT lower(email) INTO user_email
            FROM accounts_user WHERE id = target_user_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT count(*), min(lower(email)) INTO primary_count, primary_email
            FROM account_emailaddress
            WHERE user_id = target_user_id AND "primary";
            IF primary_count <> 1 OR primary_email IS DISTINCT FROM user_email THEN
                RAISE EXCEPTION 'user %% must have one matching canonical primary email',
                    target_user_id;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER accounts_user_primary_email_check
        AFTER INSERT OR UPDATE OF email ON accounts_user
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION accounts_validate_primary_email();

        CREATE CONSTRAINT TRIGGER accounts_emailaddress_primary_check
        AFTER INSERT OR UPDATE OR DELETE ON account_emailaddress
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION accounts_validate_primary_email();
        """
    )


def drop_primary_email_triggers(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        DROP TRIGGER IF EXISTS accounts_user_primary_email_check ON accounts_user;
        DROP TRIGGER IF EXISTS accounts_emailaddress_primary_check ON account_emailaddress;
        DROP FUNCTION IF EXISTS accounts_validate_primary_email();
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_alter_user_phone_number_alter_user_session_info_and_more"),
        ("account", "0009_emailaddress_unique_primary_email"),
        ("socialaccount", "0006_alter_socialaccount_extra_data"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthThrottleBucket",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("event_kind", models.CharField(max_length=32)),
                ("scope_kind", models.CharField(max_length=16)),
                ("key_digest", models.CharField(max_length=64)),
                ("window_started_at", models.DateTimeField()),
                ("count", models.PositiveIntegerField(default=0)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
        ),
        migrations.CreateModel(
            name="EmailResendCooldown",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("key_digest", models.CharField(max_length=64, unique=True)),
                ("allowed_at", models.DateTimeField(db_index=True)),
            ],
        ),
        migrations.AlterModelOptions(
            name="whitelistemail",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "학생 화이트리스트 이메일",
                "verbose_name_plural": "학생 화이트리스트 이메일 목록",
            },
        ),
        migrations.AddField(
            model_name="user",
            name="auth_session_version",
            field=models.PositiveBigIntegerField(default=0, verbose_name="인증 세션 버전"),
        ),
        migrations.AddField(
            model_name="user",
            name="email_needs_review",
            field=models.BooleanField(default=False, verbose_name="이메일 재확인 필요"),
        ),
        migrations.AddField(
            model_name="user",
            name="must_rotate_password",
            field=models.BooleanField(default=False, verbose_name="비밀번호 변경 필요"),
        ),
        migrations.RunPython(preflight_and_sync_auth_data, migrations.RunPython.noop),
        migrations.RemoveField(model_name="whitelistemail", name="role"),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                name="accounts_user_email_ci_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("is_staff", True), ("role", "admin")),
                    models.Q(("is_staff", False), models.Q(("role", "admin"), _negated=True)),
                    _connector="OR",
                ),
                name="accounts_staff_role_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("is_superuser", False),
                    models.Q(("approval_status", "approved"), ("is_staff", True)),
                    _connector="OR",
                ),
                name="accounts_superuser_authority_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="whitelistemail",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                name="accounts_whitelist_email_ci_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="auththrottlebucket",
            constraint=models.UniqueConstraint(
                fields=("event_kind", "scope_kind", "key_digest", "window_started_at"),
                name="accounts_throttle_bucket_unique",
            ),
        ),
        migrations.RunPython(create_primary_email_triggers, drop_primary_email_triggers),
    ]
