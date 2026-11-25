"""用解答檔 expected.json 驗證分析工具：異常要全部找到，也不能誤判"""
import json
from pathlib import Path

import pytest

from analyzer import detect_anomalies, parse_log

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "sample_logs"
EXPECTED = json.loads((LOGS / "expected.json").read_text(encoding="utf-8"))
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("log_name", sorted(EXPECTED))
def test_matches_expected(log_name):
    header, events = parse_log(LOGS / log_name)
    found = {(a["type"], a["line"]) for a in detect_anomalies(header, events, CONFIG)}
    answer = {(a["type"], a["line"]) for a in EXPECTED[log_name]}
    assert found == answer