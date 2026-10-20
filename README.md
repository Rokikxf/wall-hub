# wall-hub

wall-hub keeps track of the computers, printers and other devices on your
network, and tells you when one needs attention. It runs on one small Linux
machine or virtual machine on that network, and you use it from a web browser.

- **It finds devices by itself.** It scans your network and lists everything
  that answers: IP and MAC address, manufacturer, name and open ports. It can
  scan every hour, and email you when a device it has never seen joins.
- **It watches the devices you care about.** It checks them every minute and
  emails you when one goes down, and again when it is back.
- **It keeps your asset records:** who has each device, where it is, its serial
  number, purchase date and warranty, and your software licences and their
  seats. It reminds you before warranties and licences run out.
- **It reads printers and network equipment:** model, serial number, uptime and
  toner levels, with an email when toner runs low.
- **It wakes computers remotely** with Wake-on-LAN, and checks that they came on.
- **It draws a map** of your networks, their devices and the routers between them.

> Only scan networks you own or have written permission to scan.

## What you need

- **A machine that stays on**, connected to the same network as your devices:
  a small PC, a server or a virtual machine. It is tested on Ubuntu Server
  24.04, and needs about 2 GB of disk space, plus room for its database to grow.
- **Docker** with its Compose plugin. Install it with
  [Docker's guide for Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
- **For email alerts:** an email account that can send mail through SMTP. Gmail
  works with an [app password](https://support.google.com/accounts/answer/185833).

On a VirtualBox virtual machine, give the VM a **bridged** network adapter, so
it sits on your network like any other computer. A VM with only NAT cannot see
your devices.

## Install

Run these commands on the machine that will run wall-hub. They start with
`sudo`; leave it out if your user is in the `docker` group.

**1. Allow ping.** wall-hub checks devices with ping, and Ubuntu Server only lets
ordinary programs ping once you allow it:

```bash
echo 'net.ipv4.ping_group_range = 0 2147483647' | sudo tee /etc/sysctl.d/60-ping.conf
sudo sysctl -p /etc/sysctl.d/60-ping.conf
```

**2. Download wall-hub** and make your settings file:

```bash
git clone https://github.com/Rokikxf/wall-hub.git
cd wall-hub
cp .env.example .env
```

**3. Fill in the settings.** Open the file with `nano .env` and set these four:

| Setting                | What to put                                                        |
|------------------------|--------------------------------------------------------------------|
| `DJANGO_SECRET_KEY`    | A long random string (see below). It protects logins.              |
| `POSTGRES_PASSWORD`    | Another random string: the database's password. You never type it again. |
| `DJANGO_ALLOWED_HOSTS` | Add the machine's IP address: `localhost,127.0.0.1,192.168.1.10`. |
| `TIME_ZONE`            | Your time zone, for example `Europe/Dublin` or `America/New_York`. |

To make a random string, run `openssl rand -hex 32`, once for each. To find
the machine's IP address, run `hostname -I`. The other settings can wait; they
are explained under [Settings](#settings).

**4. Start wall-hub:**

```bash
sudo docker compose up --build --detach
```

The first start downloads and builds everything, which takes a few minutes.
After that, wall-hub starts by itself whenever the machine starts.

**5. Create your login.** It asks for a username, an email address (you can
leave it empty) and a password:

```bash
sudo docker compose exec web python manage.py createsuperuser
```

**6. Open it.** On any computer on the network, open a browser at
`http://<the machine's IP address>:8000`, for example `http://192.168.1.10:8000`,
and log in.

## First steps

1. **Scan your network.** Go to **Scans** and click **Scan local networks**.
   wall-hub works out by itself which networks it is connected to. The scan takes
   a few minutes; its row updates by itself, and the devices it finds appear on
   **Devices**. This first scan is the starting point: from now on, wall-hub tells
   you about devices it has not seen before.
2. **Add people and places.** Add the people who use your devices under
   **People**, and rooms or sites under **Locations**.
3. **Describe your devices.** Open a device and click **Edit asset details**:
   give it a name such as "Reception printer", a type, an owner, a location and
   whatever else you know, such as the serial number or the warranty end date.
4. **Monitor the devices that matter.** On a device's page, tick **Monitor this
   device** and click **Save**. Windows PCs do not answer ping by default: for
   them, also enter a port that is open on them under **Check TCP port**, such
   as `445`, or `3389` if Remote Desktop is on.
5. **Get emails.** Set up [email alerts](#email-alerts).
6. **Scan automatically.** Set `WALL_AUTO_SCAN_INTERVAL_MIN=60` to look for new
   devices every hour (see [Automatic scans](#automatic-scans)).

## Using wall-hub

### Devices

The home page. The tiles at the top show how many devices there are, how many
monitored devices are down, the alerts of the last 24 hours and when the last
scan ran. Search by IP address, name, MAC address, serial number, asset tag or
owner, and filter by type, owner or location. The page updates itself every 30
seconds. When a monitored device is down, a red **1 down** shows in the header
of every page.

| Status            | Meaning                                                            |
|-------------------|--------------------------------------------------------------------|
| **Up · 1.4 ms**   | Answered the last check, in 1.4 milliseconds.                      |
| **1 failed check** | Missed the last check. One more miss and it counts as down.       |
| **Down since 20:22** | Missed two checks in a row. You got an email.                   |
| **Not checked yet** | Monitored, waiting for its first check.                          |
| not monitored     | wall-hub does not check this device.                               |

### A device's page

The top shows the device's status, type, owner, location and when it was last
seen. Below:

- **Network:** what the scans found: IP and MAC address, manufacturer, hostname
  and open ports. Scans keep this up to date.
- **Asset:** your records. Change them with **Edit asset details**; scans never
  overwrite them.
- **Monitoring:** whether wall-hub checks the device, and how: ping, or a TCP
  port for devices that block ping.
- **Wake-on-LAN:** wake the device with **Wake** (see
  [Waking computers](#waking-computers)).
- **Licences** assigned to the device, **SNMP** details for printers and
  network equipment, and the device's **Alerts**.

### Map

**Map** draws each network wall-hub has scanned as a box of its devices. The
star is wall-hub itself, and the lines show how it is connected to each network.
Each network's router is a diamond, with a line to the Internet.

Shapes show the device type and colours their health: green is up, red is down,
grey is not checked yet, and an empty outline is not monitored. A faded, dashed
device was not seen in the last scan: it is switched off, or gone. Click a
device for its details, or use **Find** to search. You can drag devices around;
your browser remembers where, and **Re-arrange** puts them back in order.

### Alerts

| Alert          | When                                                         |
|----------------|--------------------------------------------------------------|
| **Down**       | A monitored device misses two checks in a row.               |
| **Back up**    | It answers again; the email says how long it was down.       |
| **New device** | A scan sees a device for the first time. One email per scan lists them all. |
| **Supply low** | A printer's toner or other supply drops below 10%.           |

Each alert is emailed to the addresses in `WALL_ALERT_EMAILS`, and listed under
**Alerts** and on the device's page. If an email could not be sent, the
**Email** column says **failed**; point at it to see why.

### People, locations and licences

**People** and **Locations** list who has which device and where devices are;
each person's and place's page lists their devices. Under **Licences**, add your
software licences with their key, number of seats and expiry date, and assign
each to the people (for per-user licences such as Microsoft 365) or devices
(for per-computer licences) that use it. Each assignment takes a seat. When more
are assigned than you have seats, the licence is marked in red. Keys stay hidden
until you click **Show**.

### Expiring warranties and licences

**Expiring** lists the warranties and licences that end in the next 90 days,
and those that ended in the last 90. Once email is set up, wall-hub also sends
a reminder at 8:00, 30 days, 7 days and 1 day before each end date, and on the
day itself.

### Printers and network equipment (SNMP)

wall-hub reads printers and network equipment that have SNMP switched on, every
6 hours: the model, serial number, name, location and uptime, and, for
printers, each supply's level as a bar. Click **Read now** on a device's page to
read it straight away. An empty model or serial number in your asset details is
filled in from SNMP; anything you entered is left alone.

It reads devices whose type is Printer or Network equipment automatically, and
devices with a printing port open (printers that have no type yet). For any
other device, choose **On** under **Read with SNMP**. SNMP must be switched on in the device's
settings, usually with the community name `public`; if yours uses another, set
`WALL_SNMP_COMMUNITY`.

### Waking computers

**Wake** on a device's page switches a computer on over the network, with
Wake-on-LAN. wall-hub then checks for up to 3 minutes whether it answers, and
shows **Awake** or **No answer**. To work:

- The computer must have Wake-on-LAN switched on: in its BIOS or UEFI settings,
  in its network card's settings and, on Windows, with Fast Startup off.
  [How to switch it on](https://github.com/Rokikxf/wall-wol#preparing-a-device).
- It must be connected by cable, on the same network as wall-hub.
- A scan must have found its MAC address. Otherwise the button is greyed out.
- Windows PCs block ping, so set **Check TCP port** to `445` first, or wall-hub
  cannot tell that the PC woke up.

### Light and dark

wall-hub follows your computer's light or dark setting. The half-circle button
in the header switches between them; your browser remembers the choice.

## Email alerts

Put your mail server's details in `.env`. For Gmail, with an
[app password](https://support.google.com/accounts/answer/185833):

```
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=you@gmail.com
WALL_ALERT_EMAILS=it@example.com
WALL_HUB_URL=http://192.168.1.10:8000
```

`WALL_ALERT_EMAILS` is who gets the alerts (several addresses separated by
commas), and `WALL_HUB_URL` puts a link to the device in each email. Apply the
settings, then send yourself a test email:

```bash
sudo docker compose up --detach --force-recreate
sudo docker compose exec web python manage.py sendtestemail you@example.com
```

## Automatic scans

Automatic scans are off until you switch them on, because they scan whatever
network the machine is plugged into. In `.env`:

```
WALL_AUTO_SCAN_INTERVAL_MIN=60
WALL_AUTO_PORT_SCAN_HOUR=2
```

The first line looks for devices every 60 minutes, which is quick and finds new
devices soon after they connect. The second also scans every device's open ports
each night at 2:30. On a VirtualBox VM, add `WALL_SCAN_EXCLUDE_INTERFACES=enp0s3`
so wall-hub does not scan VirtualBox's own NAT network.

## Settings

All settings live in `.env`. After changing one, apply it with
`sudo docker compose up --detach --force-recreate`.

**Basics**

| Setting                | Default            | Meaning                                         |
|------------------------|--------------------|-------------------------------------------------|
| `DJANGO_SECRET_KEY`    | (must be set)      | A long random string that protects logins.     |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | The addresses you open wall-hub at.          |
| `TIME_ZONE`            | `Europe/Dublin`    | For the times shown and the email schedule.     |
| `POSTGRES_PASSWORD`    | (must be set)      | The database password.                          |
| `WALL_HUB_PORT`        | `8000`             | The port wall-hub is opened at.                 |

**Email:** `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`, `WALL_ALERT_EMAILS` and `WALL_HUB_URL`,
as in [Email alerts](#email-alerts). Without `EMAIL_HOST`, emails are only
written to the log; alerts are still listed under **Alerts**.

**Scans**

| Setting                        | Default | Meaning                                         |
|--------------------------------|---------|-------------------------------------------------|
| `WALL_AUTO_SCAN_INTERVAL_MIN`  | `0`     | Look for devices every N minutes (`0`: never).  |
| `WALL_AUTO_PORT_SCAN_HOUR`     | empty   | Also scan ports every night at this hour, at :30 (empty: never). |
| `WALL_SCAN_EXCLUDE_INTERFACES` | empty   | Network adapters whose networks are never scanned, e.g. `enp0s3`. |
| `WALL_ALERT_NEW_DEVICES`       | `true`  | Email when a scan finds a new device.           |
| `WALL_SCAN_RETENTION_DAYS`     | `90`    | Delete scans older than this (`0`: keep all).    |
| `WALL_SCAN_TIMEOUT_S`          | `600`   | Stop a scan that takes longer than this.         |
| `WALL_DEFAULT_TARGETS`         | empty   | Addresses already filled in under **Scan specific addresses**. |

**Monitoring**

| Setting                       | Default | Meaning                                          |
|-------------------------------|---------|--------------------------------------------------|
| `WALL_HEALTHCHECK_INTERVAL_S` | `60`    | Check monitored devices every N seconds.         |
| `WALL_ALERT_AFTER_FAILURES`   | `2`     | Missed checks in a row before a device is down.  |

**Printers and network equipment (SNMP)**

| Setting                    | Default  | Meaning                                       |
|----------------------------|----------|-----------------------------------------------|
| `WALL_SNMP_COMMUNITY`      | `public` | The SNMP community name of your devices.      |
| `WALL_SNMP_INTERVAL_H`     | `6`      | Read them every N hours (`0`: only with **Read now**). |
| `WALL_TONER_ALERT_PERCENT` | `10`     | Email when a supply drops below this.         |

**Wake-on-LAN**

| Setting              | Default           | Meaning                                          |
|----------------------|-------------------|--------------------------------------------------|
| `WALL_WOL_WAIT_S`    | `180`             | How long to check whether a woken device answers (`0`: don't check). |
| `WALL_WOL_BROADCAST` | `255.255.255.255` | Where to send the packets for a device whose network no scan has covered. |

**Reminders**

| Setting                     | Default      | Meaning                                    |
|-----------------------------|--------------|--------------------------------------------|
| `WALL_EXPIRY_REMINDER_DAYS` | `30,7,1,0`   | Days before an end date to send a reminder (`0`: on the day). |
| `WALL_EXPIRY_REMINDER_HOUR` | `8`          | The hour the reminders are sent.           |

## Everyday tasks

**Update to the newest version.** Your data is kept:

```bash
cd wall-hub
git pull
sudo docker compose up --build --detach
```

**Back up.** Everything wall-hub knows is in its database. This saves it to a
file; keep it, together with a copy of `.env`, somewhere other than this machine:

```bash
sudo docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > wall-backup.sql
```

To restore it on a new machine: do the [Install](#install) steps 1 and 2, put
your old `.env` back in place of the new one, and replace step 4 with:

```bash
sudo docker compose up --detach db
sudo docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' < wall-backup.sql
sudo docker compose up --build --detach
```

You can then log in with your old users; skip step 5.

**Add another user.** Run `createsuperuser` again (step 5 of
[Install](#install)), or use **Admin** in the header, then **Users**. In
wall-hub's pages, every user can see and change everything.

**Stop and start wall-hub:** `sudo docker compose stop` and
`sudo docker compose start`, in the `wall-hub` folder.

**See what it is doing:** `sudo docker compose logs --tail 50 worker` shows the
latest scans, checks and emails.

## Troubleshooting

**The browser says "Bad Request (400)".** The address you opened is not in
`DJANGO_ALLOWED_HOSTS`. Add it, then apply the settings.

**The page does not open at all.** Check that wall-hub is running: in the
`wall-hub` folder, `sudo docker compose ps` should list five services as
running. Check also that you used port 8000, and that no firewall blocks it.

**Monitored devices stay "Not checked yet", and the devices page says "This
user may not open ICMP sockets".** Ping is not allowed yet: do step 1 of
[Install](#install).

**Devices have no MAC address or manufacturer.** The machine is not on the
same network as them. On a virtual machine, use a bridged adapter. Devices
behind a router never show a MAC address.

**A Windows PC shows as down, but it is on.** Windows does not answer ping. Set
**Check TCP port** to `445` on its page.

**Emails do not arrive.** Send a test email (see [Email alerts](#email-alerts)):
it shows the mail server's error, if any. For Gmail, use an app password, not
your normal password. Also check the **Email** column under **Alerts**.

**Wake does nothing.** See the list under [Waking computers](#waking-computers).
The **Sent to** column shows where the packets went: it should end in `.255` on
the computer's own network.

**A phone shows up as a new device again and again.** Phones change their MAC
address on each network, and sometimes over time, so wall-hub cannot tell it is
the same phone.

**A printer shows no SNMP details.** Switch SNMP on in the printer's settings,
check the community name (`WALL_SNMP_COMMUNITY`), and click **Read now**: the
page then says why the read failed.

## Security

- wall-hub serves plain HTTP. Use it on a network you trust, and do not make it
  reachable from the internet.
- Every page needs a login. Give each person their own, with a strong password.
- `.env` holds your passwords: keep it private, and keep a copy with your
  backups.
- The database is only reachable from the machine itself, not from the network.

## For developers

How wall-hub works inside, the contracts it checks the tools' output against,
the tests and the code layout are in [DEVELOPMENT.md](DEVELOPMENT.md). The work
on the network is done by four command-line tools:
[wall-scan](https://github.com/Rokikxf/wall-scan),
[wall-healthcheck](https://github.com/Rokikxf/wall-healthcheck),
[wall-snmpinfo](https://github.com/Rokikxf/wall-snmpinfo) and
[wall-wol](https://github.com/Rokikxf/wall-wol).
