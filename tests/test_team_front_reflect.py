"""TC-TFS · 팀원 화면 프론트 반영(D124 · 잠정) A1 · A2 · A3 — 서버는 그대로 두고 화면만 바꾼다.

- A1 대시보드 KIS 패널(주담당 강민석 · #242): 자동매매 주기 문구를 퀵스타트 응답 `interval_min` 으로 읽는다.
  응답 전 글자는 설정 기본(QUANT_CYCLE_SEC)과 같아야 한다 — 강사님 판(3분)이 들어와도 여기서 잡는다.
- A2 식 편집기 「숫자만 바꿔 조건 만들기」(주담당 신장환 · #243): 강사님 lumina-invest `5b6fc9a` 의 새 파일을 그대로 옮기고
  formula.js 에는 부르는 줄만 둔다. 이 칸이 만드는 식을 우리 산식 엔진(서버는 고치지 않음 — 10-18 지금은 강사님 최신과 blob 이 같음)이
  받아 계산하는지 본다 — 엔진과 쉬운 입력 가운데 한쪽만 바뀌어도 여기서 갈린다.
- A3 「그래프 읽는 법」(주담당 신장환 · #243): 강사님 `6e26041` 새 파일을 그대로 · 결과를 그릴 때마다 부른다.

주인 시험(TC-FM · TC-PE · TC-DA · TC-KQ · TC-KH · TC-BM · TC-NV)을 대조군으로 함께 돌린다.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "public" / "js"
APP = ROOT / "public" / "app.html"

EASY_IDS = ("fx-easy-kind", "fx-easy-n", "fx-easy-a", "fx-easy-b", "fx-easy-n-label", "fx-easy-a-label",
            "fx-easy-b-label", "fx-easy-summary", "fx-easy-example", "fx-easy-apply")
# 쉬운 입력이 기본값(RSI 14 · 30 · 70)과 두 꼴의 기본값에서 만드는 정의 — 아래 Node 시험이 글자까지 맞댄다
RSI = {"indicator_expr": "rsi(close, 14)", "buy_expr": "rsi(close, 14) < 30", "sell_expr": "rsi(close, 14) > 70"}
CROSS = {"indicator_expr": "sma(close, 5) - sma(close, 20)", "buy_expr": "crossover(sma(close, 5), sma(close, 20))",
         "sell_expr": "crossunder(sma(close, 5), sma(close, 20))"}
GAP = {"indicator_expr": "(close / sma(close, 20) - 1) * 100", "buy_expr": "(close / sma(close, 20) - 1) * 100 < -5",
       "sell_expr": "(close / sma(close, 20) - 1) * 100 > 5"}


def _read(p: Path) -> str:
  return p.read_text(encoding="utf-8")


def _view_block(view: str) -> str:
  html = _read(APP)
  start = html.index(f'<div class="view" data-view="{view}">')
  nxt = html.find('<div class="view" data-view="', start + 10)
  return html[start: nxt if nxt != -1 else len(html)]


# ── A1 ────────────────────────────────────────────────────────────────

def test_A1_KIS_패널_주기는_퀵스타트_응답값이고_응답_전_글자는_설정_기본과_같다():
  from app.config import settings

  minutes = type(settings).model_fields["QUANT_CYCLE_SEC"].default // 60
  src = _read(JS / "dashboard.js")
  m = re.search(r"^let kisIntervalMin = (\d+);", src, re.M)
  assert m, "응답 전 기본 주기 변수가 없다"
  assert int(m.group(1)) == minutes, f"응답 전 글자 {m.group(1)}분 ≠ 설정 기본 {minutes}분"
  assert re.search(r"^\s+kisIntervalMin = Number\(st\.interval_min\) \|\| kisIntervalMin;", src, re.M)
  # 실행 중 · 시작 전 안내 · 확인 창 · 시작 뒤 — 네 문구 모두 같은 변수
  # 실행 중 문구의 환경 이름은 2026-10-19 #211(오준영 · 실제 주문 환경으로 표시)이 kisEnvironmentLabel 로 바꿨다 — 주기는 같은 변수 그대로
  for phrase in ("(${escHtml(kisEnvironmentLabel(st.environment))} · ${kisIntervalMin}분 주기)", "종목 · ${kisIntervalMin}분 주기 · 1회",
                 "종목으로 ${kisIntervalMin}분마다 시그널", "${r.interval_min || kisIntervalMin}분마다"):
    assert phrase in src, phrase
  assert not re.search(r"KIS · \d+분 주기", src), "실행 중 문구에 숫자 주기가 박혀 있다"


def test_A1_화면이_읽는_interval_min_을_퀵스타트_상태_응답이_준다():
  """서버는 고치지 않았다 — 상태(GET) 응답의 칸이 이미 있는지만 본다(없으면 화면은 늘 기본 글자)."""
  tree = ast.parse(_read(ROOT / "app" / "services" / "kis_quickstart.py"))
  fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "readiness")
  keys = {k.value for r in ast.walk(fn) if isinstance(r, ast.Return) and isinstance(r.value, ast.Dict)
          for k in r.value.keys if isinstance(k, ast.Constant)}
  assert "interval_min" in keys


# ── A2 ────────────────────────────────────────────────────────────────

def test_A2_쉬운_입력_칸은_산식_화면_블록_안에_하나씩_있고_화면은_부르는_줄만_가진다():
  block, html = _view_block("indicator-formula"), _read(APP)
  guide = _read(JS / "formula-guide.js")
  for i in EASY_IDS:
    assert f'id="{i}"' in block, f"{i} 가 산식 화면 블록 밖이거나 없다"
    assert html.count(f'id="{i}"') == 1, f"{i} 가 둘 이상"
    assert f"'{i}'" in guide, f"모듈이 {i} 를 부르지 않는다 — 마크업과 모듈이 어긋남"
  fx = _read(JS / "formula.js")
  assert re.search(r'^import \{ initFormulaGuide \} from "/js/formula-guide\.js";', fx, re.M)
  # 칸이 없으면 건너뛴다 — 예외가 나면 main.js 의 첫 화면 이동까지 멈춘다
  assert re.search(r'^\s+if \(\$\("fx-easy-kind"\)\) initFormulaGuide\(', fx, re.M)


NODE_GUIDE = r"""
const els = {};
const el = id => (els[id] ??= { id, value: "", textContent: "", disabled: false, on: {},
  addEventListener(t, f) { (this.on[t] ??= []).push(f); } });
globalThis.document = { getElementById: id => el(id) };
// app.html 의 첫 값과 같게
el("fx-easy-kind").value = "rsi"; el("fx-easy-n").value = "14"; el("fx-easy-a").value = "30"; el("fx-easy-b").value = "70";
const { initFormulaGuide } = await import("__GUIDE__");
const applied = [];
initFormulaGuide(d => applied.push(d));
const fire = (id, t) => el(id).on[t].forEach(f => f());
const out = { rsi: { summary: el("fx-easy-summary").textContent, disabled: el("fx-easy-apply").disabled } };
fire("fx-easy-apply", "click"); out.rsiApplied = applied.at(-1);
el("fx-easy-a").value = "80"; fire("fx-easy-a", "input");
out.bad = { summary: el("fx-easy-summary").textContent, disabled: el("fx-easy-apply").disabled };
el("fx-easy-kind").value = "cross"; fire("fx-easy-kind", "change");
out.cross = { n: el("fx-easy-n").value, a: el("fx-easy-a").value, bDisabled: el("fx-easy-b").disabled,
              nLabel: el("fx-easy-n-label").textContent };
fire("fx-easy-apply", "click"); out.crossApplied = applied.at(-1);
el("fx-easy-kind").value = "gap"; fire("fx-easy-kind", "change");
fire("fx-easy-apply", "click"); out.gapApplied = applied.at(-1);
process.stdout.write(JSON.stringify(out));
"""


def test_A2_쉬운_입력은_기본값에서_세_정의를_만들고_잘못된_기준은_적용을_막는다(tmp_path):
  node = shutil.which("node")
  if not node:
    pytest.skip("Node 가 없어 화면 모듈을 돌릴 수 없다")
  script = tmp_path / "guide.mjs"
  script.write_text(NODE_GUIDE.replace("__GUIDE__", (JS / "formula-guide.js").resolve().as_uri()), encoding="utf-8")
  run = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
  assert run.returncode == 0, run.stderr
  out = json.loads(run.stdout)
  assert out["rsi"] == {"summary": "14일 RSI가 30 미만이면 매수 조건, 70 초과이면 매도 조건을 만족합니다.", "disabled": False}
  for got, want in ((out["rsiApplied"], RSI), (out["crossApplied"], CROSS), (out["gapApplied"], GAP)):
    assert {k: got[k] for k in want} == want
  assert out["bad"] == {"summary": "매수 기준은 매도 기준보다 작은 숫자로 입력하세요.", "disabled": True}
  assert out["cross"] == {"n": 5, "a": 20, "bDisabled": True, "nLabel": "단기 기간 (거래일)"}


def _candles(n: int = 300) -> list[dict]:
  import math

  out = []
  for i in range(n):
    close = 100 + 10 * math.sin(i / 9) + i * 0.05
    out.append({"time": 1_700_000_000 + i * 86_400, "open": close, "high": close * 1.01, "low": close * 0.99,
                "close": close, "volume": 1_000 + i})
  return out


@pytest.mark.parametrize("name, d", [("RSI", RSI), ("평균선 교차", CROSS), ("평균 대비", GAP)])
def test_A2_쉬운_입력이_만든_식을_우리_산식_엔진이_받아_계산한다(name, d):
  """쉬운 입력은 화면 파일뿐이라 서버 엔진과 따로 바뀔 수 있다 — 그 식을 우리 엔진(서버 그대로)이 검증 · 계산 · Pine 내보내기하는지 지킨다."""
  from app.services import formula

  v = formula.validate_definition(d["indicator_expr"], d["buy_expr"], d["sell_expr"], {})
  assert v["ok"] and not v["warnings"], (name, v)
  r = formula.compute(_candles(), d["indicator_expr"], d["buy_expr"], d["sell_expr"], {})
  assert r["latest_signal"] in {"BUY", "SELL", "HOLD", "HOLD_LONG"}, (name, r["latest_signal"])
  assert r["series"]["position"] is not None and r["backtest"] is not None, name
  assert r["series"]["buy_dates"] or r["series"]["sell_dates"], f"{name}: 300봉 동안 전환이 한 번도 없다 — 시험 봉을 볼 것"
  pine = formula.to_pine(name, d["indicator_expr"], d["buy_expr"], d["sell_expr"], {})
  assert "//@version" in pine and d["indicator_expr"].split("(")[0] in pine, f"{name}: Pine 내보내기가 비었거나 식이 없다"


# ── A3 ────────────────────────────────────────────────────────────────

def test_A3_그래프_읽는_법은_결과를_그릴_때마다_부르고_신호가_아니라는_문장을_지킨다():
  fx = _read(JS / "formula.js")
  assert re.search(r'^import \{ renderFormulaChartHelp \} from "/js/formula-chart-help\.js";', fx, re.M)
  body = fx[fx.index("function renderResult("): fx.index("async function computeNow(")]
  assert re.search(r"^\s+renderFormulaChartHelp\(r\);", body, re.M)
  help_ = _read(JS / "formula-chart-help.js")
  assert "매수 신호를 뜻하지 않으며" in help_
  assert "document.getElementById('fx-chart').after(box)" in help_
  assert 'id="fx-chart"' in _view_block("indicator-formula")


# ── 공통 — 옮긴 새 파일의 낱말 ─────────────────────────────────────────

BANNED = ("강력 매수", "강력매수", "적극 매수", "권장", "추천 종목", "수익 보장", "원금 보장", "무조건")
PERSONAL = ("email", "phone", "주민", "계좌번호", "password", "비밀번호")


@pytest.mark.parametrize("name", ["formula-guide.js", "formula-chart-help.js"])
def test_옮긴_새_파일은_투자_권유_낱말과_개인정보_칸을_담지_않는다(name):
  s = _read(JS / name)
  for w in BANNED:
    assert w not in s, (name, w)
  low = s.lower()
  for w in PERSONAL:
    assert w not in low, (name, w)
