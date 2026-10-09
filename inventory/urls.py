from django.urls import path

from inventory import asset_views, views

# (URL suffix, view class suffix in asset_views, URL name suffix)
CRUD = [
    ("", "List", "list"),
    ("new/", "Create", "add"),
    ("<int:pk>/", "Detail", "detail"),
    ("<int:pk>/edit/", "Update", "edit"),
    ("<int:pk>/delete/", "Delete", "delete"),
]


def crud(prefix: str, model: str) -> list:
    """List, new, detail, edit and delete URLs, e.g. people/ -> PersonList, person-list."""
    return [
        path(
            f"{prefix}/{suffix}",
            getattr(asset_views, model + view).as_view(),
            name=f"{model.lower()}-{name}",
        )
        for suffix, view, name in CRUD
    ]


urlpatterns = [
    path("", views.device_list, name="device-list"),
    path("devices/<int:pk>/", views.device_detail, name="device-detail"),
    path("devices/<int:pk>/edit/", asset_views.DeviceAssetUpdate.as_view(), name="device-edit"),
    *crud("people", "Person"),
    *crud("locations", "Location"),
    *crud("licences", "Licence"),
    path("expiring/", asset_views.Expiring.as_view(), name="expiring"),
    path("alerts/", views.alert_list, name="alert-list"),
    path("scans/", views.scan_list, name="scan-list"),
    path("scans/<int:pk>/", views.scan_detail, name="scan-detail"),
    path("scans/<int:pk>/row/", views.scan_row, name="scan-row"),
]
