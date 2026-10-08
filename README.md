# wall-hub

The web hub of the wall IT asset management system. It runs the wall-\* command
line tools, checks their JSON output against the contracts, stores the results
and shows them. So far it has one tool, [wall-scan](https://github.com/Rokikxf/wall-scan):
you start a network scan, and the hub keeps an inventory of the devices found.

Only scan networks you own or have written permission to scan.

## How it fits together

```
browser ──► web (Django) ──► Redis ──► worker (Celery) ──► wall-scan ──► nmap ──► LAN
                 │                          │
                 └──────► PostgreSQL ◄──────┘
```

1. **Run scan** creates a `Scan` and queues a Celery task.
2. The worker runs `wall-scan TARGETS --privileged`, reads the JSON document
   from its stdout, and validates it against `contracts/wall-scan/v1.json`.
   Anything that is not a valid document fails the scan with a reason, and
   wall-scan's stderr is kept for diagnosis.
3. Each device found is matched to a known device, by MAC address first, then
   by IP address, and the inventory is updated. The rules and their limits
   are in [inventory/ingest.py](inventory/ingest.py).

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
wall-scan and nmap.

```
wallhub/       Django project: settings, URLs, Celery app
inventory/     the app: models, scan task, contract validation, views
  contracts.py   validates tool output against contracts/
  runner.py      runs a wall-* tool and returns a valid document
  ingest.py      stores a scan and matches devices
contracts/     the hub's copies of the tool contracts
templates/     base layout and login page
static/vendor/ Bootstrap 5.3.8 and htmx 2.0.11, stored here so the hub works offline
```
