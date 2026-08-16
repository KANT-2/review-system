from decimal import ROUND_HALF_UP, Decimal

from django import template

register = template.Library()

# 화면에 보여줄 때는 원래 학생이 매긴 1~5점 척도로 되돌려서 소수 첫째 자리까지만 보여준다
# (raw 계산/저장은 0~100점 그대로 유지 - results/services.py는 그대로 둔다. 이건 화면
# 표기 방식만 바꾸는 것).
_FIVE_POINT_DIVISOR = Decimal("20")

_STATUS_LABELS = {
    "COMPLETE": "제출 완료",
    "PARTIAL": "일부 제출",
    "NO_DATA": "미제출",
    "NOT_APPLICABLE": "해당없음",
}

_STATUS_BADGE_CLASSES = {
    "COMPLETE": "ax-badge-complete",
    "PARTIAL": "ax-badge-partial",
    "NO_DATA": "ax-badge-no-data",
    "NOT_APPLICABLE": "ax-badge-not-applicable",
}


@register.filter
def as_five_point(value):
    """raw 0~100점(또는 None)을 화면 표시용 1~5점 척도, 소수 첫째 자리로 변환한다."""
    if value is None:
        return None
    return (Decimal(str(value)) / _FIVE_POINT_DIVISOR).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


@register.filter
def status_label(data_status):
    return _STATUS_LABELS.get(data_status, data_status)


@register.filter
def status_badge_class(data_status):
    return _STATUS_BADGE_CLASSES.get(data_status, "ax-badge-no-data")


@register.filter
def response_rate_percent(value):
    """0~1 사이 raw 응답률 값을 정수 퍼센트로 변환한다. 데이터 없으면 None."""
    if value is None:
        return None
    return int(round(value * 100))
