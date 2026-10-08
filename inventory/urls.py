from django.urls import path

from inventory import views

urlpatterns = [
    path("", views.device_list, name="device-list"),
    path("scans/", views.scan_list, name="scan-list"),
    path("scans/<int:pk>/", views.scan_detail, name="scan-detail"),
    path("scans/<int:pk>/row/", views.scan_row, name="scan-row"),
]
