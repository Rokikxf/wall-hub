import math
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inventory import alerts, expiry, snmp
from inventory.ingest import apply_scan
from inventory.models import Device, HealthRun, Scan
from inventory.monitoring import MonitoringError, apply_checks
from inventory.runner import ToolRunError, run_tool

# Extra time for wall-scan itself on top of nmap's limit, before the hub gives up.
SCAN_GRACE_S = 60
# wall-healthcheck checks up to this many targets at once (its MAX_CONCURRENT).
HEALTHCHECK_BATCH = 100
HEALTH_RUN_RETENTION = timedelta(days=7)


def scan_command(scan: Scan) -> list[str]:
    command = [settings.WALL_SCAN_COMMAND, *scan.targets.split()]
    if scan.local:
        command.append("--local")
        for interface in settings.WALL_SCAN_EXCLUDE_INTERFACES:
            command += ["--exclude-interface", interface]
    if not scan.ports:
        command.append("--no-ports")
    command += ["--timeout-s", str(settings.WALL_SCAN_TIMEOUT_S)]
    if settings.WALL_SCAN_PRIVILEGED:
        command.append("--privileged")
    return command


@shared_task
def run_scan(scan_id: int) -> str:
    """Run wall-scan for a queued Scan and store the outcome. Returns the final status."""
    scan = Scan.objects.get(pk=scan_id)
    scan.status = Scan.Status.RUNNING
    scan.started_at = timezone.now()
    scan.save(update_fields=["status", "started_at"])

    try:
        document, stderr = run_tool(
            "wall-scan", scan_command(scan), timeout_s=settings.WALL_SCAN_TIMEOUT_S + SCAN_GRACE_S
        )
    except ToolRunError as exc:
        scan.status = Scan.Status.FAILED
        scan.message = str(exc)
        scan.stderr = exc.stderr
        scan.finished_at = timezone.now()
        scan.save()
        return scan.status

    scan.stderr = stderr
    new_devices = apply_scan(scan, document)
    # Emails go out after the database work, so a slow mail server holds no locks.
    alerts.send_new_devices(new_devices)
    return scan.status


@shared_task
def auto_scan(ports: bool) -> str:
    """Scan the networks the worker is attached to, without typed targets.

    Celery beat starts this when automatic scans are configured: a quick
    discovery sweep every WALL_AUTO_SCAN_INTERVAL_MIN, and a port scan every
    night at WALL_AUTO_PORT_SCAN_HOUR. It does nothing while another scan is
    queued or running, so slow scans cannot pile up.
    """
    recent = timezone.now() - timedelta(seconds=settings.WALL_SCAN_TIMEOUT_S + SCAN_GRACE_S)
    active = Scan.objects.filter(
        status__in=[Scan.Status.QUEUED, Scan.Status.RUNNING], created_at__gte=recent
    )
    if active.exists():
        return "another scan is in progress"
    scan = Scan.objects.create(local=True, ports=ports, automatic=True)
    return run_scan(scan.pk)


def healthcheck_command(devices: list[Device]) -> list[str]:
    return [
        settings.WALL_HEALTHCHECK_COMMAND,
        *(device.check_target for device in devices),
        "--attempts",
        str(settings.WALL_HEALTHCHECK_ATTEMPTS),
        "--timeout-ms",
        str(settings.WALL_HEALTHCHECK_TIMEOUT_MS),
    ]


def healthcheck_time_limit(device_count: int) -> int:
    """Worst case for one run, when no target answers, plus a margin."""
    batches = math.ceil(device_count / HEALTHCHECK_BATCH)
    per_target_s = settings.WALL_HEALTHCHECK_ATTEMPTS * (
        settings.WALL_HEALTHCHECK_TIMEOUT_MS / 1000 + 0.2
    )
    return math.ceil(batches * per_target_s) + 30


@shared_task
def run_healthchecks() -> str:
    """Check every monitored device once, update its health and send alerts.

    Celery beat starts this every WALL_HEALTHCHECK_INTERVAL_S. If the previous run
    is still going, this one does nothing, so slow runs cannot overlap and count
    the same failure twice.
    """
    devices = list(Device.objects.filter(monitored=True).order_by("pk"))
    if not devices:
        return "no monitored devices"

    now = timezone.now()
    limit_s = healthcheck_time_limit(len(devices))
    running = HealthRun.objects.filter(status=HealthRun.Status.RUNNING)
    # A run older than the time limit died with its worker; it will never finish.
    running.filter(created_at__lt=now - timedelta(seconds=limit_s)).update(
        status=HealthRun.Status.FAILED, message="Never finished (worker stopped?)", finished_at=now
    )
    if running.exists():
        return "previous run still in progress"

    run = HealthRun.objects.create()
    sent = []
    try:
        document, stderr = run_tool("wall-healthcheck", healthcheck_command(devices), limit_s)
    except ToolRunError as exc:
        run.status, run.message, run.stderr = HealthRun.Status.FAILED, str(exc), exc.stderr
    else:
        run.stderr = stderr
        run.status = document["status"]
        run.message = "; ".join(error["message"] for error in document["errors"])
        if document["result"] is not None:
            try:
                with transaction.atomic():
                    sent = apply_checks(devices, document, timezone.now())
                run.check_count = len(document["result"]["checks"])
            except MonitoringError as exc:
                run.status, run.message = HealthRun.Status.FAILED, str(exc)
    run.finished_at = timezone.now()
    run.save()

    # Emails go out after the database work, so a slow mail server holds no locks.
    for alert in sent:
        alerts.send(alert)
    HealthRun.objects.filter(created_at__lt=now - HEALTH_RUN_RETENTION).delete()
    return run.status


@shared_task
def send_expiry_reminders() -> int:
    """Email the daily digest of warranties and licences that expire soon."""
    return expiry.send_reminders(timezone.localdate())


# wall-snmpinfo makes up to this many requests per device (system group,
# identity tables, supplies, colours), each of which can time out.
SNMP_REQUESTS = 8


def snmpinfo_command(device: Device) -> list[str]:
    # The community string is not an argument: wall-snmpinfo reads
    # WALL_SNMP_COMMUNITY from the environment, which it inherits from the worker.
    return [
        settings.WALL_SNMPINFO_COMMAND,
        device.ip,
        "--snmp-version",
        settings.WALL_SNMP_VERSION,
        "--timeout-ms",
        str(settings.WALL_SNMP_TIMEOUT_MS),
        "--retries",
        str(settings.WALL_SNMP_RETRIES),
    ]


def snmp_time_limit() -> int:
    per_request_s = (settings.WALL_SNMP_RETRIES + 1) * settings.WALL_SNMP_TIMEOUT_MS / 1000
    return math.ceil(SNMP_REQUESTS * per_request_s) + 30


@shared_task
def read_snmp(device_id: int) -> str:
    """Read one device with wall-snmpinfo, store the result and send supply alerts."""
    device = Device.objects.get(pk=device_id)
    try:
        document, _stderr = run_tool("wall-snmpinfo", snmpinfo_command(device), snmp_time_limit())
    except ToolRunError as exc:
        device.snmp_status = "failed"
        device.snmp_message = str(exc)
        device.snmp_read_at = timezone.now()
        device.save(update_fields=["snmp_status", "snmp_message", "snmp_read_at"])
        return device.snmp_status
    with transaction.atomic():
        low = snmp.apply_snmp(device, document, timezone.now())
    alerts.send_low_supplies(device, low)
    return device.snmp_status


@shared_task
def read_all_snmp() -> int:
    """Read every device that reads_snmp, one after another. Returns how many."""
    devices = [device for device in Device.objects.order_by("pk") if device.reads_snmp]
    for device in devices:
        read_snmp(device.pk)
    return len(devices)
