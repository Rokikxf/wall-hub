# wall-hub for developers

How the hub works inside, and how to work on it. Setting it up and using it is
in the [README](README.md).

The hub runs the wall-\* command-line tools, checks their JSON output against
the contracts, stores the results and shows them:

- [wall-scan](https://github.com/Rokikxf/wall-scan) discovers devices with nmap,
  and reports how each scanned network is reached;
- [wall-healthcheck](https://github.com/Rokikxf/wall-healthcheck) pings or
  TCP-connects to the monitored devices;
- [wall-snmpinfo](https://github.com/Rokikxf/wall-snmpinfo) reads identity and
  printer supplies over SNMP;
- [wall-wol](https://github.com/Rokikxf/wall-wol) sends Wake-on-LAN packets.

The hub installs each tool at an exact release tag (`requirements.txt`).

## How it fits together

```
browser ──► web (Django) ──┐                  ┌──► wall-scan ──► nmap ──────► LAN
                           ├─► Redis ─► worker┼──► wall-healthcheck ──────────► LAN
            beat (timer) ──┘                  ├──► wall-snmpinfo ─────────────► LAN
                                              └──► wall-wol ──────────────────► LAN
                 web and worker share PostgreSQL
```

1. A page (**Run scan**, **Wake**, **Read now**) or Celery beat (health checks,
   automatic scans, SNMP reads, expiry reminders) queues a Celery task.
2. The worker runs the tool, reads the JSON document from its stdout, and
   validates it against the hub's copy of the tool's contract in `contracts/`
   ([inventory/runner.py](inventory/runner.py)). Anything that is not a valid
   document fails the run with a reason, and the tool's stderr is kept.
3. The task stores the result, and sends any alerts after the database work is
   done, so a slow mail server holds no locks.

## The Docker services

`compose.yaml` runs five services: `web` (Django and gunicorn; applies the
migrations when it starts), `worker` (Celery, runs the tools), `beat` (Celery's
timer), `db` (PostgreSQL 17) and `redis` (the Celery broker).

The worker runs with `network_mode: host` and the `NET_RAW` and `NET_ADMIN`
capabilities. On Docker's default bridge network, nmap would only see Docker's
internal network: no ARP, no MAC addresses, no devices on the LAN, and
Wake-on-LAN broadcasts would not reach the LAN either. The capabilities are
attached only to the nmap binary in the image (`setcap`), and the worker runs
as an unprivileged user. Ping uses Linux ping sockets and needs no
capabilities, but the host must allow them (`net.ipv4.ping_group_range`),
because the worker shares the host's network.

Because the worker is on the host network, it reaches PostgreSQL and Redis on
`127.0.0.1`. Their ports are published on the host's loopback interface only.
The image has no shared `image:` name: Docker Engine 29 / Compose 2.40 build
web, worker and beat in parallel, and a shared name makes those builds collide.

## The rules, module by module

- **Device identity** ([inventory/ingest.py](inventory/ingest.py)): a scanned
  device is matched to a known one by MAC address first, then by IP address,
  unless both have different MACs. Phones with randomised MACs show up as new
  when the MAC changes. The first scan into an empty inventory is the baseline
  and creates no *New device* alerts.
- **Monitoring** ([inventory/monitoring.py](inventory/monitoring.py)): a device is
  down after `WALL_ALERT_AFTER_FAILURES` failed checks in a row, and up again
  after one success; each change creates exactly one alert. Health-check runs
  never overlap: one still running makes the next do nothing, and a run older
  than its time limit is marked as failed. Runs are kept for 7 days.
- **Automatic scans** ([inventory/tasks.py](inventory/tasks.py)): `wall-scan
  --local` finds the attached private networks itself. An automatic scan does
  nothing while another scan is queued or running. After every scan, scans
  older than `WALL_SCAN_RETENTION_DAYS` are deleted, except any that is still
  some device's last scan.
- **SNMP** ([inventory/snmp.py](inventory/snmp.py)): the community string goes to
  wall-snmpinfo through its environment (`WALL_SNMP_COMMUNITY`), never on a
  command line or into the database. A supply is reported low once, and again
  only after a reading at or above the threshold (a refill). Supplies with no
  number ("some left") are neither low nor refilled. Model and serial number
  fill empty asset fields only.
- **Wake-on-LAN** ([inventory/wol.py](inventory/wol.py)): the packets go to the
  directed broadcast of the most specific scanned network containing the
  device. `255.255.255.255` would leave through the adapter with the default
  route, which on the lab VM is VirtualBox's NAT adapter. After sending, each
  check is its own task queued with a countdown, so no worker waits while a PC
  boots.
- **Network map** ([inventory/netmap.py](inventory/netmap.py)): built from
  `result.networks` of the last 50 successful scans (wall-scan 0.3, schema 1.1:
  interface, own address and gateway per network). With 1.0 documents only the
  ranges are known, and the hub is recognised by nmap's `localhost-response`.
  [static/js/network_map.js](static/js/network_map.js) draws it with a fixed
  grid layout; Cytoscape's force layout cannot handle edges to compound nodes.
- **Expiry reminders** ([inventory/expiry.py](inventory/expiry.py)): the digest
  lists whatever ends exactly `WALL_EXPIRY_REMINDER_DAYS` days from today, so
  nothing is stored and nothing is sent twice.

## Contracts

`contracts/<tool>/v<major>.json` are the hub's copies of the tools' output
schemas, and `contracts/<tool>/examples/` holds valid documents that the tests
use as tool output. A document is validated against the copy chosen by the
major number of its `schema_version`, so a tool can add fields (a minor
version) without a hub change, while a new major version is rejected until the
hub has been taught it. See [contracts/README.md](contracts/README.md); the
rules all tools follow are in `CONTRACT.md` in the tool template repository.

## Working on it

Works on Windows or Linux, without Docker:

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux: . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                            # SQLite; no Redis, nmap or network needed
ruff check . && ruff format --check .
```

The tests replace the tools with the example documents from `contracts/`, so
the hub is tested against exactly what the contracts promise.

CI runs the tests on PostgreSQL. It then builds the Docker image, starts the
whole stack, and runs a real scan of 127.0.0.1 through web, Redis, the worker,
wall-scan and nmap. It monitors the device that scan found and runs a real
health check of it, and an SNMP read (there is no SNMP agent on the runner, so
it must end as a clean `snmp_timeout`). Last, it wakes the device: wall-wol
sends the magic packets to a UDP socket the test opens on 127.0.0.1, which
checks them byte for byte, and the follow-up check through Redis and the worker
must find the device awake.

## Code layout

```
wallhub/       Django project: settings, URLs, Celery app
inventory/     the app
  contracts.py   validates tool output against contracts/
  runner.py      runs a wall-* tool and returns a valid document
  tasks.py       the Celery tasks, and the tools' command lines
  ingest.py      stores a scan and matches devices
  monitoring.py  health checks to device health and alerts
  alerts.py      alert emails
  snmp.py        SNMP details on devices, low-supply alerts
  wol.py         Wake-on-LAN: where the packets go, checks that the device woke
  netmap.py      the network map's networks, devices and links
  expiry.py      warranty and licence expiry, reminder emails
  views.py       devices, scans, alerts and the map
  asset_views.py people, locations, licences and asset details pages
contracts/     the hub's copies of the tool contracts
templates/     the page layout (base.html) and the login page
static/css/    the hub's own styles on top of Bootstrap (hub.css), for light and dark
static/js/     the network map page (network_map.js)
static/vendor/ Bootstrap 5.3.8, htmx 2.0.11 and Cytoscape.js 3.34.3, stored here so the hub works offline
```

## Security notes

- The hub serves plain HTTP; HTTPS through a reverse proxy is still to come.
  Until then, `manage.py check --deploy` reports four HTTPS-related warnings.
- Scans are limited to private address ranges of at most a /16: the scan form
  checks this, and wall-scan enforces it again.
- Every page requires a login. There are no roles: every user can do everything
  in the hub's pages.
