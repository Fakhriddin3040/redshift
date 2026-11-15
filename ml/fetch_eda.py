"""DS-4: reproducible download of ISS cabin CO2 and daily radiation dose from the
NASA OSDR Environmental Data App (docs/DATA_PLAN.md §3.1). Public API, no key.

    python -m ml.fetch_eda                     # RR-1 RR-3 RR-9 RR-12 RR-19, skip existing
    python -m ml.fetch_eda --force RR-12       # re-download
    python -m ml.fetch_eda --out /tmp/x RR-6   # other folder

Writes <out>/<mission>_co2_iss.json, <out>/<mission>_radiation.json, <out>/SOURCE.txt.
Some missions (RR-6, RR-23) come back truncated in one request; those are fetched
in one-week chunks with ?start=&end=.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ml.paths import EDA

BASE = "https://visualization.osdr.nasa.gov/eda/api/missions"
MISSIONS = ["RR-1", "RR-3", "RR-9", "RR-12", "RR-19"]
CHUNK = timedelta(days=7)
MAX_EMPTY_CHUNKS = 4  # stop after this many empty weeks in a row
PAUSE_S = 1.0
FMT = "%Y-%m-%dT%H:%M:%SZ"


def get_text(url: str, tries: int = 4) -> str:
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "eda-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == tries - 1:
                raise
            print(f"  retry after error: {exc}")
            time.sleep(5 * (attempt + 1))
    raise AssertionError


def fetch_chunked(url: str, first: datetime) -> list[dict]:
    rows: list[dict] = []
    start, empty = first, 0
    while empty < MAX_EMPTY_CHUNKS:
        query = urllib.parse.urlencode(
            {"start": start.strftime(FMT), "end": (start + CHUNK).strftime(FMT)}
        )
        part = json.loads(get_text(f"{url}?{query}"))
        empty = 0 if part else empty + 1
        rows += part
        start += CHUNK
        time.sleep(PAUSE_S)
    return rows


def fetch_series(mission: str, endpoint: str) -> tuple[list[dict], str]:
    url = f"{BASE}/{mission}/{endpoint}/"
    text = get_text(url)
    try:
        rows, how = json.loads(text), "one request"
    except json.JSONDecodeError:
        first = re.search(r'"time"\s*:\s*"([^"]+)"', text)
        if first is None:
            raise RuntimeError(
                f"{url}: invalid JSON and no timestamp to start from"
            ) from None
        t0 = datetime.strptime(first.group(1), FMT).replace(tzinfo=UTC)
        t0 = t0.replace(hour=0, minute=0, second=0)
        rows, how = (
            fetch_chunked(url, t0),
            "one-week chunks (full response was truncated)",
        )
    # Merge: sort by time, drop duplicate timestamps (chunk borders).
    unique = {r["time"]: r for r in rows}
    return [unique[t] for t in sorted(unique)], how


def main(argv: list[str]) -> int:
    force = "--force" in argv
    out = EDA
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
        argv = [
            a
            for i, a in enumerate(argv)
            if i not in (argv.index("--out"), argv.index("--out") + 1)
        ]
    missions = [a for a in argv if not a.startswith("--")] or MISSIONS
    out.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for m in missions:
        for endpoint, suffix in (
            ("co2/iss", "co2_iss"),
            ("radiation_data", "radiation"),
        ):
            path = out / f"{m}_{suffix}.json"
            if path.exists() and not force:
                print(f"{path.name}: exists, skipped (use --force)")
                continue
            rows, how = fetch_series(m, endpoint)
            if not rows:
                print(f"{path.name}: no data returned, not written")
                continue
            path.write_text(json.dumps(rows, separators=(",", ":")))
            downloaded.append(path.name)
            print(
                f"{path.name}: {len(rows)} rows, {rows[0]['time']} .. {rows[-1]['time']}, {how}"
            )
            time.sleep(PAUSE_S)

    if downloaded:
        with open(out / "SOURCE.txt", "a") as f:
            f.write(
                f"\n[{date.today().isoformat()}] ml/fetch_eda.py downloaded: {', '.join(downloaded)}\n"
                f"  CO2: {BASE}/{{mission}}/co2/iss/ -> [{{time, co2_iss}}], ppm, UTC, ~5 min step\n"
                f"  Radiation: {BASE}/{{mission}}/radiation_data/ -> [{{time, gcr, saa, total, milestones}}], mGy/day, one row per day\n"
                "  API reference: https://visualization.osdr.nasa.gov/eda/api_reference\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
