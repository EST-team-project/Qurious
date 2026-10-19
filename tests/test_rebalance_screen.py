"""#170 U2·U5: 실제 HTML·JS의 비중 비교·다음 확인일·이력을 Chrome에서 검증한다.

QURIOUS_TEST_CHROME / QURIOUS_TEST_CHROME_PROFILE 지정 시 실행한다.
API는 합성 응답, 차트는 라이브러리 입력 계열을 기록한다. 운영 계정·주문을 사용하지 않는다.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get("QURIOUS_TEST_CHROME")
PROFILE = os.environ.get("QURIOUS_TEST_CHROME_PROFILE")


@pytest.mark.skipif(not (CHROME and PROFILE), reason="실제 Chrome 경로와 격리 프로필 필요")
def test_portfolio_comparison_and_rebalance_history(tmp_path):
    command = [sys.executable, str(ROOT / "tests/e2e/rebalance_portfolio.py"),
               "--chrome", CHROME, "--profile", PROFILE, "--out", str(tmp_path), "--port", "18968"]
    host = os.environ.get("QURIOUS_TEST_BROWSER_HOST")
    if host:
        command += ["--bind", "0.0.0.0", "--browser-host", host]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads((tmp_path / "browser-result.json").read_text())
    assert evidence["ok"] and len(evidence["checks"]) == 17
