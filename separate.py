"""Stem separation via audio-separator (Roformer for vocals, Demucs 6-stem for instruments)."""
from __future__ import annotations

import gc
import re
import shutil
import subprocess
import types
from pathlib import Path

import numpy as np
import soundfile as sf

MODEL_DIR = Path(__file__).parent / "models"

# id -> (label, model filename or "preset:<name>")
VOCAL_MODELS = {
    "melband_ft2": ("MelBand Roformer FT2 Bleedless — cleanest vocals (recommended)",
                    "mel_band_roformer_kim_ft2_bleedless_unwa.ckpt"),
    "melband_kim": ("MelBand Roformer Kim — natural, full-bodied vocals",
                    "vocals_mel_band_roformer.ckpt"),
    "bs_1297": ("BS-Roformer Viperx 1297 — clean instrumental (≈2× slower)",
                "model_bs_roformer_ep_317_sdr_12.9755.ckpt"),
    "mdx23c": ("MDX23C — fastest, good quality", "MDX23C-8KFFT-InstVoc_HQ.ckpt"),
    "ensemble": ("Ensemble of 2 models — maximum cleanliness (very slow)", "preset:vocal_clean"),
}
DEFAULT_MODEL = "melband_ft2"
INSTRUMENT_MODEL = "htdemucs_6s.yaml"  # drums, bass, guitar, piano, other, vocals

MODES = {
    "vocal": {"label": "Vocal Remover", "tracks": ["Vocals", "Instrumental"], "extras": []},
    "stems": {"label": "Stem Splitter",
              "tracks": ["Vocals", "Drums", "Bass", "Guitar", "Piano", "Other"],
              "extras": ["Instrumental"]},
}


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- progress hook
# audio-separator reports progress through tqdm; we swap in a tiny stand-in that
# forwards (done, total) to the active job.
_reporter = None  # callable(done:int, total:int|None)


class _HookTqdm:
    def __init__(self, iterable=None, total=None, *args, **kwargs):
        self.iterable = iterable
        if total is None and iterable is not None and hasattr(iterable, "__len__"):
            total = len(iterable)
        self.total = total
        self.n = 0

    def _emit(self):
        if _reporter:
            _reporter(self.n, self.total)

    def __iter__(self):
        for item in self.iterable:
            yield item
            self.n += 1
            self._emit()

    def update(self, n=1):
        self.n += n
        self._emit()

    def close(self):
        pass

    def set_description(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_hooks_installed = False


def _install_hooks():
    global _hooks_installed
    if _hooks_installed:
        return
    import audio_separator.separator.separator as m_sep
    from audio_separator.separator.architectures import mdxc_separator, mdx_separator, vr_separator
    from audio_separator.separator.uvr_lib_v5.demucs import apply as d_apply, utils as d_utils
    for mod in (m_sep, mdxc_separator, mdx_separator, vr_separator):
        mod.tqdm = _HookTqdm
    ns = types.SimpleNamespace(tqdm=_HookTqdm)
    d_apply.tqdm = ns
    d_utils.tqdm = ns
    _hooks_installed = True


def _make_separator(out_dir: Path, preset: str | None, hq: bool):
    from audio_separator.separator import Separator
    _install_hooks()
    return Separator(
        output_dir=str(out_dir),
        output_format="WAV",
        model_file_dir=str(MODEL_DIR),
        log_level=30,
        ensemble_preset=preset,
        mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                     "batch_size": None, "overlap": 4 if hq else 2, "pitch_shift": 0},
        demucs_params={"segment_size": "Default", "shifts": 2 if hq else 1,
                       "overlap": 0.25, "segments_enabled": True},
    )


# ---------------------------------------------------------------- helpers
def safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "track"


def _resolve(out_dir: Path, files) -> list[Path]:
    return [Path(f) if Path(f).is_absolute() else out_dir / f for f in files]


def _stem_of(path: Path) -> str:
    m = re.search(r"\(([^()]+)\)[^()]*$", path.stem)
    return (m.group(1) if m else path.stem).strip().lower()


def to_mp3(src: Path, mp3: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-codec:a", "libmp3lame",
                    "-b:a", "320k", "-ar", "44100", str(mp3)], check=True)
    return mp3


def write_wav24(data: np.ndarray, sr: int, dst: Path) -> Path:
    peak = float(np.abs(data).max()) if data.size else 0.0
    if peak > 0.999:  # never clip
        data = data / peak * 0.999
    sf.write(str(dst), data, sr, subtype="PCM_24")
    return dst


# ---------------------------------------------------------------- main entry
def separate(input_path: str, out_dir: Path, song: str, mode: str, model_id: str, hq: bool,
             report=lambda frac, msg: None, is_cancelled=lambda: False) -> dict[str, dict[str, str]]:
    """Separate `input_path` into stems inside `out_dir`.

    Returns {stem: {"wav": path, "mp3": path}} for every track and extra.
    """
    global _reporter
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    split_instruments = mode == "stems"
    vocal_range = (0.06, 0.72 if split_instruments else 0.93)
    inst_range = (0.72, 0.93)

    def phase(lo, hi, label):
        def cb(done, total):
            if is_cancelled():
                raise Cancelled()
            if total:
                frac = min(1.0, done / total)
                if total > 100_000:  # model download (bytes)
                    report(lo, f"Downloading model (first time only)… {frac*100:.0f}%")
                else:
                    report(lo + (hi - lo) * frac, label)
        return cb

    try:
        report(0.01, "Decoding audio…")
        decoded = work / f"{song}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", input_path, "-vn", "-ar", "44100",
                        "-ac", "2", "-c:a", "pcm_f32le", str(decoded)], check=True)
        if is_cancelled():
            raise Cancelled()

        # ---- step 1: vocals / instrumental
        report(0.03, "Loading vocal model…")
        _reporter = phase(*vocal_range, "Separating vocals…")
        model = VOCAL_MODELS[model_id][1]
        if model.startswith("preset:"):
            sep = _make_separator(work, model.split(":", 1)[1], hq)
            sep.load_model()
        else:
            sep = _make_separator(work, None, hq)
            sep.load_model(model_filename=model)
        report(vocal_range[0], "Separating vocals…")
        files = _resolve(work, sep.separate(str(decoded)))
        raw: dict[str, Path] = {}
        for f in files:
            s = _stem_of(f)
            if "instrument" in s or s in ("other", "no_vocals", "no vocals"):
                raw["Instrumental"] = f
            elif "vocal" in s:
                raw["Vocals"] = f
        del sep
        gc.collect()

        # ---- step 2: instruments from the instrumental
        if split_instruments and "Instrumental" in raw:
            report(inst_range[0], "Loading instrument model…")
            inst_dir = work / "inst"
            inst_dir.mkdir()
            _reporter = phase(*inst_range, "Separating drums, bass, guitar, piano…")
            sep = _make_separator(inst_dir, None, hq)
            sep.load_model(model_filename=INSTRUMENT_MODEL)
            report(inst_range[0], "Separating drums, bass, guitar, piano…")
            files = _resolve(inst_dir, sep.separate(str(raw["Instrumental"])))
            by = {_stem_of(f): f for f in files}
            for key in ("drums", "bass", "guitar", "piano", "other"):
                if key in by:
                    raw[key.capitalize()] = by[key]
            # Demucs' leftover "vocals" in the beat is bleed: fold it into Other so nothing is lost
            if "vocals" in by and "Other" in raw:
                a, sr = sf.read(str(raw["Other"]), always_2d=True)
                b, _ = sf.read(str(by["vocals"]), always_2d=True)
                n = min(len(a), len(b))
                sf.write(str(raw["Other"]), a[:n] + b[:n], sr, subtype="FLOAT")
            del sep
            gc.collect()

        # ---- step 3: WAV 24-bit + MP3 320 for every stem
        report(0.94, "Encoding WAV + MP3 320 kbps…")
        names = MODES[mode]["tracks"] + MODES[mode]["extras"]
        result: dict[str, dict[str, str]] = {}
        for stem in names:
            if stem not in raw:
                continue
            data, sr = sf.read(str(raw[stem]), always_2d=True)
            base = out_dir / f"{song} ({stem})"
            wav = write_wav24(data, sr, base.with_suffix(".wav"))
            mp3 = to_mp3(wav, base.with_suffix(".mp3"))
            result[stem] = {"wav": str(wav), "mp3": str(mp3)}
    finally:
        _reporter = None
        shutil.rmtree(work, ignore_errors=True)
        gc.collect()
    report(1.0, "Done")
    return result


def render_mix(stems: dict[str, str], gains: dict[str, float], out_wav: Path) -> Path:
    """Sum WAV stems with linear gains into a 24-bit WAV (peak-safe)."""
    mix, sr = None, 44100
    for name, path in stems.items():
        g = float(gains.get(name, 0.0))
        if g <= 0:
            continue
        data, sr = sf.read(path, always_2d=True, dtype="float32")
        data *= g
        if mix is None:
            mix = data
        else:
            n = min(len(mix), len(data))
            mix = mix[:n] + data[:n]
    if mix is None:
        mix = np.zeros((sr, 2), dtype="float32")
    return write_wav24(mix, sr, out_wav)
