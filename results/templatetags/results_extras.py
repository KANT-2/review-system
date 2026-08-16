from django import template

from results.services import round_to_display

register = template.Library()

_STATUS_LABELS = {
    "COMPLETE": "완료",
    "PARTIAL": "부분",
    "NO_DATA": "무응답",
    "NOT_APPLICABLE": "해당없음",
}

_STATUS_BADGE_CLASSES = {
    "COMPLETE": "ax-badge-complete",
    "PARTIAL": "ax-badge-partial",
    "NO_DATA": "ax-badge-no-data",
    "NOT_APPLICABLE": "ax-badge-not-applicable",
}


@register.filter
def display_score(value):
    """raw 정밀도 Decimal(또는 None)을 표시 정밀도(소수 둘째 자리)로 변환한다. N/A는 그대로 None."""
    if value is None:
        return None
    return round_to_display(value)


@register.filter
def status_label(data_status):
    return _STATUS_LABELS.get(data_status, data_status)


@register.filter
def status_badge_class(data_status):
    return _STATUS_BADGE_CLASSES.get(data_status, "ax-badge-no-data")


@register.filter
def coverage_percent(value):
    """0~1 사이 raw 커버리지 값을 정수 퍼센트 문자열로 변환한다. N/A는 None."""
    if value is None:
        return None
    return int(round(value * 100))
