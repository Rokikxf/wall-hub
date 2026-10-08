from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
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

    How scanned devices are matched to these records is in inventory/ingest.py;
    how monitored devices become up or down is in inventory/monitoring.py.
    """

    class Health(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        UP = "up", "Up"
        DOWN = "down", "Down"

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

    # Monitoring with wall-healthcheck.
    monitored = models.BooleanField(default=False)
    check_port = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text="TCP port to check, for devices that drop ping. Empty: ping.",
    )
    health = models.CharField(max_length=10, choices=Health, default=Health.UNKNOWN)
    consecutive_failures = models.PositiveIntegerField(default=0)
    down_since = models.DateTimeField(
        null=True, blank=True, help_text="First failed check of the current outage"
    )
    last_check_at = models.DateTimeField(null=True, blank=True)
    last_rtt_ms = models.FloatField(null=True, blank=True)
    last_down_reason = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.hostname or self.ip

    @property
    def check_target(self) -> str:
        """The wall-healthcheck target: IP to ping, or IP:PORT for a TCP check."""
        return f"{self.ip}:{self.check_port}" if self.check_port else self.ip

    def reset_health(self) -> None:
        """Forget the health state, e.g. after the way it is checked changes."""
        self.health = self.Health.UNKNOWN
        self.consecutive_failures = 0
        self.down_since = None
        self.last_check_at = None
        self.last_rtt_ms = None
        self.last_down_reason = ""


class HealthRun(models.Model):
    """One run of wall-healthcheck over all monitored devices."""

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        OK = "ok", "OK"
        PARTIAL = "partial", "Partial"
        ERROR = "error", "Error"  # wall-healthcheck reported an error
        FAILED = "failed", "Failed"  # no valid document from wall-healthcheck

    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status, default=Status.RUNNING)
    check_count = models.PositiveIntegerField(null=True, blank=True)
    message = models.TextField(blank=True)
    stderr = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Health run {self.pk} ({self.status})"


class Alert(models.Model):
    """A device going down or coming back up, and whether the email went out."""

    class Kind(models.TextChoices):
        DOWN = "down", "Down"
        UP = "up", "Back up"

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="alerts")
    kind = models.CharField(max_length=10, choices=Kind)
    created_at = models.DateTimeField(auto_now_add=True)
    message = models.TextField()
    emailed_to = models.TextField(blank=True)
    email_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.device} {self.get_kind_display().lower()} at {self.created_at}"
