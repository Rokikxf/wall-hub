"""Values every page can use, for the header."""

from inventory.models import Device


def hub_status(request):
    """down_count: monitored devices that are down, for the header's red pill.

    Passed as a callable, which the template calls only if it uses the value, so
    the small HTMX fragments that refresh every few seconds cost no query.
    """
    if not request.user.is_authenticated:
        return {}

    def down_count():
        return Device.objects.filter(monitored=True, health=Device.Health.DOWN).count()

    return {"down_count": down_count}
