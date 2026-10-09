# wall-hub

The web hub of the wall IT asset management system. It runs the wall-\* command
line tools, checks their JSON output against the contracts, stores the results
and shows them. So far it uses two tools:
- [wall-scan](https://github.com/Rokikxf/wall-scan): the hub scans the networks it is on (by schedule or with one click),
  and keeps an inventory of the devices found;
- [wall-healthcheck](https://github.com/Rokikxf/wall-healthcheck): the hub
  checks the devices you choose to monitor every minute, and emails you when
  one goes down or comes back up.

On top of what the tools find, it records who owns each device and where it
is, warranties, and software licences, and reminds you before they expire.

Only scan networks you own or have written permission to scan.

## How it fits together

```
browser ──► web (Django) ──┐                  ┌──► wall-scan ──► nmap ──────► LAN
                           ├─► Redis ─► worker┤
            beat (timer) ──┘                  └──► wall-healthcheck ──────────► LAN
                 web and worker share PostgreSQL
```

1. **Run scan** creates a `Scan` and queues a Celery task. Beat queues a
   health check run every `WALL_HEALTHCHECK_INTERVAL_S` seconds.
2. The worker runs the tool, reads the JSON document from its stdout, and
   validates it against the hub's copy of the contract in `contracts/`.
   Anything that is not a valid document fails the run with a reason, and the
   tool's stderr is kept for diagnosis.
3. For a scan, each device found is matched to a known device, by MAC address
   first, then by IP address. The rules and their limits are in
   [inventory/ingest.py](inventory/ingest.py). For a health check, each
   monitored device's health is updated and alerts are sent; see below.

## Running on the VM

You need an Ubuntu Server VM with
[Docker Engine and the Compose plugin](https://docs.docker.com/engine/install/ubuntu/).
Use bridged networking, so the VM is on the same LAN as the devices it scans.

```bash
git clone https://github.com/Rokikxf/wall-hub.git
cd wall-hub
cp .env.example .env
nano .env            # set the values marked CHANGE; add the VM's IP to DJANGO_ALLOWED_HOSTS
docker compose up --build --detach
docker compose exec web python manage.py createsuperuser
```

Then open `http://<VM IP>:8000`, log in, and go to **Scans**. To scan from the
command line instead, and wait for the result:

```bash
docker compose exec web python manage.py scan 192.168.1.0/24 --wait
```

To update: `git pull && docker compose up --build --detach`. Migrations run
automatically when `web` starts.

### Why the worker container is different

The worker runs with `network_mode: host` and the `NET_RAW` and `NET_ADMIN`
capabilities. On Docker's default bridge network, nmap would only see Docker's
internal network: no ARP, no MAC addresses, and no devices on the LAN. The
capabilities are attached only to the nmap binary in the image (`setcap`), and
the worker runs as an unprivileged user.

Because the worker is on the host network, it reaches PostgreSQL and Redis on
`127.0.0.1`. Their ports are published on the VM's loopback interface only,
not on the LAN.

## Automatic scans and new-device alerts

You don't need to type addresses. **Scan local networks** on the Scans page
(or `manage.py scan --local --wait`) runs `wall-scan --local`. That finds every
private network the VM is directly attached to, and skips Docker's and VPN
networks. Each scan's page lists the networks it actually scanned.

To scan on a schedule, set in `.env`:

| Setting                         | Effect                                                      |
|---------------------------------|-------------------------------------------------------------|
| `WALL_AUTO_SCAN_INTERVAL_MIN=60` | A quick discovery sweep (no ports) every 60 minutes: finds new devices fast. |
| `WALL_AUTO_PORT_SCAN_HOUR=2`    | A full scan, with ports, every day at 02:30.                |
| `WALL_SCAN_EXCLUDE_INTERFACES=enp0s3` | Never scan these interfaces' networks (here VirtualBox's NAT). |

Both are off by default, because they scan whatever network the VM is plugged
into: switch them on only where you are allowed to scan. An automatic scan does
nothing while another scan is still running.

**New devices:** when a scan sees a device for the first time, the hub creates
a *New device* alert and emails `WALL_ALERT_EMAILS`. It sends one email per
scan, listing every new device with its MAC address, vendor, hostname and open
ports. The very first scan is the baseline and alerts nothing; otherwise every
device in the office would be "new". Turn this off with
`WALL_ALERT_NEW_DEVICES=false`. Phones and laptops with randomised MAC
addresses can show up as new when their address changes.

## Monitoring and alerts

Open a device and tick **Monitor this device**. By default it is pinged. For a
device that drops ping, such as a Windows PC, enter a TCP port that is open on
it instead, e.g. 445 or 3389.

- Beat starts a run every `WALL_HEALTHCHECK_INTERVAL_S` seconds (60 by default).
  The worker checks all monitored devices in one `wall-healthcheck` call.
- A device counts as **down** after `WALL_ALERT_AFTER_FAILURES` failed checks in
  a row (2 by default). That avoids alarms for a single lost ping. One
  successful check brings it back **up**.
- Each change creates one alert: one DOWN email when the device goes down, and
  one BACK UP email, with the outage length, when it returns. Alerts are listed
  on the **Alerts** page and on each device's page. The rules are in
  [inventory/monitoring.py](inventory/monitoring.py).
- Runs never overlap: if a run is still going when the next is due, the next one
  is skipped. A run that fails (for example, ping not permitted) leaves every
  device's health unchanged, and the device list shows the reason.

To send email, set the `EMAIL_*` values and `WALL_ALERT_EMAILS` in `.env`.
Without `EMAIL_HOST`, emails are printed to the worker's log
(`docker compose logs worker`). To check the mail settings, and to run a health
check now and wait for the result:

```bash
docker compose exec web python manage.py sendtestemail you@example.com
docker compose exec web python manage.py healthcheck --wait
```

Ping uses Linux ping sockets and needs no capabilities. The host must allow
them through `net.ipv4.ping_group_range`, because the worker shares the host's
network. Ubuntu Server 24.04 has them **disabled** (`1 0`); without them every
health check run fails with `icmp_not_permitted`. Allow them once on the VM:

```bash
echo 'net.ipv4.ping_group_range = 0 2147483647' | sudo tee /etc/sysctl.d/60-ping.conf
sudo sysctl -p /etc/sysctl.d/60-ping.conf
```

## Assets: owners, locations, warranties and licences

Scans find devices; people add the business details. These are never changed
by a scan.

- **People** and **Locations** have their own pages. Set a device's owner,
  location, type, asset tag, make and model, serial number, purchase date and
  warranty end date with **Edit asset details** on its page.
- **Licences** have a key, a number of seats (empty means unlimited) and an
  optional expiry date. Assign each one to people (for per-user licences such
  as Microsoft 365) and to devices (for per-device licences). Each assignment
  uses a seat. Over-allocation is shown, not blocked, so the list matches
  reality. Keys are hidden until you click **Show** on the licence page.
- **Devices** can be searched and filtered: by IP address, name, hostname,
  MAC address, serial number, asset tag or owner, and by type, owner or location.
- **Expiring** lists warranties and licences that end in the next 90 days or
  ended in the last 90. Every morning (`WALL_EXPIRY_REMINDER_HOUR`), beat emails
  a digest of whatever ends in exactly 30, 7 or 1 days, or today
  (`WALL_EXPIRY_REMINDER_DAYS`), to `WALL_ALERT_EMAILS`. The rule depends only
  on the date, so nothing is stored and nothing is sent twice. The logic is in
  [inventory/expiry.py](inventory/expiry.py).

## Security notes

- The hub serves plain HTTP. That is fine on a trusted LAN, but HTTPS through
  a reverse proxy is still to come. Until then, `manage.py check --deploy`
  reports four HTTPS-related warnings.
- Scans are limited to private address ranges of at most a /16. The scan
  form checks this, and wall-scan enforces it again.
- Every page requires a login. Create users with `createsuperuser` or in the
  admin site at `/admin/`.

## Contracts

`contracts/<tool>/v<major>.json` are the hub's copies of the tools' output
schemas. See [contracts/README.md](contracts/README.md). The rules all tools
follow are in `CONTRACT.md` in the tool template repository.

## Development

Works on Windows or Linux, without Docker:

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux: . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                            # SQLite; no Redis, nmap or network needed
ruff check . && ruff format --check .
```

The tests replace wall-scan with the example documents from `contracts/`, so
the hub is tested against exactly what the contract promises.

CI runs the tests on PostgreSQL. It then builds the Docker image, starts the
whole stack, and runs a real scan of 127.0.0.1 through web, Redis, the worker,
wall-scan and nmap. It then monitors the device that scan found, and runs a real
health check of it through wall-healthcheck.

```
wallhub/       Django project: settings, URLs, Celery app
inventory/     the app: models, scan task, contract validation, views
  contracts.py   validates tool output against contracts/
  runner.py      runs a wall-* tool and returns a valid document
  ingest.py      stores a scan and matches devices
  monitoring.py  health checks to device health and alerts
  alerts.py      alert emails
  expiry.py      warranty and licence expiry, reminder emails
  asset_views.py people, locations, licences and asset details pages
contracts/     the hub's copies of the tool contracts
templates/     base layout and login page
static/vendor/ Bootstrap 5.3.8 and htmx 2.0.11, stored here so the hub works offline
```
