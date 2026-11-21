# StemSplitter: notes for future work

Local vocalremover.org-style app for Apple Silicon (built on MacBook Air M2 8GB).
The owner is a DJ. **Talk to them in Vietnamese with diacritics. The app UI stays English.**

## Run
- `./start.sh` starts the server (http://127.0.0.1:7861) and opens the browser. `./stop.sh` kills it by port.
- Logs go to `app.log`. After editing Python, restart with `./stop.sh && ./start.sh`. After editing `static/`, reloading the page is enough (index.html is served no-store; bump `?v=` on css/js if the browser caches).
- New Mac: `./setup.sh` (needs Python 3.12 + `brew install ffmpeg`). It builds `.venv`, installs requirements and creates the launcher via `tools/make_app.sh`.
- Not in git: `.venv/` and `models/` (~2–3 GB). audio-separator re-downloads models on first use.

## Layout
- `server.py`: FastAPI. Jobs are in the `JOBS` dict. Separation runs one at a time under `GPU_LOCK`; analysis runs in a parallel thread.
  - Cache key: `sha1[:16]-mode-model-hq`, stored in `~/Music/StemSplitter/<song>/job.json`. The Library reads `*/job.json`.
  - Endpoints: `/api/upload`, `/api/jobs/{id}` (+ `/cancel`, `/audio/{stem}`, `/download/{stem}?fmt`, `/mix?fmt&gains&name`, `/zip`, `/spectrogram`, `/reveal`), `/api/library`, `/api/scan*`, `/api/choose-folder`.
- `separate.py`:
  - `VOCAL_MODELS` (id → label, checkpoint) and `MODES` (`vocal`: Vocals+Instrumental; `stems`: Vocals/Drums/Bass/Guitar/Piano/Other + Instrumental extra).
  - Stems mode runs the vocal model first, then `htdemucs_6s` on the instrumental. Demucs' leftover "vocals" gets added to Other.
  - Progress: audio-separator's `tqdm` is monkeypatched with `_HookTqdm`. Raising `Cancelled` inside the hook cancels the job.
  - Output: WAV 24-bit + MP3 320 CBR (ffmpeg libmp3lame). `render_mix` sums stems × gains with a peak limit.
- `analyze.py`:
  - Fake-320 detection uses the spectral-cutoff "cliff" (128k ≈ 16–17 kHz, 320 ≥ 19.9 kHz, lossless ≥ 20.8 kHz). Status is ok/fake/low.
  - BPM/key: Essentia `RhythmExtractor2013(multifeature)` + `KeyExtractor(bgate)`, Camelot output. librosa is the fallback.
- `static/`: vanilla JS, no build step.
  - `app.js` uses hash routing (#/vocal #/stems #/scan #/library).
  - The `mixer` object decodes every stem into an AudioBuffer and starts all sources together so playback stays in sync. Each track has its own GainNode, then a master gain. Waveforms are drawn on canvas.
  - Track colors live in `COLORS`.

## Performance facts (M2 8GB, MPS)
- 20 s clip: FT2 48 s, MDX23C 34 s, BS-Roformer 90 s, CPU ~2× slower than MPS. A full 2:49 song with the Kim model takes about 10 min.
- overlap 2 is the default; the "High quality" option uses 4 (2× slower). fp16/autocast did not help.
- 8 GB RAM is tight, so only one separation runs at a time.

## Gotchas
- The `.venv` is not relocatable (it points at /opt/anaconda3 python). Rebuild it with `setup.sh` instead of copying it.
- zsh does not word-split `$var`. Use arrays or loops.
- `curl -OJ` ignores `filename*=`. Browsers handle it fine.

## Ideas / roadmap (not done)
- Batch separation (a queue of many songs).
- Key/BPM-based tools for DJs: pitch/tempo shift of stems, Camelot-compatible suggestions.
- Export stems trimmed or looped to a selected region; fade in/out.
- Better models as they appear (e.g. newer Roformer checkpoints); per-model quality comparison.
- Optional native wrapper (pywebview) instead of the browser tab.
