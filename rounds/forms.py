from django import forms

from accounts.models import User
from rounds.models import EvaluationRound, QuestionTemplate, TemplateQuestion


class EvaluationRoundForm(forms.ModelForm):
    """회차 기본 정보 폼.

    참가 수강생은 화면에서 고르지 않는다 - 승인된 활성 수강생 전원이 자동으로 참가자가 된다.
    필드 자체는 save_round가 쓰기 때문에 남겨 두되, 값은 clean에서 서버가 채운다.
    """

    participants = forms.ModelMultipleChoiceField(
        label="참가 수강생",
        queryset=User.objects.none(),
        required=False,
        widget=forms.MultipleHiddenInput,
    )

    class Meta:
        model = EvaluationRound
        fields = (
            "title",
            "description",
            "evaluation_start_at",
            "evaluation_end_at",
            "team_template",
            "peer_template",
            "team_score_weight",
            "personal_score_weight",
            "tutor_score_weight",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "evaluation_start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "evaluation_end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "team_score_weight": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "personal_score_weight": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "tutor_score_weight": forms.NumberInput(attrs={"min": 0, "max": 100}),
        }
        labels = {
            "title": "회차 제목",
            "description": "설명",
            "evaluation_start_at": "평가 시작",
            "evaluation_end_at": "평가 종료",
            "team_template": "팀 평가 템플릿",
            "peer_template": "개인 평가 템플릿",
            "team_score_weight": "팀 점수 비율(%)",
            "personal_score_weight": "개인 점수 비율(%)",
            "tutor_score_weight": "튜터 점수 비율(%)",
        }
        help_texts = {
            "tutor_score_weight": "0%면 튜터 점수를 최종 점수에 반영하지 않습니다. 세 비율의 합은 100%여야 합니다.",
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
        # 세 비율 필드는 옛 폼(비율 필드가 없던 시절)이 보낸 요청도 계속 통과해야 하므로
        # 필수로 두지 않는다 - 값이 안 오면 clean()에서 모델 기본값(40/60/0) 또는 기존 값으로
        # 채운다.
        for weight_field in ("team_score_weight", "personal_score_weight", "tutor_score_weight"):
            self.fields[weight_field].required = False
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs.setdefault(
                    "class",
                    "form-select" if isinstance(field.widget, forms.Select) else "form-control",
                )

    def clean(self):
        cleaned = super().clean()
        # 화면에서 온 값은 무시하고 승인된 활성 수강생 전원으로 다시 채운다.
        user_ids = set(self.fields["participants"].queryset.values_list("pk", flat=True))
        if self.instance.pk:
            # 이미 참가 중인 사람은 승인·활성 상태가 바뀌었더라도 빼지 않는다. 팀에 배정된
            # 참가자는 삭제 자체가 막히고(TeamMembership PROTECT), 팀 배정을 조용히 잃는
            # 것도 곤란하다 - 내보내려면 팀 편성에서 먼저 빼야 한다.
            user_ids |= set(self.instance.participants.values_list("user_id", flat=True))
        cleaned["participants"] = User.objects.filter(pk__in=user_ids)
        for weight_field in ("team_score_weight", "personal_score_weight", "tutor_score_weight"):
            if cleaned.get(weight_field) is None:
                default = (
                    getattr(self.instance, weight_field)
                    if self.instance.pk
                    else EvaluationRound._meta.get_field(weight_field).default
                )
                cleaned[weight_field] = default
        return cleaned


class QuestionTemplateForm(forms.ModelForm):
    """템플릿 기본 정보 폼.

    평가 유형은 빈 선택("---------") 없이 팀 평가를 기본값으로 둔다 - 유형을 고르지 않은
    템플릿은 어차피 저장할 수 없어서 빈 선택지가 실수만 늘린다.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        category = self.fields["category"]
        category.choices = QuestionTemplate.Category.choices
        if not self.instance.pk:
            category.initial = QuestionTemplate.Category.TEAM

    class Meta:
        model = QuestionTemplate
        fields = ("name", "description", "category")
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "예: 5기 팀 평가"}
            ),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "category": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {"name": "템플릿 이름", "description": "설명", "category": "평가 유형"}


class TemplateQuestionForm(forms.ModelForm):
    """문항 한 줄. 순서는 화면에 나온 순서대로 저장 시 다시 매긴다.

    빈 줄은 그냥 무시한다 - 응답 형식 select는 브라우저가 항상 값을 보내므로, 문항을 비워 둔
    여유 줄까지 "필수 항목" 오류를 내면 화면을 쓸 수 없다.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prompt"].required = False
        self.fields["competency"].choices = [
            ("", "역량 미지정")
        ] + TemplateQuestion.Competency.choices
        if not self.instance.pk:
            # 새 줄은 1~5점을 기본으로 둔다 - 점수 문항이 하나도 없으면 회차를 시작할 수 없다.
            self.fields["response_type"].initial = TemplateQuestion.ResponseType.RATING_5

    def _post_clean(self):
        # 문항을 비워 둔 줄은 저장하지 않으므로 모델 검증(TemplateQuestion.clean)도 건너뛴다.
        if not (self.cleaned_data.get("prompt") or "").strip():
            return
        super()._post_clean()

    class Meta:
        model = TemplateQuestion
        fields = ("prompt", "response_type", "competency", "is_required")
        widgets = {
            "prompt": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "예: 결과물의 완성도는 충분한가요?"}
            ),
            "response_type": forms.Select(attrs={"class": "form-select"}),
            "competency": forms.Select(attrs={"class": "form-select"}),
            "is_required": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "prompt": "문항",
            "response_type": "응답 형식",
            "competency": "역량",
            "is_required": "필수",
        }


class BaseTemplateQuestionFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        filled = [
            form
            for form in self.forms
            if form.cleaned_data
            and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("prompt")
        ]
        if not filled:
            raise forms.ValidationError("문항을 한 개 이상 입력해 주세요.")


TemplateQuestionFormSet = forms.inlineformset_factory(
    QuestionTemplate,
    TemplateQuestion,
    form=TemplateQuestionForm,
    formset=BaseTemplateQuestionFormSet,
    extra=3,
    can_delete=True,
)
