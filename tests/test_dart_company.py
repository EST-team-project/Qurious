"""기업 업종 · KSIC 시험 (TC-CI) — `collector/dart_company.py` (할 일 ①-05 G2 · 2026-10-24 · 사용자 결정 「7일에 한 번 전체」).

여기서 지키는 것 —
1. **개인 칸을 남기지 않는다** — 대표자 · 등록번호 · 주소 · 전화 · 팩스는 표에도 원문 백업 표에도 없다(지문만).
2. 판 — 처음은 새 · 같은 값이면 마지막 확인 시각만 · 값이 바뀌면 새 판 한 줄 · 예전 값으로 되돌아오면 그 판을 다시 지금 판으로.
3. 7일 — 처음 · 7일 지나면 전체 · 그 사이엔 새로 든 회사만(없으면 「건너뜀」 한 줄 · 호출 0).
4. 유니버스 — 마지막 판(끝 날짜 · 같으면 이름) · ETF 뺌 · 고유번호를 모르는 종목은 알림.
5. KSIC — 엑셀(대 · 중 · 소 · 세 · 세세 다섯 쌍 · 위 단계 들고 감) · 통째로 다시 읽기 · 원본 지문 처음엔 적기만 · 바뀌면 경고 + 다시 읽기 ·
   받지 못하면 경고(조용한 0건 금지).
6. 옮겨 담기 — 일회 수집 원문(네트워크 0회) · 받은 시각 = 파일 시각 · 「마지막 전체」 = 그 시각(다음 전체는 7일 뒤).
7. 멈춤 · 종료코드 — 상한 · 020 은 멈춤(3) · KSIC 경고 10 · 키 없음 78.
8. 연결 — 러너 단계 · 백업 · 관제 · 자료 안내.

네트워크 · 실제 수집 DB 를 쓰지 않는다.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from collector import config, db
from collector import dart_company as C
from collector.sources import dart

KST = timezone(timedelta(hours=9))
CORP_MAP = {"005930": ["00126380", "삼성전자"], "000660": ["00164779", "SK하이닉스"], "035420": ["00266961", "NAVER"]}
PERSONAL = {"ceo_nm": "홍길동", "jurir_no": "1101110000000", "bizr_no": "1248100000", "adres": "경기도 수원시 영통구",
            "phn_no": "02-0000-0000", "fax_no": "031-000-0000"}


def _doc(corp, induty="264", name="회사", status="000"):
    d = {"status": status, "message": "정상", "corp_code": corp, "corp_name": name, "corp_name_eng": "Co", "stock_name": name,
         "stock_code": next((s for s, v in CORP_MAP.items() if v[0] == corp), ""), "corp_cls": "Y", "induty_code": induty,
         "est_dt": "19690113", "acc_mt": "12", "hm_url": "www.example.com", "ir_url": ""}
    d.update(PERSONAL)
    return d


class _Resp:
    def __init__(self, body, status=200):
        self.content, self.status_code, self.headers = body, status, {}


class _Session:
    def __init__(self, docs):
        self.docs, self.calls = dict(docs), []

    def get(self, url, params=None, timeout=None):
        corp = params["corp_code"]
        self.calls.append(corp)
        d = self.docs.get(corp)
        if isinstance(d, bytes):
            return _Resp(d)
        return _Resp(json.dumps(d or {"status": "013", "message": "없음"}, ensure_ascii=False).encode("utf-8"))


class _NoWait:
    calls = 0

    def wait(self):
        pass

    def observe(self, headers):
        pass


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "dart_key", lambda: "dartTEST" + "0" * 32)
    monkeypatch.delenv(dart.LEDGER_ENV, raising=False)
    c = db.connect(tmp_path / "m.sqlite3")
    c.executemany("INSERT INTO intraday_universe (version, symbol, itms_nm, market, reason) VALUES (?, ?, '', ?, '')",
                  [("u2-20260930", "005930", "KOSPI"), ("u2-20260930", "000660", "KOSPI"), ("u2-20260930", "069500", "ETF"),
                   ("u2-20260930", "123456", "KOSDAQ"), ("u1-20260930", "035420", "KOSPI")])
    yield c
    c.close()


def _run(conn, s, now, **kw):
    return C.run(conn, now=now, session=s, limiter=_NoWait(), corp_map=CORP_MAP, fetch_ksic=lambda names: None, **kw)


def test_personal_fields_never_stored(conn):
    """TC-CI-01 · 개인 칸 — 남기는 칸에 없고 · 표의 어느 칸 값에도 없고 · 원문 백업 표에 기업개황 원문이 없다(지문만)."""
    assert not set(PERSONAL) & set(C.KEEP) and set(C.DROPPED) == set(PERSONAL)
    s = _Session({"00126380": _doc("00126380"), "00164779": _doc("00164779")})
    _run(conn, s, datetime(2026, 10, 25, 12, 40, tzinfo=KST))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(dart_company)")]
    assert not set(PERSONAL) & set(cols)
    dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM dart_company")], ensure_ascii=False)
    assert all(v not in dump for v in PERSONAL.values())
    assert conn.execute("SELECT COUNT(*) FROM raw_response").fetchone()[0] == 0
    assert all(len(r[0]) == 64 for r in conn.execute("SELECT raw_sha256 FROM dart_company"))


def test_versions_new_same_changed_and_revert(conn):
    """TC-CI-02 · 판 — 새 · 같음(마지막 확인만) · 바뀜(새 판 한 줄) · 되돌아옴(예전 판이 다시 지금 판 · 처음 본 시각 그대로) · 지문은 칸 차례와 무관."""
    f = C.keep_fields(_doc("00126380", induty="264"))
    assert C.fields_sha(f) == C.fields_sha(dict(reversed(list(f.items()))))
    assert C.keep_fields({"corp_name": " 삼성  전자 "})["corp_name"] == "삼성 전자"
    assert C.upsert_company(conn, "00126380", f, at="t1", raw_sha256="a", universe_version="u2") == "new"
    assert C.upsert_company(conn, "00126380", f, at="t2", raw_sha256="a", universe_version="u2") == "same"
    g = C.keep_fields(_doc("00126380", induty="26410"))
    assert C.upsert_company(conn, "00126380", g, at="t3", raw_sha256="b", universe_version="u2") == "changed"
    assert C.current(conn, "00126380")["induty_code"] == "26410"
    assert C.upsert_company(conn, "00126380", f, at="t4", raw_sha256="a", universe_version="u2") == "changed"
    cur = C.current(conn, "00126380")
    assert (cur["induty_code"], cur["first_seen_at"], cur["last_seen_at"]) == ("264", "t1", "t4")
    assert conn.execute("SELECT COUNT(*) FROM dart_company").fetchone()[0] == 2


def test_universe_latest_version_without_etf(conn):
    """TC-CI-03 · 유니버스 — 판 끝 날짜가 같으면 이름이 큰 판(u2) · ETF 뺌 · 고유번호를 모르는 종목은 따로."""
    ver, pairs, missing = C.universe(conn, CORP_MAP)
    assert ver == "u2-20260930" and [s for s, _c in pairs] == ["005930", "000660"] and missing == ["123456"]
    conn.execute("INSERT INTO intraday_universe (version, symbol, itms_nm, market, reason) VALUES ('u1-20261231', '035420', '', 'KOSPI', '')")
    assert C.latest_universe_version(conn) == "u1-20261231", "날짜가 늦은 판이 이름보다 먼저"


def test_weekly_full_then_only_new_then_full_again(conn):
    """TC-CI-04 · 7일 — 처음은 전체 · 7일 안엔 새로 든 회사만(없으면 호출 0 · 건너뜀 · 다음 전체 날) · 7일 뒤 전체."""
    docs = {"00126380": _doc("00126380"), "00164779": _doc("00164779"), "00266961": _doc("00266961")}
    t0 = datetime(2026, 10, 25, 12, 40, tzinfo=KST)
    s = _Session(docs)
    t = _run(conn, s, t0)
    assert t.mode == "전체" and sorted(s.calls) == ["00126380", "00164779"] and t.new == 2
    s2 = _Session(docs)
    t2 = _run(conn, s2, t0 + timedelta(days=3))
    assert t2.mode == "새 회사만" and s2.calls == [] and t2.next_full == "2026-11-01"
    conn.execute("INSERT INTO intraday_universe (version, symbol, itms_nm, market, reason) VALUES ('u2-20260930', '035420', '', 'KOSPI', '')")
    s3 = _Session(docs)
    t3 = _run(conn, s3, t0 + timedelta(days=4))
    assert t3.mode == "새 회사만" and s3.calls == ["00266961"] and t3.new == 1
    s4 = _Session(docs)
    t4 = _run(conn, s4, t0 + timedelta(days=7))
    assert t4.mode == "전체" and len(s4.calls) == 3 and t4.same == 3


def test_ksic_parse_reload_and_fingerprint(conn, tmp_path):
    """TC-CI-05 · KSIC — 엑셀 다섯 쌍(위 단계 칸은 새 값일 때만 차 있음 → 들고 감) · 시트 이름으로 차수 · 통째로 다시 읽기 ·
    원본 지문은 처음엔 적기만 · 바뀌면 경고 + 파일 바꿈 + 다시 읽기 · 받지 못하면 경고."""
    import openpyxl

    def book(path, extra=False):
        wb = openpyxl.Workbook()
        for title in ("11차 분류체계", "10차 분류체계"):
            ws = wb.create_sheet(title)
            ws.append(["한국표준산업분류"])
            ws.append(["대분류", "", "중분류", "", "소분류", "", "세분류", "", "세세분류", ""])
            ws.append(["코드", "항목명"] * 5)
            ws.append(["C", "제조업", "26", "전자 부품 제조업", "264", "통신 장비", "2641", "유선", "26410", "유선 통신장비"])
            ws.append([None, None, None, None, None, None, None, None, "26411", "교환기"])
            if extra:
                ws.append([None, None, None, None, "265", "영상 장비", None, None, None, None])
        wb.remove(wb["Sheet"])
        wb.save(path)

    d = tmp_path / "ksic"
    d.mkdir()
    book(d / C.KSIC_TABLE_FILE)
    rows = C.parse_ksic_xlsx(d / C.KSIC_TABLE_FILE)
    r11 = [r for r in rows if r["revision"] == "11"]
    assert [(r["level"], r["code"], r["parent_code"], r["section"]) for r in r11] == [
        ("대분류", "C", "", "C"), ("중분류", "26", "C", "C"), ("소분류", "264", "26", "C"), ("세분류", "2641", "264", "C"),
        ("세세분류", "26410", "2641", "C"), ("세세분류", "26411", "2641", "C")]
    assert {r["revision"] for r in rows} == {"11", "10"}
    cnt = C.load_ksic(conn, d)
    assert cnt["11차 세세분류"] == 2 and conn.execute("SELECT COUNT(*) FROM ksic_code").fetchone()[0] == 12
    files = {local: (d / C.KSIC_TABLE_FILE).read_bytes() for local, _n in C.KSIC_FILES}
    assert C.check_ksic(conn, fetch=lambda names: ("u", files[C.KSIC_TABLE_FILE]), ksic_dir=d) == ("같음", False)
    book(tmp_path / "new.xlsx", extra=True)
    new = (tmp_path / "new.xlsx").read_bytes()
    note, warn = C.check_ksic(conn, fetch=lambda names: ("u", new), ksic_dir=d)
    assert warn and "바뀜" in note
    assert conn.execute("SELECT COUNT(*) FROM ksic_code WHERE code='265'").fetchone()[0] == 2, "바뀐 원본으로 다시 읽었다"
    note2, warn2 = C.check_ksic(conn, fetch=lambda names: None, ksic_dir=d)
    assert warn2 and "확인 못 함" in note2


def test_seed_from_one_time_raw_offline(conn, tmp_path):
    """TC-CI-06 · 옮겨 담기 — 유니버스 안 · 값 있음만 · 받은 시각 = 파일 시각 · 원문은 남기지 않음 · 「마지막 전체」 = 가장 늦은 파일 시각."""
    raw = tmp_path / "raw_company"
    raw.mkdir()
    for corp, st in (("00126380", "000"), ("00164779", "013"), ("00999999", "000")):
        f = raw / f"{corp}.json.gz"
        f.write_bytes(gzip.compress(json.dumps(_doc(corp, status=st), ensure_ascii=False).encode("utf-8"), mtime=0))
        os.utime(f, (1792641457, 1792641457))
    out = C.seed(conn, raw, corp_map=CORP_MAP)
    assert (out["files"], out["rows"], out["skipped"]) == (3, 1, 2)
    row = C.current(conn, "00126380")
    assert row["first_seen_at"].startswith("2026-10-22T12:57") and conn.execute("SELECT COUNT(*) FROM raw_response").fetchone()[0] == 0
    assert C.last_full(conn).isoformat().startswith("2026-10-22T12:57")
    assert C.seed(conn, raw, corp_map=CORP_MAP)["rows"] == 0, "다시 돌려도 같은 판"


def test_stop_and_exit_codes(conn, tmp_path, monkeypatch, capsys):
    """TC-CI-07 · 상한에 닿거나 020 이면 멈춤(받은 것은 남음) · 명령 종료코드 — 멈춤 3 · KSIC 경고 10 · 키 없음 78."""
    s = _Session({"00126380": _doc("00126380"), "00164779": _doc("00164779")})
    t = _run(conn, s, datetime(2026, 10, 25, 12, 40, tzinfo=KST), max_calls=1)
    assert "상한" in t.stopped and conn.execute("SELECT COUNT(*) FROM dart_company").fetchone()[0] == 1
    s2 = _Session({"00164779": json.dumps({"status": "020", "message": "한도"}).encode()})
    t2 = _run(conn, s2, datetime(2026, 10, 25, 12, 41, tzinfo=KST), full=True)
    assert "한도" in t2.stopped
    dbp = tmp_path / "cli.sqlite3"

    def missing():
        raise config.MissingKey("DART_API_KEY 가 없다")
    monkeypatch.setattr(config, "dart_key", missing)
    assert C.main(["weekly", "--db", str(dbp)]) == C.EX_CONFIG == 78
    assert "DART 인증키" in capsys.readouterr().out
    monkeypatch.setattr(config, "dart_key", lambda: "k" * 40)
    monkeypatch.setattr(C, "run", lambda *a, **k: C.Tally(mode="전체", ksic="원본 바뀜", ksic_warn=True))
    assert C.main(["weekly", "--db", str(dbp)]) == C.EX_KSIC_WARN == 10
    monkeypatch.setattr(C, "run", lambda *a, **k: C.Tally(mode="전체", stopped="상한"))
    assert C.main(["weekly", "--db", str(dbp)]) == C.EX_STOPPED == 3
    monkeypatch.setattr(C, "run", lambda *a, **k: C.Tally(mode="새 회사만", next_full="2026-11-01"))
    assert C.main(["weekly", "--db", str(dbp)]) == 0 and "건너뜀" in capsys.readouterr().out


def test_wired_runner_backup_status_guide():
    """TC-CI-08 · 연결 — 러너 단계(재무 전체 뒤 · 일정 앞 · 받기 · 멈추지 않음 · 상한 = 몫 표 · 3 · 10 은 경고) · 백업(업종 · KSIC) ·
    관제 줄(새 행 없는 날이 정상 — 단계 결과로) · 자료 안내 한 자료(표 둘)."""
    from app.services import data_guide as dg
    from app.services import data_status as ds
    from scripts import daily_update as du
    from scripts import hf_dataset

    names = [s.name for s in du.STEPS]
    assert names.index("financial_full") + 1 == names.index("company") < names.index("schedule")
    step = du.STEPS[names.index("company")]
    assert step.args[:4] == ["-m", "collector.dart_company", "weekly", "--quiet"] and not step.fatal
    assert step.args[step.args.index("--max-calls") + 1] == str(du.DART_CAPS["company"]) and step.warn_codes == (3, 10)
    assert {"dart_company", "ksic_code"} <= set(hf_dataset.TABLES)
    assert ds.FRESHNESS["dart_company"] == ("step_checked", "company")
    item = next(it for it in dg.load_guide()["items"] if it["key"] == "company-industry")
    assert item["dev"]["tables"] == ["dart_company", "ksic_code"] and "kssc" in item["sources"]
