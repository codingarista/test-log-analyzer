"""測試 log 異常分析工具：解析 log → 找出異常 → 比對已知問題 → 產生報告"""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

KNOWN_CODES = {"UNDERRUN", "DSI_ERR"}   # 已有判斷規則的錯誤代碼

DISCLAIMER = [
    "> **說明**",
    "> - 本報告由分析工具讀取輸入的 log 檔後，依判斷規則自動計算產生，並非事先寫好的固定內容。",
    "> - 輸入的 log 為模擬資料，由 `generator.py` 依設定的情境產生，異常為刻意放入；面板型號、數值與規格均為虛構。",
    "> - 「已知問題比對」中的可能原因與檢查步驟為一般性範例，僅供參考，不代表實際產品的診斷結果。",
]


# ===== 1. 解析 =====
def parse_log(path):
    """把 log 轉成結構化資料：檔頭（dict）與事件清單（list）"""
    header, events = {}, []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, start=1):
        if line.startswith("#"):
            for pair in line[1:].split():
                key, value = pair.split("=", 1)
                header[key] = value
            continue
        date, time, level, module, code, *rest = line.split()
        events.append({
            "line": line_no,
            "time": datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M:%S.%f"),
            "level": level.strip("[]"),
            "module": module.strip("[]"),
            "code": code,
            "fields": dict(item.split("=", 1) for item in rest),
        })
    return header, events


# ===== 2. 異常偵測 =====
def ms_between(a, b):
    return (b - a).total_seconds() * 1000


def detect_anomalies(header, events, cfg):
    anomalies = []
    frame_ms = 1000 / int(header.get("refresh_rate", 60))
    drop_ms = frame_ms * cfg["frame_drop_ratio"]

    # 掉幀：兩幀間隔超過門檻
    prev = None
    for e in events:
        if e["code"] == "FRAME_DONE":
            if prev and ms_between(prev["time"], e["time"]) > drop_ms:
                anomalies.append({"type": "FRAME_DROP", "line": e["line"], "time": e["time"],
                                  "detail": f"幀間隔 {ms_between(prev['time'], e['time']):.1f} ms"})
            prev = e

    # UNDERRUN：依時間分組，組內次數決定「連續」或「機率性」
    underruns = [e for e in events if e["code"] == "UNDERRUN"]
    groups = []
    for e in underruns:
        if groups and ms_between(groups[-1][0]["time"], e["time"]) <= cfg["underrun_window_ms"]:
            groups[-1].append(e)
        else:
            groups.append([e])
    for g in groups:
        kind = "UNDERRUN_BURST" if len(g) >= cfg["underrun_burst_count"] else "UNDERRUN_INTERMITTENT"
        for e in g:
            anomalies.append({"type": kind, "line": e["line"], "time": e["time"],
                              "detail": f"1 秒內共 {len(g)} 次"})

    for e in events:
        # DSI 錯誤：出現即異常
        if e["code"] == "DSI_ERR":
            anomalies.append({"type": "DSI_ERROR", "line": e["line"], "time": e["time"], "detail": ""})
        # 背光：偏離目標超過容許範圍
        elif e["code"] == "BL_LEVEL":
            nits, target = int(e["fields"]["nits"]), int(e["fields"]["target"])
            if abs(nits - target) / target > cfg["backlight_tolerance"]:
                anomalies.append({"type": "BACKLIGHT_OUT_OF_RANGE", "line": e["line"], "time": e["time"],
                                  "detail": f"{nits} nits（目標 {target}）"})
        # 未知異常：ERROR 等級但沒有對應規則
        elif e["level"] == "ERROR" and e["code"] not in KNOWN_CODES:
            anomalies.append({"type": "UNKNOWN_ERROR", "line": e["line"], "time": e["time"],
                              "detail": e["code"]})

    anomalies.sort(key=lambda a: a["line"])
    return anomalies


def find_chains(anomalies, cfg):
    """找出「UNDERRUN 之後短時間內發生掉幀」的連鎖關係"""
    underruns = [a for a in anomalies if a["type"].startswith("UNDERRUN")]
    chains = []
    for d in (a for a in anomalies if a["type"] == "FRAME_DROP"):
        for u in underruns:
            if 0 <= ms_between(u["time"], d["time"]) <= cfg["chain_window_ms"]:
                chains.append((u, d))
                break
    return chains


# ===== 3. 比對已知問題 =====
def match_known_issues(anomalies, known_issues):
    table = {k["anomaly_type"]: k for k in known_issues}
    return {a["type"]: table.get(a["type"]) for a in anomalies}


# ===== 4. 產生報告 =====
def fmt(t):
    return t.strftime("%H:%M:%S.") + f"{t.microsecond // 1000:03d}"


def build_report(log_name, header, anomalies, matches, chains, around=None):
    out = [f"# 測試 log 分析報告：{log_name}", "", *DISCLAIMER, ""]
    out.append(f"- 測試項目：{header.get('test_case', '-')}（{header.get('duration_s', '-')} 秒）")
    if around:
        out.append(f"- 查詢範圍：{fmt(around[0])} ～ {fmt(around[1])}")
    types = sorted({a["type"] for a in anomalies})
    out.append(f"- 判定：{'FAIL' if anomalies else 'PASS'}（發現 {len(types)} 類異常）")
    out.append("")
    if not anomalies:
        out.append("未發現異常。")
        return "\n".join(out) + "\n"

    out += ["## 異常摘要", "", "| 異常類型 | 次數 | 首次出現 | 證據行號 |", "|---|---|---|---|"]
    for t in types:
        items = [a for a in anomalies if a["type"] == t]
        lines = ", ".join(f"L{a['line']}" for a in items[:5]) + ("…" if len(items) > 5 else "")
        out.append(f"| {t} | {len(items)} | {fmt(items[0]['time'])} | {lines} |")

    out += ["", "## 已知問題比對", ""]
    for t in types:
        k = matches[t]
        if k:
            out.append(f"### {t} → {k['id']}「{k['title']}」")
            out.append(f"- 可能原因：{k['possible_cause']}")
            out.append("- 建議檢查步驟：")
            out += [f"  {i}. {s}" for i, s in enumerate(k["check_steps"], start=1)]
        else:
            out.append(f"### {t} → 未對應已知問題（需人工確認，確認後補進 known_issues.json）")
        out.append("")

    if chains:
        out += ["## 關聯分析", ""]
        for u, d in chains:
            out.append(f"- {fmt(d['time'])} 的掉幀（L{d['line']}）發生在 UNDERRUN（L{u['line']}）之後 "
                       f"{ms_between(u['time'], d['time']):.0f} ms 內，可能是連鎖反應，建議先處理 UNDERRUN")
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description="分析測試 log 並產生報告")
    parser.add_argument("log", help="要分析的 log 檔")
    parser.add_argument("--around", help="只看某個時間點前後，例如 10:02 或 10:02:15")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--known", default="known_issues.json")
    parser.add_argument("--outdir", default="reports")
    args = parser.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    known = json.loads(Path(args.known).read_text(encoding="utf-8"))
    header, events = parse_log(args.log)
    anomalies = detect_anomalies(header, events, cfg)

    around = None
    if args.around:
        day = events[0]["time"].date()
        fmt_in = "%H:%M:%S" if args.around.count(":") == 2 else "%H:%M"
        center = datetime.combine(day, datetime.strptime(args.around, fmt_in).time())
        w = timedelta(seconds=cfg["around_window_s"])
        around = (center - w, center + w)
        anomalies = [a for a in anomalies if around[0] <= a["time"] <= around[1]]

    report = build_report(Path(args.log).name, header, anomalies,
                          match_known_issues(anomalies, known), find_chains(anomalies, cfg), around)
    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True)
    out_path = outdir / (Path(args.log).stem + ("_around" if around else "") + "_report.md")
    out_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"報告已存到 {out_path}")


if __name__ == "__main__":
    main()