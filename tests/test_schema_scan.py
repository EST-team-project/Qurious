"""스키마 스캐너 시험 (TC-SS) — ERD · 데이터 사전의 약속을 지키는가.

무엇이 틀렸었나 —
① 재현성: 함수로 된 모델 기본값(`default=dict`)을 `str()` 로 적어 `<function dict at 0x0000023781BC0B80>`
   이 나왔다. 주소는 실행마다 달라서 **돌릴 때마다 사전이 7줄씩 달라졌다**(2026-09-28 S57 발견).
② 설명의 출처: 수집 DB 표의 칸 설명을 **DB 파일에 저장된 CREATE 문**에서 읽었다. 그 문장은 표를 처음
   만들 때 것이라, 그 뒤 코드에서 고친 주석(`corporate_action.kind` 의 네 번째 값 `shares`)과
   `ALTER TABLE` 로 나중에 더한 칸(`benchmark_index` 의 세 칸)의 설명이 사전에 들어가지 않았다
   (2026-09-29). 사전이 「설명을 고치려면 코드 주석을 고친다」 고 약속하는데 수집 DB 쪽은 그게 안 됐다.
③ 표 속성 대장: 표마다 한글명 · 유형 · 발생 주기 · 보존 기간 · 공개를 사람이 적는 대장이다. 스캐너가
   싣고 빠진 곳을 알린다. 실제 저장소에는 「대장이 모든 표를 덮는다」 를 걸지 않는다 — 팀원이 표를
   더하는 것은 좋은 일인데 그 순간 시험이 깨진다(API 명세 스캐너 시험과 같은 원칙). 판정 규칙은
   합성 대장으로 재고, 실제 대장에는 파일 자체의 형식(머리 줄 · 겹친 줄 · 정한 말)만 건다.
"""
from __future__ import annotations

import re
import sqlite3

import pytest

from scripts import schema_scan


def test_callable_default_is_written_by_name():
    assert schema_scan._기본값_글자(dict) == "dict()"
    assert schema_scan._기본값_글자(list) == "list()"
    assert schema_scan._기본값_글자("now()") == "now()"     # 글자 기본값은 그대로
    assert schema_scan._기본값_글자(0) == "0"


def test_app_schema_has_no_memory_address():
    """옛 코드에서는 실패한다 — 기본값 7칸에 메모리 주소가 찍혔다."""
    주소 = re.compile(r" at 0x[0-9A-Fa-f]+")
    찍힌_칸 = [
        f"{t.이름}.{c.이름}"
        for t in schema_scan.앱_스키마()
        for c in t.칸들
        if c.기본값 and 주소.search(c.기본값)
    ]
    assert 찍힌_칸 == []


# ── 합성 수집 DB — 표를 옛 주석으로 만든 뒤 코드에서 주석을 고치고 칸을 더한 모양 ──────────

옛_DDL = """CREATE TABLE ev (
    bas_dt TEXT NOT NULL,
    kind   TEXT NOT NULL DEFAULT 'review',   -- split / rights / review
    PRIMARY KEY (bas_dt)
)"""

파일에만_있는_표_DDL = """CREATE TABLE only_file (
    a TEXT   -- 파일에만 있는 표의 설명
)"""

새_코드 = '''
SCHEMA = """
-- 표 설명 줄 (칸의 설명이 아니다)
CREATE TABLE IF NOT EXISTS ev (
    bas_dt TEXT NOT NULL,                     -- 기준일
    -- split / rights / review
    -- / shares=주식 수로 조정
    kind   TEXT NOT NULL DEFAULT 'review',
    n_new  INTEGER NOT NULL DEFAULT 0,        -- 나중에 더한 칸
    PRIMARY KEY (bas_dt)
);
CREATE INDEX IF NOT EXISTS ix_ev ON ev(kind);
"""
'''


def _합성(tmp_path):
    db = tmp_path / "market.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(옛_DDL)
    conn.execute("ALTER TABLE ev ADD COLUMN n_new INTEGER NOT NULL DEFAULT 0")
    conn.execute(파일에만_있는_표_DDL)
    conn.commit()
    conn.close()
    코드폴더 = tmp_path / "collector"
    코드폴더.mkdir()
    (코드폴더 / "db.py").write_text(새_코드, encoding="utf-8")
    return db, schema_scan._코드_DDL(코드폴더)


def _설명(표들, 표이름):
    return {c.이름: c.설명 for t in 표들 if t.이름 == 표이름 for c in t.칸들}


def test_ss03_수집_DB_칸_설명은_DB_파일이_아니라_코드의_CREATE_문에서_온다(tmp_path):
    """옛 코드에서 실패한다 — DB 파일의 CREATE 문(표를 처음 만들 때 것)을 읽어 고친 주석 · 더한 칸이 빠졌다."""
    db, 코드 = _합성(tmp_path)
    설명 = _설명(schema_scan.수집기_스키마(db, 코드), "ev")
    assert 설명["kind"] == "split / rights / review / shares=주식 수로 조정"
    assert 설명["n_new"] == "나중에 더한 칸"        # ALTER TABLE 로 더한 칸 — DB 파일에는 주석이 없다
    assert 설명["bas_dt"] == "기준일"
    assert "표 설명 줄" not in " ".join(설명.values())   # CREATE 위의 표 설명은 칸에 붙지 않는다


def test_ss04_코드에_CREATE_문이_없는_표는_DB_파일의_주석을_쓴다(tmp_path):
    db, 코드 = _합성(tmp_path)
    assert _설명(schema_scan.수집기_스키마(db, 코드), "only_file") == {"a": "파일에만 있는 표의 설명"}


def test_ss05_대조가_설명이_다른_칸과_한쪽에만_있는_칸을_가린다(tmp_path):
    db, 코드 = _합성(tmp_path)
    결과 = schema_scan.수집기_주석_대조(db, 코드)
    assert sorted(f'{d["표"]}.{d["칸"]}' for d in 결과["설명이_다른_칸"]) == ["ev.bas_dt", "ev.kind", "ev.n_new"]
    assert 결과["코드에_없는_표"] == ["only_file"]
    assert 결과["코드에만_있는_칸"] == [] and 결과["파일에만_있는_칸"] == []

    # 코드가 칸을 더했는데 DB 파일에 아직 없으면 — 그 칸에 쓰는 INSERT 가 터진다
    더한_코드 = {"ev": 코드["ev"].replace("    PRIMARY KEY", "    extra TEXT,   -- 새 칸\n    PRIMARY KEY")}
    assert schema_scan.수집기_주석_대조(db, 더한_코드)["코드에만_있는_칸"] == ["ev.extra"]
    # 코드에서 칸을 뺐는데 DB 파일에는 남아 있으면
    뺀_코드 = {"ev": 코드["ev"].replace("    n_new  INTEGER NOT NULL DEFAULT 0,        -- 나중에 더한 칸\n", "")}
    assert schema_scan.수집기_주석_대조(db, 뺀_코드)["파일에만_있는_칸"] == ["ev.n_new"]


def test_ss06_실제_코드의_CREATE_문이_수집_DB_표를_모두_담고_kind_네_값을_설명한다():
    """DB 파일 없이도 도는 실제 저장소 검사 — 늘 참이어야 하는 성질만."""
    코드 = schema_scan._코드_DDL()
    assert {"raw_response", "price_daily", "ingest_day", "price_adjusted", "corporate_action",
            "dividend", "price_total_return", "benchmark_index"} <= set(코드)
    kind = schema_scan._ddl_주석_추출(코드["corporate_action"])["kind"]
    assert all(값 in kind for 값 in ("split=", "rights=", "review=", "shares="))
    벤치 = schema_scan._ddl_주석_추출(코드["benchmark_index"])
    assert 벤치["n_fixed"] and 벤치["base_dt"] and 벤치["base_level"]


# ── 표 속성 대장 ─────────────────────────────────────────────────

def _대장(tmp_path, *줄들, 머리=None):
    p = tmp_path / "대장.tsv"
    p.write_text("\n".join(["\t".join(머리 or schema_scan.표속성_칸)] + ["\t".join(z) for z in 줄들]) + "\n",
                 encoding="utf-8")
    return schema_scan.표속성_읽기(p)


def _줄(표, DB, **바꿈):
    기본 = {"표": 표, "DB": DB, "한글명": 표 + " 한글", "업무영역": "영역", "유형": "파생", "발생주기": "매일",
            "보존기간": "다시 만들 때까지", "공개": "비공개", "공개_근거": "근거", "관련표": "—"}
    기본.update(바꿈)
    return [기본[k] for k in schema_scan.표속성_칸]


def test_ss07_대장_대조가_빠진_표_겹친_줄_틀린_DB_빈_칸_정한_말_밖을_가린다(tmp_path):
    대장 = _대장(tmp_path,
                 _줄("ev", "수집"), _줄("ev", "수집"),               # 겹친 줄
                 _줄("users", "수집"),                                # DB 틀림 (앱 표)
                 _줄("ghost", "앱"),                                  # DB 에 없는 표
                 _줄("orders", "앱", 발생주기="", 공개="공개함", 유형="기타"))
    결과 = schema_scan.표속성_대조(대장, ["ev", "price"], ["users", "orders"])
    assert 결과["대장에_없는_표"] == ["price"]
    assert 결과["대장에만_있는_표"] == ["ghost"]
    assert 결과["겹친_줄"] == ["ev"]
    assert 결과["DB_다름"] == ["users(수집 → 앱)"]
    assert 결과["빈_칸"] == ["orders.발생주기"]
    assert 결과["모르는_값"] == ["orders.공개=공개함", "orders.유형=기타"]
    assert 결과["머리_다름"] == []
    # 머리 줄이 정한 칸과 다르면 (칸 하나를 빠뜨림)
    빠진 = _대장(tmp_path, _줄("ev", "수집")[:-1], 머리=schema_scan.표속성_칸[:-1])
    assert schema_scan.표속성_대조(빠진, ["ev"], [])["머리_다름"] != []
    # 파일이 없으면 빈 대장 — 멈추지 않는다
    assert schema_scan.표속성_읽기(tmp_path / "없음.tsv") == []


def test_ss08_실제_대장은_정한_머리_줄_겹침_없음_정한_말만_쓴다():
    """실제 대장 파일 자체의 형식만 건다 — 모든 표를 덮는지는 스캐너 요약 출력이 알린다."""
    대장 = schema_scan.표속성_읽기()
    assert 대장, "docs/데이터/대장/표-속성대장.tsv 가 없다"
    assert list(대장[0].keys()) == list(schema_scan.표속성_칸)
    이름 = [z["표"] for z in 대장]
    assert len(이름) == len(set(이름))
    assert {z["DB"] for z in 대장} <= set(schema_scan.표속성_DB.values())
    assert {z["유형"] for z in 대장} <= set(schema_scan.표속성_유형)
    assert {z["공개"] for z in 대장} <= set(schema_scan.표속성_공개)


def _표(이름, 출처, 칸들, 행수=None):
    return schema_scan.표(이름=이름, 출처=출처, 확실도="실측" if 출처 == "수집기" else "정의",
                         칸들=칸들, 행수=행수)


def test_ss09_표_목록_사전_ERD_가_대장을_싣고_앱_그림을_업무_영역으로_나눈다(tmp_path, capsys):
    C = schema_scan.칸
    수집 = [_표("ev", "수집기", [C("bas_dt", "TEXT", False, 기본키=True, 설명="기준일")], 행수=1234)]
    users = _표("users", "앱", [C("id", "UUID", False, 기본키=True), C("email", "VARCHAR", False)])
    orders = _표("orders", "앱", [C("id", "UUID", False, 기본키=True),
                                  C("user_id", "UUID", False, 외래키="users.id")])
    fills = _표("order_fills", "앱", [C("id", "UUID", False, 기본키=True),
                                     C("order_id", "UUID", False, 외래키="orders.id")])
    cache = _표("data_cache", "앱", [C("id", "UUID", False, 기본키=True)])
    대장 = _대장(tmp_path,
                 _줄("ev", "수집", 한글명="이벤트", 업무영역="시세"),
                 _줄("orders", "앱", 한글명="주문", 업무영역="주문", 유형="사용자"),
                 _줄("order_fills", "앱", 한글명="체결", 업무영역="주문", 유형="사용자"),
                 _줄("users", "앱", 한글명="사용자 계정", 업무영역="계정", 유형="사용자"))
    앱 = [cache, fills, orders, users]                  # data_cache 는 대장에 없다

    schema_scan.표목록마크다운(수집, 앱, 대장)
    목록 = capsys.readouterr().out
    assert "| `ev` | 이벤트 | 수집 | 시세 | 파생 | 1,234 | 1/1 |" in 목록
    assert "| `data_cache` | ⚠️ 대장에 없음 | 앱 |" in 목록
    assert 목록.index("`orders`") < 목록.index("`users`")    # 대장 차례: 주문 영역이 계정 영역보다 먼저
    assert "| `ev` | 매일 | 다시 만들 때까지 | 비공개 | 근거 |" in 목록

    schema_scan.사전마크다운(수집, 앱, 대장)
    사전 = capsys.readouterr().out
    assert "#### `ev` · 이벤트 · **1,234행**" in 사전
    assert "파생 · 시세 · 발생 주기: 매일 · 보존 기간: 다시 만들 때까지 · 공개: 비공개" in 사전

    schema_scan.erd출력(수집, 앱, 대장, "앱")
    그림 = capsys.readouterr().out
    assert 그림.count("erDiagram") == 3                         # 주문 · 계정 · 업무 영역 미정
    주문 = 그림.split("**앱 DB — 주문 ·")[1].split("**앱 DB —")[0]
    assert "2표 · 관계 2개" in 주문 and "다른 영역의 표 `users` 는 기본키만" in 주문
    assert "  users {\n    UUID id PK\n  }" in 주문                # 밖의 표는 기본키 한 칸만
    assert 'users ||--o{ orders : "user_id"' in 주문 and 'orders ||--o{ order_fills : "order_id"' in 주문
    assert "**앱 DB — 업무 영역 미정 · 1표 · 관계 0개**" in 그림 and "선이 없다" in 그림
    assert "수집 DB" not in 그림                                  # --erd 앱 은 수집 DB 를 그리지 않는다


def test_ss10_문서_채우기는_표시_사이만_바꾸고_줄_끝을_지킨다():
    글 = "머리 글\r\n<!-- schema_scan:list -->\r\n옛 표\r\n<!-- /schema_scan:list -->\r\n사람이 쓴 꼬리\r\n"
    새글, 수 = schema_scan.fill_doc(글, {"list": "새 표 1\n새 표 2", "md": "쓰지 않는 블록"})
    assert 수 == 1
    assert 새글 == ("머리 글\r\n<!-- schema_scan:list -->\r\n새 표 1\r\n새 표 2\r\n"
                   "<!-- /schema_scan:list -->\r\n사람이 쓴 꼬리\r\n")
    with pytest.raises(SystemExit):                              # 표시가 하나도 없으면 멈춘다
        schema_scan.fill_doc("표시 없는 글", {"list": "x"})
    with pytest.raises(SystemExit):                              # 여는 표시가 두 번이면 멈춘다
        schema_scan.fill_doc("<!-- schema_scan:list -->\n<!-- schema_scan:list -->\n<!-- /schema_scan:list -->",
                             {"list": "x"})
    # --check 는 행 수(천 단위 쉼표 수)만 다른 것을 「같다」 로 본다 — 수집 DB 는 매일 는다
    어제 = "| `ev` | 이벤트 | 수집 | 4,472,185 | 13/17 |\n#### `ev` · **13,462,818행**"
    오늘 = "| `ev` | 이벤트 | 수집 | 4,475,055 | 13/17 |\n#### `ev` · **13,471,460행**"
    assert 어제 != 오늘 and schema_scan._행수_가림(어제) == schema_scan._행수_가림(오늘)
    assert schema_scan._행수_가림(어제) != schema_scan._행수_가림(오늘.replace("13/17", "14/17"))   # 설명 수는 가리지 않는다
