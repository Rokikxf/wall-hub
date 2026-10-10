# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Network scans with wall-scan v0.1.0: start one from the Scans page or with
  `manage.py scan`, run it in a Celery worker, and follow its status live.
- Device inventory: devices matched across scans by MAC address, then by IP
  address. The latest hostname, vendor and open ports are kept.
- Validation of tool output against the hub's copies of the contracts
  (`contracts/`), selected by major schema version. Startup checks catch
  silently disabled date-time validation and broken contract files.
- Docker Compose deployment (web, worker, PostgreSQL, Redis). The worker uses
  the host network, and nmap has raw-socket capabilities.
- CI: tests on PostgreSQL, and an end-to-end scan through the Docker stack.
- Monitoring with wall-healthcheck v0.1.0. Turn it on per device, by ping or
  by a TCP port. Celery beat runs a check of all monitored devices every
  minute, and runs never overlap. Health is shown on the device list, which
  refreshes itself.
- Alerts: a device is down after 2 failed checks in a row (configurable). One
  DOWN and one BACK UP alert per outage, emailed through SMTP when configured.
  Mail failures are recorded and never stop monitoring. Alerts page, and
  `manage.py healthcheck --wait`.
- Asset management: people and locations, and asset details on devices (name,
  type, asset tag, owner, location, make and model, serial number, purchase
  date, warranty end).
- Licences with key, seats and expiry, assigned to people and/or devices. Seat
  use is counted and over-allocation shown.
- Device search and filters (type, owner, location); the auto-refresh keeps them.
- Expiring page, and a daily reminder email for warranties and licences ending
  in 30, 7 or 1 days, or today (configurable).
- Scans without typed addresses: "Scan local networks" and
  `manage.py scan --local` use wall-scan v0.2.0 `--local`, which finds the
  networks the worker is attached to. Optional automatic scans: a discovery
  sweep every `WALL_AUTO_SCAN_INTERVAL_MIN` and a daily port scan at
  `WALL_AUTO_PORT_SCAN_HOUR`; both off by default.
- New-device alerts: a device seen for the first time creates a "New device"
  alert, and each scan sends one email listing them. The first scan is the
  baseline and alerts nothing.
- compose.yaml works with Docker Engine 29 / Compose 2.40 (no shared image name).
- SNMP details with wall-snmpinfo v0.1.0: model, serial number, uptime and
  printer supply levels on each device page, read every 6 hours and with "Read
  now". Automatic for printers and network equipment, and devices with a
  printing port open; on or off per device. Empty model and serial number
  asset fields are filled in.
- Supply low alerts: one email per device when supplies drop below
  `WALL_TONER_ALERT_PERCENT` (10%); a supply is reported again after a refill.
