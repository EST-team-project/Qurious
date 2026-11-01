"""보고식 알림 렌더러 시험 (TC-AF) — DB · 네트워크 없이 채널별 모양 · 한도 · 이스케이프를 확인한다."""
import json
from datetime import datetime, timezone

from app.services import alert_format as af


def _ev(**kw) -> af.AlertEvent:
    base = dict(
        kind="auto_fill", title="자동매매 매수 가상 체결", summary="삼성전자 10주 × 70,000원", severity="normal",
        fields=[("종목", "삼성전자 (005930)"), ("수량", "10주"), ("체결가", "70,000원")],
        reason="MA 교차 신호", risk="일손실 한도 사용률 12%", next_action="설정 화면에서 확인",
        mock=True, ts=datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc),
    )
    base.update(kw)
    return af.AlertEvent(**base)


def test_af01_plain_kst_and_footer():
    """시각은 KST 고정 오프셋(UTC 12:00 → 21:00), 모의투자면 가상 자금 문구가 푸터에 들어간다."""
    text = af.render_plain(_ev())
    assert "2026-11-01 21:00:00 KST" in text
    assert "모의투자(가상 자금)" in text
    assert "이유: MA 교차 신호" in text and "다음 행동:" in text
    assert "투자 권유가 아닙니다" in af.render_plain(_ev(mock=False))


def test_af02_telegram_escapes_values_not_template():
    """외부 글의 `<` `&` 는 이스케이프하고, 틀의 <b> 태그는 살린다 — 텔레그램 400 방지."""
    out = af.render_telegram(_ev(reason="<script>alert(1)</script> & 오류 <b", summary="a<b"))
    assert "<script>" not in out and "&lt;script&gt;" in out and "&amp;" in out
    assert "<b>자동매매 매수 가상 체결</b>" in out
    assert "a&lt;b" in out


def _tag_balanced(html_text: str) -> bool:
    import re
    for tag in ("b", "i", "blockquote"):
        if len(re.findall(rf"<{tag}[ >]", html_text)) != html_text.count(f"</{tag}>"):
            return False
    return not re.search(r"&(?!amp;|lt;|gt;)", html_text)   # 이스케이프가 반으로 갈린 `&` 가 없다


def test_af03_telegram_limit_and_expandable():
    out = af.render_telegram(_ev(fields=[(f"항목{i}", "가" * 300) for i in range(40)]))
    assert len(out) <= 4096 and _tag_balanced(out)           # 한도에서 항목을 빼도 태그 짝 · 이스케이프가 온전하다
    # 이유 · 위험이 길고 `&` `<` 가 많아도(이스케이프하면 글이 늘어남) 한도 안이고 깨지지 않는다
    nasty = af.render_telegram(_ev(reason="<&>" * 3000, risk="&" * 3000, fields=[]))
    assert len(nasty) <= 4096 and _tag_balanced(nasty)
    legacy = af.render_telegram(af.legacy_event("&<" * 4000, html_message="<b>" + "&amp;" * 2000 + "</b>"))
    assert len(legacy) <= 4096 and _tag_balanced(legacy)
    long = af.render_telegram(_ev(reason="길" * 500))
    assert "<blockquote expandable>" in long and long.count("<blockquote expandable>") == 1
    assert "<blockquote" not in af.render_telegram(_ev())   # 짧으면 접지 않는다


def test_af04_discord_embed_limits():
    ev = _ev(title="제" * 400, summary="요" * 6000, fields=[(f"항목{i}", "값" * 2000) for i in range(40)])
    emb = af.render_discord(ev)["embeds"][0]
    assert len(emb["title"]) <= 256 and len(emb["description"]) <= 4096
    assert len(emb["fields"]) <= 25 and all(len(f["value"]) <= 1024 for f in emb["fields"])
    total = (len(emb["title"]) + len(emb["description"]) + len(emb["footer"]["text"])
             + sum(len(f["name"]) + len(f["value"]) for f in emb["fields"]))
    assert total <= 6000
    assert emb["color"] == 0x3498DB
    assert af.render_discord(_ev(severity="urgent"))["embeds"][0]["color"] == 0xE74C3C


def test_af05_slack_blocks():
    fallback, blocks = af.render_slack(_ev(summary="a<b>&c", fields=[(f"k{i}", "v") for i in range(30)]))
    assert fallback.startswith("✅") and len(blocks) <= 50
    assert blocks[0]["type"] == "header" and len(blocks[0]["text"]["text"]) <= 150
    assert len(blocks[2]["fields"]) <= 10
    assert "a&lt;b&gt;&amp;c" in blocks[1]["text"]["text"]
    assert blocks[-1]["type"] == "context"


def test_af06_email_html_and_text_alternative():
    subject, html_body, text = af.render_email(_ev(reason="<img src=x onerror=1>"))
    assert subject.startswith("[매매 알림]")
    assert "<img" not in html_body and "&lt;img" in html_body
    assert "<table" in html_body and "자동매매 매수 가상 체결" in text


def test_af07_sms_one_line():
    sms = af.render_sms(_ev(summary="가" * 200))
    assert len(sms) <= 80 and "\n" not in sms


def test_af08_payload_roundtrip_and_size_cap():
    ev = _ev(fields=[(f"항목{i}", "값" * 300) for i in range(25)], reason="이" * 600)
    data = af.to_payload(ev)
    assert len(json.dumps(data, ensure_ascii=False).encode("utf-8")) <= af.PAYLOAD_MAX_BYTES
    back = af.from_payload(data)
    assert back.kind == "auto_fill" and back.severity == "normal" and back.mock is True
    assert back.stamp_text() == ev.stamp_text()
    blob = json.dumps(data, ensure_ascii=False)
    assert "webhook" not in blob.lower() and "token" not in blob.lower()


def test_af09_legacy_event_passthrough():
    ev = af.legacy_event("[주문 오류] 매수\n종목: A", html_message="<b>오류</b>", subject="제목")
    assert af.render_plain(ev) == "[주문 오류] 매수\n종목: A"
    assert af.render_telegram(ev) == "<b>오류</b>"
    assert af.render_discord(ev) == {"content": "[주문 오류] 매수\n종목: A"}
    fallback, blocks = af.render_slack(ev)
    assert fallback.startswith("[주문 오류]") and blocks == []
    assert af.render_email(ev)[0] == "제목"


def test_af10_digest_event_counts_and_severity():
    items = [{"title": f"주문 생략 {i}", "summary": "중복 주문", "ts": "2026-11-01T01:00:00+00:00",
              "severity": "info", "kind": "risk_skip"} for i in range(20)]
    d = af.digest_event(items, "조용한 시간", "ref-1")
    assert d.kind == "digest" and d.title == "알림 묶음 20건"
    assert len(d.fields) == 15 and "외 5건" in d.summary
    assert d.fields[0][0] == "10:00"          # UTC 01:00 → KST 10:00
    assert d.severity == "info"
    items.append({"title": "비상 정지", "severity": "urgent", "kind": "risk_halt"})
    assert af.digest_event(items, "조용한 시간", "ref-2").severity == "important"


def test_af11_helpers():
    assert af.won(1234567) == "1,234,567원" and af.won(None) == "-"
    assert af.pct(1.234) == "+1.23%" and af.pct(None) == "-"
