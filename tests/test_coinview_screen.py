"""TC-CRY — 코인 모의매매 화면의 정직한 글 · 가격 차트 판단(public/js/coinview.js · paper.js · app.html) · 2026-10-30 · 할 일 ①-20

옛 화면은 시세에 출처 · 받은 시각이 없었고, 주문이 수수료 · 슬리피지 없이 현재가로 즉시 체결되며 이 앱의 모의 장부에만 기록된다는 말이 없었다.
설계 결정(2026-10-30 · 질문 · 바로 · 안 A + 차트) — 글을 시세 밑 · 주문 칸 위에 한 줄씩, 업비트 일봉 차트를 시세 아래에.
1. 글 — 출처 · 저장 시간 · 시각 미표시 · 못 받으면 마지막 값 / 모의 장부에만 기록 · 업비트로 나가지 않음 · 수수료 · 슬리피지 없음. (TC-CRY-01)
2. 서버가 실제로 그렇게 한다(글이 지어낸 말이 아니다) — 체결 코드에 수수료 · 슬리피지가 없고 시세 저장이 5초다. (TC-CRY-02)
3. 차트 점 — 일봉 종가만 · 날짜는 앞 10자 · 없는 줄은 뺀다 · 아래 글에 최고 · 최저 · 마지막 일봉과 「저장하지 않음 · 진행 중 · 실시간 아님」. (TC-CRY-03)
4. 화면 — 글 · 차트 칸이 app.html 에 있고 paper.js 가 시세를 그릴 때 채운다 · 야후가 없다. (TC-CRY-04)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CV = ROOT / "public" / "js" / "coinview.js"
APP = (ROOT / "public" / "app.html").read_text(encoding="utf-8")
PAPER = (ROOT / "public" / "js" / "paper.js").read_text(encoding="utf-8")
SERVICE = (ROOT / "app" / "services" / "paper_trading.py").read_text(encoding="utf-8")


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as cv from "{CV.resolve().as_uri()}";\nconst out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n', encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_notes_say_source_limits_and_how_orders_fill(tmp_path):
    """TC-CRY-01 — 시세 글(출처 · 약 5초 · 시각 미표시 · 마지막 값) · 주문 글(모의 장부 · 업비트로 안 나감 · 수수료 · 슬리피지 없음)."""
    out = _run(tmp_path, "out.s = cv.COIN_SOURCE_NOTE; out.o = cv.COIN_ORDER_NOTE;")
    s, o = out["s"], " ".join(out["o"])
    assert "업비트 공개 시세" in s and "약 5초" in s and "받은 시각은 표시되지 않음" in s and "마지막으로 받은 값이 나올 수 있습니다" in s
    assert "모의 장부에만 기록" in o and "업비트로 주문이 나가지 않습니다" in o and "수수료 · 슬리피지 없이 즉시 체결" in o
    assert "서버" not in s + o and "DB" not in s + o                      # 화면 글에 개발 티가 나는 말을 쓰지 않는다(규칙 L317)


def test_notes_match_what_the_server_really_does():
    """TC-CRY-02 — 글이 지어낸 말이 아니다: 코인 체결 코드에 수수료 · 슬리피지가 없고, 시세 저장은 5초이며, 실패하면 마지막 값을 돌려준다."""
    buy = SERVICE[SERVICE.index("async def crypto_buy("):SERVICE.index("async def crypto_sell(")]
    sell = SERVICE[SERVICE.index("async def crypto_sell("):SERVICE.index("async def crypto_history(")]
    for body in (buy, sell):
        assert "fee" not in body.lower() and "slippage" not in body.lower() and "수수료" not in body
        assert "upbit_trade_price" in body                                   # 위 현재가 그대로
    assert "account.cash = float(account.cash - buy_krw)" in buy and "proceeds = round(price * sell_count)" in sell
    assert "_UPBIT_TICKER_TTL = 5" in SERVICE
    tick = SERVICE[SERVICE.index("async def upbit_tickers("):SERVICE.index("async def upbit_trade_price(")]
    assert "except Exception:\n            pass" in tick and "return [_UPBIT_TICKER_CACHE[c][\"data\"]" in tick   # 실패하면 저장 값을 그대로(서버 고침은 장부 담당 몫)


def test_chart_points_and_summary(tmp_path):
    """TC-CRY-03 — 점은 종가 · 날짜 앞 10자 · 빠진 줄은 뺀다 · 글에 최고 · 최저 · 마지막 일봉 · 저장하지 않음 · 진행 중 · 실시간이 아님."""
    out = _run(tmp_path, """
      const c = [{time: "2026-10-28T09:00:00", close: 100000000}, {time: "2026-10-29T09:00:00", close: 104000000}, {time: "2026-10-30T09:00:00", close: 102500000},
                 {time: "bad", close: 1}, {time: "2026-10-31T09:00:00", close: null}];
      out.p = cv.coinPoints(c); out.s = cv.coinChartSummary(out.p); out.e = [cv.coinChartSummary([]), cv.coinPoints(null)];
    """)
    assert [p["time"] for p in out["p"]] == ["2026-10-28", "2026-10-29", "2026-10-30"] and len(out["p"]) == 3
    s = out["s"]
    assert "최근 3일 최고 104,000,000원 · 최저 100,000,000원 · 마지막 일봉 102,500,000원(2026-10-30)" in s
    assert "저장하지 않으며" in s and "오늘 봉은 진행 중" in s and "초 단위 실시간 차트가 아닙니다" in s
    assert out["e"] == ["일봉 자료를 받지 못했습니다.", []]


def test_screen_wires_notes_and_chart_without_yahoo():
    """TC-CRY-04 — app.html 에 글 · 차트 칸이 있고 paper.js 가 시세를 그릴 때 채운다 · 일봉은 기존 캔들 길 · 야후 없음."""
    view = re.search(r'data-view="paper-crypto">(.*?)data-view="paper-alternative"', APP, flags=re.S).group(1)
    for ident in ("pc-source-note", "pc-chart", "pc-chart-note", "pc-order-note"):
        assert f'id="{ident}"' in view, ident
    assert view.index('id="pc-ticker"') < view.index('id="pc-source-note"') < view.index('id="pc-chart"') < view.index('id="pc-order-note"') < view.index('id="pc-buy-krw"')
    body = PAPER[PAPER.index("async function cryptoTicker()"):PAPER.index("async function cryptoTicker()") + 2400]
    assert "COIN_SOURCE_NOTE" in body and "COIN_ORDER_NOTE" in body and "pcDrawChart(code)" in body
    assert "/api/paper/crypto/${encodeURIComponent(code)}/candles?unit=days&count=120" in PAPER
    code = CV.read_text(encoding="utf-8").split("*/", 1)[1]
    assert "yahoo" not in code.lower() and "/api/stocks/" not in code
