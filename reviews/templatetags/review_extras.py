from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """대상 id로 제출 id를 꺼낸다 - 템플릿에서 dict 조회를 하기 위한 필터."""
    if not mapping:
        return None
    return mapping.get(key)
