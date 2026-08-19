from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Notice(models.Model):
    title = models.CharField("제목", max_length=200)
    content = models.TextField("내용")
    is_published = models.BooleanField("공개 여부", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notices",
        verbose_name="작성자",
    )
    created_at = models.DateTimeField("작성일", auto_now_add=True)
    updated_at = models.DateTimeField("수정일", auto_now=True)

    class Meta:
        verbose_name = "공지"
        verbose_name_plural = "공지 목록"
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(condition=~Q(title=""), name="notices_title_not_blank"),
            models.CheckConstraint(condition=~Q(content=""), name="notices_content_not_blank"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if not self.title.strip():
            raise ValidationError({"title": "제목을 입력해 주세요."})
        if not self.content.strip():
            raise ValidationError({"content": "내용을 입력해 주세요."})
