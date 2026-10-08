from django.contrib import admin

from inventory.models import Alert, Device, HealthRun, Scan


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ["ip", "hostname", "mac", "vendor", "monitored", "health", "last_seen"]
    list_filter = ["monitored", "health"]
    search_fields = ["ip", "hostname", "mac", "vendor"]


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ["pk", "targets", "status", "device_count", "created_at", "requested_by"]
    list_filter = ["status"]
    readonly_fields = ["created_at"]


@admin.register(HealthRun)
class HealthRunAdmin(admin.ModelAdmin):
    list_display = ["pk", "created_at", "status", "check_count", "message"]
    list_filter = ["status"]


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ["created_at", "device", "kind", "emailed_to", "email_error"]
    list_filter = ["kind"]
