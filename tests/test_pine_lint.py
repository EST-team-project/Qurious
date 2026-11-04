"""TC-PL — 커스텀 인디케이터 Pine v6 템플릿 · 간이 문법 점검(public/js/pine-lint.js · indicator.js) · 2026-11-04 · D7

1. 템플릿 — 화면이 만드는 Pine 코드는 네 가지 기본 모양 모두 v6 로 시작하고 점검을 오류 · 경고 0건으로 통과한다.
   실제 `generatePineCode()` 를 indicator.js 에서 잘라 node 로 돌린다(복사본이 아니다). 옛 코드의 `parseInt(buyTh)` 글자 누출이 없다. (TC-PL-01 · 02)
2. 점검 규칙 — 확실한 문법 오류는 「오류」, 추정은 「경고」. 줄 · 열이 맞다. 문자열 · 주석 안의 글자는 보지 않는다. (TC-PL-03 · 04)
3. 서버가 만드는 v6 코드(전략 카드 판 1 · 판 2 · 자유 산식 내보내기)를 점검에 넣어도 오류가 없다 — 잘못 잡는 오류(false positive)가 없고,
   화면 템플릿과 서버 코드가 같은 v6 로 어긋나지 않는다는 대조를 겸한다. (TC-PL-05)
4. 화면 연결 — 점검 결과 칸은 코드 칸 뒤에 JS 로 만들고(app.html 을 안 고침), 생성 · 저장 · 백테스트 클릭에서 보여 주되 요청을 막지 않는다. (TC-PL-06)
node 가 없으면 건너뛴다.
"""
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
LINT_URL = (PUB / "js" / "pine-lint.js").as_uri()
IND = (PUB / "js" / "indicator.js").read_text(encoding="utf-8")


def _node():
  node = shutil.which("node")
  if not node:
    pytest.skip("node 가 없어 건너뜀")
  return node


def _run(tmp_path, body: str, name="t.mjs"):
  script = tmp_path / name
  script.write_text(f'import {{ checkPineV6, formatPineCheck }} from "{LINT_URL}";\nconst out = {{}};\n{body}\nconsole.log(JSON.stringify(out));\n', encoding="utf-8")
  r = subprocess.run([_node(), str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
  assert r.returncode == 0, r.stderr
  return json.loads(r.stdout.strip().splitlines()[-1])


def _cut(start: str, end: str) -> str:
  i = IND.index(start)
  return IND[i:IND.index(end, i)]


def _template_source() -> str:
  """indicator.js 에서 Pine 템플릿을 만드는 부분만 — 이름 거름 한 줄 · 정수 읽기 · generatePineCode."""
  safe = re.search(r"^const ciSafeName = .*$", IND, re.M).group(0)
  ints = _cut("const ciPineInt =", "\n};\n") + "\n};\n"
  gen = _cut("function generatePineCode()", "\n}\n") + "\n}\n"
  return "\n".join([safe, ints, gen])


def _generate(tmp_path, fields: dict) -> dict:
  """실제 generatePineCode 를 가짜 입력 칸으로 돌려 { base: 코드 } 와 점검 결과를 돌려준다."""
  body = f"""
const FIELDS = {json.dumps(fields)};
globalThis.document = {{ getElementById: id => ({{ value: FIELDS[id] ?? "" }}) }};
{_template_source()}
out.codes = {{}}; out.checks = {{}};
for (const base of ["rsi_ma", "macd_bb", "volume_rsi", "triple_ma"]) {{
  FIELDS["ci-base"] = base;
  const code = generatePineCode();
  out.codes[base] = code;
  out.checks[base] = checkPineV6(code);
}}
"""
  return _run(tmp_path, body, "gen.mjs")


def test_all_four_templates_are_v6_and_pass_the_lint_with_nothing(tmp_path):
  """TC-PL-01 · 네 기본 모양(RSI+이동평균 · MACD+볼린저 · 거래량 RSI · 삼중 이동평균) 모두 v6 · 오류 0 · 경고 0 · 옛 글자 누출 없음."""
  o = _generate(tmp_path, {"ci-name": "MyIndicator", "ci-short": "5", "ci-mid": "20", "ci-rsi": "14", "ci-buy-th": "35"})
  for base, code in o["codes"].items():
    assert code.startswith("//@version=6\nindicator(\"MyIndicator\", overlay=true)"), base
    chk = o["checks"][base]
    assert chk["diagnostics"] == [] and chk["errors"] == 0 and chk["warnings"] == 0, (base, chk["diagnostics"])
    assert "parseInt" not in code and "buyTh" not in code and "${" not in code and "undefined" not in code, base
    assert "sell_th   = input.int(65, " in code, "매도 임계값 100-35 는 JS 가 계산해 숫자로 적는다"
  macd = o["codes"]["macd_bb"]
  assert "bb_upper = bb_mid + 2 * ta.stdev(close, mid_len)" in macd and "or close > bb_upper" in macd
  assert macd.index("bb_upper =") < macd.index("sell_signal"), "볼린저 위쪽 띠 계산은 조건식보다 앞(and / or 단락 평가)"
  assert "ta.stdev" not in macd.split("sell_signal")[1], "or 오른쪽에 ta.* 호출이 없다"


def test_template_inputs_are_integers_and_the_name_cannot_break_the_string(tmp_path):
  """TC-PL-02 · 칸에 소수(35.5)를 적어도 input.int 에는 정수만 · 빈칸은 기본값 · 이름의 따옴표 · 역슬래시 · ${} 는 문자열 안에서 무해."""
  o = _generate(tmp_path, {"ci-name": 'a"b\\c ${x}', "ci-short": "5.9", "ci-mid": "", "ci-rsi": "13.2", "ci-buy-th": "35.5"})
  code = o["codes"]["rsi_ma"]
  assert 'indicator("a\'b/c ${x}", overlay=true)' in code
  assert 'short_len = input.int(5, ' in code and 'mid_len   = input.int(20,' in code and 'rsi_len   = input.int(13,' in code
  assert 'buy_th    = input.int(35, ' in code and 'sell_th   = input.int(65, ' in code
  for base, chk in o["checks"].items():
    assert chk["errors"] == 0 and chk["warnings"] == 0, (base, chk["diagnostics"])


def test_rules_report_certain_errors_and_only_suspect_warnings(tmp_path):
  """TC-PL-03 · 규칙마다 줄 · 열 · 심각도 — 버전 · parseInt · study/iff · transp · when · bool=na · 괄호 · 중복 인자 · 빈 인자 · 대입 뒤 빈칸 = 오류, 단락 평가 ta.* · 이상한 글자 = 경고."""
  cases = {
    "no_version": ("indicator(\"x\")\nplot(close)\n", [(1, 1, "error", "//@version=6")]),
    "v5": ("//@version=5\nindicator(\"x\")\nplot(close)\n", [(1, 1, "error", "v5")]),
    "dup_version": ("//@version=6\n//@version=6\nindicator(\"x\")\n", [(2, 1, "error", "중복")]),
    "bad_version_form": ("//@version=6x\nindicator(\"x\")\n", [(1, 1, "error", "형식")]),
    "parseint": ("//@version=6\nindicator(\"x\")\na = input.int(100 - parseInt(b), \"t\")\n", [(3, 21, "error", "parseInt")]),
    "study": ("//@version=6\nstudy(\"x\")\n", [(2, 1, "error", "study")]),
    "iff": ("//@version=6\nindicator(\"x\")\na = iff(c, 1, 2)\n", [(3, 5, "error", "iff")]),
    "transp": ("//@version=6\nindicator(\"x\")\nplot(close, transp=50)\n", [(3, 13, "error", "transp")]),
    "when": ("//@version=6\nstrategy(\"x\")\nstrategy.entry(\"L\", strategy.long, when=c)\n", [(3, 36, "error", "when")]),
    "bool_na": ("//@version=6\nindicator(\"x\")\nbool b = na\n", [(3, 1, "error", "bool")]),
    "paren_open": ("//@version=6\nindicator(\"x\")\nplot(close\n", [(3, 5, "error", "닫히지")]),
    "paren_close": ("//@version=6\nindicator(\"x\")\nplot(close))\n", [(3, 12, "error", "여는 괄호")]),
    "dup_arg": ("//@version=6\nindicator(\"x\")\nplot(close, title=\"a\", title=\"b\")\n", [(3, 24, "error", "중복")]),
    "empty_arg": ("//@version=6\nindicator(\"x\")\nplot(, close)\n", [(3, 6, "error", "비어")]),
    "dangling_op": ("//@version=6\nindicator(\"x\")\na = 1 +\n", [(3, 7, "error", "연산자 뒤")]),
    "dangling_assign": ("//@version=6\nindicator(\"x\")\na =\n", [(3, 3, "error", "대입")]),
    "two_decl": ("//@version=6\nindicator(\"x\")\nindicator(\"y\")\n", [(3, 1, "error", "정확히 한 번")]),
    "no_decl": ("//@version=6\nplot(close)\n", [(1, 1, "error", "정확히 한 번")]),
    "unclosed_string": ("//@version=6\nindicator(\"x)\n", [(2, 11, "error", "닫는 따옴표")]),
    "leaked_template": ("//@version=6\nindicator(\"x\")\na = ${n}\n", [(3, 5, "error", "치환되지 않은")]),
    "lazy_ta": ("//@version=6\nindicator(\"x\")\nb = c or close > ta.sma(close, 3)\n", [(3, 18, "warning", "ta.sma")]),
    "brace": ("//@version=6\nindicator(\"x\")\nif a {\n", [(3, 6, "warning", "{")]),
    "indented_decl": ("//@version=6\n  indicator(\"x\")\n", [(2, 3, "warning", "들여쓰기")]),
    "js_leak": ("//@version=6\nindicator(\"x\")\na = undefined\n", [(3, 5, "warning", "undefined")]),
  }
  o = _run(tmp_path, f"const cases = {json.dumps({k: v[0] for k, v in cases.items()})}; out.r = Object.fromEntries(Object.entries(cases).map(([k, s]) => [k, checkPineV6(s).diagnostics]));")
  for name, (_, expected) in cases.items():
    got = o["r"][name]
    for line, col, sev, word in expected:
      hit = [d for d in got if d["line"] == line and d["column"] == col and d["severity"] == sev and word in d["message"]]
      assert hit, f"{name}: {line}행 {col}열 {sev} '{word}' 없음 — 실제 {got}"


def test_strings_comments_generics_and_continuations_are_not_false_positives(tmp_path):
  """TC-PL-04 · 문자열 · 주석 안의 글자(괄호 · 중괄호 · parseInt · ${)는 보지 않는다 · 여러 줄 호출 · 지수 숫자 · 제네릭(array<float>) · 부호 · 이름 있는 인자는 그대로 통과."""
  src = """//@version=6
// 주석 안의 ( { parseInt( ${x} study( 는 본 적이 없다
indicator("제목 ( { ; parseInt(", overlay = true, max_lines_count = 500)
var arr = array.new<float>(0)
var m = map.new<string, array<float>>()
a = 1e-5 + 2.5E3 - -1
b = close > open ? ta.sma(close, 3) : na
c = ta.crossover(close, open) and close > open
d = request.security(syminfo.tickerid, "D",
  close)
plot(a, "x", color = color.new(color.blue, 80), linewidth = 2)
if barstate.isconfirmed and c
    label.new(bar_index, high, "신호 {x}", color = color.green)
"""
  o = _run(tmp_path, f"out.r = checkPineV6({json.dumps(src)});")
  assert o["r"]["diagnostics"] == [], o["r"]["diagnostics"]


def test_server_generated_v6_code_passes_without_errors(tmp_path):
  """TC-PL-05 · 서버가 만드는 v6 코드 — 전략 카드 판 1 · 판 2(종가 판정 · 장중 판정) · 자유 산식 내보내기 — 를 점검에 넣어도 오류 0. 화면 템플릿과 서버 코드가 같은 v6 로 어긋나지 않는다."""
  from app.services import formula
  from app.services import pine_strategy as ps
  v1 = {"strategy_id": "ma_cross_kr", "version": 2, "universe": ["005930"], "timeframe": "1d",
        "entry": {"indicator": "ma_cross", "condition": "short_above_long", "params": {"short_window": 20, "long_window": 60}},
        "exit": {"indicator": "ma_cross", "condition": "short_below_long", "params": {"short_window": 20, "long_window": 60}},
        "signal_weights": {"technical": 1.0, "lightgbm": 0, "buy_threshold": 0.25, "sell_threshold": -0.25},
        "position_sizing": {"max_position_pct": 10, "max_symbols": 1}}
  v2 = json.loads((ROOT / "docs/phase-3/02-design/system/예시/strategy-card-ma-cross-v2.json").read_text(encoding="utf-8"))
  v2_intrabar = copy.deepcopy(v2)
  v2_intrabar["stops"]["judge"] = "intrabar"
  codes = {
    "card_v1": ps.generate(copy.deepcopy(v1), ref_price=70000, mintick=100).code,
    "card_v2": ps.generate(copy.deepcopy(v2), ref_price=70000, mintick=100).code,
    "card_v2_intrabar": ps.generate(v2_intrabar, ref_price=70000, mintick=100).code,
    "formula": formula.to_pine("점검 지표", "zscore(close, n)", "close < bb_lower(close, n, k)", "close > bb_upper(close, n, k)", {"n": 20, "k": 2.0}),
    "formula_plain": formula.to_pine("rsi", "rsi(close, n)", "", "", {"n": 14}),
  }
  o = _run(tmp_path, f"const codes = {json.dumps(codes)}; out.r = Object.fromEntries(Object.entries(codes).map(([k, s]) => [k, checkPineV6(s)]));")
  for name, chk in o["r"].items():
    assert chk["errors"] == 0, (name, [d for d in chk["diagnostics"] if d["severity"] == "error"])
    assert codes[name].startswith("//@version=6"), name
  assert all(chk["warnings"] == 0 for chk in o["r"].values()), {k: v["diagnostics"] for k, v in o["r"].items() if v["warnings"]}


def test_format_for_the_screen_is_plain_text_with_row_and_column(tmp_path):
  """TC-PL-05b · 화면에 쓸 글 — 「N행 M열」 · 오류/경고 · 닿은 줄의 글자(snippet)를 담고, 20개를 넘으면 나머지 개수를 알린다. 요약 줄에 「컴파일 전」 한계를 적는다."""
  bad = "//@version=6\nindicator(\"x\")\n" + "".join(f"a{i} = parseInt(q)\n" for i in range(25))
  o = _run(tmp_path, f"const s = {json.dumps(bad)}; out.v = formatPineCheck(checkPineV6(s), s); out.ok = formatPineCheck(checkPineV6('//@version=6\\nindicator(\"x\")\\n'), '');")
  v = o["v"]
  assert v["tone"] == "error" and "오류 25개" in v["summary"] and "컴파일 전" in v["summary"]
  assert len(v["items"]) == 20 and v["more"] == 5
  first = v["items"][0]
  assert first["where"] == "3행 6열" and first["label"] == "오류" and "parseInt" in first["message"] and first["snippet"] == "a0 = parseInt(q)"
  assert o["ok"]["tone"] == "ok" and "발견된 문제 없음" in o["ok"]["summary"] and "보장하지 않습니다" in o["ok"]["summary"]


def test_screen_wiring_shows_the_check_without_blocking_requests():
  """TC-PL-06 · 결과 칸은 코드 칸 뒤에 JS 로 한 번 만든다(app.html 을 고치지 않음) · 처음 · 코드 생성 · 저장 · 백테스트에서 보이되 요청을 막지 않는다 · 템플릿은 v6."""
  assert "//@version=6" in IND and "//@version=5" not in IND
  assert 'import { checkPineV6, formatPineCheck } from "/js/pine-lint.js";' in IND
  assert 'pre.insertAdjacentElement("afterend", box)' in IND and 'id="ci-pine-check"' not in (PUB / "app.html").read_text(encoding="utf-8")
  gen = _cut('getElementById("ci-generate-btn").addEventListener', "});")
  assert "renderPineCheck();" in gen and gen.index("ci-pine-code") < gen.index("renderPineCheck();")
  test_btn = _cut('getElementById("ci-test-btn").addEventListener', "// 초기 코드 생성")
  save_btn = _cut('getElementById("ci-save-btn")', "const CI_BASE_LABELS")
  for part in (test_btn, save_btn):
    assert "if (!ciGuard()) return;\n" in part and "renderPineCheck();" in part
    assert part.index("renderPineCheck();") < part.index("await api("), "점검은 요청 앞에서 보이고"
    assert not re.search(r"if \(\s*(?:!?\s*)?\w*[Pp]ine\w*\.errors", part), "점검 결과로 요청을 막지 않는다"
  first = _cut("// 초기 코드 생성", "// ── 커스텀 인디케이터 저장/불러오기")
  assert "renderPineCheck();" in first
  # 점검 결과는 글자로만 넣는다 — 코드 · 점검 글을 HTML 로 넣지 않는다
  render = _cut("function renderPineCheck()", "function generatePythonCode()")
  assert "innerHTML" not in render and render.count("textContent") >= 3
  assert "strategy(" not in IND, "표시용 indicator 코드라는 안내(TC-TVK-03)가 거짓이 되지 않게"
