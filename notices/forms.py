from django import forms

from notices.models import Notice


class NoticeForm(forms.ModelForm):
    class Meta:
        model = Notice
        fields = ("title", "content", "is_published")
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "예: 8주차 평가 일정 변경 안내"}
            ),
            "content": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "is_published": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {"title": "제목", "content": "내용", "is_published": "바로 공개"}
