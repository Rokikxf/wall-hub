"""The page layout: the header's navigation and down count, and the devices page's tiles."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from inventory.models import Alert, Device, Scan

pytestmark = pytest.mark.django_db


def test_navigation_marks_the_current_section(logged_in, make_device):
    device = make_device("192.168.1.20")

    page = logged_in.get(reverse("device-detail", args=[device.pk])).content.decode()

    assert '<a class="nav-link active" href="/" aria-current="page">Devices</a>' in page
    assert '<a class="nav-link" href="/map/">Map</a>' in page


def test_down_count_in_the_header(logged_in, make_device):
    assert "hub-alarm" not in logged_in.get(reverse("alert-list")).content.decode()

    make_device("192.168.1.50", monitored=True, health="down")
    make_device("192.168.1.51", monitored=False, health="down")  # not monitored: not counted

    page = logged_in.get(reverse("alert-list")).content.decode()
    assert '">1 down</a>' in page


def test_logged_out_pages_have_no_navigation(client):
    page = client.get(reverse("login")).content.decode()

    assert "hub-nav" not in page
    assert "Log in" in page


def test_device_tiles(logged_in, make_device):
    make_device("192.168.1.10", monitored=True, health="up")
    down = make_device("192.168.1.50", monitored=True, health="down")
    make_device("192.168.1.60")
    Alert.objects.create(device=down, kind="down", message="down")
    Scan.objects.create(targets="192.168.1.0/24", status="ok", device_count=3)

    response = logged_in.get(reverse("device-list"))

    assert response.context["stats"] == {
        "total": 3, "monitored": 2, "up": 1, "down": 1, "alerts_today": 1,
    }  # fmt: skip
    assert response.context["last_scan"].device_count == 3
    assert 'class="row-down"' in response.content.decode()


def counts_down_devices(queries) -> bool:
    return any('"health"' in q["sql"] and "COUNT" in q["sql"] for q in queries)


def test_refreshing_fragments_skip_the_down_count(logged_in, make_device):
    device = make_device("192.168.1.20")

    with CaptureQueriesContext(connection) as fragment:
        logged_in.get(reverse("device-wakes", args=[device.pk]))
    with CaptureQueriesContext(connection) as page:
        logged_in.get(reverse("alert-list"))  # a full page with the header

    assert not counts_down_devices(fragment)
    assert counts_down_devices(page)
    assert Device.objects.count() == 1
