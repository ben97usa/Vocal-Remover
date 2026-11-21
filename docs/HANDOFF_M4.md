# Bàn giao: tăng tốc StemSplitter trên MacBook M4

Tài liệu này dành cho người giúp chạy và nâng cấp app trên MacBook M4.
Mục tiêu: tách **vocal + beat cho một bài ~3:30 trong khoảng 1–2 phút**, gần bằng vocalremover.org, mà vẫn giữ chất lượng.

## Cần biết trước
- **Tốc độ phụ thuộc vào máy đang *chạy* app, không phụ thuộc máy *build* app.** Build trên M4 rồi gửi lại cho MacBook Air M2 thì Air vẫn chạy với tốc độ của Air. Có 2 cách để được lợi từ M4:
  1. **Tối ưu code** trên M4 (chọn model, tham số, MLX/CoreML…). Các cải tiến này đẩy lên GitHub, máy M2 kéo về cũng nhanh hơn, nhưng không nhanh bằng M4.
  2. **Dùng M4 làm máy chủ tách nhạc:** app chạy trên M4, máy M2 mở giao diện qua mạng (cùng Wi-Fi hoặc Tailscale). Hiện server chỉ nghe `127.0.0.1`, nên cần thêm tuỳ chọn để nghe trên mạng, có bảo vệ.
- vocalremover.org nhanh vì chạy trên GPU NVIDIA ở máy chủ và có thể dùng model nhẹ hơn. Trên Mac, model chạy qua PyTorch MPS.

## Bước 1: cài đặt (khoảng 10 phút + tải ~3 GB model)
```bash
brew install python@3.12 ffmpeg git
git clone https://github.com/ben97usa/Vocal-Remover.git ~/Projects/StemSplitter
cd ~/Projects/StemSplitter
./setup.sh
./start.sh          # mở http://127.0.0.1:7861 và thử tách 1 bài cho model tải về
```

## Bước 2: đo tốc độ gốc (trước khi sửa gì)
Lúc đo, tắt bớt app khác và đừng tách bài nào trong app.
```bash
.venv/bin/python tools/benchmark.py "/đường/dẫn/bài.mp3" --seconds 30 --models melband_ft2,mdx23c,bs_1297 --stems
```
Kết quả được ghi vào `benchmarks/<chip>.md`. Số liệu của M2 nằm ở `benchmarks/Apple_M2.md` để so sánh.

## Bước 3: dán prompt này vào Claude Code (mở trong thư mục project)

```text
You are working on StemSplitter (this repo). Read CLAUDE.md, README.md and docs/HANDOFF_M4.md first.
This Mac is an Apple M4 (check exact chip/GPU cores/RAM with tools/benchmark.py output).

Goal: make vocal/instrumental separation of a 3:30 song finish in ~1–2 minutes on this Mac
(currently ~8 min on an M2 Air with melband_ft2), WITHOUT a noticeable drop in vocal cleanliness,
and keep the app working the same way (English UI, FastAPI + static mixer, live progress, Cancel, cache).

Work in this order and measure everything with tools/benchmark.py (same song, same clip, app idle):
1. Baseline: run the benchmark for melband_ft2, mdx23c, bs_1297 and --stems. Commit results in benchmarks/.
2. Cheap tuning in separate.py (_make_separator): mdxc batch_size, segment_size, overlap (1 vs 2),
   demucs segment/shifts; check MPS memory with larger batches (this Mac has more RAM/GPU than the M2).
   Try torch fp16/bfloat16 on MPS for the Roformer models (it did not help on M2; re-test on M4).
3. Faster backends: investigate MLX or CoreML/ONNX ports of MelBand/BS-Roformer or MDX23C
   (only well-maintained open-source code; verify outputs numerically against the PyTorch version).
4. Add a "Fast" preset in the UI (model + params chosen from the measurements) next to the existing
   model select and High quality toggle; keep the current default available.
5. Quality check: for each candidate, compare vocals against the current default (e.g. SDR vs the
   default output, plus listen to a few seconds) and report the trade-off in a table.
6. Optional: add an opt-in "LAN server" mode (env var, bind 0.0.0.0, simple token) so another Mac on
   the same network can use this Mac for separation. Off by default.

Rules: do not commit .venv/ or models/; keep requirements.txt and setup.sh up to date; one commit per
step with benchmark numbers in the message; update CLAUDE.md (performance facts) and benchmarks/.
Finish with a short summary: before/after times per model, chosen defaults, and anything that failed.
```

## Bước 4: gửi lại
- Đẩy code lên GitHub (cần quyền ghi vào repo `ben97usa/Vocal-Remover`; chủ repo mời làm collaborator, hoặc fork rồi tạo Pull Request).
- Trên máy M2: `cd ~/Projects/StemSplitter && git pull && .venv/bin/pip install -r requirements.txt && ./stop.sh && ./start.sh`.
