# Apple M2 (MacBook Air 15", 10 GPU cores, 8 GB RAM, macOS 27.2) baseline

Measured 2026-11-20 on a 20 s clip, overlap 2 (normal quality), PyTorch MPS, app otherwise idle.

| model | mode | time (20 s clip) | ×realtime | 3:30 song (est.) |
|---|---|---|---|---|
| mdx23c | vocal | 34 s | 1.7 | ≈6 min |
| melband_ft2 | vocal | 48 s | 2.4 | ≈8.5 min |
| bs_1297 | vocal | 90 s | 4.5 | ≈16 min |
| mdx23c | stems (6) | 52 s | 2.6 | ≈9 min |
| bs_1297 on CPU | vocal | 178 s | 8.9 | ≈31 min |

Real song: 2:49 with melband_kim took ≈10 min. fp16/autocast gave no speedup on M2.
