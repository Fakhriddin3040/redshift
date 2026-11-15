#!/usr/bin/env bash
# Vigil: one script for a new server.
#
#   cp .env.example .env      # set DOMAIN_URL and COMPOSE_PROJECT_NAME
#   ./deploy.sh               # everything, in order (see below)
#
# What `./deploy.sh` does:
#   1. checks Docker, the .env file and free disk space;
#   2. data: takes the datasets from data_archives/ or downloads them, extracts them,
#      downloads the NASA files, converts everything to the formats the code uses;
#   3. trains the XGBoost pattern classifier and checks that the generator raises
#      no alerts on normal data;
#   4. makes the prepared files readable for the containers;
#   5. builds the images and starts postgres, backend, vdev, client, nginx, Traefik;
#   6. waits until the stream is live and the proxy chain answers, then prints the URL.
#
# Nothing is started before this script is run, and the script does not install or
# start Docker itself. Running it again is safe: finished slow steps are skipped.
#
# Other commands:
#   ./deploy.sh install-docker          install Docker Engine + Compose (Ubuntu / Debian, sudo); once per server
#   ./deploy.sh up                      start the stack without touching the data
#   ./deploy.sh train [--force]         steps 2-4 only (--force redoes every step)
#   ./deploy.sh status                  containers, stream state, crew levels
#   ./deploy.sh incident NAME [CREW] [SEVERITY]   start a demo incident (CREW 1-7, SEVERITY 1-3)
#   ./deploy.sh incidents               list the incident names
#   ./deploy.sh speed 1|10|60           clock rate of the virtual devices
#   ./deploy.sh reset                   wipe the readings and replay the history
#   ./deploy.sh logs [SERVICE]          follow the logs
#   ./deploy.sh down                    stop everything (data in Postgres is kept)
#   ./deploy.sh destroy                 stop everything and delete the Postgres volume

set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
info() { printf '   %s\n' "$*"; }
die()  { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- configuration

load_env() {
  [ -f .env ] || die ".env not found. Run: cp .env.example .env  and set DOMAIN_URL, COMPOSE_PROJECT_NAME, ACME_EMAIL."
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  : "${DOMAIN_URL:?set DOMAIN_URL in .env (the public host name, e.g. vigil.example.org)}"
  : "${COMPOSE_PROJECT_NAME:?set COMPOSE_PROJECT_NAME in .env (e.g. vigil)}"
  TRAEFIK_MODE="${TRAEFIK_MODE:-own}"
  case "$TRAEFIK_MODE" in
    own|external) ;;
    *)        die "TRAEFIK_MODE must be 'own' or 'external', not '$TRAEFIK_MODE'" ;;
  esac
  ACME_EMAIL="${ACME_EMAIL:-}"  # optional: Let's Encrypt no longer needs an address
  export DOMAIN_URL COMPOSE_PROJECT_NAME TRAEFIK_MODE ACME_EMAIL

  COMPOSE_FILES=(-f compose.yml -f compose.traefik.yml)
  [ "$TRAEFIK_MODE" = own ] && COMPOSE_FILES+=(-f compose.traefik-own.yml)
  # Extra compose files for unusual machines, space separated (optional).
  for f in ${COMPOSE_EXTRA_FILES:-}; do COMPOSE_FILES+=(-f "$f"); done
  ML_IMAGE="${COMPOSE_PROJECT_NAME}-ml"
}

dc() { docker compose "${COMPOSE_FILES[@]}" "$@"; }

# retry N command...  : image pulls and package downloads fail now and then on a
# poor connection; what was already downloaded is cached, so trying again is cheap.
retry() {
  local n="$1" i; shift
  for i in $(seq 1 "$n"); do
    "$@" && return 0
    [ "$i" -lt "$n" ] && { info "attempt $i of $n failed, trying again in 10 s"; sleep 10; }
  done
  return 1
}

# Docker Engine + Compose plugin from Docker's own repository (Ubuntu / Debian).
# A separate command on purpose: the normal run never installs or starts Docker.
install_docker() {
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    info "Docker is already installed: $(docker --version)"
  else
    command -v apt-get >/dev/null || die "automatic install supports Ubuntu / Debian only; install Docker Engine by hand."
    say "Installing Docker Engine and the Compose plugin (needs sudo)"
    # shellcheck disable=SC1091
    . /etc/os-release
    sudo apt-get update -qq
    sudo apt-get install -y -qq ca-certificates curl >/dev/null
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
      | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
    info "installed: $(docker --version)"
  fi
  sudo systemctl enable --now docker >/dev/null 2>&1 || true
  if ! id -nG "$USER" | grep -qw docker; then
    sudo usermod -aG docker "$USER"
    info "added $USER to the docker group: log out and in again, then run ./deploy.sh"
  fi
}

check_docker() {
  command -v docker >/dev/null || die "Docker is not installed. Run: ./deploy.sh install-docker   (or install Docker Engine with the Compose plugin yourself)."
  docker compose version >/dev/null 2>&1 || die "The Docker Compose plugin is missing (docker compose version fails)."
  docker info >/dev/null 2>&1 || die "The Docker daemon is not running, or this user may not use it. This script does not start Docker."
}

# ---------------------------------------------------------------- data and model

pipeline() {
  say "Data and model (ml/run_all.py, inside a container)"
  local need_gb=45 free_gb
  free_gb=$(df -Pk . | awk 'NR==2 {print int($4 / 1048576)}')
  if [ ! -d data/ppg+dalia ] && [ "$free_gb" -lt "$need_gb" ]; then
    die "Only ${free_gb} GB free here; the datasets need about ${need_gb} GB while they are prepared."
  fi

  info "building the pipeline image"
  # shellcheck disable=SC2086
  retry 4 docker build -f Dockerfile.ml -t "$ML_IMAGE" ${DOCKER_BUILD_ARGS:-} . \
    || die "could not build the pipeline image (network? see the messages above)"

  mkdir -p data data_archives ml/out ml/models
  # Run as the current user so the files in the repository stay ours, not root's.
  # shellcheck disable=SC2086
  docker run --rm --user "$(id -u):$(id -g)" ${DOCKER_RUN_ARGS:-} \
    -v "$PWD":/app "$ML_IMAGE" python -m ml.run_all "$@" \
    || die "the data / training pipeline failed. Fix the step named above and run ./deploy.sh again; finished steps are skipped."

  say "Permissions"
  # The images are built from these files and the containers run as other users:
  # everything the application reads must be readable by everyone.
  chmod -R a+rX ml/models ml/out vigil/vdev/assets vigil/backend/seed docs/actions.yaml nginx 2>/dev/null || true
  chmod -R a+rX data 2>/dev/null || true
  info "prepared files are world-readable"
  for f in ml/models/pattern.json vigil/vdev/assets/co2_iss_rr12.csv vigil/backend/seed/radiation_daily.csv docs/actions.yaml; do
    [ -s "$f" ] || die "expected file is missing or empty: $f"
    info "ok  $f"
  done
}

# ---------------------------------------------------------------- stack

ensure_network() {
  if ! docker network inspect traefik >/dev/null 2>&1; then
    [ "$TRAEFIK_MODE" = external ] && die "TRAEFIK_MODE=external, but the Docker network 'traefik' does not exist. Start your Traefik first, or use TRAEFIK_MODE=own."
    docker network create traefik >/dev/null
    info "created the Docker network 'traefik'"
  fi
}

# api METHOD PATH [JSON]  -> prints "<status> <body>"; runs inside the backend container
api() {
  dc exec -T -e M="$1" -e P="$2" -e B="${3:-}" backend python -c '
import os, sys, urllib.request, urllib.error
body = os.environ["B"].encode() or None
if os.environ["M"] == "POST" and body is None:
    body = b"{}"
req = urllib.request.Request("http://localhost:8000/api/v1" + os.environ["P"], data=body,
                             method=os.environ["M"], headers={"content-type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
except Exception as e:
    print(0, e)
'
}

up() {
  say "Images"
  ensure_network
  retry 4 dc build || die "image build failed (network? see the messages above)"

  say "Start"
  retry 3 dc up -d --remove-orphans || die "docker compose up failed (see: ./deploy.sh logs)"

  say "Waiting for the stream"
  local i out
  for i in $(seq 1 60); do
    out=$(api GET /health 2>/dev/null || true)
    [[ "$out" == 200* ]] && break
    sleep 2
  done
  [[ "${out:-}" == 200* ]] || die "the backend did not become healthy. See: ./deploy.sh logs backend"
  info "backend is up (database schema created, crew seeded)"

  # History of 14 days is replayed first; then the stream turns live.
  for i in $(seq 1 90); do
    out=$(api GET /sim/state 2>/dev/null || true)
    [[ "$out" == *'"mode":"live"'* ]] && break
    sleep 2
  done
  [[ "$out" == *'"mode":"live"'* ]] || die "the virtual devices did not reach live mode. See: ./deploy.sh logs vdev"
  info "virtual devices are streaming live"

  say "Checks"
  # The backend may still be working through the replayed history when vdev
  # reports "live", so the checks are repeated for up to two minutes.
  dc exec -T backend python - <<'PY' || die "the stack is up but a check failed (see above)"
import json, sys, time, urllib.request
base = "http://localhost:8000/api/v1"
get = lambda p: json.load(urllib.request.urlopen(base + p, timeout=10))

def run():
    health, crew, radiation = get("/health"), get("/crew"), get("/radiation")
    learned = sum(c["baseline"]["state"] == "learned" for c in crew)
    incidents = sum(a["key"] == "incident" for c in crew for a in get(f"/crew/{c['id']}/alerts"))
    return [
        ("no rejected frames", health["bad_frames"] == health["unknown_frames"] == health["stale_frames"] == 0),
        ("history written to the database", health["write_queue"] == 0),
        ("7 crew members streaming", len(crew) == 7 and all(c["now_ts"] for c in crew)),
        ("6 baselines learned, 1 learning", learned == 6),
        ("every level is Usual", all(c["level"] == 0 for c in crew)),
        ("no incident on normal data", incidents == 0),
        ("NASA radiation series loaded", len(radiation["days"]) == 14),
    ]

deadline = time.monotonic() + 120
while True:
    try:
        checks = run()
    except Exception as exc:  # the backend is busy: try again
        checks = [(f"backend answers ({exc})", False)]
    if all(ok for _, ok in checks) or time.monotonic() > deadline:
        break
    time.sleep(3)
for name, ok in checks:
    print(f"   {'ok ' if ok else 'FAIL'} {name}")
sys.exit(0 if all(ok for _, ok in checks) else 1)
PY

  # The proxy chain, from inside: nginx -> backend and nginx -> client.
  dc exec -T nginx sh -c 'curl -fsS -o /dev/null http://localhost/api/v1/health && curl -fsS -o /dev/null http://localhost/' \
    && info "ok  nginx routes /api to the backend and / to the client" \
    || die "nginx does not reach the backend or the client. See: ./deploy.sh logs nginx"
  if [ "$TRAEFIK_MODE" = own ]; then
    local code
    code=$(curl -ksS -o /dev/null -m 10 -w '%{http_code}' --resolve "${DOMAIN_URL}:${HTTPS_PORT:-443}:127.0.0.1" \
      "https://${DOMAIN_URL}:${HTTPS_PORT:-443}/api/v1/health" 2>/dev/null || true)
    [ "$code" = 200 ] && info "ok  Traefik serves https://${DOMAIN_URL} (checked on this host)" \
      || info "!!  Traefik did not answer on port ${HTTPS_PORT:-443} of this host (code '${code}'). See: ./deploy.sh logs traefik"
  fi

  say "Ready"
  info "Open:      https://${DOMAIN_URL}"
  info "Incident:  ./deploy.sh incident hypoxia        (see ./deploy.sh incidents)"
  info "Status:    ./deploy.sh status"
  [ "$TRAEFIK_MODE" = own ] && info "The first certificate takes up to a minute; DOMAIN_URL must point to this server and ports 80/443 must be open."
  return 0
}

status() {
  dc ps --format 'table {{.Service}}\t{{.Status}}'
  echo
  dc exec -T backend python - <<'PY' || true
import json, urllib.request
base = "http://localhost:8000/api/v1"
get = lambda p: json.load(urllib.request.urlopen(base + p, timeout=10))
names = ["Usual", "Watch", "Alert", "Critical"]
try:
    sim = get("/sim/state")
    print(f"stream: {sim['mode']}, speed x{sim['speed']}, active incidents: "
          + (", ".join(f"{a['name']} (crew {a['crew'] or 'cabin'}, {a['elapsed_s'] // 60} min)" for a in sim["active"]) or "none"))
except Exception as exc:
    print("stream: virtual device not reachable:", exc)
for c in get("/crew"):
    level = "no data" if c["level"] is None else names[c["level"]]
    print(f"  crew {c['id']}  {c['name']:<14} {level:<9} baseline {c['baseline']['state']}"
          + (f"  [{c['topic']}]" if c.get("topic") else ""))
print("health:", get("/health"))
PY
}

incident() {
  local name="${1:-}" crew="${2:-1}" severity="${3:-}"
  [ -n "$name" ] || die "usage: ./deploy.sh incident NAME [CREW 1-7] [SEVERITY 1-3]   (names: ./deploy.sh incidents)"
  local body out
  body="{\"name\":\"$name\",\"crew\":$crew"
  [ -n "$severity" ] && body+=",\"severity\":$severity"
  body+="}"
  out=$(api POST /sim/scenario "$body")
  [[ "$out" == 200* ]] || die "incident not started: $out"
  echo "started '$name' for crew $crew${severity:+, severity $severity}. Watch: ./deploy.sh status   (faster: ./deploy.sh speed 60)"
}

incidents() {
  cat <<'TXT'
Demo incidents (./deploy.sh incident NAME [CREW] [SEVERITY]):
  hypoxia            blood oxygen falls in stages: Watch, then Alert, then Critical
  tachycardia_rest   fast heart rate at rest: Alert (severity 3: Critical)
  bradycardia        slow heart rate: Alert (severity 3: Critical)
  fever_like         skin temperature rises: Watch or Alert
  hypercapnia        cabin CO2 above the limit, whole crew (slow: use speed 60)
  depressurization   cabin pressure drops, whole crew
Not incidents, on purpose (no alert is the correct result):
  exercise           effort: heart rate 130+, no alert
  sensor_off         wristband taken off: "no data", no alert
  motion_artifact    noisy sensor: readings dropped, no alert
TXT
}

# ---------------------------------------------------------------- commands

cmd="${1:-all}"
[ $# -gt 0 ] && shift

case "$cmd" in
  incidents|help|-h|--help)
    [ "$cmd" = incidents ] && incidents || sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'
    exit 0 ;;
  install-docker)
    install_docker
    exit 0 ;;
esac

load_env
check_docker

case "$cmd" in
  all)       pipeline "$@"; up ;;
  train)     pipeline "$@" ;;
  up)        up ;;
  status)    status ;;
  incident)  incident "$@" ;;
  speed)     [[ "${1:-}" =~ ^(1|10|60)$ ]] || die "usage: ./deploy.sh speed 1|10|60"
             out=$(api POST /sim/speed "{\"speed\":$1}"); [[ "$out" == 200* ]] && echo "speed x$1" || die "$out" ;;
  reset)     out=$(api POST /sim/reset '{}'); [[ "$out" == 200* ]] && echo "reset: history is being replayed, ready in about 20 s" || die "$out" ;;
  logs)      dc logs -f --tail 100 "$@" ;;
  down)      dc down ;;
  destroy)   dc down -v ;;
  *)         die "unknown command '$cmd'. See: ./deploy.sh help" ;;
esac
