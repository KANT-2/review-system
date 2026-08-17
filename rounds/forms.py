from django import forms

from accounts.models import User
from rounds.models import EvaluationRound, QuestionTemplate


class EvaluationRoundForm(forms.ModelForm):
    participants = forms.ModelMultipleChoiceField(
        label="참가 수강생",
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = EvaluationRound
        fields = (
            "title",
            "description",
            "evaluation_start_at",
            "evaluation_end_at",
            "target_team_count",
            "team_template",
            "peer_template",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "evaluation_start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "evaluation_end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
        labels = {
            "title": "회차 제목",
            "description": "설명",
            "evaluation_start_at": "평가 시작",
            "evaluation_end_at": "평가 종료",
            "target_team_count": "목표 팀 수",
            "team_template": "팀 평가 템플릿",
            "peer_template": "개인 평가 템플릿",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["participants"].queryset = User.objects.filter(
            role=User.Role.STUDENT,
            approval_status=User.ApprovalStatus.APPROVED,
            is_active=True,
        ).order_by("first_name", "email")
        self.fields["team_template"].queryset = QuestionTemplate.objects.filter(
            category=QuestionTemplate.Category.TEAM
        )
        self.fields["peer_template"].queryset = QuestionTemplate.objects.filter(
            category=QuestionTemplate.Category.PEER
        )
        if self.instance.pk:
            self.fields["participants"].initial = self.instance.participants.values_list(
                "user_id", flat=True
            )
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs.setdefault(
                    "class",
                    "form-select" if isinstance(field.widget, forms.Select) else "form-control",
                )

    def clean(self):
        cleaned = super().clean()
        participants = cleaned.get("participants")
        team_count = cleaned.get("target_team_count")
        if participants is not None and team_count and team_count > participants.count():
            self.add_error("target_team_count", "팀 수는 참가자 수보다 많을 수 없습니다.")
        return cleaned
