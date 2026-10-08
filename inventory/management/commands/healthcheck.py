"""manage.py healthcheck [--wait]: queue a health check run of all monitored devices.

Celery beat already runs one every WALL_HEALTHCHECK_INTERVAL_S. This command is for
checking on demand, and with --wait for an end-to-end test of the monitoring path:
Redis, worker, wall-healthcheck and the database. It waits for the next run to
finish (whichever started it) and exits non-zero unless that run succeeded.
"""

import time

from django.core.management.base import BaseCommand, CommandError

from inventory.models import Device, HealthRun
from inventory.tasks import run_healthchecks


class Command(BaseCommand):
    help = "Queue a health check of all monitored devices; with --wait, wait for the result."

    def add_arguments(self, parser):
        parser.add_argument("--wait", action="store_true", help="wait for a run to finish")
        parser.add_argument(
            "--wait-timeout", type=int, default=300, help="seconds to wait (default: 300)"
        )

    def handle(self, *args, **options):
        if not Device.objects.filter(monitored=True).exists():
            raise CommandError("No devices are monitored.")
        previous = HealthRun.objects.first()
        run_healthchecks.delay()
        self.stdout.write("Health check queued.")
        if not options["wait"]:
            return

        deadline = time.monotonic() + options["wait_timeout"]
        while True:
            newer = HealthRun.objects.exclude(status=HealthRun.Status.RUNNING)
            if previous is not None:
                newer = newer.filter(pk__gt=previous.pk)
            run = newer.order_by("-pk").first()
            if run is not None:
                break
            if time.monotonic() > deadline:
                raise CommandError("No health check run finished before the wait timeout")
            time.sleep(1)

        if run.status not in (HealthRun.Status.OK, HealthRun.Status.PARTIAL):
            raise CommandError(f"Health run {run.pk} {run.status}: {run.message}")
        up = Device.objects.filter(monitored=True, health=Device.Health.UP).count()
        down = Device.objects.filter(monitored=True, health=Device.Health.DOWN).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Health run {run.pk} finished: {run.check_count} checked, {up} up, {down} down"
            )
        )
