"""튜터 메모를 회차 참가자 단위에서 수강생 계정 단위로 옮긴다.

결과·공개 화면에 있던 메모가 수강생 관리 화면으로 이동하면서, 회차마다 따로 남기던 메모를
학생 한 명당 한 건으로 합친다. 같은 학생에게 회차별 메모가 여러 건 있으면 가장 최근에
수정한 것만 남긴다 - 합치는 기준이 필요하고, 최신 메모가 가장 쓸모 있다.

회차별 메모를 되살릴 방법이 없으므로 이 마이그레이션은 되돌릴 수 없다.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def move_notes_to_students(apps, schema_editor):
    TutorNote = apps.get_model("results", "TutorNote")
    keep_ids = []
    seen_user_ids = set()
    for note in TutorNote.objects.select_related("participant").order_by("-updated_at", "-id"):
        user_id = note.participant.user_id
        if user_id in seen_user_ids:
            continue
        seen_user_ids.add(user_id)
        note.student_id = user_id
        note.save(update_fields=["student"])
        keep_ids.append(note.pk)
    TutorNote.objects.exclude(pk__in=keep_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("results", "0003_tutornote"),
        ("rounds", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="tutornote",
            options={"ordering": ("id",)},
        ),
        migrations.AddField(
            model_name="tutornote",
            name="student",
            field=models.OneToOneField(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tutor_note",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(move_notes_to_students, migrations.RunPython.noop),
        migrations.RemoveField(model_name="tutornote", name="participant"),
        migrations.AlterField(
            model_name="tutornote",
            name="student",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tutor_note",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterModelOptions(
            name="tutornote",
            options={"ordering": ("student__email",)},
        ),
    ]
