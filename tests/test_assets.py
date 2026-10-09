"""Asset management: device asset details, people, locations and licences."""

import pytest
from django.urls import reverse

from inventory.forms import DeviceAssetForm
from inventory.models import Device, Licence, Location, Person

pytestmark = pytest.mark.django_db


@pytest.fixture
def anna():
    return Person.objects.create(name="Anna Byrne", department="Accounts", email="anna@example.com")


@pytest.fixture
def reception():
    return Location.objects.create(name="Reception")


# --- models ---


def test_device_name_falls_back_to_hostname_then_ip(make_device):
    device = make_device("192.168.1.50")
    assert str(device) == "192.168.1.50"
    device.hostname = "npi1a2b3c.lan"
    assert str(device) == "npi1a2b3c.lan"
    device.name = "Reception printer"
    assert str(device) == "Reception printer"


def test_licence_seats(make_device, anna):
    licence = Licence.objects.create(name="Microsoft 365", seats=1)
    assert (licence.seats_used, licence.over_allocated) == (0, False)

    licence.people.add(anna)
    licence.devices.add(make_device("192.168.1.20"))

    assert (licence.seats_used, licence.over_allocated) == (2, True)
    licence.seats = None  # unlimited
    assert licence.over_allocated is False


# --- device asset details ---


def asset_data(**overrides):
    data = {"name": "", "kind": "unknown", "asset_tag": "", "notes": ""}
    data.update(overrides)
    return data


def test_empty_asset_tags_are_stored_as_null_so_many_devices_can_have_none(make_device):
    for ip in ["192.168.1.1", "192.168.1.2"]:
        form = DeviceAssetForm(asset_data(asset_tag="  "), instance=make_device(ip))
        assert form.is_valid(), form.errors
        assert form.save().asset_tag is None


def test_asset_tags_are_unique(make_device):
    make_device("192.168.1.1", asset_tag="WALL-0001")

    form = DeviceAssetForm(asset_data(asset_tag="WALL-0001"), instance=make_device("192.168.1.2"))

    assert not form.is_valid()
    assert "asset_tag" in form.errors


def test_edit_asset_details(logged_in, make_device, anna, reception):
    device = make_device("192.168.1.50", hostname="npi1a2b3c.lan", monitored=True, health="up")
    url = reverse("device-edit", args=[device.pk])
    assert logged_in.get(url).status_code == 200

    response = logged_in.post(
        url,
        asset_data(
            name="Reception printer",
            kind="printer",
            asset_tag="WALL-0042",
            owner=anna.pk,
            location=reception.pk,
            manufacturer="HP",
            model_name="Color LaserJet Pro M454dw",
            serial_number="VNB3K12345",
            purchase_date="2024-03-01",
            warranty_expires="2027-02-28",
        ),
    )

    assert response.status_code == 302
    assert response.url == reverse("device-detail", args=[device.pk])
    device.refresh_from_db()
    assert (device.name, device.kind, device.owner, device.location) == (
        "Reception printer",
        "printer",
        anna,
        reception,
    )
    assert str(device.warranty_expires) == "2027-02-28"
    # Asset changes never touch monitoring.
    assert (device.monitored, device.health) == (True, "up")

    page = logged_in.get(reverse("device-detail", args=[device.pk])).content.decode()
    assert "Reception printer" in page
    assert anna.get_absolute_url() in page
    assert "VNB3K12345" in page
    assert "28 Feb 2027" in page


# --- device list filters ---


@pytest.fixture
def office(make_device, anna, reception):
    make_device("192.168.1.20", name="Anna's PC", kind="computer", owner=anna)
    make_device("192.168.1.50", name="Reception printer", kind="printer", location=reception)
    make_device("192.168.1.77", serial_number="SN-PHONE-1")


@pytest.mark.parametrize(
    "query, expected",
    [
        ({"q": "anna byrne"}, ["192.168.1.20"]),  # by owner name, any case
        ({"q": "SN-PHONE"}, ["192.168.1.77"]),  # by serial number
        ({"q": "192.168.1.5"}, ["192.168.1.50"]),  # by part of the IP address
        ({"kind": "printer"}, ["192.168.1.50"]),
        (
            {"q": "", "kind": "", "owner": "", "location": ""},
            ["192.168.1.20", "192.168.1.50", "192.168.1.77"],
        ),
    ],
    ids=["owner", "serial", "ip", "type", "empty-filters"],
)
def test_device_list_filters(logged_in, office, query, expected):
    response = logged_in.get(reverse("device-list"), query)

    assert [d.ip for d in response.context["devices"]] == expected


def test_device_list_filter_by_location_and_refresh_keeps_filters(logged_in, office, reception):
    response = logged_in.get(reverse("device-list"), {"location": reception.pk})

    assert [d.ip for d in response.context["devices"]] == ["192.168.1.50"]
    assert f'hx-get="/?location={reception.pk}"' in response.content.decode()


def test_device_list_with_no_matches(logged_in, office):
    response = logged_in.get(reverse("device-list"), {"q": "nothing like this"})
    assert "No devices match" in response.content.decode()


# --- people and locations ---


def test_create_edit_and_list_people(logged_in, make_device):
    response = logged_in.post(
        reverse("person-add"), {"name": "Ciara Walsh", "department": "Sales", "email": ""}
    )
    person = Person.objects.get()
    assert response.url == person.get_absolute_url()

    logged_in.post(
        reverse("person-edit", args=[person.pk]), {"name": "Ciara Walsh", "department": "Marketing"}
    )
    make_device("192.168.1.30", owner=person)

    person.refresh_from_db()
    assert person.department == "Marketing"
    listing = logged_in.get(reverse("person-list"))
    assert listing.context["object_list"][0].device_count == 1


def test_deleting_a_person_keeps_their_devices_and_frees_seats(logged_in, make_device, anna):
    device = make_device("192.168.1.20", owner=anna)
    licence = Licence.objects.create(name="Microsoft 365", seats=5)
    licence.people.add(anna)

    response = logged_in.post(reverse("person-delete", args=[anna.pk]), follow=True)

    assert "Deleted Anna Byrne." in response.content.decode()
    device.refresh_from_db()
    assert device.owner is None
    assert licence.seats_used == 0


def test_person_page_lists_devices_and_licences(logged_in, make_device, anna):
    make_device("192.168.1.20", name="Anna's PC", owner=anna)
    Licence.objects.create(name="Microsoft 365").people.add(anna)

    page = logged_in.get(anna.get_absolute_url()).content.decode()

    assert "Anna&#x27;s PC" in page
    assert "Microsoft 365" in page


def test_locations(logged_in, make_device):
    logged_in.post(reverse("location-add"), {"name": "Server cupboard", "notes": ""})
    location = Location.objects.get()
    device = make_device("192.168.1.10", location=location)
    assert "192.168.1.10" in logged_in.get(location.get_absolute_url()).content.decode()

    logged_in.post(reverse("location-delete", args=[location.pk]))

    device.refresh_from_db()
    assert device.location is None


def test_location_names_are_unique(logged_in, reception):
    response = logged_in.post(reverse("location-add"), {"name": "Reception"})
    assert response.status_code == 200
    assert "already exists" in response.content.decode()


# --- licences ---


def test_create_licence_with_assignments(logged_in, make_device, anna):
    pc = make_device("192.168.1.20", name="Anna's PC")

    response = logged_in.post(
        reverse("licence-add"),
        {
            "name": "Microsoft 365 Business Standard",
            "vendor": "Microsoft",
            "licence_key": "XXXXX-XXXXX-XXXXX-XXXXX-XXXXX",
            "seats": "1",
            "expires": "2027-01-31",
            "people": [anna.pk],
            "devices": [pc.pk],
        },
    )

    licence = Licence.objects.get()
    assert response.url == licence.get_absolute_url()
    assert list(licence.people.all()) == [anna]
    assert list(licence.devices.all()) == [pc]

    listing = logged_in.get(reverse("licence-list")).content.decode()
    assert "2 / 1" in listing  # over-allocated
    assert "XXXXX" not in listing  # keys never appear in the list

    page = logged_in.get(licence.get_absolute_url()).content.decode()
    assert "but the licence has 1 seat." in page
    assert "<details><summary>Show</summary>" in page


def test_licence_device_choices_show_name_and_ip(logged_in, make_device):
    make_device("192.168.1.20", name="Anna's PC")
    make_device("192.168.1.21")

    content = logged_in.get(reverse("licence-add")).content.decode()

    assert "Anna&#x27;s PC (192.168.1.20)" in content
    assert ">192.168.1.21</option>" in content


@pytest.mark.parametrize(
    "name",
    ["person-list", "person-add", "location-list", "licence-list", "licence-add", "expiring"],
)
def test_asset_pages_need_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))


def test_unknown_records_are_404(logged_in):
    for name in ["person-detail", "location-edit", "licence-delete", "device-edit"]:
        assert logged_in.get(reverse(name, args=[999])).status_code == 404


def test_device_kinds_cover_common_office_equipment():
    assert {"computer", "printer", "network", "phone"} <= set(Device.Kind.values)
