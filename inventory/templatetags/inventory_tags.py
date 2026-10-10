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


@register.filter
def duration(seconds):
    """Seconds as the two largest units, e.g. "10 days, 3 hours" or "4 minutes"."""
    if seconds is None:
        return "—"
    seconds = int(seconds)
    parts = []
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count} {unit}{'s' if count != 1 else ''}")
    return ", ".join(parts[:2]) or "0 seconds"


# Bootstrap has no magenta; its red is the closest.
COLORANT_CLASSES = {
    "black": "bg-dark",
    "cyan": "bg-info",
    "magenta": "bg-danger",
    "yellow": "bg-warning",
}


@register.filter
def supply_bar(colorant):
    """Bootstrap background for a supply's level bar, after its colour."""
    for colour, css in COLORANT_CLASSES.items():
        if colorant and colour in colorant.lower():
            return css
    return "bg-secondary"
