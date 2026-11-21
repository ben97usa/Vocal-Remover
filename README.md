# StemSplitter 🎛️

Local stem separation for Apple Silicon Macs. Nothing is uploaded to the internet.

## Open / close
- **Open:** double-click `StemSplitter` on the Desktop (or in `~/Applications`). The app opens at `http://127.0.0.1:7861`.
- **Quit (free RAM):** run `~/Projects/StemSplitter/stop.sh`.

## Workflow
1. Pick a mode in the sidebar:
   - **Vocal Remover**: Vocals + Instrumental
   - **Stem Splitter**: Vocals, Drums, Bass, Guitar, Piano, Other (+ full Instrumental for download)
2. Drop a song. Separation starts immediately; quality (real bitrate / fake 320), BPM and key appear while it runs.
3. When done, the **mixer** opens: synced playback, waveform per track, volume (0–150%), mute / solo,
   presets (All tracks / Vocals only / No vocals). Space = play/pause, click a waveform to seek.
4. Download: **mix** with your current settings, each **stem**, or **all stems (ZIP)**, in MP3 320 kbps or WAV 24-bit.

Results are cached in `~/Music/StemSplitter/<song>/` (see **Library**). Dropping the same song again with the same settings opens it instantly.

## Quality Scan
Scans a whole folder and flags genuine 320 / fake 320 / low quality, with optional BPM & key. Exports a CSV.
Fake-320 detection: MP3 encoders cut high frequencies by bitrate (128 kbps ≈ 16–17 kHz, 320 kbps ≈ 20–20.5 kHz);
a 128 kbps file re-encoded as 320 keeps its 16 kHz cliff.

## Files
- `server.py`: FastAPI backend (jobs, cache, mix rendering, folder scan)
- `static/`: mixer UI (HTML/CSS/JS, Web Audio)
- `separate.py`: audio-separator (Roformer vocals, Demucs 6-stem) with live progress
- `analyze.py`: real bitrate, BPM, key (Essentia), spectrogram

## Speed / other Macs
- `tools/benchmark.py` measures separation speed (results in `benchmarks/`).
- `docs/HANDOFF_M4.md`: setup on another Mac (e.g. M4) + a ready-to-paste Claude Code prompt for speed work.
