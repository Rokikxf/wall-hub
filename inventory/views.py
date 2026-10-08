import ipaddress
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from kombu.exceptions import OperationalError

from inventory.forms import ScanForm
from inventory.models import Device, Scan
from inventory.tasks import run_scan

log = logging.getLogger(__name__)


@login_required
def device_list(request):
    devices = sorted(Device.objects.all(), key=lambda d: ipaddress.IPv4Address(d.ip))
    return render(request, "inventory/device_list.html", {"devices": devices})


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


@login_required
def scan_list(request):
    if request.method == "POST":
        form = ScanForm(request.POST)
        if form.is_valid():
            scan = Scan.objects.create(
                targets=form.cleaned_data["targets"], requested_by=request.user
            )
            if queue_scan(scan):
                messages.success(request, f"Scan of {scan.targets} queued.")
            else:
                messages.error(request, scan.message)
            return redirect("scan-list")
    else:
        form = ScanForm(initial={"targets": settings.WALL_DEFAULT_TARGETS})
    scans = Scan.objects.select_related("requested_by")[:50]
    return render(request, "inventory/scan_list.html", {"form": form, "scans": scans})


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
