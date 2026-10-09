from django import template
from django.utils import timezone

register = template.Library()

SOON_DAYS = 30


@register.inclusion_tag("inventory/_expiry_badge.html")
def expiry_badge(date, none_text="—"):
    """A warranty or licence end date: red when past, yellow within 30 days."""
    if date is None:
        return {"status": "none", "none_text": none_text}
    days = (date - timezone.localdate()).days
    if days < 0:
        status = "expired"
    elif days <= SOON_DAYS:
        status = "soon"
    else:
        status = "ok"
    return {"status": status, "date": date, "days": days}
