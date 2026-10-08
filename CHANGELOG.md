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
