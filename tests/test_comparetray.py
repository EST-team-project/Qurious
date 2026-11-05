"""TC-CMT — 비교 트레이 분석 · 분석 메모 복사(public/js/comparetray.js · core.js 연결 · indicator.js 담기) · 2026-11-04 · D8

강사님 lumina-invest 의 비교 트레이 분석을 우리 규칙으로 다시 설계한 것을 지킨다.

1. 지표는 요약 글에서 정규식으로 뽑지 않고 담을 때 함께 넣은 구조 칸(`metrics`)에서 읽는다 · 구조 칸이 없는 옛 항목만 우리 화면이 실제로 내는
   요약 글 꼴에 맞춰 읽고 「요약 글에서 읽음」 표시 · 못 읽으면 지어내지 않고 「분석에서 뺀 항목」. (TC-CMT-01 · 02 · 03)
2. 구조 칸의 이름은 서버 응답 칸과 실제로 맞는다(서버를 돌려 본다). (TC-CMT-04)
3. 문구 규칙 — 별표 · 판단 문장 · 권유로 읽히는 말이 없고, 고지 한 줄(learnnotice.js NOTICE_LINE)이 화면과 메모 양쪽에 있다. (TC-CMT-05)
4. 글자 넣기 안전 — HTML 은 꺾쇠를 막고 Markdown 표는 | 와 줄바꿈을 막는다. (TC-CMT-06)
5. 연결 — core.js 는 가져오기 · 복사 연결 · 카드 안 한 줄뿐이고 comparetray.js 는 core.js 를 가져오지 않는다 · indicator.js 의 담기 단추 꼴은 그대로. (TC-CMT-07)
6. 복사 — 클립보드가 막히면 글을 띄워 직접 복사하게 한다. (TC-CMT-08)
node 가 없으면 건너뛴다(TC-CLV-07 과 같은 길 — 화면 파일을 그대로 불러 돌린다).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.investment_research import backtest_strategy
from tests.conftest import make_candles

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
CT_URL = (PUB / "js" / "comparetray.js").as_uri()
NOTICE_URL = (PUB / "js" / "learnnotice.js").as_uri()

BT_A = {"id": "a", "source": "성과 검증 (Python)", "label": "이동평균 교차 · 삼성전자", "summary": "수익률 +12.0% · 샤프 0.80 · MDD -20.5% · 승률 51.2%",
        "kind": "backtest", "symbol": "005930.KS", "as_of": "2026-10-15", "data_from": "2020-01-02", "data_note": "수집 DB 일봉(수정주가) · 2020-01-02 ~ 2026-10-15 종가",
        "metrics": {"return_pct": 12.0, "bh_pct": 20.0, "sharpe": 0.8, "mdd_pct": -20.5, "win_rate_pct": 51.2, "trade_count": 40}}
BT_B = {"id": "b", "source": "성과 검증 (Python)", "label": "볼린저밴드 · 삼성전자", "summary": "수익률 +8.0% · 샤프 1.10 · MDD -10.0% · 승률 55.0%",
        "kind": "backtest", "symbol": "005930.KS", "as_of": "2026-10-15", "data_from": "2020-01-02", "data_note": "수집 DB 일봉(수정주가) · 2020-01-02 ~ 2026-10-15 종가",
        "metrics": {"return_pct": 8.0, "bh_pct": 20.0, "sharpe": 1.1, "mdd_pct": -10.0, "win_rate_pct": 55.0, "trade_count": 12}}
# 옛 항목(구조 칸 없음) — 우리 화면이 실제로 내는 요약 글 꼴 그대로
LEAN = {"id": "c", "source": "LEAN 백테스트", "label": "AAPL · 이동평균", "summary": "수익률 +3.20% · MDD 4.5% · 샤프 0.4"}
ML = {"id": "d", "source": "ML 모델 비교", "label": "005930.KS · RandomForest", "summary": "CV 평균 52.3% (±1.4%) · 검증 정확도 50.1% · 기간 5y"}
QUANT_SNAPSHOT = {"id": "e", "source": "퀀트 전략 분석", "label": "삼성전자", "summary": "RSI 54.1 · 규칙 신호 중립 (점수 0)"}
MV = {"id": "f", "source": "모델 비교", "label": "삼성전자 · 5년", "summary": "기준선을 뚜렷이 넘은 모델 1/7 · 가장 높은 모델 LightGBM 52.0% · 기준일 2026-10-15"}
NO_TRADE = {"id": "g", "source": "성과 검증 (Python)", "label": "RSI 역추세 · 에코프로", "summary": "거래 0회 · 신호 없음 · 매수 후 보유 5.0% · 자료 2020-01-02 ~ 2026-10-15",
            "kind": "backtest", "symbol": "086520.KS", "as_of": "2026-10-15", "data_from": "2020-01-02",
            "metrics": {"return_pct": None, "bh_pct": 5.0, "sharpe": None, "mdd_pct": None, "win_rate_pct": None, "trade_count": 0}}


def _node():
  node = shutil.which("node")
  if not node:
    pytest.skip("node 가 없어 건너뜀")
  return node


def _run(tmp_path, body: str):
  """comparetray.js 를 그대로 불러 body 를 돌리고 마지막 줄의 JSON 을 돌려준다."""
  script = tmp_path / "t.mjs"
  script.write_text(f'import * as ct from "{CT_URL}";\nimport {{ NOTICE_LINE }} from "{NOTICE_URL}";\nconst out = {{}};\n{body}\nconsole.log(JSON.stringify(out));\n', encoding="utf-8")
  r = subprocess.run([_node(), str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
  assert r.returncode == 0, r.stderr
  return json.loads(r.stdout.strip().splitlines()[-1])


def test_structured_entries_make_a_ranked_table_with_extremes(tmp_path):
  """TC-CMT-01 · 구조 칸에서 읽는다 — 샤프 큰 순 · 열마다 최대 · 최소 표시 · 차이(%p) · 수익/낙폭 · 기준일 · 자료 출처. 요약 글에서 읽었다는 표시는 없다."""
  o = _run(tmp_path, f"const c = ct.buildComparison({json.dumps([BT_A, BT_B])}); out.c = c; out.html = ct.comparisonHtml(c);")
  t = o["c"]["backtest"]
  assert [r["name"] for r in t["rows"]] == ["볼린저밴드 · 삼성전자", "이동평균 교차 · 삼성전자"], "샤프 큰 순"
  b, a = t["rows"]
  assert a["cells"]["ret"] == {"text": "+12.00%", "tag": "최대", "tone": "pos"} and b["cells"]["ret"]["tag"] == "최소"
  assert a["cells"]["mddAbs"]["text"] == "-20.50%" and a["cells"]["mddAbs"]["tag"] == "최대" and b["cells"]["mddAbs"]["tag"] == "최소"
  assert a["cells"]["excess"]["text"] == "-8.00%p" and b["cells"]["excess"]["text"] == "-12.00%p"
  assert a["cells"]["ratio"]["text"] == "0.59" and b["cells"]["ratio"]["text"] == "0.80"
  assert a["cells"]["bh"]["tag"] == "" and a["cells"]["trades"]["text"] == "40회", "단순 보유 · 매매 횟수에는 표시를 붙이지 않는다"
  assert a["when"] == "2020-01-02 ~ 2026-10-15" and not a["fromSummary"]
  assert o["c"]["notes"][0]["note"].startswith("수집 DB 일봉"), "서버가 준 자료 출처 글이 그대로 나온다"
  assert "요약 글에서 읽음" not in o["html"] and o["c"]["excluded"] == []
  # 같은 종목 · 같은 기간 · 같은 곳이면 섞임 주의는 없다 — 매매 횟수 적음(30회 미만 · 12회)만
  joined = " ".join(o["c"]["cautions"])
  assert "서로 다른 종목" not in joined and "자료 기간이 서로 다릅니다" not in joined and "추가된 곳이 서로 다릅니다" not in joined
  assert "30회 미만" in joined and "12회" in joined


def test_equal_values_get_no_extreme_tag_and_single_row_none(tmp_path):
  """TC-CMT-01b · 값이 하나뿐이거나 모두 같으면 최대 · 최소를 붙이지 않는다 · 숫자가 아닌 값(null · 빈 글 · 불리언)은 0 이 아니라 빈 칸."""
  same = dict(BT_A, id="a2")
  odd = dict(BT_B, id="b2", metrics={"return_pct": "", "bh_pct": None, "sharpe": True, "mdd_pct": "abc", "win_rate_pct": None, "trade_count": None})
  o = _run(tmp_path, f"out.one = ct.buildComparison({json.dumps([BT_A])}).backtest.rows[0].cells;"
                     f"out.two = ct.buildComparison({json.dumps([BT_A, same])}).backtest.rows.map(r => r.cells.ret.tag);"
                     f"out.odd = ct.buildComparison({json.dumps([odd])});")
  assert all(c["tag"] == "" for c in o["one"].values())
  assert o["two"] == ["", ""]
  assert o["odd"]["backtest"] is None and o["odd"]["excluded"], "수익률이 숫자가 아니면 표에 넣지 않고 이유와 함께 뺀다"


def test_legacy_summaries_are_read_narrowly_and_marked(tmp_path):
  """TC-CMT-02 · 구조 칸이 없는 항목 — 우리 화면의 요약 글 꼴(LEAN · ML)만 읽고 「요약 글에서 읽음」 표시 · 주의 줄. 꼴이 다르면 뺀다(지어내지 않음)."""
  o = _run(tmp_path, f"const l = {json.dumps([BT_A, LEAN, ML, QUANT_SNAPSHOT, MV])}; const c = ct.buildComparison(l); out.c = c; out.html = ct.comparisonHtml(c);"
                     f"out.read = ['수익률 +3.20% · MDD 4.5% · 샤프 0.4', '수익률 -1,234.5% · 샤프 -0.3 · MDD -50.0% · 승률 40.0% · 자료 2020-01-02 ~ 2026-10-15',"
                     f"'수익률 - · MDD undefined% · 샤프 undefined', '수익률 +3% · 샤프 abc', 'CV 평균 52.3% (±1.4%) · 검증 정확도 50.1%', '거래 0회 · 신호 없음 · 매수 후 보유 5.0%'].map(ct.readSummary);")
  c = o["c"]
  lean = next(r for r in c["backtest"]["rows"] if r["name"] == "AAPL · 이동평균")
  assert lean["fromSummary"] and lean["cells"]["ret"]["text"] == "+3.20%" and lean["cells"]["mddAbs"]["text"] == "-4.50%" and lean["cells"]["sharpe"]["text"] == "0.40"
  assert lean["when"] == "기준일 없음", "담은 시각은 기준일이 아니다 — 모르면 모른다고 쓴다"
  assert c["ml"]["rows"][0]["cells"]["cv"]["text"] == "52.3%" and c["ml"]["rows"][0]["cells"]["gap"]["text"] == "+2.20%p"
  assert {x["label"] for x in c["excluded"]} == {"삼성전자", "삼성전자 · 5년"}, "신호 스냅샷 · 다른 지표의 모델 비교는 읽지 않고 뺀다"
  assert all("요약:" in x["reason"] for x in c["excluded"]), "못 읽은 이유와 함께 원래 요약 글을 보인다"
  joined = " ".join(c["cautions"])
  assert "요약 글에서 숫자를 읽은 항목" in joined and "AAPL · 이동평균" in joined and "ML 정확도" in joined
  assert "추가된 곳이 서로 다릅니다" in joined and "기준일 정보가 없는 항목" in joined
  r = o["read"]
  assert r[0]["m"]["ret"] == 3.2 and r[0]["m"]["mddAbs"] == 4.5 and r[0]["m"]["sharpe"] == 0.4
  assert r[1]["m"]["ret"] == -1234.5 and r[1]["m"]["mddAbs"] == 50 and r[1]["asOf"] == "2026-10-15" and r[1]["from"] == "2020-01-02"
  assert r[2] is None, "수익률이 숫자가 아니면 통째로 못 읽는다(0 으로 읽지 않는다)"
  assert r[3]["m"]["ret"] == 3 and r[3]["m"]["sharpe"] is None, "숫자가 아닌 조각만 건너뛰고 나머지는 읽는다"
  assert r[4]["kind"] == "ml" and r[5]["m"]["trades"] == 0 and r[5]["m"]["bh"] == 5.0


def test_no_trade_is_left_out_with_the_reason_not_zero(tmp_path):
  """TC-CMT-03 · 거래 0회는 수익률 · 샤프 · 낙폭 · 승률이 0 이 아니라 값이 없다 — 표에 넣지 않고 「거래 0회」 이유 + 매수 후 보유를 적는다(성과 검증 화면과 같은 규칙)."""
  fields = {"total_return_pct": 0, "buy_hold_return_pct": 5.0, "sharpe_ratio": 0, "mdd_pct": 0, "win_rate_pct": 0, "trade_count": 0, "symbol": "086520.KS",
            "data_from": "2020-01-02", "data_as_of": "2026-10-15", "data_note": "n"}
  o = _run(tmp_path, f"out.f = ct.backtestTrayFields({json.dumps(fields)}); const c = ct.buildComparison({json.dumps([NO_TRADE, BT_A])}); out.c = c;")
  m = o["f"]["metrics"]
  assert m == {"return_pct": None, "bh_pct": 5.0, "sharpe": None, "mdd_pct": None, "win_rate_pct": None, "trade_count": 0}
  assert o["f"]["kind"] == "backtest" and o["f"]["as_of"] == "2026-10-15" and o["f"]["symbol"] == "086520.KS"
  assert [r["name"] for r in o["c"]["backtest"]["rows"]] == ["이동평균 교차 · 삼성전자"]
  x = o["c"]["excluded"][0]
  assert x["label"] == "RSI 역추세 · 에코프로" and "거래 0회" in x["reason"] and "+5.00%" in x["reason"]


def test_tray_fields_match_the_real_server_response(tmp_path):
  """TC-CMT-04 · 담기 단추가 읽는 서버 응답 칸 이름이 실제 응답에 있다 — 서버(성과 검증과 같은 backtest_strategy)를 돌려 그 값을 구조 칸에 담아 본다."""
  r = backtest_strategy(make_candles(400), strategy="ma")
  r.update({"symbol": "005930.KS", "data_from": "2020-01-02", "data_as_of": "2026-10-15", "data_note": "수집 DB 일봉"})
  need = ("total_return_pct", "buy_hold_return_pct", "sharpe_ratio", "mdd_pct", "win_rate_pct", "trade_count")
  assert all(k in r for k in need), [k for k in need if k not in r]
  o = _run(tmp_path, f"out.f = ct.backtestTrayFields({json.dumps({k: r[k] for k in (*need, 'symbol', 'data_from', 'data_as_of', 'data_note')})});")
  m = o["f"]["metrics"]
  assert m["return_pct"] == r["total_return_pct"] and m["bh_pct"] == r["buy_hold_return_pct"] and m["sharpe"] == r["sharpe_ratio"]
  assert m["mdd_pct"] == r["mdd_pct"] and m["win_rate_pct"] == r["win_rate_pct"] and m["trade_count"] == r["trade_count"]
  assert all(isinstance(v, (int, float)) for v in m.values()), "거래가 있으면 모든 지표가 숫자다"


FORBIDDEN = ["★", "☆", "fa-star", "우수", "추천", "좋음", "유리", "권유", "권장", "사세요", "파세요", "효율", "버티기", "맞습니다", "약합니다", "분산", "비중"]


def test_wording_has_no_judgement_and_carries_the_notice_once_per_form(tmp_path):
  """TC-CMT-05 · 화면 글 · 메모 글에 별표 · 우수 · 추천 · 판단 문장이 없다(고지 한 줄만 「권유」 를 말한다) — 고지는 learnnotice.js 의 NOTICE_LINE 그대로, 화면에 한 번 · 메모에 머리와 꼬리 두 번."""
  o = _run(tmp_path, f"const c = ct.buildComparison({json.dumps([BT_A, BT_B, LEAN, ML, QUANT_SNAPSHOT, NO_TRADE])}); out.html = ct.comparisonHtml(c);"
                     f"out.md = ct.comparisonMarkdown(c, '2026-11-04 15:00:00 (KST)'); out.notice = NOTICE_LINE; out.c = c;")
  assert o["notice"] and o["html"].count(o["notice"]) == 1 and o["md"].count(o["notice"]) == 2
  for form in ("html", "md"):
    body = o[form].replace(o["notice"], "")
    hits = [w for w in FORBIDDEN if w in body]
    assert not hits, f"{form}: 판단 · 권유로 읽힐 수 있는 낱말 {hits}"
  assert "정렬 기준일 뿐 좋고 나쁨의 판단이 아닙니다" in o["html"] and "만든 시각: 2026-11-04 15:00:00 (KST)" in o["md"]


def test_untrusted_text_cannot_inject_html_or_break_the_markdown_table(tmp_path):
  """TC-CMT-06 · 이름 · 출처 · 요약은 사용자 글/외부 글이다 — HTML 은 꺾쇠 · 따옴표를 막고, Markdown 표는 | 와 줄바꿈을 막는다."""
  evil = dict(BT_A, label='<img src=x onerror=alert(1)> | a\nb', source='"><script>x</script>', data_note="<b>n</b>")
  o = _run(tmp_path, f"const c = ct.buildComparison({json.dumps([evil, BT_B])}); out.html = ct.comparisonHtml(c); out.md = ct.comparisonMarkdown(c, 's');")
  assert "<img" not in o["html"] and "<script" not in o["html"] and "<b>n</b>" not in o["html"]
  assert "&lt;img src=x onerror=alert(1)&gt;" in o["html"]
  assert "\\|" in o["md"], "이름 안의 | 는 \\| 로"
  lines = o["md"].splitlines()
  head = next(line for line in lines if line.startswith("| # | 이름"))
  row = next(line for line in lines if "onerror" in line and line.startswith("| "))
  cells = lambda s: len(re.split(r"(?<!\\)\|", s))                       # 이스케이프하지 않은 | 만 칸 나눔
  assert cells(row) == cells(head), "이름 안의 | · 줄바꿈이 있어도 칸 수가 머리와 같다(표가 한 줄로 유지)"


def test_wiring_core_gets_three_lines_and_no_import_cycle():
  """TC-CMT-07 · core.js 는 가져오기 · 복사 연결 · 카드 안 한 줄뿐 · comparetray.js 는 core.js 를 가져오지 않는다 · 담기 단추 꼴(`})'>⚖️ 비교에 추가`)은 그대로."""
  core = (PUB / "js" / "core.js").read_text(encoding="utf-8")
  assert core.count('from "/js/comparetray.js"') == 1
  assert "window.compareTrayCopy = () => copyComparison(compareTrayGet(), setToast);" in core
  assert core.count("${compareTrayAnalysisHtml(list)}") == 1
  ct = (PUB / "js" / "comparetray.js").read_text(encoding="utf-8")
  assert not re.search(r'^import .*core\.js', ct, re.M), "core.js 가 이 파일을 가져간다 — 거꾸로 가져오면 순환"
  assert re.findall(r'^import .* from "([^"]+)"', ct, re.M) == ["./learnnotice.js"], "가져오는 것은 고지 글 하나뿐(다른 화면 모듈을 끌고 오지 않는다)"
  ind = (PUB / "js" / "indicator.js").read_text(encoding="utf-8")
  assert 'import { backtestTrayFields } from "/js/comparetray.js";' in ind and "...backtestTrayFields(data)" in ind
  buttons = re.findall(r"onclick='compareTrayAdd\(.*?</button>", ind, flags=re.S)
  assert buttons and all(b.endswith("})'>⚖️ 비교에 추가</button>") for b in buttons)
  assert '.replace(/&/g, "&amp;").replace(/\'/g, "&#39;")' in ind, "담을 때 구조 칸 글에 & 가 있어도 속성이 깨지지 않게"
  # 이 파일은 가져올 때 하는 일이 없다 — 화면 전역(document · window · localStorage)을 쓰지 않는다(복사만 globalThis.navigator 로)
  code = re.sub(r"/\*.*?\*/", "", ct, flags=re.S)
  code = "\n".join(line.split("//")[0] if "//" in line and "http" not in line else line for line in code.splitlines())
  for name in ("document.", "window.", "localStorage", "addEventListener"):
    assert name not in code, name


def test_copy_falls_back_to_prompt_when_clipboard_is_blocked(tmp_path):
  """TC-CMT-08 · 복사 — 클립보드가 되면 알림, 막히면(없음 · 거부) 글을 띄워 직접 복사하게 한다."""
  o = _run(tmp_path, f"""
const list = {json.dumps([BT_A, BT_B])};
const calls = [];
const setNav = value => Object.defineProperty(globalThis, "navigator", {{ value, configurable: true, writable: true }});
globalThis.prompt = (m, t) => calls.push(["prompt", m]);
setNav({{ clipboard: {{ writeText: async t => {{ calls.push(["clip", t.slice(0, 12)]); }} }} }});
await ct.copyComparison(list, (m, k) => calls.push(["toast", m, k]));
setNav({{ clipboard: {{ writeText: async () => {{ throw new Error("denied"); }} }} }});
await ct.copyComparison(list, (m, k) => calls.push(["toast", m, k]));
setNav({{}});
await ct.copyComparison(list, (m, k) => calls.push(["toast", m, k]));
out.calls = calls;
""")
  assert o["calls"] == [["clip", "# 비교 트레이 분석 메모"[:12]], ["toast", "분석 메모를 복사했습니다", "ok"], ["prompt", "복사해 쓰세요:"], ["prompt", "복사해 쓰세요:"]]


def test_empty_and_broken_tray_never_throws(tmp_path):
  """TC-CMT-09 · 빈 트레이 · 깨진 항목(null · 문자열 · 구조 칸이 이상한 값)이 섞여도 화면 글을 내고 던지지 않는다 — 던지면 트레이 표까지 사라진다."""
  o = _run(tmp_path, """
out.empty = ct.compareTrayAnalysisHtml([]);
out.notList = ct.compareTrayAnalysisHtml(null);
out.broken = ct.compareTrayAnalysisHtml([null, "x", 3, {}, { metrics: 5 }, { metrics: { cv_mean: "1" } }, { label: 1, summary: {} }]).length > 0;
out.mixed = ct.buildComparison([null, { metrics: { return_pct: "7" }, label: "L" }]).backtest.rows[0].cells.ret.text;
""")
  assert o["empty"] == "" and o["notList"] == "" and o["broken"] is True and o["mixed"] == "+7.00%"
