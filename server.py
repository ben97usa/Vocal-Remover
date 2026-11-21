"""StemSplitter local server: FastAPI backend + static mixer UI on http://127.0.0.1:7861."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import analyze
import separate

ROOT = Path(__file__).parent
OUT_ROOT = Path.home() / "Music" / "StemSplitter"
OUT_ROOT.mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.gettempdir()) / "stemsplitter"
(TMP / "uploads").mkdir(parents=True, exist_ok=True)
(TMP / "exports").mkdir(parents=True, exist_ok=True)
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".aiff", ".aif", ".ogg", ".opus", ".wma"}

app = FastAPI(title="StemSplitter")
GPU_LOCK = threading.Lock()  # one separation at a time (RAM / GPU)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


# ---------------------------------------------------------------- job storage
def _public(job: dict) -> dict:
    keys = ("id", "song", "mode", "model", "hq", "status", "progress", "message", "error",
            "analysis", "tracks", "extras", "created", "started", "finished", "dir")
    return {k: job.get(k) for k in keys}


def _save(job: dict) -> None:
    d = Path(job["dir"])
    if d.exists():
        data = {k: v for k, v in job.items() if not k.startswith("_")}
        (d / "job.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))


def _load_library() -> None:
    for jf in OUT_ROOT.glob("*/job.json"):
        try:
            job = json.loads(jf.read_text())
        except Exception:
            continue
        if job.get("status") != "done":
            continue
        job["dir"] = str(jf.parent)
        JOBS[job["id"]] = job


def _new_dir(song: str) -> Path:
    d = OUT_ROOT / song
    i = 2
    while d.exists():
        d = OUT_ROOT / f"{song} ({i})"
        i += 1
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------- workers
def _run_analysis(job: dict, src: str) -> None:
    try:
        rep, _, _ = analyze.analyze_quality(src)
        info = {
            "codec": rep.codec.upper(), "sample_rate": rep.sample_rate, "channels": rep.channels,
            "duration": rep.duration, "bitrate": rep.container_bitrate_kbps,
            "cutoff_khz": None if rep.full_band else round(rep.cutoff_hz / 1000, 1),
            "full_band": rep.full_band, "quality": rep.estimated_label,
            "status": rep.status, "verdict": rep.verdict, "notes": rep.notes,
        }
        job["analysis"] = dict(info)
        m = analyze.analyze_music(src)
        info.update(bpm=m["tempo"]["bpm"], bpm_exact=m["tempo"]["exact"],
                    key=m["key"]["key"], key_short=m["key"]["short"],
                    camelot=m["key"]["camelot"], key_alt=m["key"]["runner_up"])
        job["analysis"] = dict(info)
        try:
            analyze.spectrogram_png(src, str(Path(job["dir"]) / "spectrogram.png"),
                                    None if rep.full_band else rep.cutoff_hz)
            job["analysis"]["spectrogram"] = True
        except Exception:
            pass
    except Exception as e:
        job["analysis"] = {"error": str(e)}
    _save(job)


def _run_separation(job: dict, src: str) -> None:
    def report(frac, msg):
        job["progress"] = round(frac, 4)
        job["message"] = msg

    job["status"], job["message"] = "queued", "Waiting for the previous song to finish…"
    with GPU_LOCK:
        if job.get("_cancel"):
            job["status"], job["message"] = "cancelled", "Cancelled"
            return
        job["status"], job["started"] = "running", time.time()
        try:
            result = separate.separate(
                src, Path(job["dir"]), job["song"], job["mode"], job["model"], job["hq"],
                report=report, is_cancelled=lambda: job.get("_cancel", False))
            job["files"] = result
            job["status"], job["progress"], job["message"] = "done", 1.0, "Done"
            job["finished"] = time.time()
            _save(job)
        except separate.Cancelled:
            job["status"], job["message"] = "cancelled", "Cancelled"
            shutil.rmtree(job["dir"], ignore_errors=True)
        except Exception as e:
            traceback.print_exc()
            job["status"], job["error"], job["message"] = "error", str(e), "Failed"
    try:
        os.remove(src)
    except OSError:
        pass


# ---------------------------------------------------------------- API
@app.get("/api/config")
def config():
    return {"models": [{"id": k, "label": v[0]} for k, v in separate.VOCAL_MODELS.items()],
            "default_model": separate.DEFAULT_MODEL,
            "modes": {k: v for k, v in separate.MODES.items()},
            "output_dir": str(OUT_ROOT)}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), mode: str = Form("vocal"),
                 model: str = Form(separate.DEFAULT_MODEL), hq: bool = Form(False)):
    if mode not in separate.MODES or model not in separate.VOCAL_MODELS:
        raise HTTPException(400, "Unknown mode or model")
    ext = Path(file.filename or "song.mp3").suffix.lower() or ".mp3"
    song = separate.safe_name(Path(file.filename or "song").stem)
    tmp = TMP / "uploads" / f"{uuid.uuid4().hex}{ext}"
    h = hashlib.sha1()
    with open(tmp, "wb") as fh:
        while chunk := await file.read(1 << 20):
            h.update(chunk)
            fh.write(chunk)
    key = f"{h.hexdigest()[:16]}-{mode}-{model}-{'hq' if hq else 'std'}"

    with JOBS_LOCK:
        existing = JOBS.get(key)
        if existing and existing["status"] in ("done", "running", "queued"):
            if existing["status"] != "done" or all(
                    Path(f["mp3"]).exists() for f in existing.get("files", {}).values()):
                tmp.unlink(missing_ok=True)
                return {"id": key, "cached": existing["status"] == "done"}
        job = {
            "id": key, "song": song, "mode": mode, "model": model, "hq": hq,
            "status": "queued", "progress": 0.0, "message": "Starting…", "error": None,
            "analysis": None, "tracks": separate.MODES[mode]["tracks"],
            "extras": separate.MODES[mode]["extras"], "created": time.time(),
            "dir": str(_new_dir(song)), "files": {},
        }
        JOBS[key] = job
    # analysis needs its own copy because the separation worker deletes the upload when done
    ana_src = TMP / "uploads" / f"{uuid.uuid4().hex}{ext}"
    shutil.copyfile(tmp, ana_src)

    def ana():
        _run_analysis(job, str(ana_src))
        ana_src.unlink(missing_ok=True)

    threading.Thread(target=ana, daemon=True).start()
    threading.Thread(target=_run_separation, args=(job, str(tmp)), daemon=True).start()
    return {"id": key, "cached": False}


def _job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = _job(job_id)
    data = _public(job)
    if job["status"] in ("running",) and job.get("started") and job["progress"] > 0.08:
        elapsed = time.time() - job["started"]
        data["eta"] = max(0, elapsed * (1 - job["progress"]) / job["progress"])
    data["stems"] = [s for s in job["tracks"] if s in job.get("files", {})]
    data["extra_stems"] = [s for s in job["extras"] if s in job.get("files", {})]
    return data


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    job = _job(job_id)
    job["_cancel"] = True
    return {"ok": True}


@app.get("/api/jobs/{job_id}/audio/{stem}")
def stem_audio(job_id: str, stem: str):
    f = _job(job_id).get("files", {}).get(stem)
    if not f:
        raise HTTPException(404)
    return FileResponse(f["mp3"], media_type="audio/mpeg")


@app.get("/api/jobs/{job_id}/spectrogram")
def spectrogram(job_id: str):
    p = Path(_job(job_id)["dir"]) / "spectrogram.png"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png")


@app.get("/api/jobs/{job_id}/download/{stem}")
def download_stem(job_id: str, stem: str, fmt: str = "wav"):
    f = _job(job_id).get("files", {}).get(stem)
    if not f or fmt not in ("wav", "mp3"):
        raise HTTPException(404)
    return FileResponse(f[fmt], filename=Path(f[fmt]).name)


@app.get("/api/jobs/{job_id}/mix")
def download_mix(job_id: str, fmt: str = "mp3", gains: str = "{}", name: str = "Custom Mix"):
    job = _job(job_id)
    g = json.loads(gains)
    stems = {s: job["files"][s]["wav"] for s in job["tracks"] if s in job.get("files", {})}
    label = separate.safe_name(name)[:60] or "Custom Mix"
    out = TMP / "exports" / uuid.uuid4().hex
    out.mkdir()
    wav = separate.render_mix(stems, g, out / f"{job['song']} ({label}).wav")
    if fmt == "mp3":
        target = separate.to_mp3(wav, wav.with_suffix(".mp3"))
    else:
        target = wav
    return FileResponse(target, filename=target.name)


@app.get("/api/jobs/{job_id}/zip")
def download_zip(job_id: str, fmt: str = "wav"):
    job = _job(job_id)
    out = TMP / "exports" / f"{uuid.uuid4().hex}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for stem, f in job.get("files", {}).items():
            z.write(f[fmt], Path(f[fmt]).name)
    return FileResponse(out, filename=f"{job['song']} (stems {fmt.upper()}).zip")


@app.post("/api/jobs/{job_id}/reveal")
def reveal(job_id: str):
    subprocess.run(["open", _job(job_id)["dir"]])
    return {"ok": True}


@app.get("/api/library")
def library():
    items = [_public(j) for j in JOBS.values() if j["status"] == "done"]
    items.sort(key=lambda j: j.get("finished") or 0, reverse=True)
    return items


# ---------------------------------------------------------------- folder scan
SCANS: dict[str, dict] = {}


@app.post("/api/choose-folder")
def choose_folder():
    r = subprocess.run(["osascript", "-e",
                        'POSIX path of (choose folder with prompt "Choose a music folder to scan")'],
                       capture_output=True, text=True)
    return {"path": r.stdout.strip()}


@app.post("/api/scan")
def start_scan(payload: dict):
    folder = Path(str(payload.get("folder", "")).strip().strip("'\""))
    if not folder.is_dir():
        raise HTTPException(400, "Folder not found")
    files = sorted(p for p in folder.rglob("*")
                   if p.suffix.lower() in AUDIO_EXT and not p.name.startswith("._"))
    sid = uuid.uuid4().hex[:12]
    scan = {"id": sid, "folder": str(folder), "total": len(files), "rows": [], "done": False,
            "csv": None, "music": bool(payload.get("music"))}
    SCANS[sid] = scan

    def work():
        for f in files:
            if scan.get("_cancel"):
                break
            row = {"file": str(f.relative_to(folder)), "path": str(f)}
            try:
                rep, _, _ = analyze.analyze_quality(str(f))
                row.update(status=rep.status, bitrate=rep.container_bitrate_kbps,
                           cutoff_khz=None if rep.full_band else round(rep.cutoff_hz / 1000, 1),
                           quality=rep.estimated_label, verdict=rep.verdict)
                if scan["music"]:
                    m = analyze.analyze_music(str(f))
                    row.update(bpm=m["tempo"]["bpm"], key=m["key"]["key"],
                               camelot=m["key"]["camelot"])
            except Exception as e:
                row.update(status="error", verdict=str(e)[:120])
            scan["rows"].append(row)
        csv_path = OUT_ROOT / f"Quality scan - {folder.name}.csv"
        cols = ["status", "file", "bitrate", "cutoff_khz", "quality", "verdict", "bpm", "key", "camelot"]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(scan["rows"])
        scan["csv"] = str(csv_path)
        scan["done"] = True

    threading.Thread(target=work, daemon=True).start()
    return {"id": sid, "total": len(files)}


@app.get("/api/scan/{sid}")
def scan_status(sid: str, since: int = 0):
    scan = SCANS.get(sid)
    if not scan:
        raise HTTPException(404)
    return {"total": scan["total"], "count": len(scan["rows"]), "rows": scan["rows"][since:],
            "done": scan["done"], "csv": scan["csv"]}


@app.post("/api/scan/{sid}/cancel")
def scan_cancel(sid: str):
    if sid in SCANS:
        SCANS[sid]["_cancel"] = True
    return {"ok": True}


@app.get("/api/scan/{sid}/csv")
def scan_csv(sid: str):
    scan = SCANS.get(sid)
    if not scan or not scan["csv"]:
        raise HTTPException(404)
    return FileResponse(scan["csv"], filename=Path(scan["csv"]).name)


@app.post("/api/reveal-path")
def reveal_path(payload: dict):
    p = Path(str(payload.get("path", "")))
    if p.exists():
        subprocess.run(["open", "-R", str(p)])
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
_load_library()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 7861)), log_level="warning")
