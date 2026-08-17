from django import forms

from rounds.models import TemplateQuestion


class ReviewForm(forms.Form):
    def __init__(self, *args, questions, **kwargs):
        super().__init__(*args, **kwargs)
        self.questions = tuple(questions)
        for question in self.questions:
            field_name = f"question_{question.pk}"
            if question.response_type == TemplateQuestion.ResponseType.RATING_5:
                self.fields[field_name] = forms.TypedChoiceField(
                    label=question.prompt,
                    choices=((value, str(value)) for value in range(1, 6)),
                    coerce=int,
                    widget=forms.RadioSelect,
                    required=question.is_required,
                )
            else:
                self.fields[field_name] = forms.CharField(
                    label=question.prompt,
                    max_length=2000,
                    required=question.is_required,
                    widget=forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
                )

    def answer_values(self):
        return {
            question.pk: self.cleaned_data.get(f"question_{question.pk}")
            for question in self.questions
            if self.cleaned_data.get(f"question_{question.pk}") not in (None, "")
        }
