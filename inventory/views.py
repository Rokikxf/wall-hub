import ipaddress
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from kombu.exceptions import OperationalError

from inventory.forms import DeviceFilterForm, MonitoringForm, ScanForm
from inventory.models import Alert, Device, HealthRun, Scan
from inventory.tasks import read_snmp, run_scan

log = logging.getLogger(__name__)

SEARCH_FIELDS = [
    "ip",
    "hostname",
    "name",
    "mac",
    "vendor",
    "serial_number",
    "asset_tag",
    "owner__name",
]


@login_required
def device_list(request):
    form = DeviceFilterForm(request.GET or None)
    devices = Device.objects.select_related("owner", "location")
    if form.is_valid():
        search = form.cleaned_data["q"].strip()
        if search:
            query = Q()
            for field in SEARCH_FIELDS:
                query |= Q(**{f"{field}__icontains": search})
            devices = devices.filter(query)
        for field in ["kind", "owner", "location"]:
            if form.cleaned_data[field]:
                devices = devices.filter(**{field: form.cleaned_data[field]})
    context = {
        "form": form,
        "filtered": form.is_bound,
        "devices": sorted(devices, key=lambda d: ipaddress.IPv4Address(d.ip)),
        "monitored_count": Device.objects.filter(monitored=True).count(),
        "last_run": HealthRun.objects.first(),
    }
    return render(request, "inventory/device_list.html", context)


SNMP_SETTINGS = {"auto": None, "on": True, "off": False}


@login_required
def device_detail(request, pk):
    device = get_object_or_404(Device, pk=pk)
    if request.method == "POST" and "read_snmp" in request.POST:
        try:
            read_snmp.delay(device.pk)
            messages.success(request, "SNMP read queued; refresh in a few seconds.")
        except OperationalError as exc:
            messages.error(request, f"Could not queue the SNMP read (is Redis running?): {exc}")
        return redirect("device-detail", pk=device.pk)
    if request.method == "POST" and request.POST.get("snmp_setting") in SNMP_SETTINGS:
        device.snmp_enabled = SNMP_SETTINGS[request.POST["snmp_setting"]]
        device.save(update_fields=["snmp_enabled"])
        messages.success(request, "SNMP setting saved.")
        return redirect("device-detail", pk=device.pk)
    if request.method == "POST":
        form = MonitoringForm(request.POST, instance=device)
        if form.is_valid():
            if form.has_changed():
                # A new way of checking: earlier results say nothing about it.
                device.reset_health()
            form.save()
            messages.success(request, "Monitoring settings saved.")
            return redirect("device-detail", pk=device.pk)
    else:
        form = MonitoringForm(instance=device)
    context = {
        "device": device,
        "form": form,
        "alerts": device.alerts.all()[:20],
        "licences": device.licences.all(),
        "snmp_setting": next(k for k, v in SNMP_SETTINGS.items() if v == device.snmp_enabled),
        "toner_threshold": settings.WALL_TONER_ALERT_PERCENT,
    }
    return render(request, "inventory/device_detail.html", context)


@login_required
def alert_list(request):
    alerts = Alert.objects.select_related("device")[:100]
    return render(request, "inventory/alert_list.html", {"alerts": alerts})


def queue_scan(scan: Scan) -> bool:
    """Hand the scan to a worker. Returns False, and marks it failed, if Redis is down."""
    try:
        run_scan.delay(scan.pk)
    except OperationalError as exc:
        log.error("could not queue scan %s: %s", scan.pk, exc)
        scan.status = Scan.Status.FAILED
        scan.message = f"Could not queue the scan (is Redis running?): {exc}"
        scan.finished_at = timezone.now()
        scan.save()
        return False
    return True


def start_scan(request, scan: Scan):
    if queue_scan(scan):
        messages.success(request, f"Scan of {scan.describe_targets()} queued.")
    else:
        messages.error(request, scan.message)
    return redirect("scan-list")


@login_required
def scan_list(request):
    form = ScanForm(initial={"targets": settings.WALL_DEFAULT_TARGETS})
    if request.method == "POST":
        if "local" in request.POST:
            # No targets to type: wall-scan finds the attached networks itself.
            return start_scan(request, Scan.objects.create(local=True, requested_by=request.user))
        form = ScanForm(request.POST)
        if form.is_valid():
            scan = Scan.objects.create(
                targets=form.cleaned_data["targets"], requested_by=request.user
            )
            return start_scan(request, scan)
    context = {
        "form": form,
        "scans": Scan.objects.select_related("requested_by")[:50],
        "auto_interval": settings.WALL_AUTO_SCAN_INTERVAL_MIN,
        "auto_port_hour": settings.WALL_AUTO_PORT_SCAN_HOUR,
    }
    return render(request, "inventory/scan_list.html", context)


@login_required
def scan_row(request, pk):
    """One row of the scan table. Unfinished rows poll this view with HTMX."""
    scan = get_object_or_404(Scan, pk=pk)
    return render(request, "inventory/_scan_row.html", {"scan": scan})


@login_required
def scan_detail(request, pk):
    scan = get_object_or_404(Scan, pk=pk)
    result = (scan.output or {}).get("result") or {}
    context = {
        "scan": scan,
        "found": result.get("devices", []),
        "output_json": json.dumps(scan.output, indent=2) if scan.output else "",
    }
    return render(request, "inventory/scan_detail.html", context)
