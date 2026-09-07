# Bird Corroborator

Bird Corroborator is a low-priority companion to BirdNET-Go on the same Raspberry Pi. It stores BirdNET-Go detections, enriches them with nearby BirdWeather evidence, calculates a transparent corroboration score, and exposes a LAN-only FastAPI API. It performs no audio work or ML inference and never controls, changes, or writes to BirdNET-Go.

> **EMERGENCY STOP — does not stop or alter BirdNET-Go**
>
> ```bash
> sudo systemctl stop bird-corroborator
> ```

## Architecture and verified APIs

```text
BirdNET-Go local API -> checkpointed poll -> SQLite
                                                ^
BirdWeather -> cached/load-shed single worker ---+-> FastAPI -> home LAN
```

Current BirdNET-Go source documents `GET /api/v2/detections/recent?limit=...`, date-ranged `GET /api/v2/detections`, `/api/v2/detections/{id}`, `/api/v2/ping`, and SSE. Responses contain stable numeric IDs, names, fractional confidence, ISO-8601 timestamps, and clip metadata. Normal polls use `recent`; bounded catch-up uses `start_date`. Private mode may require authentication, which V1 does not configure. See the [BirdNET-Go API v2 documentation](https://github.com/tphakala/birdnet-go/blob/main/internal/api/v2/README.md).

BirdWeather documents unauthenticated GraphQL at `https://app.birdweather.com/graphql`. Its `detections` query accepts time, species, and NE/SW bounds and returns IDs, station metadata, coordinates, timestamps, species, and confidence. The client searches for the exact species, queries a bounding square, then applies Haversine radius locally. No numeric rate limit is published, so V1 uses a 15-minute cache, 15-second timeout, three exponential retries, bounded results, and one enrichment at a time. See the [BirdWeather API](https://app.birdweather.com/api/index.html).

Both adapters and paths are isolated/configurable. Validate them against the installed versions.

## Requirements and ARM audit

- Raspberry Pi OS/Debian-family Linux with systemd
- Python 3.11+ with `venv`
- Local BirdNET-Go HTTP API; Internet is optional for ingestion

Runtime dependencies are FastAPI, plain Uvicorn, SQLAlchemy, Pydantic Settings, HTTPX, and Tenacity. There is no Docker, Redis, external queue, monitoring agent, or multi-worker server. Pydantic Core and SQLAlchemy's Greenlet dependency provide common ARM/aarch64 wheels; an old/unsupported 32-bit OS may attempt native compilation. Verify wheel availability during installation. Optional native `uvicorn[standard]` speedups are deliberately omitted.

Detect the actual target first:

```bash
uname -m
cat /etc/os-release
tr -d '\0' </proc/device-tree/model; echo
systemctl --version
python3 --version
```

Validate systemd directives with `sudo systemd-analyze verify /etc/systemd/system/bird-corroborator.service`. `Nice` is broadly supported; `CPUWeight` and `MemoryMax` require their cgroup controllers. Inspect effective values with `systemctl show bird-corroborator -p Nice -p CPUWeight -p MemoryMax -p ControlGroup`. If the target rejects a resource directive, retain `Nice=10`, remove only that rejected line, and document the local variation.

## Configuration

Copy `.env.example` to `.env`. Supply or verify:

```env
BIRDNET_BASE_URL=http://127.0.0.1:ACTUAL_PORT
HOME_LATITUDE=YOUR_DECIMAL_LATITUDE
HOME_LONGITUDE=YOUR_DECIMAL_LONGITUDE
LOCAL_TIMEZONE=America/New_York
```

Important defaults are `BIRDNET_POLL_SECONDS=300`, `BIRDNET_CATCHUP_HOURS=12`, `BIRDWEATHER_CACHE_MINUTES=15`, `ENRICHMENT_CONCURRENCY=1`, `LOAD_SHEDDING_ENABLED=true`, `LOAD_SHEDDING_THRESHOLD=3.0`, `DATABASE_URL=sqlite:///data/birds.db`, `API_HOST=0.0.0.0`, and `API_PORT=8000`. See [.env.example](.env.example) for every value. `.env` is ignored by Git and installed mode `0640`. Coordinates are not returned or routinely logged and are sent only to BirdWeather.

### Find the BirdNET-Go loopback URL

Do not assume port 8080. Inspect read-only state:

```bash
sudo ss -ltnp
systemctl status birdnet-go --no-pager
systemctl cat birdnet-go
```

The existing UI URL, process arguments, or referenced config should reveal the port. Verify without changing BirdNET-Go:

```bash
curl -fsS http://127.0.0.1:PORT/api/v2/ping
curl -fsS 'http://127.0.0.1:PORT/api/v2/detections/recent?limit=2&includeWeather=false'
curl -fsS "http://127.0.0.1:PORT/api/v2/detections?start_date=$(date +%F)&limit=2"
```

If private mode blocks access, stop and add supported authentication later; do not scrape HTML or access BirdNET-Go's database.

# SAFE DEPLOYMENT AND ROLLBACK

BirdNET-Go is primary. Install without enabling startup and validate gradually.

## Stage A — pre-deployment baseline

```bash
cd /opt/bird-corroborator
./scripts/pi-baseline.sh | tee ~/birdnet-baseline-before.txt
```

Or run `uptime`, `free -h`, `df -h`, `vcgencmd measure_temp`, `vcgencmd get_throttled`, and `systemctl --failed`. Also record BirdNET-Go dashboard CPU/load, memory, temperature, audio buffer drops, overruns, analysis latency, and service state. Do not proceed if BirdNET-Go is unhealthy.

## Stage B — install, deliberately not enabled

Package names vary by release; on current Raspberry Pi OS/Debian they are normally:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git curl sqlite3
sudo mkdir -p /opt/bird-corroborator
sudo chown "$USER":"$USER" /opt/bird-corroborator
# Copy/clone this repository's contents into /opt/bird-corroborator.
cd /opt/bird-corroborator
chmod +x scripts/*.sh
sudo ./scripts/install-systemd.sh
sudoedit /opt/bird-corroborator/.env
sudo systemd-analyze verify /etc/systemd/system/bird-corroborator.service
```

The installer creates unprivileged user `birdcorroborator`, `.venv`, its own data directory, and the unit. It **does not start or enable** it and never touches BirdNET-Go.

Test before first start:

```bash
cd /opt/bird-corroborator
sudo .venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
```

## Stage C — first start and five-minute validation

```bash
sudo systemctl daemon-reload
sudo systemctl start bird-corroborator
sudo systemctl status bird-corroborator --no-pager
curl -fsS http://localhost:8000/api/v1/status
```

For five minutes inspect `journalctl -u bird-corroborator -f`, `top`, `free -h`, `vcgencmd measure_temp`, `vcgencmd get_throttled`, and BirdNET-Go health. Stop immediately for new buffer drops/overruns, material latency, sustained load/temperature increase, memory pressure, throttling, or crash loops:

```bash
sudo systemctl stop bird-corroborator
```

## Stage D — thirty-minute validation

After 30 minutes:

```bash
curl -fsS http://localhost:8000/api/v1/detections/today
curl -fsS http://localhost:8000/api/v1/species/today
curl -fsS http://localhost:8000/api/v1/nearby/today
journalctl -u bird-corroborator --since '30 minutes ago' --no-pager
```

Confirm new unique detections, enrichment/cache behavior, responsive API, stable memory/temperature, and unchanged BirdNET-Go drops, overruns, and latency.

## Stage E — several-hour validation

```bash
journalctl -u bird-corroborator --since '4 hours ago' --no-pager
curl -fsS http://localhost:8000/api/v1/status
./scripts/pi-baseline.sh | tee ~/birdnet-baseline-after.txt
diff -u ~/birdnet-baseline-before.txt ~/birdnet-baseline-after.txt || true
```

Require no new BirdNET drops/overruns, sustained resource increase, throttling, crash loop, unbounded backlog, excessive requests, or SQLite errors.

## Stage F — enable at boot only after validation

```bash
sudo systemctl enable bird-corroborator
systemctl is-enabled bird-corroborator
```

## Stage G — controlled reboot

When BirdNET-Go is healthy, run `sudo reboot`. Afterward verify BirdNET-Go first, then:

```bash
systemctl status birdnet-go --no-pager
sudo systemctl status bird-corroborator --no-pager
curl -fsS http://localhost:8000/api/v1/status
```

Confirm catch-up, no duplicates, resumed enrichment, normal load, and healthy BirdNET audio.

## Emergency stop, disable, and isolation test

```bash
sudo systemctl stop bird-corroborator
sudo systemctl disable bird-corroborator
```

Explicitly test rollback isolation during rollout: stop Corroborator, confirm BirdNET-Go and its audio pipeline remain healthy, then run `sudo systemctl start bird-corroborator` and curl status. No Corroborator operation invokes a BirdNET-Go control.

## Safe backup

SQLite uses WAL. The simplest consistent backup stops only Corroborator briefly:

```bash
sudo systemctl stop bird-corroborator
sudo cp -a /opt/bird-corroborator/data/birds.db \
  "/opt/bird-corroborator/data/birds.db.backup-$(date +%F-%H%M%S)"
sudo systemctl start bird-corroborator
```

For a live online backup: `sqlite3 /opt/bird-corroborator/data/birds.db ".backup '/opt/bird-corroborator/data/birds-online-backup.db'"`.

Retain working code before upgrades without copying the live database, environment, or virtualenv:

```bash
sudo systemctl stop bird-corroborator
sudo tar --exclude='./data' --exclude='./.env' --exclude='./.venv' \
  -C /opt/bird-corroborator -czf /opt/bird-corroborator-code-working.tar.gz .
sudo systemctl start bird-corroborator
```

## Upgrade and rollback

Before upgrading, confirm BirdNET health, capture a baseline, back up SQLite/code, and do not update BirdNET-Go simultaneously. Then:

```bash
sudo systemctl stop bird-corroborator
cd /opt/bird-corroborator
sudo .venv/bin/pip install --upgrade .
sudo .venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
sudo systemctl start bird-corroborator
curl -fsS http://localhost:8000/api/v1/status
```

Repeat the resource/audio comparison. Roll back failed code without touching BirdNET-Go:

```bash
sudo systemctl stop bird-corroborator
sudo mv /opt/bird-corroborator /opt/bird-corroborator.failed
sudo mkdir /opt/bird-corroborator
sudo tar -xzf /opt/bird-corroborator-code-working.tar.gz -C /opt/bird-corroborator
sudo mv /opt/bird-corroborator.failed/data /opt/bird-corroborator/
sudo mv /opt/bird-corroborator.failed/.env /opt/bird-corroborator/
sudo mv /opt/bird-corroborator.failed/.venv /opt/bird-corroborator/
sudo /opt/bird-corroborator/.venv/bin/pip install --upgrade /opt/bird-corroborator
sudo systemctl daemon-reload
sudo systemctl start bird-corroborator
curl -fsS http://localhost:8000/api/v1/status
```

Current initialization is additive: missing tables/indexes and a schema-version row are created; records are never dropped. Restore a database backup only if future release notes identify an incompatible migration. An irreversible migration must require a backup and explain rollback.

## Runtime behavior

Normal polling requests at most 100 recent records every 300 seconds. A durable UTC timestamp checkpoint with five-second overlap avoids gaps; unique source IDs prevent duplicates. Startup catch-up is limited to 12 hours and 20 pages. For a deliberate larger import at low load:

```bash
sudo systemctl stop bird-corroborator
cd /opt/bird-corroborator
sudo -u birdcorroborator .venv/bin/python -m app.cli catchup --hours 72
sudo systemctl start bird-corroborator
```

Ingestion stores detections as `PENDING` without waiting for Internet work. A separate worker selects one due SQLite record. Cache entries last 15 minutes. HTTP attempts are limited; persistent failure schedules exponentially delayed SQLite retries, capped at 32 times the 15-minute base and 12 attempts.

Before BirdWeather work, the service reads the cheap one-minute load average. Above 3.0, enrichment and nearby refresh defer while ingestion and REST continue. They resume oldest-first when load falls.

## API and diagnostics

- `/api/v1/status`
- `/api/v1/detections/today`
- `/api/v1/detections/latest?limit=20`
- `/api/v1/detections/{id}`
- `/api/v1/species/today`
- `/api/v1/nearby/today`
- `http://PI-IP:8000/docs`

Status contains connection state, timestamps, SQLite health, pending count, RSS, sampled process CPU, one-minute load, and Pi thermal-zone temperature. Unavailable metrics return `null`.

Find the LAN address with `hostname -I`, then test `curl http://PI-IP:8000/api/v1/status` from a trusted LAN device. Do not configure forwarding, UPnP, tunnels, public DNS, or a public proxy.

## Scoring

BirdNET confidence stays separate. V1 awards 0–20 confidence points; distance 25 (≤2 mi), 18 (≤5 mi), or 10; time 25 (≤15 min), 18 (≤60 min), or 8 (≤24 h); independent stations after the first add 8 (cap 24); repeats add 2 (cap 6); evidence before and after adds 5. At 0–29 the result is `UNVERIFIED`, 30–54 `POSSIBLE`, 55–79 `LIKELY`, and 80–100 `STRONGLY_CORROBORATED`. It is evidence strength, not probability.

## Operations and resource monitoring

```bash
sudo systemctl status bird-corroborator
journalctl -u bird-corroborator -f
sudo systemctl restart bird-corroborator
sudo systemctl stop bird-corroborator
sudo systemctl enable bird-corroborator
sudo systemctl disable bird-corroborator
top
free -h
uptime
vcgencmd measure_temp
vcgencmd get_throttled
systemctl show bird-corroborator -p MemoryCurrent -p CPUUsageNSec -p NRestarts
ps -o pid,ni,%cpu,%mem,rss,etime,cmd -C uvicorn
```

The estimate is near-zero idle CPU, brief work every five minutes, and preferably under 100 MB RSS; these are design expectations, not Pi measurements. `MemoryMax=256M` is a ceiling. Watch sustained CPU, memory pressure, temperature/throttling, BirdNET drops/overruns/latency, growing `pending_enrichments`, and restarts.

Troubleshooting: verify the loopback URL for connection failures; private mode for 401/403; Internet/DNS for unavailable enrichment; load threshold for backlog; coordinates/radius for empty nearby results; and data ownership plus `sqlite3 data/birds.db 'PRAGMA integrity_check;'` for SQLite errors. For any resource concern, use the emergency stop.
