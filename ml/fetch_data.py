"""Step 1 of the pipeline: get the raw datasets into data/ in the layout of ml/paths.py.

    python -m ml.fetch_data

For each dataset: use the archive in data_archives/ if it is there, download it
otherwise, then extract it. Everything is skipped when already done, so the
command is safe to run again. NASA files come from ml.fetch_eda.

From PPG-DaLiA only S#.pkl, the csv files and the readme are extracted: the raw
RespiBAN and Empatica files are not used and take 4 GB.
"""

import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from ml import fetch_eda
from ml.paths import BIDMC, DALIA, DATA, ROOT, SLEEP

ARCHIVES = ROOT / "data_archives"
SOURCES = {
    "ppg+dalia.zip": "https://archive.ics.uci.edu/static/public/495/ppg+dalia.zip",
    "bidmc-ppg-and-respiration-dataset-1.0.0.zip": (
        "https://physionet.org/static/published-projects/bidmc/"
        "bidmc-ppg-and-respiration-dataset-1.0.0.zip"
    ),
    "sleep-accel-1.0.0.zip": (
        "https://physionet.org/static/published-projects/sleep-accel/"
        "motion-and-heart-rate-from-a-wrist-worn-wearable-and-labeled-sleep-"
        "from-polysomnography-1.0.0.zip"
    ),
}
DALIA_SKIP = ("_RespiBAN.h5", "_E4.zip")
CHUNK = 1 << 20


def download(name: str, tries: int = 5) -> Path:
    """Download with resume: a broken connection continues where it stopped."""
    target = ARCHIVES / name
    part = target.with_suffix(target.suffix + ".part")
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, tries + 1):
        have = part.stat().st_size if part.exists() else 0
        req = urllib.request.Request(
            SOURCES[name],
            headers={"User-Agent": "dataset-fetch/1.0", "Range": f"bytes={have}-"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resumed = resp.status == 206
                total = int(resp.headers.get("Content-Length") or 0) + (
                    have if resumed else 0
                )
                with open(part, "ab" if resumed else "wb") as f:
                    done, shown = (have if resumed else 0), time.monotonic()
                    while chunk := resp.read(CHUNK):
                        f.write(chunk)
                        done += len(chunk)
                        if time.monotonic() - shown > 10:
                            shown = time.monotonic()
                            pct = f" ({done / total:.0%})" if total else ""
                            print(f"  {name}: {done / 1e6:.0f} MB{pct}", flush=True)
            part.rename(target)
            return target
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and have:  # the .part file is already complete
                part.rename(target)
                return target
            print(f"  {name}: HTTP {exc.code} (attempt {attempt}/{tries})", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            print(f"  {name}: {exc} (attempt {attempt}/{tries})", flush=True)
        time.sleep(5 * attempt)
    raise SystemExit(
        f"could not download {name}. Put the file into {ARCHIVES}/ by hand "
        f"(source: {SOURCES[name]}) and run again."
    )


def archive(name: str) -> Path:
    path = ARCHIVES / name
    if path.exists():
        if not zipfile.is_zipfile(path):
            raise SystemExit(
                f"{path} is not a valid zip file; delete it and run again."
            )
        return path
    print(f"{name}: not in {ARCHIVES.name}/, downloading", flush=True)
    return download(name)


def extract(zf: zipfile.ZipFile, dest: Path, skip: tuple[str, ...] = ()) -> int:
    n = 0
    for info in zf.infolist():
        if info.is_dir() or info.filename.endswith(skip):
            continue
        out = dest / info.filename
        if out.exists() and out.stat().st_size == info.file_size:
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst, CHUNK)
        n += 1
    return n


def have_dalia() -> bool:
    return all((DALIA / f"S{i}" / f"S{i}.pkl").exists() for i in range(1, 16))


def have_bidmc() -> bool:
    return len(list(BIDMC.glob("bidmc_*_Numerics.csv"))) == 53


def have_sleep() -> bool:
    return len(list((SLEEP / "labels").glob("*_labeled_sleep.txt"))) == 31


def main() -> int:
    DATA.mkdir(exist_ok=True)

    if have_dalia():
        print("PPG-DaLiA: already extracted")
    else:
        with zipfile.ZipFile(archive("ppg+dalia.zip")) as outer:
            # The archive holds one inner archive, data.zip, stored without compression.
            with outer.open("data.zip") as inner, zipfile.ZipFile(inner) as zf:
                n = extract(zf, DALIA.parent, DALIA_SKIP)
        print(f"PPG-DaLiA: extracted {n} files")
        if not have_dalia():
            raise SystemExit("PPG-DaLiA: the archive does not contain S1..S15")

    if have_bidmc():
        print("BIDMC: already extracted")
    else:
        with zipfile.ZipFile(
            archive("bidmc-ppg-and-respiration-dataset-1.0.0.zip")
        ) as zf:
            n = extract(zf, BIDMC.parents[1])
        print(f"BIDMC: extracted {n} files")
        if not have_bidmc():
            raise SystemExit(
                "BIDMC: the archive does not contain the 53 numerics files"
            )

    if have_sleep():
        print("sleep-accel: already extracted")
    else:
        with zipfile.ZipFile(archive("sleep-accel-1.0.0.zip")) as zf:
            n = extract(zf, SLEEP.parent)
        print(f"sleep-accel: extracted {n} files")
        if not have_sleep():
            raise SystemExit(
                "sleep-accel: the archive does not contain the 31 label files"
            )

    return fetch_eda.main([])  # NASA OSDR EDA: CO2 and radiation, skips existing files


if __name__ == "__main__":
    sys.exit(main())
