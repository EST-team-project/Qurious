"""TC-KR — KIS 모의투자 결과 화면(public/js/kis-results.js · 화면 키 kis-results) · 2026-11-04

강사님 lumina-invest 「KIS 모의투자결과」(D1)의 축소판: 내 주문만 · 필터 · 쪽 · CSV 내려받기 · 상태 요약 카드.
새 그리드 부품 없이 일반 표 + 우리 스타일. 데이터는 `GET /api/quant/kis/orders?owner=me` 하나(읽기만).

무엇을 지키나
1. 상태 표 — 서버 ORDER_STATUSES 열 개가 한 번씩 묶음에 들어 있고 모두 한국어 낱말이 있다 · 카드 숫자의 합 = 전체 ·
   모르는 코드는 「기타」 · UNKNOWN/LOST 는 「실패」 가 아니라 「확인 필요」. (TC-KR-01)
2. 시각 · 질의 — KST 변환 · owner 는 늘 me · 상태 조건을 뺀 질의 · limit 상한 500 · 날짜 순서 검사. (TC-KR-02)
3. CSV — BOM · CRLF · 따옴표 두 번 · 글자 셀 앞 `= + - @` 수식 주입 막음 · 숫자 셀 그대로 · 개인정보 칸 없음 · 파일 이름. (TC-KR-03)
4. 쪽 계산 — 처음 · 가운데 · 끝 · 빈 목록 · 범위 밖. (TC-KR-04)
5. 표 · 카드 · 쪽 글 — 이스케이프 · 상태는 낱말+코드 · 가격 줄표 · 모의가 아닌 계좌 구분은 숨기지 않음 · IP/브라우저 칸 없음. (TC-KR-05)
6. 빈 상태 — 필터 없이 0건이면 까닭과 자동매매로 가는 링크, 조건이 있으면 조건 지우기. (TC-KR-06)
7. 소스 규칙 — owner=me 고정 · 모니터 API · 쓰기 요청 · 새 그리드 부품 · 브라우저 저장소 없음 · 절대 경로 import 없음. (TC-KR-07)
8. 연결 — 메뉴(퀀트자동매매) · 사용법 글 · 화면 칸 · CSS · 진입 훅 · 좁은 화면 규칙. (TC-KR-08)
9. 화면 스캐너가 이 화면의 진입 API 를 orders 하나로 본다. (TC-KR-09)
10. 화면 동작(가짜 DOM) — 요청 주소는 모두 owner=me 읽기 · 상태 거르기는 카드용 질의를 따로 · 쪽 이동 · CSV 는 500건씩 받아 합침. (TC-KR-10)
화면 모양(390 폭 넘침 · 글자 대비 · 표 스크롤)은 손으로 본다 — 결과 기록은 docs/_local/lumina-port-2026-11-04/D1-결과.md.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
KR = PUB / "js" / "kis-results.js"
KR_CSS = PUB / "css" / "kis-results.css"

ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')


def _read(rel: str) -> str:
  return (PUB / rel).read_text(encoding="utf-8")


def _run(tmp_path: Path, body: str) -> dict:
  node = shutil.which("node")
  if not node:
    pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
  script = tmp_path / "run.mjs"
  script.write_text(f'import * as kr from "{KR.resolve().as_uri()}";\n{ESC}\nconst out = {{}};\n{body}\n'
                    "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
  done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=60)
  assert done.returncode == 0, done.stderr
  return json.loads(done.stdout)


def test_status_table_matches_server(tmp_path):
  """TC-KR-01 — 서버 ORDER_STATUSES 열 개가 묶음에 한 번씩 · 모두 한국어 낱말 · 카드 합 = 전체 · 모르는 코드는 기타 · UNKNOWN/LOST 는 확인 필요."""
  from app.routes import kis_monitor

  out = _run(tmp_path, """
    out.groups = kr.KR_GROUPS.map(g => ({ key: g.key, label: g.label, codes: [...g.codes] }));
    out.words = kr.KR_STATUS_WORD;
    out.views = Object.fromEntries(Object.keys(kr.KR_STATUS_WORD).map(c => [c, kr.krStatusView(c)]));
    out.unknown = kr.krStatusView("brand_new");
    out.empty = kr.krStatusView(null);
    out.lower = kr.krStatusView("filled").group;
    out.counts = kr.krStatusCounts({ FILLED: 5, ACCEPTED: 2, PARTIALLY_FILLED: 1, REJECTED: 1, ERROR: 1, CANCELLED: 3, UNKNOWN: 2, LOST: 1, WEIRD: 4, BAD: "x", NEG: -3 });
    out.none = kr.krStatusCounts(null);
    out.values = Object.fromEntries(kr.KR_GROUPS.map(g => [g.key, kr.krGroupValue(g.key)]));
  """)
  codes = [c for g in out["groups"] for c in g["codes"]]
  assert sorted(codes) == sorted(kis_monitor.ORDER_STATUSES), "서버 상태 코드와 묶음이 어긋났다 — 새 코드는 묶음에 넣는다"
  assert len(codes) == len(set(codes)), "한 코드가 두 묶음에 있다"
  assert set(out["words"]) == set(kis_monitor.ORDER_STATUSES) and all(out["words"].values())
  for code, view in out["views"].items():
    assert view["code"] == code and view["word"] == out["words"][code] and view["group"] != "other"
  assert out["views"]["FILLED"]["kind"] == "ok" and out["views"]["REJECTED"]["kind"] == "bad"
  assert out["views"]["UNKNOWN"]["group"] == "check" and out["views"]["LOST"]["group"] == "check"
  assert out["views"]["UNKNOWN"]["kind"] == "warn" and "실패" not in out["words"]["UNKNOWN"] + out["words"]["LOST"], "체결됐을 수도 있어 실패로 부르지 않는다"
  assert out["unknown"] == {"code": "BRAND_NEW", "word": "BRAND_NEW", "group": "other", "kind": "idle"}   # 모르는 코드는 코드 그대로
  assert out["empty"]["code"] == "-" and out["empty"]["word"] == "-" and out["lower"] == "filled"
  c = out["counts"]
  per = {g["key"]: g["count"] for g in c["groups"]}
  assert per == {"filled": 5, "open": 3, "failed": 2, "cancelled": 3, "check": 3} and c["other"] == 4 and c["total"] == 5 + 3 + 2 + 3 + 3 + 4
  assert sum(per.values()) + c["other"] == c["total"], "카드 합이 전체와 같다(음수 · 글자는 0)"
  assert out["none"]["total"] == 0 and out["none"]["other"] == 0
  assert out["values"]["open"] == "PENDING,ACCEPTED,PARTIALLY_FILLED,CANCEL_REQUESTED" and out["values"]["filled"] == "FILLED"


def test_time_and_query(tmp_path):
  """TC-KR-02 — UTC→KST(+9) · 모르는 값은 줄표 · 질의의 owner 는 늘 me · 상태 조건 빼기 · limit 상한 500 · 날짜 순서 검사."""
  out = _run(tmp_path, """
    out.t = [kr.krKstText("2026-11-04T06:30:21.563353+00:00"), kr.krKstText("2026-11-04 06:30:21"), kr.krKstText("2026-11-04T15:30:21+09:00"),
             kr.krKstText("2026-11-04T15:30:00Z"), kr.krKstText(null), kr.krKstText(""), kr.krKstText("not a date"), kr.krKstText(new Date("2026-12-31T15:00:00Z"))];
    out.d = [kr.krKstDate("2026-11-04T16:00:00Z"), kr.krKstDate(null), kr.krCsvFileName(new Date("2026-11-04T06:00:00Z")), kr.krCsvFileName(null)];
    const all = { status: "FILLED,ACCEPTED", side: "BUY", q: "  삼성전자  ", dateFrom: "2026-11-01", dateTo: "2026-11-04" };
    out.full = kr.krQuery(all, { offset: 40, limit: 20 });
    out.bare = kr.krQuery({}, {});
    out.noStatus = kr.krQuery(all, { limit: 1, withStatus: false });
    out.clamp = [kr.krQuery({}, { limit: 99999 }), kr.krQuery({}, { limit: 0 }), kr.krQuery({}, { offset: -5 })];
    out.longQ = new URLSearchParams(kr.krQuery({ q: "가".repeat(200) }, {})).get("q").length;
    out.owners = [all, {}, { status: "X" }, { q: "owner=all" }, { q: "&owner=batch" }].map(f => new URLSearchParams(kr.krQuery(f, {})).getAll("owner"));
    out.problems = [kr.krFilterProblem({ dateFrom: "2026-11-05", dateTo: "2026-11-04" }), kr.krFilterProblem({ dateFrom: "2026-11-04", dateTo: "2026-11-04" }),
                    kr.krFilterProblem({ dateFrom: "2026-11-04" }), kr.krFilterProblem(null)];
    out.active = [kr.krFiltersActive({}), kr.krFiltersActive({ q: "  " }), kr.krFiltersActive({ q: "a" }), kr.krFiltersActive({ side: "BUY" }), kr.krFiltersActive({ dateTo: "2026-11-01" })];
  """)
  assert out["t"] == ["2026-11-04 15:30:21", "2026-11-04 15:30:21", "2026-11-04 15:30:21", "2026-11-05 00:30:00", "-", "-", "-", "2027-01-01 00:00:00"]
  assert out["d"] == ["2026-11-05", "", "kis-my-orders-2026-11-04.csv", "kis-my-orders-export.csv"]
  assert out["full"].startswith("owner=me&"), "owner 는 맨 앞에 me 로 못 박는다"
  q = dict(p.split("=", 1) for p in out["full"].split("&"))
  assert q["status"] == "FILLED%2CACCEPTED" and q["side"] == "BUY" and q["date_from"] == "2026-11-01" and q["date_to"] == "2026-11-04"
  assert q["limit"] == "20" and q["offset"] == "40" and q["q"].startswith("%EC%82%BC%EC%84%B1") and "%20%20" not in q["q"], "검색어는 앞뒤 공백을 떼고 보낸다"
  assert out["bare"] == "owner=me&limit=20&offset=0"
  assert "status=" not in out["noStatus"] and "side=BUY" in out["noStatus"] and "limit=1&" in out["noStatus"]
  assert out["clamp"] == ["owner=me&limit=500&offset=0", "owner=me&limit=20&offset=0", "owner=me&limit=20&offset=0"]
  assert out["longQ"] == 80, "서버 검색어 상한 80자를 넘기지 않는다"
  assert all(o == ["me"] for o in out["owners"]), "어떤 조건이 와도 owner 는 me 하나"
  assert out["problems"][0] == "시작일은 종료일보다 앞서야 합니다." and out["problems"][1:] == ["", "", ""]
  assert out["active"] == [False, False, True, True, True]


def test_csv(tmp_path):
  """TC-KR-03 — BOM · CRLF · 모든 셀 따옴표 · 따옴표는 두 번 · 글자 셀의 `= + - @` 수식 주입 막음 · 숫자 셀 그대로 · 개인정보 칸 없음."""
  out = _run(tmp_path, """
    out.cells = ["=SUM(A1)", "+1", "-2", "@x", "\\tfoo", "\\rbar", "정상", 'a"b', "줄\\n바꿈", "", null, 5, -5, 0].map(kr.krCsvCell);
    const row = { created_at: "2026-11-04T06:30:21+00:00", symbol: "005930.KS", name: '=HYPERLINK("http://x")', side: "BUY", order_type: "LIMIT",
                  quantity: 3, price: 71000, filled_quantity: 3, avg_filled_price: 70950.5, status: "FILLED", order_no: "0000123", environment: "paper",
                  message: "첫줄\\n둘째줄 \\"인용\\"", ip: "1.2.3.4", user_agent: "UA", client_ip: "9.9.9.9" };
    out.csv = kr.krCsvText([row, { symbol: "AAPL", status: "WEIRD", side: "SELL" }]);
    out.empty = kr.krCsvText([]);
    out.heads = kr.KR_CSV_COLUMNS.map(c => c[0]);
  """)
  assert out["cells"] == ['"\'=SUM(A1)"', '"\'+1"', '"\'-2"', '"\'@x"', '"\'\tfoo"', '"\'\rbar"', '"정상"', '"a""b"', '"줄\n바꿈"', '""', '""', '"5"', '"-5"', '"0"']
  csv = out["csv"]
  assert csv.startswith("\ufeff\"시각(KST)\""), "맨 앞 BOM(엑셀 한글 깨짐 방지)"
  lines = csv.split("\r\n")
  assert len(lines) == 3, "머리 + 두 행 — 행 사이는 CRLF(셀 안의 줄바꿈은 \\n 그대로)"
  assert out["empty"] == "\ufeff" + ",".join(f'"{h}"' for h in out["heads"])
  assert '"\'=HYPERLINK(""http://x"")"' in csv, "종목명이 수식이면 앞에 작은따옴표 · 안의 따옴표는 두 번"
  assert '"2026-11-04 15:30:21","005930","\'=HYPERLINK' in csv and '"매수","LIMIT","3","71000","3","70950.5","체결","FILLED","0000123","paper"' in csv
  assert '"첫줄\n둘째줄 ""인용"""' in csv, "메모의 줄바꿈 · 따옴표는 한 셀 안에"
  assert '"","AAPL","","매도","","","","","","WEIRD","WEIRD","","",""' in csv, "모르는 값은 빈 셀(0 으로 메우지 않는다) · 모르는 상태 코드는 그대로"
  for banned in ("1.2.3.4", "UA", "9.9.9.9"):
    assert banned not in csv, "IP · 브라우저는 CSV 에 없다"
  assert len(out["heads"]) == 14 and not [h for h in out["heads"] if re.search(r"IP|브라우저|계정|User|사용자", h)]


def test_paging(tmp_path):
  """TC-KR-04 — 쪽 계산: 처음 · 가운데 · 끝 · 빈 목록 · 범위 밖 · 이상한 입력."""
  out = _run(tmp_path, """
    out.first = kr.krPageInfo({ total: 93, offset: 0, limit: 20 });
    out.mid = kr.krPageInfo({ total: 93, offset: 40, limit: 20 });
    out.last = kr.krPageInfo({ total: 93, offset: 80, limit: 20 });
    out.exact = kr.krPageInfo({ total: 40, offset: 20, limit: 20 });
    out.none = kr.krPageInfo({ total: 0, offset: 0, limit: 20 });
    out.beyond = kr.krPageInfo({ total: 30, offset: 500, limit: 20 });
    out.odd = kr.krPageInfo({ total: "x", offset: -4, limit: "y" });
  """)
  f, m, last = out["first"], out["mid"], out["last"]
  assert (f["page"], f["pages"], f["from"], f["to"], f["hasPrev"], f["hasNext"]) == (1, 5, 1, 20, False, True)
  assert (m["page"], m["from"], m["to"], m["prevOffset"], m["nextOffset"]) == (3, 41, 60, 20, 60)
  assert (last["page"], last["from"], last["to"], last["hasNext"], last["lastOffset"]) == (5, 81, 93, False, 80)
  assert (out["exact"]["page"], out["exact"]["pages"], out["exact"]["hasNext"]) == (2, 2, False)
  n = out["none"]
  assert (n["page"], n["pages"], n["from"], n["to"], n["hasPrev"], n["hasNext"]) == (1, 1, 0, 0, False, False)
  b = out["beyond"]
  assert b["page"] == 2 and b["pages"] == 2 and b["to"] == 30 and b["lastOffset"] == 20, "범위 밖 offset 도 마지막 쪽으로 읽는다"
  assert out["odd"]["total"] == 0 and out["odd"]["limit"] == 20 and out["odd"]["offset"] == 0


def test_html_builders(tmp_path):
  """TC-KR-05 — 표 · 카드 · 쪽 글: 이스케이프 · 상태 낱말+코드 · 가격 줄표/시장가 · 모의 아닌 계좌 구분은 보임 · IP/브라우저/계정 칸 없음."""
  out = _run(tmp_path, """
    const base = { created_at: "2026-11-04T06:30:21+00:00", symbol: "005930.KS", name: "삼성<전자>", side: "BUY", order_type: "LIMIT",
                   quantity: 1234, price: 71000, filled_quantity: 1234, avg_filled_price: 70950.5, status: "FILLED", order_no: "00012", environment: "paper", message: "" };
    const rows = [base,
      { ...base, name: "", symbol: "AAPL", side: "SELL", price: null, order_type: "MARKET", filled_quantity: 0, avg_filled_price: null, status: "REJECTED", order_no: null,
        message: "<b>" + "장".repeat(120) + "</b>" },
      { ...base, price: 0, order_type: "LIMIT", status: "UNKNOWN", environment: "real", owner: "batch", owner_label: "봇(배치)", client_ip: "9.9.9.9", user_agent: "UA" }];
    out.table = kr.krTableHtml(rows, esc);
    out.view0 = kr.krRowView(rows[0]);
    out.view1 = kr.krRowView(rows[1]);
    out.cards = kr.krCardsHtml({ FILLED: 12, ACCEPTED: 2, REJECTED: 1, UNKNOWN: 1, CANCELLED: 3, WEIRD: 2 }, esc);
    out.cardsNoOther = kr.krCardsHtml({ FILLED: 1 }, esc);
    out.notes = [kr.krCardsNote({}), kr.krCardsNote({ statusFiltered: true, truncated: true })];
    out.pagerMid = kr.krPagerHtml(kr.krPageInfo({ total: 193, offset: 50, limit: 50 }), esc);
    out.pagerFirst = kr.krPagerHtml(kr.krPageInfo({ total: 5, offset: 0, limit: 20 }), esc);
    out.empty = kr.krTableHtml([], esc);
    out.num = [kr.krNum(1234567), kr.krNum(70950.5), kr.krNum(0.125), kr.krNum(null), kr.krNum("x"), kr.krNum(-1234.5), kr.krNum("")];
    out.code = [kr.krCode("005930.KS"), kr.krCode("krx:000660"), kr.krCode("aapl"), kr.krCode(null)];
  """)
  t = out["table"]
  assert t.count("<tr>") == 1 + 3, "머리 한 줄 + 주문 세 줄"
  assert "삼성&lt;전자&gt;" in t and "삼성<전자>" not in t and "<b>" not in t and "&lt;b&gt;" in t, "서버 글은 모두 이스케이프"
  assert '<span class="kr-badge" data-kind="ok">체결</span> <small class="kr-code">FILLED</small>' in t, "상태는 한국어 낱말 + 원래 코드(작게)"
  assert '<span class="kr-badge" data-kind="bad">거부</span> <small class="kr-code">REJECTED</small>' in t
  assert '<span class="kr-badge" data-kind="warn">접수 여부 미확인</span> <small class="kr-code">UNKNOWN</small>' in t
  assert '<td data-label="수량" class="kr-num">1,234</td>' in t and '<td data-label="가격 (원)" class="kr-num">71,000</td>' in t
  assert '<td data-label="체결" class="kr-num">1,234주 @ 70,950.5</td>' in t
  assert '<td data-label="가격 (원)" class="kr-num">시장가</td>' in t, "가격 없는 시장가 주문은 시장가"
  assert t.count('class="kr-num">-</td>') >= 2, "가격 0 · 체결 없음은 줄표(0 으로 메우지 않는다)"
  assert 'data-kind="buy">매수</span>' in t and 'data-kind="sell">매도</span>' in t
  assert "계좌 구분: real" in t and t.count("계좌 구분") == 1, "모의(paper)가 아닌 계좌 구분만 숨기지 않고 보인다"
  assert 'title="&lt;b&gt;' in t and "…" in t, "긴 메모는 줄이고 전체는 title"
  for banned in ("9.9.9.9", "UA", "봇(배치)", "batch", ">IP<", "브라우저", "계정"):
    assert banned not in t, f"표에 {banned}"
  assert re.findall(r'<th scope="col"[^>]*>([^<]+)</th>', t) == ["시각 (KST)", "종목", "방향", "수량", "가격 (원)", "체결", "상태", "주문번호"]
  assert 'role="region"' in t and 'tabindex="0"' in t and "kr-table-wrap" in t
  assert out["view0"]["name"] == "삼성<전자>" and out["view0"]["code"] == "005930" and out["view0"]["showCode"] is True
  assert out["view1"]["name"] == "AAPL" and out["view1"]["showCode"] is False and out["view1"]["orderNo"] == "-" and out["view1"]["price"] == "시장가"
  c = out["cards"]
  assert c.count("<li ") == 7, "전체 + 묶음 다섯 + 기타"
  assert re.search(r'data-kr-stat="all"[^>]*>.*?<b class="kr-stat-n">21</b>', c), "전체 = 합(12+2+1+1+3+2)"
  assert re.search(r'data-kr-stat="filled".*?<b class="kr-stat-n">12</b>.*?FILLED', c)
  assert re.search(r'data-kr-stat="open".*?<b class="kr-stat-n">2</b>', c) and re.search(r'data-kr-stat="check".*?<b class="kr-stat-n">1</b>.*?UNKNOWN · LOST', c)
  assert re.search(r'data-kr-stat="other".*?<b class="kr-stat-n">2</b>', c)
  assert 'data-kr-stat="other"' not in out["cardsNoOther"] and out["cardsNoOther"].count("<li ") == 6
  assert out["notes"][0] == "방향 · 기간 · 검색어 조건에 맞는 내 주문의 건수입니다"
  assert "상태 조건은 뺀 숫자" in out["notes"][1] and "2,000건" in out["notes"][1]
  pm = out["pagerMid"]
  assert "data-kr-prev>" in pm and "data-kr-next>" in pm and "2 / 4 쪽 · 51–100번째 · 총 193건" in pm, "가운데 쪽은 이전 · 다음 모두 눌린다"
  assert '<option value="50" selected>50건</option>' in pm and '<option value="20">20건</option>' in pm and '<option value="100">100건</option>' in pm
  assert "data-kr-prev disabled" in out["pagerFirst"] and "data-kr-next disabled" in out["pagerFirst"] and "1 / 1 쪽 · 1–5번째 · 총 5건" in out["pagerFirst"]
  assert "<tbody></tbody>" in out["empty"]
  assert out["num"] == ["1,234,567", "70,950.5", "0.13", "-", "-", "-1,234.5", "-"]
  assert out["code"] == ["005930", "000660", "AAPL", ""]


def test_empty_states(tmp_path):
  """TC-KR-06 — 필터 없이 0건: 까닭 + 다음 행동(자동매매 현황 링크 · 마이페이지) · 조건이 있으면 조건 지우기 단추 · 오류는 role=alert 와 이스케이프."""
  out = _run(tmp_path, """
    out.none = kr.krEmptyHtml("none", esc);
    out.filtered = kr.krEmptyHtml("filtered", esc);
    out.err = kr.krErrorHtml("<img src=x onerror=1>", esc);
    out.errDefault = kr.krErrorHtml("", esc);
    out.shell = kr.krShellHtml(esc);
  """)
  n = out["none"]
  assert "아직 내 KIS 모의투자 주문이 없습니다" in n and 'href="#quant-auto"' in n and 'href="#mypage"' in n and "data-kr-reset" not in n
  f = out["filtered"]
  assert "조건에 맞는 주문이 없습니다" in f and "data-kr-reset" in f and "href=" not in f
  assert 'role="alert"' in out["err"] and "&lt;img" in out["err"] and "<img" not in out["err"] and "다시 시도" in out["errDefault"]
  s = out["shell"]
  assert "모의투자 계좌 기준" in s and "실거래 주문이 아니며" in s, "머리에서 실거래로 읽히지 않게"
  assert "교육 · 연습용이며 투자 권유가 아닙니다 · 주문은 모의 계좌로만" in s, "고지 한 줄은 learnnotice.js 의 NOTICE_LINE"
  for name in ("status", "side", "dateFrom", "dateTo", "q"):
    assert f'name="{name}"' in s, name
  assert 'maxlength="80"' in s and 'type="date"' in s and 'type="search"' in s
  assert "data-kr-csv" in s and "data-kr-refresh" in s and "data-kr-reset" in s and 'aria-live="polite"' in s
  assert s.count("<label") == s.count("</label>") == 5, "입력칸은 모두 label 로 감싼다"
  assert 'value="PENDING,ACCEPTED,PARTIALLY_FILLED,CANCEL_REQUESTED">접수 · 대기' in s and 'value="UNKNOWN,LOST">확인 필요' in s


def test_source_rules():
  """TC-KR-07 — 소스 규칙: owner=me 한 곳 · 모니터 API · 쓰기 요청 · 새 그리드 부품 · 브라우저 저장소 · 절대 경로 import · 투자 권유 낱말 없음."""
  src = KR.read_text(encoding="utf-8")
  code = "\n".join(line for line in src.splitlines() if not line.strip().startswith(("//", "*", "/*")))   # 주석은 빼고 코드만 본다
  assert re.search(r'^const KR_OWNER = "me";', src, re.M) and 'p.set("owner", KR_OWNER)' in src
  assert len(re.findall(r"owner", code)) <= 4, "owner 는 상수 정의와 질의 한 곳에서만"
  apis = set(re.findall(r"/api/[A-Za-z0-9_/\-]+", code))
  assert apis == {"/api/quant/kis/orders"}, apis
  for banned in ("/monitor", "/holdings", "/batch", "/cancel", "/retry", "owner=all", "owner=batch", "method:", "POST", "DELETE", "PUT", "PATCH",
                 "fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "indexedDB", "agGrid", "ag-grid", "AG Grid", "createGrid", "new Function"):
    assert banned not in src, f"kis-results.js 에 {banned}"
  assert re.findall(r'^import .*? from "([^"]+)"', src, re.M) == ["./learnnotice.js"], "맨 위 import 는 상대 경로 하나(node 가 그대로 불러야 한다)"
  assert "NOTICE_LINE" in src
  for word in ("추천", "유망", "수익 보장", "사세요", "파세요"):
    assert word not in src, word
  # 모듈 맨 위에서 document 를 만지지 않는다 — 들여쓰지 않은 줄에 document 가 없다
  assert not [line for line in src.splitlines() if line.startswith("document") or re.match(r"^(const|let|var) .*\bdocument\b", line)]
  # IP · 브라우저 칸 금지
  for personal in ("client_ip", "user_agent", "actor", "owner_label"):
    assert personal not in src, personal
  css = KR_CSS.read_text(encoding="utf-8")
  for banned in ("ag-", "agGrid", "@import"):
    assert banned not in css, banned


def test_screen_is_wired():
  """TC-KR-08 — 메뉴(퀀트자동매매 · 자동매매 현황 바로 다음) · 사용법 글 · 화면 칸 · CSS 링크 · 진입 훅 · 좁은 화면 규칙이 한 줄씩 이어져 있다."""
  core, html, main = _read("js/core.js"), _read("app.html"), _read("js/main.js")
  quant = core[core.index("\n  quant: {"):]
  quant = quant[:quant.index("\n  },")]
  keys = re.findall(r'\{ key: "([^"]+)"', quant)
  assert keys[:3] == ["quant-dashboard", "quant-auto", "kis-results"], keys
  assert re.search(r'\{ key: "kis-results",\s+icon: "fa-solid fa-receipt",\s+label: "KIS 모의투자 결과" \},', quant)
  guide = re.search(r'"kis-results":\s+\{ summary: "([^"]+)", steps: \[(.+?)\], relatedTerms: \[([^\]]*)\] \},', core)
  assert guide, "사용법 글"
  guide_text = guide.group(1) + guide.group(2)
  assert "실시간" not in guide_text and "모의투자 계좌" in guide_text and "실거래 주문이 아닙니다" in guide_text
  assert re.findall(r'"(\w+)"', guide.group(3)) == ["paper_trading", "broker_api"]
  assert html.count('data-view="kis-results"') == 1 and html.count('id="kr-root"') == 1
  assert '<div class="view" data-view="kis-results">' in html
  block = html[html.index('data-view="kis-results"'):]
  block = block[:block.index('data-view="quant-backtest"')]
  assert "<style" not in block and "<script" not in block and "onclick" not in block and "onsubmit" not in block
  assert html.index('data-view="quant-auto"') < html.index('data-view="kis-results"') < html.index('data-view="quant-backtest"')
  assert '<link rel="stylesheet" href="/css/kis-results.css" />' in html and KR_CSS.is_file()
  assert 'import { onKisResultsViewActivated } from "/js/kis-results.js";' in main
  assert re.search(r'if \(view === "kis-results"\) onKisResultsViewActivated\(\{ api \}\);', main), "api 는 main.js 가 넘긴다"
  css = KR_CSS.read_text(encoding="utf-8")
  assert re.search(r"\.kr-table-wrap\s*\{[^}]*overflow-x:\s*auto", css), "표 칸만 좌우 스크롤"
  assert re.search(r"\.kr-root\s*\{[^}]*min-width:\s*0", css) and re.search(r"\.kr-card\s*\{[^}]*min-width:\s*0", css), "쪽 전체가 넘치지 않게"
  assert "@media (max-width: 640px)" in css
  # 글자색은 토큰만(옅은 하드코딩 회색 없음) — 방향 색 둘과 상태 배지 색은 대비를 따로 잰 값이다
  assert not re.search(r"color:\s*#(?:94a3b8|cbd5e1|9ca3af|d1d5db|a1a1aa|e2e8f0)", css, re.I)
  assert "var(--text-mute)" in css


def test_view_scan_sees_only_orders_api():
  """TC-KR-09 — 화면 스캐너(view_scan)는 함수를 이름으로 잇는다 — 진입 API 는 orders 읽기 하나, 조작 API 는 없다(쓰기 없음)."""
  from scripts import view_scan

  row = next(r for r in view_scan.scan()["rows"] if r["key"] == "kis-results")
  assert row["gnb"] == "quant" and row["hook"] == ["onKisResultsViewActivated"] and row["guide"] is True
  assert row["entry_apis"] == ["/api/quant/kis/orders"], row["entry_apis"]
  assert row["action_apis"] == [], row["action_apis"]


FAKE_DOM = r"""
const calls = [];
const listeners = { host: {}, form: {} };
const stub = (name) => ({ name, innerHTML: "", textContent: "", attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; } });
const els = {};
const formEls = { status: { value: "" }, side: { value: "" }, dateFrom: { value: "" }, dateTo: { value: "" }, q: { value: "" } };
const form = { elements: formEls, reset() { for (const e of Object.values(formEls)) e.value = ""; },
               addEventListener(t, f) { listeners.form[t] = f; } };
const host = {
  innerHTML: "", attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; },
  querySelector(sel) { if (sel === "[data-kr-form]") return form; return (els[sel] ??= stub(sel)); },
  addEventListener(t, f) { (listeners.host[t] ??= []).push(f); },
  contains() { return true; },
};
const button = (attr, extra = {}) => ({ disabled: false, textContent: "단추", hasAttribute: (a) => a === attr, ...extra });
const click = (b) => listeners.host.click.forEach((f) => f({ target: { closest: () => b } }));
const settle = async (ms = 30) => { await new Promise((r) => setTimeout(r, ms)); };
// 서버 흉내 — 합계 total 건을 offset/limit 으로 나눠 준다. status 가 있으면 FILLED 만 남은 것처럼 total 을 줄인다
const fakeApi = (totalAll, totalFilled) => async (...args) => {
  calls.push(args);
  const url = new URL("http://x" + args[0]);
  const p = url.searchParams;
  const total = p.get("status") ? totalFilled : totalAll;
  const off = Number(p.get("offset")), lim = Number(p.get("limit"));
  const rows = [];
  for (let i = off; i < Math.min(total, off + lim); i++) rows.push({ id: "id" + i, created_at: "2026-11-04T06:30:21+00:00", symbol: "005930", name: "삼성전자", side: "BUY", order_type: "LIMIT",
                                                                  quantity: 1, price: 70000, filled_quantity: 1, avg_filled_price: 70000, status: "FILLED", order_no: "N" + i, environment: "paper", message: "" });
  return { total, offset: off, limit: lim, truncated: false, counts_by_status: p.get("status") ? { FILLED: totalFilled } : { FILLED: totalFilled, REJECTED: totalAll - totalFilled }, rows };
};
const saved = [];
globalThis.URL.createObjectURL = (b) => { saved.push(b); return "blob:fake"; };
globalThis.URL.revokeObjectURL = () => {};
globalThis.document = { createElement: () => ({ style: {}, click() { saved.at(-1).__name = this.download; }, remove() {} }), body: { appendChild() {} } };
"""


def test_screen_behavior_with_fake_dom(tmp_path):
  """TC-KR-10 — 화면 동작(가짜 DOM): 처음 요청은 owner=me 한 번 · 상태로 거르면 카드용 질의를 따로(상태 뺌, 1건) · 쪽 이동은 offset · 쪽당 건수 바꾸면 첫 쪽 ·
  조건 없는 0건은 빈 상태 · CSV 는 500건씩 받아 합치고 BOM · 모든 요청은 경로만(읽기)."""
  out = _run(tmp_path, FAKE_DOM + r"""
    const now = () => new Date("2026-11-04T06:30:00Z");
    // ① 처음 읽기
    let api = fakeApi(93, 40);
    let ctl = kr.mountKisResults(host, { api, esc, now });
    await ctl.krReload(); await settle();
    out.first = { calls: calls.map((c) => c[0]), list: els["[data-kr-list]"].innerHTML, result: els["[data-kr-result]"].textContent, pager: els["[data-kr-pager]"].innerHTML,
                  cards: els["[data-kr-cards]"].innerHTML, note: els["[data-kr-cards-note]"].textContent };
    // ② 다음 쪽
    calls.length = 0; click(button("data-kr-next")); await settle();
    out.next = { calls: calls.map((c) => c[0]), pager: els["[data-kr-pager]"].innerHTML };
    // ③ 쪽당 건수 50 → 첫 쪽으로
    calls.length = 0; listeners.host.change.forEach((f) => f({ target: { closest: () => ({ value: "50" }) } })); await settle();
    out.size = calls.map((c) => c[0]);
    // ④ 상태로 거르기 — 카드용 질의가 따로 한 번
    calls.length = 0; formEls.status.value = "FILLED"; listeners.form.change({ target: { name: "status" } }); await settle();
    out.status = { calls: calls.map((c) => c[0]), cards: els["[data-kr-cards]"].innerHTML, note: els["[data-kr-cards-note]"].textContent, result: els["[data-kr-result]"].textContent };
    // ⑤ 날짜가 거꾸로면 요청 없이 까닭
    calls.length = 0; formEls.dateFrom.value = "2026-11-05"; formEls.dateTo.value = "2026-11-04"; listeners.form.change({ target: { name: "dateFrom" } }); await settle();
    out.badDates = { calls: calls.length, result: els["[data-kr-result]"].textContent };
    // ⑥ 다시 마운트(앞 마운트의 처리기가 같은 단추 객체를 먼저 건드리지 않게 비운다) — 1200건 CSV 를 500 · 500 · 200 으로
    form.reset(); listeners.host = {}; listeners.form = {};
    api = fakeApi(1200, 1200); ctl = kr.mountKisResults(host, { api, esc, now }); calls.length = 0; saved.length = 0;
    await ctl.krReload(); await settle(); calls.length = 0;
    click(button("data-kr-csv", { textContent: "CSV 내려받기" })); await settle(100);
    const blob = saved.at(-1);
    out.csv = { calls: calls.map((c) => c[0]), args: [...new Set(calls.map((c) => c.length))], name: blob && blob.__name, text: blob ? await blob.text() : "",
                bom: blob ? [...new Uint8Array(await blob.arrayBuffer()).slice(0, 3)] : [], type: blob && blob.type };   // Blob.text() 는 BOM 을 떼므로 바이트로 본다
    // ⑦ 내 주문이 하나도 없고 조건도 없음
    listeners.host = {}; listeners.form = {};
    calls.length = 0; ctl = kr.mountKisResults(host, { api: fakeApi(0, 0), esc, now }); await ctl.krReload(); await settle();
    out.empty = els["[data-kr-list]"].innerHTML;
    // ⑧ 서버 오류
    ctl = kr.mountKisResults(host, { api: async () => { throw new Error("서버 오류 500"); }, esc, now }); await ctl.krReload(); await settle();
    out.error = els["[data-kr-list]"].innerHTML;
  """)
  f = out["first"]
  assert f["calls"] == ["/api/quant/kis/orders?owner=me&limit=20&offset=0"], "처음에는 내 주문 첫 쪽 한 번만"
  assert f["list"].count("<tr>") == 1 + 20 and "검색 결과 93건" in f["result"] and "2026-11-04 15:30:00 (KST)" in f["result"]
  assert "1 / 5 쪽 · 1–20번째 · 총 93건" in f["pager"] and "data-kr-prev disabled" in f["pager"]
  assert re.search(r'data-kr-stat="all".*?<b class="kr-stat-n">93</b>', f["cards"]) and "상태 조건은 뺀" not in f["note"]
  assert out["next"]["calls"] == ["/api/quant/kis/orders?owner=me&limit=20&offset=20"] and "2 / 5 쪽 · 21–40번째" in out["next"]["pager"]
  assert out["size"] == ["/api/quant/kis/orders?owner=me&limit=50&offset=0"], "쪽당 건수를 바꾸면 첫 쪽부터"
  s = out["status"]
  assert s["calls"] == ["/api/quant/kis/orders?owner=me&status=FILLED&limit=50&offset=0", "/api/quant/kis/orders?owner=me&limit=1&offset=0"], s["calls"]
  assert re.search(r'data-kr-stat="all".*?<b class="kr-stat-n">93</b>', s["cards"]), "카드는 상태 조건을 뺀 전체"
  assert "상태 조건은 뺀 숫자" in s["note"] and "검색 결과 40건" in s["result"]
  assert out["badDates"] == {"calls": 0, "result": "시작일은 종료일보다 앞서야 합니다."}
  c = out["csv"]
  assert c["calls"] == ["/api/quant/kis/orders?owner=me&limit=500&offset=0", "/api/quant/kis/orders?owner=me&limit=500&offset=500", "/api/quant/kis/orders?owner=me&limit=500&offset=1000"]
  assert c["args"] == [1], "api 에는 경로만 넘긴다(방법 · 본문 없음 = 읽기)"
  assert c["name"] == "kis-my-orders-2026-11-04.csv"
  assert c["bom"] == [0xEF, 0xBB, 0xBF] and c["type"] == "text/csv;charset=utf-8", "파일 맨 앞 UTF-8 BOM"
  assert c["text"].count("\r\n") == 1200 and c["text"].count("N1199") == 1 and c["text"].count('"N0"') == 1, "머리 + 1200행 — 쪽 경계(500 · 1000)에서 겹치거나 빠지지 않는다"
  assert "아직 내 KIS 모의투자 주문이 없습니다" in out["empty"] and 'href="#quant-auto"' in out["empty"]
  assert "주문 기록을 불러오지 못했습니다" in out["error"] and "서버 오류 500" in out["error"]
