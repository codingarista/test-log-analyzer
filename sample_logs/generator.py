"""測試 log 產生器：產生顯示器壓力測試的模擬 log 與解答檔"""
import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

# ===== 基本設定 =====
REFRESH_RATE = 60                    # 更新率 60 Hz
FRAME_MS = 1000 / REFRESH_RATE       # 每幀間隔約 16.67 ms
JITTER_MS = 0.5                      # 每幀隨機誤差 ±0.5 ms
FRAME_DROP_MS = FRAME_MS * 1.5       # 掉幀門檻：超過每幀間隔的 1.5 倍
BL_TARGET = 300                      # 背光目標亮度 300 nits
BL_NORMAL_RANGE = 3                  # 正常亮度誤差 ±3 nits
START_TIME = datetime(2026, 11, 25, 10, 0, 0)


def fmt_time(ms):
    """把「開始後第幾毫秒」轉成 log 時間格式"""
    t = START_TIME + timedelta(milliseconds=ms)
    return t.strftime("%Y-%m-%d %H:%M:%S.") + f"{t.microsecond // 1000:03d}"


def make_header(test_id, duration):
    return [
        f"# test_id={test_id}",
        "# panel=PNL-X156 resolution=1920x1080 refresh_rate=60",
        f"# test_case=video_playback_stress duration_s={duration}",
    ]


def make_normal_events(duration, rng):
    """產生正常的事件：每幀 FRAME_DONE、每秒 BL_LEVEL"""
    events = []
    t = 0.0
    frame = 0
    while t < duration * 1000:
        events.append({"ms": t, "level": "INFO", "module": "DISP",
                       "text": f"FRAME_DONE frame={frame}"})
        frame += 1
        t += FRAME_MS + rng.uniform(-JITTER_MS, JITTER_MS)
    for sec in range(1, duration):
        nits = BL_TARGET + rng.randint(-BL_NORMAL_RANGE, BL_NORMAL_RANGE)
        events.append({"ms": sec * 1000, "level": "INFO", "module": "BL",
                       "text": f"BL_LEVEL nits={nits} target={BL_TARGET}"})
    return events


def shift_frames_after(events, at_ms, delay_ms):
    """模擬掉幀：把 at_ms 之後的所有畫面往後推 delay_ms"""
    for e in events:
        if e["module"] == "DISP" and e["text"].startswith("FRAME_DONE") and e["ms"] > at_ms:
            e["ms"] += delay_ms


def add_underrun_burst(events, at_ms, count=4):
    """在 at_ms 附近放入連續 UNDERRUN，並造成 1 次掉幀"""
    for i in range(count):
        events.append({"ms": at_ms + i * 20, "level": "ERROR", "module": "DISP",
                       "text": "UNDERRUN layer=0 fifo_level=0",
                       "expect": "UNDERRUN_BURST"})
    shift_frames_after(events, at_ms, FRAME_MS * 2)   # 多等了約 2 幀


def add_single_underrun(events, at_ms):
    """偶發 1 次 UNDERRUN：屬於機率性異常"""
    events.append({"ms": at_ms, "level": "ERROR", "module": "DISP",
                   "text": "UNDERRUN layer=0 fifo_level=0",
                   "expect": "UNDERRUN_INTERMITTENT"})


def add_dsi_errors(events, at_ms, count=5):
    for i in range(count):
        events.append({"ms": at_ms + i * 150, "level": "ERROR", "module": "DSI",
                       "text": "DSI_ERR lane=0 crc_err=1", "expect": "DSI_ERROR"})


def add_backlight_unstable(events, start_sec, seconds=20):
    for e in events:
        if e["module"] == "BL" and start_sec * 1000 <= e["ms"] < (start_sec + seconds) * 1000:
            sec = int(e["ms"] // 1000)
            nits = 250 if sec % 2 == 0 else 340
            e["level"] = "WARN"
            e["text"] = f"BL_LEVEL nits={nits} target={BL_TARGET}"
            e["expect"] = "BACKLIGHT_OUT_OF_RANGE"


def add_unknown_error(events, at_ms):
    events.append({"ms": at_ms, "level": "ERROR", "module": "DISP",
                   "text": "OVERLAY_FAIL layer=1", "expect": "UNKNOWN_ERROR"})


def write_log(path, header, events):
    """寫出 log 檔，並回傳解答（哪一行放了什麼異常）"""
    events.sort(key=lambda e: e["ms"])
    lines = list(header)
    answers = []
    prev_frame_ms = None
    for e in events:
        lines.append(f"{fmt_time(e['ms'])} [{e['level']}] [{e['module']}] {e['text']}")
        line_no = len(lines)
        if "expect" in e:
            answers.append({"type": e["expect"], "line": line_no, "time": fmt_time(e["ms"])})
        if e["text"].startswith("FRAME_DONE"):
            if prev_frame_ms is not None and e["ms"] - prev_frame_ms > FRAME_DROP_MS:
                answers.append({"type": "FRAME_DROP", "line": line_no, "time": fmt_time(e["ms"]),
                                "gap_ms": round(e["ms"] - prev_frame_ms, 1)})
            prev_frame_ms = e["ms"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return answers


def main():
    parser = argparse.ArgumentParser(description="產生顯示器壓力測試的模擬 log")
    parser.add_argument("--duration", type=int, default=600, help="測試長度（秒），預設 600")
    parser.add_argument("--seed", type=int, default=42, help="隨機種子，預設 42")
    parser.add_argument("--outdir", default="sample_logs", help="輸出資料夾")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True)
    d = args.duration
    expected = {}

    scenarios = {
        "normal": lambda ev: None,
        "underrun_flicker": lambda ev: (add_underrun_burst(ev, 135_000),
                                        add_single_underrun(ev, 300_000)),
        "dsi_error": lambda ev: add_dsi_errors(ev, 270_000),
        "backlight_unstable": lambda ev: add_backlight_unstable(ev, 360),
        "mixed": lambda ev: (add_underrun_burst(ev, 100_000),
                             add_dsi_errors(ev, 250_000),
                             add_backlight_unstable(ev, 400),
                             add_unknown_error(ev, 500_000)),
    }

    for i, (name, inject) in enumerate(scenarios.items(), start=1):
        rng = random.Random(args.seed + i)
        events = make_normal_events(d, rng)
        inject(events)
        header = make_header(f"PT-20261125-{i:02d}", d)
        expected[f"{name}.log"] = write_log(outdir / f"{name}.log", header, events)

    (outdir / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已產生 {len(scenarios)} 份 log 與 expected.json 到 {outdir}/")


if __name__ == "__main__":
    main()