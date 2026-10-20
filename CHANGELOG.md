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
- Wake-on-LAN with wall-wol v0.1.0: **Wake** on the device page. The packets go
  to the broadcast address of the network a scan found the device on (else
  `WALL_WOL_BROADCAST`), and the device is then checked every 15 seconds for up
  to `WALL_WOL_WAIT_S` (3 minutes) to show whether it woke. Every wake is kept,
  with who sent it and the result.
- The wall-wol contract copy follows the released tool. The draft written
  before the tool existed allowed one MAC address per run and had no
  `source_ip`.
- Network map with Cytoscape.js 3.34.3 (vendored): the scanned networks as
  boxes of devices, the hub's link to each (interface and address), each
  network's gateway and the way to the Internet, device type and health, and
  devices the newest scan missed. Search, details panel, fixed layout with
  remembered drags, refresh every 30 seconds.
- wall-scan v0.3.0, whose schema 1.1 adds `result.networks` (interface, own
  address, gateway); the hub's contract copy and examples follow it.
- Scan history is pruned: scans older than `WALL_SCAN_RETENTION_DAYS` (90) are
  deleted after each scan, except a device's last scan.

### Changed

- A new look: a dark header with grouped navigation that marks the current
  page, and a red "down" count when monitored devices are down; light and
  dark themes (following the system, with a switch in the header, the map
  included); summary tiles on the devices page; page headers with
  breadcrumbs; sections and tables in cards; soft status pills with a dot.
  The device page shows its status and key facts at the top. Still no CDN:
  one stylesheet, static/css/hub.css.
- The device list's 30-second refresh also updates the summary tiles, but no
  longer replaces the filter form, so it cannot wipe what is being typed.
- The Scans page no longer loads each scan's full output, only the networks
  it scanned.
- `Device.ip` is indexed, since every scan looks devices up by IP address.
- The person, location and licence pages load the listed devices' owners and
  locations in one query, instead of up to two more queries per device.
- `manage.py scan --wait` returns as soon as the scan has finished, instead
  of always waiting at least a second.
- wall-snmpinfo v0.1.1: an SNMP error in a table is reported as an error, not a
  timeout.
