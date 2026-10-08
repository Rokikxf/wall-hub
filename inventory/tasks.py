from celery import shared_task
from django.conf import settings
from django.utils import timezone

from inventory.ingest import apply_scan
from inventory.models import Scan
from inventory.runner import ToolRunError, run_tool

# Extra time for wall-scan itself on top of nmap's limit, before the hub gives up.
SCAN_GRACE_S = 60


def scan_command(scan: Scan) -> list[str]:
    command = [
        settings.WALL_SCAN_COMMAND,
        *scan.targets.split(),
        "--timeout-s",
        str(settings.WALL_SCAN_TIMEOUT_S),
    ]
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
    apply_scan(scan, document)
    return scan.status
