"""manage.py scan [TARGET...] [--local] [--wait]: queue a wall-scan run from the command line.

With --wait it polls until a worker has finished the scan and exits non-zero unless
the scan succeeded. That makes it usable as an end-to-end check of the whole stack:
database, Redis, worker, wall-scan and nmap.
"""

import time

from django.core.management.base import BaseCommand, CommandError

from inventory.forms import ScanForm
from inventory.models import Scan
from inventory.views import queue_scan


class Command(BaseCommand):
    help = "Queue a wall-scan run; with --wait, wait for the result."

    def add_arguments(self, parser):
        parser.add_argument("targets", nargs="*", help="IPv4 addresses or CIDR ranges")
        parser.add_argument(
            "--local",
            action="store_true",
            help="also scan the networks the worker is attached to",
        )
        parser.add_argument("--wait", action="store_true", help="wait for the scan to finish")
        parser.add_argument(
            "--wait-timeout", type=int, default=900, help="seconds to wait (default: 900)"
        )

    def handle(self, *args, **options):
        targets = ""
        if options["targets"]:
            form = ScanForm({"targets": " ".join(options["targets"])})
            if not form.is_valid():
                raise CommandError(form.errors["targets"][0])
            targets = form.cleaned_data["targets"]
        elif not options["local"]:
            raise CommandError("Give at least one target, or --local.")
        scan = Scan.objects.create(targets=targets, local=options["local"])
        if not queue_scan(scan):
            raise CommandError(scan.message)
        self.stdout.write(f"Scan {scan.pk} queued: {scan.describe_targets()}")
        if not options["wait"]:
            return

        deadline = time.monotonic() + options["wait_timeout"]
        while not scan.is_finished:
            if time.monotonic() > deadline:
                raise CommandError(f"Scan {scan.pk} still {scan.status} after the wait timeout")
            time.sleep(1)
            scan.refresh_from_db()

        summary = f"Scan {scan.pk} finished: {scan.status}, {scan.device_count} device(s)"
        if scan.status not in (Scan.Status.OK, Scan.Status.PARTIAL):
            raise CommandError(f"{summary}. {scan.message}")
        self.stdout.write(self.style.SUCCESS(summary))
