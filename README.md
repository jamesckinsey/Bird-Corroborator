# Bird Corroborator

Bird Corroborator is a lightweight companion to BirdNET-Go. It polls the existing BirdNET-Go HTTP API, stores detections in SQLite, enriches them with nearby BirdWeather observations, and provides a FastAPI API and responsive dashboard. It performs no audio analysis and never controls or writes to BirdNET-Go.

Production deployment targets Docker on `birdpi` (Debian Linux, Raspberry Pi 4, arm64/aarch64). The Compose project contains **only Bird Corroborator**. BirdNET-Go remains a separately managed container.

## Architecture and isolation

```text
existing birdnet-go container --published HTTP port--> bird-corroborator
existing BirdNET data directory --read-only mount-----> /birdnet-data
BirdWeather / Wikimedia Commons --HTTPS-------------> bird-corroborator
Corroborator SQLite and images <---------------------- /home/jkinsey/bird-corroborator-data
dashboard/API <--------------------------------------- birdpi:8000
```

The `/birdnet-data` mount is present for read-only visibility and future compatible media references. Current ingestion uses BirdNET-Go's HTTP API; it does not modify files in that mount. Docker starts and supervises Uvicorn directly—there is no production systemd unit.

## Configuration

All runtime configuration and secrets come from `.env`, which is ignored by Git and excluded from the image build context. Copy `.env.example` and set at least:

```env
BIRDNET_BASE_URL=http://host.docker.internal:8080
HOME_LATITUDE=42.362
HOME_LONGITUDE=-71.449
LOCAL_TIMEZONE=America/New_York
BIRDWEATHER_EXCLUDED_STATION_IDS=
```

Find the host port already published by BirdNET-Go without changing it:

```bash
docker ps --filter name='^birdnet-go$'
docker port birdnet-go
curl -fsS http://127.0.0.1:PORT/api/v2/ping
```

The deployed BirdNET-Go port is 8080. `host.docker.internal` is mapped to Docker's host gateway by Compose. Do not use `127.0.0.1` in `BIRDNET_BASE_URL`; inside the Corroborator container it refers to the Corroborator itself.

Important defaults include a 300-second poll interval, 12-hour startup catch-up, one enrichment worker, load shedding, 10-mile radius, 24-hour lookback, and a 15-minute BirdWeather cache. Compose deliberately fixes container-owned paths to `/data/birds.db` and `/data/species-images`.

### Evidence definitions and station exclusion

- A **local detection** is any detection reported by the BirdNET-Go installation on birdpi. Corroborator applies no minimum-confidence admission threshold: it retains the original BirdNET confidence, displays it, exposes it through the API, and uses it as one input to the corroboration score.
- An **independent station** is a unique BirdWeather `station.id`, excluding IDs configured in `BIRDWEATHER_EXCLUDED_STATION_IDS`. It is not inferred from geographic distance.
- **Total nearby BirdWeather detections** counts distinct returned BirdWeather observations. Repeats from one station increase this total but that station counts only once.

BirdWeather diagnostic log lines contain the stable station ID, species, approximate distance, detection time, and whether the station was excluded. Identify birdpi's own station after activity occurs:

```bash
docker logs --tail 500 bird-corroborator 2>&1 | grep 'BirdWeather observation'
```

Find the station ID associated with birdpi, then set it in `.env`. Multiple IDs are comma-separated:

```env
BIRDWEATHER_EXCLUDED_STATION_IDS=12345
# or: BIRDWEATHER_EXCLUDED_STATION_IDS=12345,67890
```

Rebuild/restart after changing `.env`. Existing stored matches from excluded IDs are filtered when APIs and pages calculate evidence; future responses are discarded before scoring and persistence.

## First deployment on birdpi

Install Docker Engine and its Compose plugin using Docker's Debian instructions if needed. Then run these exact commands as `jkinsey`:

```bash
ssh jkinsey@birdpi
cd /home/jkinsey
git clone git@github.com:jamesckinsey/Bird-Corroborator.git Bird-Corroborator
cd /home/jkinsey/Bird-Corroborator
cp .env.example .env
chmod 600 .env
docker port birdnet-go
nano .env
mkdir -p /home/jkinsey/bird-corroborator-data
docker compose config
docker compose build
docker compose up -d
docker compose ps
curl -fsS http://localhost:8000/api/v1/status
```

Before `docker compose up`, set the published BirdNET-Go port and coordinates in `.env`. The official Python 3.11 Debian base image is multi-architecture and supports `linux/arm64` natively. Do not add BirdNET-Go to this Compose project or run these Compose commands from its installation directory.

Open `http://birdpi:8000/` for the dashboard or `http://birdpi:8000/docs` for API documentation. Main API routes include `/api/v1/status`, `/api/v1/detections/today`, `/api/v1/detections/latest?limit=20`, `/api/v1/species/today`, and `/api/v1/nearby/today`.

## Validation and routine operations

The healthcheck calls `/api/v1/status` inside the container. A response proves the HTTP service and SQLite status route operate; BirdNET-Go or BirdWeather may still be reported as temporarily degraded in the JSON.

```bash
# Status and health
cd ~/Bird-Corroborator
docker compose ps
docker inspect --format '{{.State.Health.Status}}' bird-corroborator
curl -fsS http://localhost:8000/api/v1/status

# Follow logs
docker compose logs -f --tail=200 bird-corroborator

# Restart only Corroborator
docker compose restart bird-corroborator

# Stop/remove only Corroborator; persistent data remains
docker compose down

# Start it again
docker compose up -d
```

None of these commands targets the independently managed `birdnet-go` container.

## Upgrade

Back up the Corroborator database, then pull and rebuild. The brief `down` used for a consistent SQLite copy affects only Corroborator:

```bash
cd ~/Bird-Corroborator
docker compose down
cp -a /home/jkinsey/bird-corroborator-data/birds.db \
  "/home/jkinsey/bird-corroborator-data/birds.db.backup-$(date +%F-%H%M%S)"
git pull
docker compose up -d --build
docker compose ps
curl -fsS http://localhost:8000/api/v1/status
```

Database initialization is additive. Corroborator-owned data survives image and container replacement in `/home/jkinsey/bird-corroborator-data`.

## Rollback and troubleshooting

Record the current revision before an upgrade with `git rev-parse HEAD`. To roll code back without touching BirdNET-Go or Corroborator data:

```bash
cd ~/Bird-Corroborator
git log --oneline -10
git checkout PREVIOUS_GOOD_COMMIT
docker compose up -d --build
curl -fsS http://localhost:8000/api/v1/status
```

After diagnosis, return with `git switch master`. Restore a database backup only when a release specifically documents an incompatible migration:

```bash
cd ~/Bird-Corroborator
docker compose down
cp -a /home/jkinsey/bird-corroborator-data/birds.db.backup-TIMESTAMP \
  /home/jkinsey/bird-corroborator-data/birds.db
docker compose up -d
```

Useful read-only diagnostics:

```bash
docker compose config
docker compose ps
docker compose logs --tail=300 bird-corroborator
docker inspect bird-corroborator
docker stats --no-stream bird-corroborator
docker port birdnet-go
curl -v http://127.0.0.1:PORT/api/v2/ping
ls -ld /home/jkinsey/bird-corroborator-data
df -h /home/jkinsey/bird-corroborator-data
```

The concise production checks are:

```bash
docker ps
curl -fsS http://localhost:8000/api/v1/status
docker logs --tail 100 bird-corroborator
```

If startup reports permission denied for `/data`, ensure the host directory is owned by the account running Docker:

```bash
sudo chown -R jkinsey:jkinsey /home/jkinsey/bird-corroborator-data
docker compose up -d
```

If BirdNET-Go is unreachable, verify its published host port and `BIRDNET_BASE_URL`; do not restart, recreate, edit, or join BirdNET-Go to this Compose project. If port 8000 is occupied, identify the listener with `sudo ss -ltnp '( sport = :8000 )'` rather than changing BirdNET-Go.

## Development and maintenance

Local development remains standard Python and does not require Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
```

Run maintenance in the deployed container:

```bash
docker compose exec bird-corroborator python -m app.cli catchup --hours 72
docker compose exec bird-corroborator python -m app.cli images-reset
```

`images-reset` moves cached images to a timestamped backup within the Corroborator data directory and queues fresh retrieval; it does not delete or alter BirdNET-Go media.

Species images are requested asynchronously from Wikimedia Commons with an application-identifying User-Agent, stored under `/data/species-images`, and served locally. Successful images and attribution metadata are reused from cache. Failures—including HTTP 403—leave the local placeholder in place and are retried only after the configured backoff.

## Runtime behavior

Normal polling requests at most 100 recent records every 300 seconds. A durable UTC checkpoint with a five-second overlap avoids gaps, and unique source IDs prevent duplicates. Ingestion commits detections before external enrichment. BirdWeather and Wikimedia requests are serialized, retried with backoff, cached, and deferred during high system load. Dashboard page loads query local SQLite only and never trigger external requests.
