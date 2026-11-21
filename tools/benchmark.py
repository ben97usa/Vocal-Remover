"""Measure separation speed on this Mac.

Usage:
  .venv/bin/python tools/benchmark.py SONG.mp3 [--seconds 30] [--models melband_ft2,mdx23c] [--stems]

Cuts a clip from the middle of SONG, separates it with each model and prints the
realtime factor plus the estimated time for a 3.5-minute song. Results are appended
to benchmarks/<chip>.md so they can be compared across machines (M2 vs M4…).
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import separate  # noqa: E402


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def machine() -> str:
    chip = sh(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor()
    ram = int(sh(["sysctl", "-n", "hw.memsize"]) or 0) // 2**30
    gpu = ""
    for line in sh(["system_profiler", "SPDisplaysDataType"]).splitlines():
        if "Total Number of Cores" in line:
            gpu = line.split(":")[-1].strip()
            break
    return f"{chip}, {gpu or '?'} GPU cores, {ram} GB RAM, macOS {platform.mac_ver()[0]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--models", default="melband_ft2,mdx23c")
    ap.add_argument("--stems", action="store_true", help="also run the 6-stem mode")
    ap.add_argument("--hq", action="store_true")
    ap.add_argument("--force", action="store_true", help="run even if the app is separating a song")
    a = ap.parse_args()

    busy = list((Path.home() / "Music" / "StemSplitter").glob("*/_work"))
    if busy and not a.force:
        sys.exit(f"The app is separating '{busy[0].parent.name}' right now; results would be wrong "
                 "(GPU/RAM shared). Wait for it to finish, or pass --force.")

    info = machine()
    print(info)
    tmp = Path(tempfile.mkdtemp(prefix="stembench-"))
    try:
        dur = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", a.song]) or 0)
        start = max(0.0, dur / 2 - a.seconds / 2)
        clip = tmp / "clip.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start}", "-t", f"{a.seconds}",
                        "-i", a.song, "-ar", "44100", "-ac", "2", str(clip)], check=True)

        runs = [(m, "vocal") for m in a.models.split(",")]
        if a.stems:
            runs.append((a.models.split(",")[0], "stems"))
        rows = []
        for model, mode in runs:
            out = tmp / f"{model}-{mode}"
            t0 = time.time()
            separate.separate(str(clip), out, "clip", mode, model, a.hq)
            el = time.time() - t0
            rtf = el / a.seconds
            rows.append((model, mode, el, rtf, rtf * 210))
            print(f"{model:12s} {mode:6s} {el:6.1f}s  {rtf:4.2f}× realtime  ≈{rtf*210/60:4.1f} min per 3:30 song")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bench = ROOT / "benchmarks"
    bench.mkdir(exist_ok=True)
    name = "".join(c if c.isalnum() else "_" for c in info.split(",")[0]).strip("_")
    f = bench / f"{name}.md"
    with f.open("a") as fh:
        fh.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')}: {info}\n"
                 f"clip {a.seconds:.0f}s, hq={a.hq}\n\n| model | mode | time | ×realtime | 3:30 song |\n|---|---|---|---|---|\n")
        for model, mode, el, rtf, full in rows:
            fh.write(f"| {model} | {mode} | {el:.1f}s | {rtf:.2f} | {full/60:.1f} min |\n")
    print(f"Saved → {f}")


if __name__ == "__main__":
    main()
