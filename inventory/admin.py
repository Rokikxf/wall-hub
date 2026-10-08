from django.contrib import admin

from inventory.models import Device, Scan


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["ip", "hostname", "mac", "vendor", "last_seen"]
    search_fields = ["ip", "hostname", "mac", "vendor"]


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ["pk", "targets", "status", "device_count", "created_at", "requested_by"]
    list_filter = ["status"]
    readonly_fields = ["created_at"]
