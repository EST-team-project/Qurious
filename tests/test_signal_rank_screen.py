"""TC-RKS — 신호 기록 순위 화면 판단 모듈(public/js/signal-rank.js) · 2026-10-29 · 할 일 ②-19

설계서(신호순위-화면설계.md v0.1 · 팀 검토 전)의 「검토로 뒤집히지 않는 부분」 만 지킨다. 붙는 자리(탭 / 새 화면)는 아직 없다.
1. 순위 줄 — 근거 개수 글은 counts 합 그대로 · counts 가 없으면(낯선 근거 문장) 개수를 비우고 서버 까닭을 보존 · 기준일은 MM-DD ·
   모르는 값은 줄표(0 으로 메우지 않는다). (TC-RKS-01)
2. 가격 두 줄 — 신호 기준 종가는 선택한 행의 as_of 날짜 줄만(없으면 확인 불가) · 지금 가격을 못 받으면 종가를 그 칸에 대신 넣지 않고 서버 까닭을 보인다 · 종가에는 항상 날짜가 붙고
   신호 기준일과 다르면 그 사실을 말한다 · 출처 글은 quote.label 그대로. (TC-RKS-02)
3. 비어 있음 갈래 — 줄이 0 이면 안내 글과 missing 의 서버 문장을 그대로 · explain 404 는 서버의 한국어 까닭 그대로. (TC-RKS-03)
4. 서랍은 문장을 짓지 않는다 — summary · reasons · counter_reasons · notes · disclaimer 를 그대로 그리고, 응답에 없는 숫자가
   서랍 글에 나오지 않는다 · HTML 은 이스케이프된다. (TC-RKS-04)
5. 화면 파일에 BUY · SELL 낱말이 없다(규칙 표시이지 매매 권유가 아니다) · 공용 파일(app.html · core.js)은 아직 안 고쳤다. (TC-RKS-05)
6. 서랍의 「관련 최신 뉴스」 — 허브 news 칸을 그대로(제목 · 출처 · 날짜 · 원문 링크만 · http(s) 만 링크 · 5건까지 · 서버 note 는 늘 보임 ·
   없거나 못 받으면 서버 까닭). (TC-RKS-06)
7. 표 위 정렬 기준 · 중립/관망 안내 · 근거 주기 · 요약 위치 · 근거 개수 정의 — 오준영 님 #373 답. (TC-RKS-07)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SR = ROOT / "public" / "js" / "signal-rank.js"

ESC = ('const esc = s => String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")'
       '.replace(/"/g,"&quot;").replace(/\'/g,"&#39;");')


def _run(tmp_path: Path, body: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
    script = tmp_path / "run.mjs"
    script.write_text(f'import * as sr from "{SR.resolve().as_uri()}";\n{ESC}\nconst out = {{}};\n{body}\n'
                      "process.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
    done = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_rank_row_view(tmp_path):
    """TC-RKS-01 — 근거 개수는 counts 합 · counts 없음은 개수를 비우고 까닭 보존 · 모르는 값은 줄표."""
    out = _run(tmp_path, """
      out.ok = sr.rowView({rank: 1, symbol: "005930", as_of: "2026-10-26", signal: "매수", strength: "강",
                           composite: 2.345, confidence: 0.667, counts: {buy: 3, neutral: 1, sell: 1}}, s => "삼성전자");
      out.odd = sr.rowView({rank: 2, symbol: "000660", as_of: "2026-10-26", signal: "관망",
                            counts: null, counts_note: "낯선 근거 문장"}, null);
      out.unknown = sr.rowView({rank: 3, symbol: "x", as_of: "", signal: null, composite: null, confidence: null, counts: null}, null);
    """)
    assert out["ok"]["countsText"] == "근거 5개 (매수 쪽 3 · 중립 1 · 매도 쪽 1)"
    assert out["ok"]["asOf"] == "10-26" and out["ok"]["signal"] == "매수 쪽" and out["ok"]["name"] == "삼성전자"
    assert out["ok"]["composite"] == "2.35" and out["ok"]["confidence"] == "67%"
    assert out["odd"]["countsText"] == "근거 개수를 셀 수 없습니다" and out["odd"]["countsNote"] == "낯선 근거 문장"   # 0개로 두지 않는다
    assert out["odd"]["signal"] == "관망"                       # 서버 글 그대로
    assert out["unknown"]["asOf"] == "—" and out["unknown"]["composite"] == "—" and out["unknown"]["signal"] == "—"


def test_price_lines_never_substitute(tmp_path):
    """TC-RKS-02 — 신호 기준 종가는 선택한 행의 as_of 날짜 줄만 · 그날 줄이 없으면 확인 불가(마지막 종가로 대신하지 않음) ·
    지금 가격을 못 받아도 종가를 대신 넣지 않는다 · 출처 글은 quote.label 그대로."""
    out = _run(tmp_path, """
      const day = {basis: "raw", rows: [{trade_date: "2026-10-26", close: 72300}]};
      out.both = sr.priceLines(day, {price: 73100, label: "증권사 연계 조회 · 14:02"}, "2026-10-26");
      out.noQuote = sr.priceLines(day, {price: null, label: "지금 가격을 받지 못했습니다", fallback: "증권사 키 없음"}, "2026-10-26");
      out.noQuoteAtAll = sr.priceLines(day, null, "2026-10-26");
      out.otherDay = sr.priceLines({basis: "raw", rows: [{trade_date: "2026-10-28", close: 75000}]}, null, "2026-10-26");   // 다른 날 줄만 있다
      out.emptyRows = sr.priceLines({basis: "raw", rows: []}, null, "2026-10-26");
      out.failed = sr.priceLines(null, null, "2026-10-26", "서버에 연결할 수 없습니다.");
      out.adj = sr.priceLines({basis: "adj_base", rows: [{trade_date: "2026-10-26", close: 72300}]}, null, "2026-10-26");
      out.code = [sr.ohlcvCode("005930"), sr.ohlcvCode("005930.KS"), sr.ohlcvCode("0000d0"), sr.ohlcvCode("AAPL"), sr.ohlcvCode("../x"), sr.ohlcvCode("")];
    """)
    assert out["both"]["close"]["text"] == "신호 기준 종가(10-26) 72,300원" and out["both"]["close"]["note"] == "수정하지 않은 종가"
    assert out["both"]["quote"]["text"] == "지금 가격 73,100원" and out["both"]["quote"]["note"] == "증권사 연계 조회 · 14:02"
    assert out["noQuote"]["quote"]["ok"] is False and "72,300" not in out["noQuote"]["quote"]["text"] + out["noQuote"]["quote"]["note"]
    assert out["noQuote"]["quote"]["note"] == "증권사 키 없음"
    assert out["noQuoteAtAll"]["quote"]["text"] == "지금 가격을 받지 못했습니다"
    # 그날 줄이 없으면 다른 날 종가(75,000)로 대신하지 않고 확인 불가
    assert out["otherDay"]["close"]["ok"] is False and "75,000" not in out["otherDay"]["close"]["text"] + out["otherDay"]["close"]["note"]
    assert out["otherDay"]["close"]["text"] == "신호 기준 종가(10-26) 확인 불가" and out["otherDay"]["close"]["note"] == "이 날짜의 일봉이 없습니다."
    assert out["emptyRows"]["close"]["ok"] is False and out["failed"]["close"]["note"] == "서버에 연결할 수 없습니다."
    assert out["adj"]["close"]["note"] == "수정 방식 adj_base"
    assert out["code"] == ["005930", "005930", "0000D0", "", "", ""]


def test_empty_and_failure_texts(tmp_path):
    """TC-RKS-03 — 줄 0 이면 안내 + missing 서버 문장 그대로 · explain 404 는 서버 까닭 그대로."""
    out = _run(tmp_path, """
      out.empty = sr.renderRankTable({rows: [], missing: [{symbol: "123456", reason: "none", message: "아직 이 종목의 다중 주기 신호 기록이 없습니다."}],
                                      on: "2026-10-26", total: 0, notice: "참고용"}, esc);
      out.notFound = sr.drawerFailText({status: 404, message: "신호 기록 없음: 123456 · 지금까지"});
      out.expired = sr.drawerFailText({status: 401});
      out.offline = sr.drawerFailText({status: 0});
    """)
    assert "신호 기록이 아직 없습니다" in out["empty"]
    assert "아직 이 종목의 다중 주기 신호 기록이 없습니다." in out["empty"]
    assert out["notFound"] == "신호 기록 없음: 123456 · 지금까지"
    assert "로그인" in out["expired"] and "연결" in out["offline"]


def test_drawer_does_not_invent_sentences(tmp_path):
    """TC-RKS-04 — 서랍 글의 숫자는 모두 응답 값 · 문장은 응답 그대로 · HTML 은 이스케이프."""
    out = _run(tmp_path, """
      const ex = {symbol: "005930", as_of: "2026-10-26", summary: "일봉 기준으로 5일선이 20일선 위라 매수 쪽입니다.",
                  confidence_text: "주기 셋 중 둘이 매수 쪽 · 기운 정도 보통",
                  reasons: [{label: "일봉", text: "5일선이 20일선 위", observed: "5일선 72,100 · 20일선 70,900"}],
                  counter_reasons: [{label: "주봉", text: "RSI 71 과열권"}],
                  notes: ["주봉은 이번 주가 끝나지 않았습니다."], disclaimer: "과거 자료 기준 참고용입니다 <script>x</script>"};
      const prices = sr.priceLines({basis: "raw", rows: [{trade_date: "2026-10-26", close: 72300}]}, {price: 73100, label: "증권사 연계 조회 · 14:02"}, ex.as_of);
      out.html = sr.renderDrawer(ex, prices, esc, {name: "삼성전자"});
      out.src = JSON.stringify(ex) + JSON.stringify(prices) + "삼성전자";
    """)
    html = out["html"]
    text = re.sub(r"<[^>]+>", " ", html)
    allowed = set(re.findall(r"\d[\d,.]*", out["src"]))
    # 서랍 글(태그 뺀)의 숫자는 응답 · 가격 값에서 온 것만 — MM-DD 는 as_of 의 일부
    for n in re.findall(r"\d[\d,.]*", text):
        assert n.strip(".,") in {a.strip(".,") for a in allowed} | {"10", "26"}, n
    for must in ("일봉 기준으로 5일선이 20일선 위라 매수 쪽입니다.", "주기 셋 중 둘이 매수 쪽", "RSI 71 과열권", "주봉은 이번 주가 끝나지 않았습니다."):
        assert must in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_news_under_evidence(tmp_path):
    """TC-RKS-06 — 서랍의 「관련 최신 뉴스」(2026-10-29 제안) — 허브 news 칸을 그대로: 제목 · 출처 · 날짜 · 원문 링크만 ·
    http(s) 만 링크 · 제목은 이스케이프 · 5건까지 · 서버의 note 는 늘 보이고 · 기사가 없거나 못 받았으면 서버 까닭을 보인다."""
    out = _run(tmp_path, """
      const mk = (i, url) => ({title: `기사 ${i} <b>x</b>`, url, source: "gdelt", source_label: "언론사 기사 제목(GDELT)", published: `2026-10-2${i}T09:00:00+09:00`});
      const ok = {status: "ok", note: "종목 이름표는 규칙으로 붙였습니다 — 이름이 같은 다른 뜻의 기사가 섞일 수 있습니다.",
                  source: "정책브리핑 정책뉴스 · 언론사 기사 제목(GDELT) — 본문은 원문 링크로",
                  data: {items: [mk(1, "https://example.com/a"), mk(2, "javascript:alert(1)"), mk(3, "http://example.com/c"),
                                 mk(4, "https://example.com/d"), mk(5, "https://example.com/e"), mk(6, "https://example.com/f"), mk(7, "https://example.com/g")]}};
      out.ok = sr.renderNews(ok, esc);
      out.empty = sr.renderNews({status: "empty", reason: "이 종목 이름이 붙은 기사를 찾지 못했습니다.", note: "이름이 같은 다른 뜻의 기사가 섞일 수 있습니다.", data: {items: []}}, esc);
      out.error = sr.renderNews({status: "error", reason: "지금은 읽지 못했습니다.", data: null}, esc);
      out.none = sr.renderNews(null, esc);
      out.ymd = [sr.ymd("2026-10-28T09:00:00+09:00"), sr.ymd(""), sr.ymd("어제")];
      out.safe = [sr.safeHttpUrl("https://a.b"), sr.safeHttpUrl("javascript:1"), sr.safeHttpUrl("//a.b"), sr.safeHttpUrl(null)];
    """)
    ok = out["ok"]
    assert ok.count("<li>") == 5 and "기사 6" not in ok and "기사 7" not in ok          # 5건까지
    assert 'href="https://example.com/a"' in ok and 'href="http://example.com/c"' in ok
    assert "javascript:" not in ok                                                       # 위험한 주소는 링크가 아니다
    assert "기사 2 &lt;b&gt;x&lt;/b&gt;" in ok and "<b>x</b>" not in ok                  # 제목 이스케이프(링크 없는 줄도)
    assert 'rel="noopener noreferrer"' in ok and 'target="_blank"' in ok
    assert "2026-10-21" in ok and "언론사 기사 제목(GDELT)" in ok                        # 날짜(연도까지) · 출처
    assert "이름이 같은 다른 뜻의 기사가 섞일 수 있습니다" in ok and "본문은 원문 링크로" in ok   # 서버 글 그대로
    assert "이 종목 이름이 붙은 기사를 찾지 못했습니다." in out["empty"] and "섞일 수 있습니다" in out["empty"] and "<li>" not in out["empty"]
    assert "지금은 읽지 못했습니다." in out["error"] and "뉴스를 받지 못했습니다." in out["none"]
    assert out["ymd"] == ["2026-10-28", "—", "—"] and out["safe"] == ["https://a.b", "", "", ""]
    src = SR.read_text(encoding="utf-8")
    assert "sections=news" in src and "sections=price" not in src and "renderNews(news, esc)" in src   # 서랍은 허브에서 뉴스 칸만(종가는 as_of 줄 — 마지막 종가를 쓰지 않는다)
    assert "/api/data/ohlcv?symbol=" in src and "&basis=raw" in src


def test_rank_table_header_and_drawer_order(tmp_path):
    """TC-RKS-07 — 오준영 님 #373 답: 표 위에 「기록된 종합 점수 순」 + 정렬 기준 + 추천 아님 · 「중립」 과 「관망」 구분 안내 ·
    근거마다 주기 · 한 줄 요약이 서랍 맨 위(차트 자리 위) · 서랍에도 근거 개수(counts 합) · 서버 정렬 설명과 같은 기준."""
    out = _run(tmp_path, """
      out.table = sr.renderRankTable({rows: [{rank: 1, symbol: "005930", as_of: "2026-10-26", signal: "매수", composite: 2.1, confidence: 0.6,
                                              counts: {buy: 3, neutral: 1, sell: 1}},
                                             {rank: 2, symbol: "000660", as_of: "2026-10-26", signal: "관망", composite: 0.2, confidence: 0.3,
                                              counts: null, counts_note: "낯선 근거 문장"}],
                                     missing: [], on: "2026-10-26", total: 401, notice: "참고용"}, esc);
      const ex = {symbol: "005930", as_of: "2026-10-26", summary: "일봉 기준으로 매수 쪽입니다.", confidence_text: "주기 셋 중 둘이 매수 쪽",
                  reasons: [{label: "일봉", text: "5일선이 20일선 위"}, {label: "주봉", text: "RSI 55"}],
                  counter_reasons: [{label: "60분봉", text: "종가가 하단 아래"}], notes: [], disclaimer: "참고용"};
      out.drawer = sr.renderDrawer(ex, sr.priceLines(null, null, ex.as_of), esc, {counts: "근거 5개 (매수 쪽 3 · 중립 1 · 매도 쪽 1)"});
      out.order = sr.RANK_ORDER_NOTE; out.help = sr.NEUTRAL_HELP;
    """)
    t, d = out["table"], out["drawer"]
    assert out["order"] in t and "추천 순위가 아닙니다" in out["order"] and "종합 점수 → 신뢰도 → 종목코드" in out["order"]
    assert out["help"] in t and "「중립」" in out["help"] and "「관망」" in out["help"] and "자료 부족이나 계산 실패가 아닙니다" in out["help"]
    assert "판단 보류" not in t + d                                                       # 자료 부족 · 계산 실패로 읽히는 말은 쓰지 않는다
    assert "근거 개수를 셀 수 없습니다" in t and "낯선 근거 문장" in t                       # 못 세면 0개가 아니라 안내
    assert "근거 5개 (매수 쪽 3 · 중립 1 · 매도 쪽 1)" in t
    assert d.index("일봉 기준으로 매수 쪽입니다.") < d.index("신호 기준 종가") < d.index("data-sr-chart") < d.index("[일봉]")   # 요약 → 가격 → 차트 자리 → 근거
    assert "[일봉]" in d and "[주봉]" in d and "[60분봉]" in d                              # 근거마다 주기
    assert "근거 5개 (매수 쪽 3 · 중립 1 · 매도 쪽 1)" in d
    # 정렬 기준 문구가 서버 설명과 같은 기준(종합 점수 → 신뢰도 → 종목코드)인지 — 서버가 바뀌면 이 시험이 알린다
    from app.services import stock_hub
    assert "종합 점수 → 신뢰도 → 종목코드" in stock_hub.SIGNAL_RANK_NOTE


def test_source_rules():
    """TC-RKS-05 — BUY · SELL 낱말 없음 · 공용 파일은 아직 이 모듈을 부르지 않는다."""
    src = SR.read_text(encoding="utf-8")
    assert not re.search(r"\b(BUY|SELL)\b", src)
    for shared in ("public/app.html", "public/js/core.js"):
        assert "signal-rank" not in (ROOT / shared).read_text(encoding="utf-8"), shared
