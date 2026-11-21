"""Audio analysis: real bitrate (fake-320 detection), BPM, musical key."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

import numpy as np
import librosa

# Typical encoder lowpass per bitrate. True 320 kbps reaches ~20–20.5 kHz; 128 kbps stops at ~16–17 kHz.
QUALITY_TABLE = [
    # (min cutoff Hz, label, estimated kbps)
    (20_800, "Lossless / 320 kbps (full band)", 320),
    (19_900, "320 kbps", 320),
    (19_000, "~256 kbps (or VBR V0)", 256),
    (18_200, "~192–224 kbps", 192),
    (17_200, "~160 kbps", 160),
    (15_000, "~128 kbps", 128),
    (12_500, "~96 kbps", 96),
    (0, "≤ 64 kbps (very low)", 64),
]

LOSSLESS_CODECS = {"flac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le",
                   "pcm_s16be", "pcm_s24be", "pcm_f64le", "wavpack", "ape", "tta"}


@dataclass
class QualityReport:
    codec: str = "?"
    container_bitrate_kbps: int | None = None
    sample_rate: int = 0
    channels: int = 0
    duration: float = 0.0
    cutoff_hz: float = 0.0
    full_band: bool = False
    estimated_label: str = ""
    estimated_kbps: int = 0
    verdict: str = ""
    status: str = ""  # ok | fake | low
    is_standard_320: bool = False
    notes: list[str] = field(default_factory=list)


def probe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", path],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    return {"stream": stream, "format": fmt}


def _load_for_spectrum(path: str, max_seconds: float = 90.0) -> tuple[np.ndarray, int]:
    """Load mono audio at native sample rate (middle ~90s for speed)."""
    dur = librosa.get_duration(path=path)
    offset = max(0.0, (dur - max_seconds) / 2) if dur > max_seconds else 0.0
    y, sr = librosa.load(path, sr=None, mono=True, offset=offset,
                         duration=min(dur, max_seconds))
    return y, sr


def spectral_cutoff(y: np.ndarray, sr: int) -> tuple[float, bool, np.ndarray, np.ndarray]:
    """Find the high-frequency "cliff" left by lossy encoders.

    Returns (cutoff_hz, full_band, freqs, spectrum_db).
    """
    n_fft = 8192
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=n_fft // 2)) ** 2
    # ignore quiet frames
    frame_energy = S.sum(axis=0)
    if frame_energy.max() <= 0:
        return 0.0, False, np.array([]), np.array([])
    loud = frame_energy > np.percentile(frame_energy, 30)
    spec = S[:, loud].mean(axis=1) if loud.any() else S.mean(axis=1)
    spec_db = 10 * np.log10(spec + 1e-20)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    # smooth over ~150 Hz
    bin_hz = freqs[1] - freqs[0]
    k = max(3, int(150 / bin_hz))
    smooth = np.convolve(spec_db, np.ones(k) / k, mode="same")

    nyq = sr / 2
    ref_mask = (freqs >= 2000) & (freqs <= 8000)
    ref = np.median(smooth[ref_mask])

    # strongest drop between 11 kHz and Nyquist
    lo = np.searchsorted(freqs, 11_000)
    hi = np.searchsorted(freqs, nyq - 300)
    w_below = max(2, int(400 / bin_hz))
    w_above = max(2, int(400 / bin_hz))
    gap = max(1, int(80 / bin_hz))
    best_drop, best_i = 0.0, None
    for i in range(lo, hi - w_above - gap):
        below = smooth[i - w_below:i].mean()
        above = smooth[i + gap:i + gap + w_above].mean()
        drop = below - above
        if drop > best_drop:
            best_drop, best_i = drop, i

    # above the cliff must be near-silent compared to the reference band
    if best_i is not None and best_drop >= 18:
        above_level = smooth[best_i + gap:hi].mean() if best_i + gap < hi else smooth[-1]
        if ref - above_level > 45:
            return float(freqs[best_i]), False, freqs, smooth

    # no clear cliff: highest frequency that still carries energy
    thresh = ref - 70
    above_idx = np.where(smooth[:hi] > thresh)[0]
    top = float(freqs[above_idx[-1]]) if len(above_idx) else 0.0
    full = top >= min(20_800, nyq - 500)
    return top, full, freqs, smooth


def classify(cutoff_hz: float, full_band: bool) -> tuple[str, int]:
    if full_band:
        return QUALITY_TABLE[0][1], QUALITY_TABLE[0][2]
    for min_hz, label, kbps in QUALITY_TABLE:
        if cutoff_hz >= min_hz:
            return label, kbps
    return QUALITY_TABLE[-1][1], QUALITY_TABLE[-1][2]


def analyze_quality(path: str) -> tuple[QualityReport, np.ndarray, np.ndarray]:
    r = QualityReport()
    info = probe(path)
    st, fmt = info["stream"], info["format"]
    r.codec = st.get("codec_name", "?")
    r.sample_rate = int(st.get("sample_rate", 0) or 0)
    r.channels = int(st.get("channels", 0) or 0)
    r.duration = float(fmt.get("duration", 0) or 0)
    br = st.get("bit_rate") or fmt.get("bit_rate")
    if br:
        r.container_bitrate_kbps = round(int(br) / 1000)

    y, sr = _load_for_spectrum(path)
    r.cutoff_hz, r.full_band, freqs, spec = spectral_cutoff(y, sr)
    r.estimated_label, r.estimated_kbps = classify(r.cutoff_hz, r.full_band)
    r.is_standard_320 = r.estimated_kbps >= 320

    lossless = r.codec in LOSSLESS_CODECS
    nominal = r.container_bitrate_kbps
    if r.sample_rate and r.sample_rate < 44_100:
        r.notes.append(f"Low sample rate ({r.sample_rate} Hz), below CD standard 44.1 kHz.")

    if r.is_standard_320:
        r.status, r.verdict = "ok", "Genuine 320 kbps quality"
    elif lossless:
        r.status = "fake"
        r.verdict = (f"Fake lossless: {r.codec.upper()} file, but the audio is only "
                     f"{r.estimated_label} (upconverted from a lossy file)")
    elif nominal and nominal >= 300:
        r.status = "fake"
        r.verdict = f"Fake 320: tagged {nominal} kbps, real quality only {r.estimated_label}"
    else:
        r.status, r.verdict = "low", f"Below standard: real quality {r.estimated_label}"

    if nominal and not lossless and nominal < 300 and r.is_standard_320:
        r.notes.append("Low nominal bitrate but full spectrum (efficient VBR/AAC).")
    return r, freqs, spec


# ---------------------------------------------------------------- BPM & Key

_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_CAMELOT_MAJOR = {"C": "8B", "C#": "3B", "D": "10B", "D#": "5B", "E": "12B", "F": "7B",
                  "F#": "2B", "G": "9B", "G#": "4B", "A": "11B", "A#": "6B", "B": "1B"}
_CAMELOT_MINOR = {"C": "5A", "C#": "12A", "D": "7A", "D#": "2A", "E": "9A", "F": "4A",
                  "F#": "11A", "G": "6A", "G#": "1A", "A": "8A", "A#": "3A", "B": "10A"}
_FLAT = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb"}


def detect_key(y: np.ndarray, sr: int) -> dict:
    y_h = librosa.effects.harmonic(y, margin=4)
    chroma = librosa.feature.chroma_cqt(y=y_h, sr=sr, bins_per_octave=36)
    profile = chroma.mean(axis=1)
    scores = []
    for i in range(12):
        maj = np.corrcoef(np.roll(_MAJOR, i), profile)[0, 1]
        mnr = np.corrcoef(np.roll(_MINOR, i), profile)[0, 1]
        scores.append((maj, _NOTES[i], "major"))
        scores.append((mnr, _NOTES[i], "minor"))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    note, mode = best[1], best[2]
    name = note + ("" if mode == "major" else "m")
    alt = _FLAT.get(note)
    camelot = (_CAMELOT_MAJOR if mode == "major" else _CAMELOT_MINOR)[note]
    return {
        "key": f"{note} {'Major' if mode == 'major' else 'Minor'}",
        "short": name + (f" / {alt}{'' if mode == 'major' else 'm'}" if alt else ""),
        "camelot": camelot,
        "confidence": float(best[0]),
        "runner_up": f"{second[1]} {'Major' if second[2] == 'major' else 'Minor'}",
    }


def detect_bpm(y: np.ndarray, sr: int) -> dict:
    onset = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median)
    tempo = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=onset, sr=sr))[0])
    # fold into the common 70–180 BPM range
    while tempo < 70:
        tempo *= 2
    while tempo > 180:
        tempo /= 2
    return {"bpm": round(tempo, 1), "half": round(tempo / 2, 1), "double": round(tempo * 2, 1)}


_ES_CAMELOT = {
    ("C", "major"): "8B", ("C#", "major"): "3B", ("Db", "major"): "3B", ("D", "major"): "10B",
    ("D#", "major"): "5B", ("Eb", "major"): "5B", ("E", "major"): "12B", ("F", "major"): "7B",
    ("F#", "major"): "2B", ("Gb", "major"): "2B", ("G", "major"): "9B", ("G#", "major"): "4B",
    ("Ab", "major"): "4B", ("A", "major"): "11B", ("A#", "major"): "6B", ("Bb", "major"): "6B",
    ("B", "major"): "1B",
    ("C", "minor"): "5A", ("C#", "minor"): "12A", ("Db", "minor"): "12A", ("D", "minor"): "7A",
    ("D#", "minor"): "2A", ("Eb", "minor"): "2A", ("E", "minor"): "9A", ("F", "minor"): "4A",
    ("F#", "minor"): "11A", ("Gb", "minor"): "11A", ("G", "minor"): "6A", ("G#", "minor"): "1A",
    ("Ab", "minor"): "1A", ("A", "minor"): "8A", ("A#", "minor"): "3A", ("Bb", "minor"): "3A",
    ("B", "minor"): "10A",
}


def _analyze_music_essentia(path: str) -> dict:
    import essentia
    import essentia.standard as es
    essentia.log.infoActive = False
    essentia.log.warningActive = False
    audio = es.MonoLoader(filename=path, sampleRate=44100)()[: 44100 * 300]
    bpm, _, conf, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    while bpm < 70:
        bpm *= 2
    while bpm > 190:
        bpm /= 2
    key, scale, strength = es.KeyExtractor(profileType="bgate")(audio)
    key2, scale2, _ = es.KeyExtractor(profileType="edma")(audio)
    camelot = _ES_CAMELOT.get((key, scale), "?")
    alt = f"{key2} {scale2.capitalize()} ({_ES_CAMELOT.get((key2, scale2), '?')})"
    return {
        "tempo": {"bpm": int(round(bpm)), "exact": round(float(bpm), 2),
                  "half": round(bpm / 2, 1), "double": round(bpm * 2, 1),
                  "confidence": round(float(conf), 2)},
        "key": {"key": f"{key} {scale.capitalize()}",
                "short": key + ("m" if scale == "minor" else ""),
                "camelot": camelot, "confidence": round(float(strength), 2),
                "runner_up": alt if (key2, scale2) != (key, scale) else "—"},
    }


def analyze_music(path: str) -> dict:
    try:
        return _analyze_music_essentia(path)
    except Exception:
        y, sr = librosa.load(path, sr=22050, mono=True, duration=240)
        t = detect_bpm(y, sr)
        t["exact"] = t["bpm"]
        t["bpm"] = int(round(t["bpm"]))
        return {"tempo": t, "key": detect_key(y, sr)}


def spectrogram_png(path: str, out_png: str, cutoff_hz: float | None = None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import librosa.display

    y, sr = _load_for_spectrum(path, max_seconds=60)
    D = librosa.amplitude_to_db(np.abs(librosa.stft(y, n_fft=4096, hop_length=1024)), ref=np.max)
    fig, ax = plt.subplots(figsize=(10, 3.6), dpi=110)
    fig.patch.set_facecolor("#16161d")
    ax.set_facecolor("#16161d")
    librosa.display.specshow(D, sr=sr, hop_length=1024, x_axis="time", y_axis="linear",
                             ax=ax, cmap="magma", vmin=-100, vmax=0)
    for hz, lbl in [(16_000, "16k (128kbps)"), (19_500, "19.5k"), (20_500, "20.5k (320kbps)")]:
        if hz < sr / 2:
            ax.axhline(hz, color="#7cf", lw=0.6, ls="--", alpha=0.6)
            ax.text(0.5, hz + 150, lbl, color="#7cf", fontsize=7)
    if cutoff_hz:
        ax.axhline(cutoff_hz, color="#ff4d6d", lw=1.2)
        ax.text(0.5, cutoff_hz - 900, f"cutoff ≈ {cutoff_hz/1000:.1f} kHz", color="#ff4d6d", fontsize=8)
    ax.set_title("Spectrogram (middle 60 s)", color="white", fontsize=10)
    ax.tick_params(colors="#aaa", labelsize=7)
    ax.xaxis.label.set_color("#aaa")
    ax.yaxis.label.set_color("#aaa")
    fig.tight_layout()
    fig.savefig(out_png, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_png
