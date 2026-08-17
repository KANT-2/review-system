from decimal import ROUND_DOWN, Decimal

from django import template

register = template.Library()

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
    """저장된 1~5점 값(또는 None)을 화면용 소수 둘째 자리에서 절사한다."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.00"), rounding=ROUND_DOWN)


@register.filter
def status_label(data_status):
    return _STATUS_LABELS.get(data_status, data_status)


@register.filter
def status_badge_class(data_status):
    return _STATUS_BADGE_CLASSES.get(data_status, "ax-badge-no-data")


@register.filter
def five_point_percent(value):
    """1~5점 점수를 점수 막대 너비(0~100%)로 환산한다. 데이터 없으면 None."""
    if value is None:
        return None
    return int(Decimal(str(value)) / Decimal("5") * 100)


@register.filter
def response_rate_percent(value):
    """0~1 사이 raw 응답률 값을 정수 퍼센트로 변환한다. 데이터 없으면 None."""
    if value is None:
        return None
    return int(round(value * 100))


@register.filter
def get_item(mapping, key):
    """템플릿에서 dict[변수] 형태의 동적 키 조회를 하기 위한 필터."""
    return mapping.get(key)
