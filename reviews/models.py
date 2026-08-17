from django.db import models
from django.conf import settings

class Review(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='received_reviews',
        verbose_name='학생'
    )
    tutor = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='written_reviews',
        verbose_name='튜터'
    )
    title = models.CharField(max_length=255, verbose_name='피드백 제목')
    content = models.TextField(verbose_name='피드백 내용')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='작성일')

    class Meta:
        db_table = 'reviews'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.email}님을 위한 피드백: {self.title}"