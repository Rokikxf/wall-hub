from django.conf import settings
from django.db import models


class Scan(models.Model):
    """One run of wall-scan, from the request to the stored result."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        OK = "ok", "OK"
        PARTIAL = "partial", "Partial"
        # wall-scan ran and reported an error (its document has status "error").
        ERROR = "error", "Error"
        # The hub got no valid document: wall-scan missing, crashed, or broke its contract.
        FAILED = "failed", "Failed"

    FINISHED = {Status.OK, Status.PARTIAL, Status.ERROR, Status.FAILED}

    targets = models.CharField(max_length=500, help_text="Space-separated addresses and ranges")
    status = models.CharField(max_length=10, choices=Status, default=Status.QUEUED)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    message = models.TextField(blank=True, help_text="What went wrong, if anything")
    output = models.JSONField(null=True, blank=True, help_text="The validated wall-scan document")
    stderr = models.TextField(blank=True)
    device_count = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Scan {self.pk} of {self.targets} ({self.status})"

    @property
    def is_finished(self) -> bool:
        return self.status in self.FINISHED


class Device(models.Model):
    """A device on the network, with the last known values from wall-scan.

    How scanned devices are matched to these records is in inventory/ingest.py.
    """

    ip = models.GenericIPAddressField(protocol="IPv4")
    mac = models.CharField(max_length=17, unique=True, null=True, blank=True)
    vendor = models.CharField(max_length=200, blank=True)
    hostname = models.CharField(max_length=255, blank=True)
    open_ports = models.JSONField(
        null=True, blank=True, help_text="From the last port scan; null if never port-scanned"
    )
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    last_scan = models.ForeignKey(
        Scan, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self):
        return self.hostname or self.ip
