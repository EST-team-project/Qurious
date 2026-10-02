"""용어사전 — 파일을 표에 넣고(적재), 표에서 찾는다(검색 · 단건 · 분류 · 상태).

큰 그림
    용어의 원본은 파일이다: `app/services/glossary_data/terms.json` (만드는 법은 scripts/glossary_build.py).
    앱이 켜질 때 `ensure_loaded()` 가 「지금 넣을 행」 의 체크섬을 마지막 적재 기록과 견주어, **다를 때만** 표를 파일과 같게 맞춘다.
    그 뒤의 조회는 전부 표에서 한다.

왜 「다를 때만」 인가
    개발 모드에서는 코드를 저장할 때마다 앱이 다시 켜진다. 그때마다 용어 수백 개를 다시 넣으면 느리고,
    앱이 둘 이상 뜨면 서로 덮어쓴다. 체크섬이 같으면 조회 한 번으로 끝난다.
    (같은 원리: Flyway 의 repeatable migration — 내용의 체크섬이 바뀔 때만 다시 적용한다.)

왜 파일이 아니라 「넣을 행」 의 체크섬인가
    검색용 칸(찾기용 모양 · 초성 · 이름 글 · 본문 글)은 파일에 없고 적재할 때 만든다(`seed_rows`). 파일은 그대로인데 그 칸을 만드는
    규칙만 고치면 파일 체크섬은 같아서 표가 옛 값으로 남는다. 넣을 행 자체를 세면(`rows_checksum`) 파일이 바뀌든 규칙이 바뀌든 잡힌다.
    파일 체크섬은 「어떤 판의 파일이 들어왔나」 를 사람이 알아보는 값으로 이력에 함께 남긴다(빌드 스크립트가 찍는 판과 같다).

왜 잠그나
    앱 인스턴스 둘이 동시에 켜지면 둘 다 「다르다」 고 보고 같이 넣으려 한다. PostgreSQL 의 advisory lock 으로
    한 번에 하나만 넣게 하고, 잠금을 얻은 뒤 **다시 한 번** 체크섬을 본다(먼저 들어간 쪽이 이미 끝냈을 수 있다).

검색 규칙 (순위가 낮을수록 위에 나온다 — `match_rank`)
    0  이름이 정확히 같다 (대표 이름 · 약어 · 영어 이름 · 화면 키)
    1  대표 이름이 검색어로 시작한다 · 초성이 검색어로 시작한다
    2  다른 이름(약어 · 영어 이름)이 검색어로 시작한다 · 초성 가운데에 들어 있다
    3  이름 가운데에 검색어가 들어 있다 — 한글이거나 영문 네 글자 이상일 때만
    4  풀이(본문)에만 들어 있다 — 영문 세 글자 이하는 풀이에서 낱말로 있을 때만
    같은 순위 안에서는 대표 이름 가나다순.
    영문 세 글자 이하를 가운데에서 찾지 않는 까닭: 「per」 로 찾으면 이름의 「o-per-ations」, 풀이의 「pro-per-ty」 가
    든 용어가 줄줄이 나온다(「동산」 「법인」 「부동산」 이 PER 검색에 걸렸다). 짧은 영문은 약어라서 통째로 맞을 때만 뜻이 있다.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GlossaryAlias, GlossaryCategory, GlossaryLoad, GlossarySource, GlossaryTerm
from app.services.glossary_text import chosung, escape_like, is_chosung_query, norm

SEED_PATH = Path(__file__).resolve().parent / "glossary_data" / "terms.json"

#: 이 앱이 읽을 줄 아는 용어 파일 모양. 파일의 판이 다르면 넣지 않고 알린다(모르는 모양을 추측해서 넣지 않는다).
SUPPORTED_FORMAT = 1

#: 용어사전 적재 전용 잠금 번호. 값에 뜻은 없고, 다른 기능의 잠금과 겹치지 않으면 된다.
LOAD_LOCK_KEY = 71_001_101

MAX_LIMIT = 100
ALIAS_KIND_PRIMARY = "대표 이름"

# 주소 /api/glossary/{이름} 에서 용어 ID 로 쓸 수 없는 이름 — 같은 자리에 고정 주소가 있다.
RESERVED_IDS = ("categories", "meta")


# ─────────────────────────────────────────────────────────────────────
# 파일 읽기
# ─────────────────────────────────────────────────────────────────────
def read_seed(path: Path | None = None) -> tuple[dict, str]:
    """(용어 파일 내용, 체크섬). 체크섬은 줄끝을 LF 로 맞춘 글의 SHA-256 이다.

    Windows 에서 받은 파일은 줄끝이 CRLF 일 수 있다. 바이트 그대로 세면 같은 내용인데 PC 마다 값이 달라
    PC 를 옮길 때마다 다시 넣게 된다. 빌드 스크립트의 `checksum()` 과 같은 방법이다.
    """
    raw = (path or SEED_PATH).read_bytes().decode("utf-8").replace("\r\n", "\n")
    return json.loads(raw), hashlib.sha256(raw.encode("utf-8")).hexdigest()


def seed_rows(data: dict) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """용어 파일 → 표에 넣을 행(분류 · 자료 · 용어 · 별칭). 검색용 칸은 여기서 만든다.

    DB 없이 부를 수 있는 순수 함수다 — 파일이 표의 제약(길이 · 유일 · 외래 키)을 지키는지 시험에서 본다.
    """
    categories = [{"code": c["code"], "name": c["name"], "description": c.get("description", ""),
                   "sort_order": c.get("sort_order", 0)} for c in data["categories"]]
    sources = [{"code": s["code"], "title": s["title"], "origin": s.get("origin", ""), "paths": s.get("paths", ""),
                "sort_order": i * 10} for i, s in enumerate(data["sources"], 1)]
    terms, aliases = [], []
    taken: dict[str, str] = {}
    for t in data["terms"]:
        # 이름 → 용어 찾기 표. 대표 이름과 ID 도 별칭 표에 넣어, 찾을 때 표 하나만 보면 되게 한다.
        names = [(t["term"], ALIAS_KIND_PRIMARY), (t["id"], ALIAS_KIND_PRIMARY)]
        names += [(a["alias"], a["kind"]) for a in t["aliases"]]
        own: list[str] = []
        for alias, kind in names:
            key = norm(alias)
            if not key or taken.setdefault(key, t["id"]) != t["id"] or key in own:
                continue          # 다른 용어가 먼저 가진 이름 — 빌드가 이미 걸렀지만, 표의 유일 제약을 여기서도 지킨다
            own.append(key)
            aliases.append({"alias_norm": key, "term_id": t["id"], "alias": alias, "kind": kind})
        # 이 용어도 쓰지만 임자는 다른 용어인 이름(「NAV」 — 순자산가치 · 기준가격). 별칭 표에는 임자만 들어가고(이름 하나 = 용어 하나),
        # 검색용 글에는 이 용어에도 넣는다 — 그 이름으로 검색하면 두 용어가 모두 나온다.
        shared = [k for k in dict.fromkeys(norm(x) for x in t.get("shared_names", [])) if k and k not in own]
        body = " ".join([t["summary"], t["definition"], t["example"], t["caution"], t["app_note"],
                         *[n["text"] for n in t["notes"]]])
        terms.append({
            "id": t["id"], "term": t["term"], "english": t["english"], "hanja": t["hanja"],
            "category_code": t["category"], "lead_source_code": t["lead_source"],
            "summary": t["summary"], "definition": t["definition"], "example": t["example"], "caution": t["caution"],
            "formula": t["formula"], "origin_note": t["origin_note"], "app_note": t["app_note"],
            "source_codes": t["sources"], "notes": t["notes"],
            "sort_key": norm(t["term"]), "chosung": chosung(t["term"]),
            "name_text": "|" + "|".join(own + shared) + "|",  # |per|priceearningsratio|주가수익비율| — 앞뒤 | 로 「정확히 같은 이름」 을 가린다
            "body_text": body.lower(),
        })
    return categories, sources, terms, aliases


def rows_checksum(rows: tuple[list[dict], ...]) -> str:
    """표에 넣을 행 전체의 SHA-256 — 「다시 넣을지」 의 기준.

    용어 파일의 체크섬만 보면, 파일은 그대로인데 검색용 칸을 만드는 규칙(seed_rows · 글자 규칙)만 바뀐 때에 표가 옛 값으로 남는다.
    넣을 행 자체를 세면 파일이 바뀌든 규칙이 바뀌든 값이 달라진다 — 규칙을 고친 사람이 판 번호를 올릴 것을 기억하지 않아도 된다.
    """
    text = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────
# 적재
# ─────────────────────────────────────────────────────────────────────
async def _latest_load(db: AsyncSession) -> GlossaryLoad | None:
    return (await db.execute(select(GlossaryLoad).order_by(GlossaryLoad.id.desc()).limit(1))).scalar_one_or_none()


async def _upsert(db: AsyncSession, model, rows: list[dict], key: str) -> None:
    """있으면 고치고 없으면 넣는다. 지우고 다시 넣지 않는 까닭 — 뒤에 다른 표가 용어를 가리키면 지울 수 없다."""
    if not rows:
        return
    columns = [c for c in rows[0] if c != key]
    for start in range(0, len(rows), 500):      # 한 문장에 매개변수가 너무 많아지지 않게 나눠 넣는다
        stmt = pg_insert(model).values(rows[start:start + 500])
        await db.execute(stmt.on_conflict_do_update(index_elements=[key], set_={c: stmt.excluded[c] for c in columns}))


async def ensure_loaded(db: AsyncSession, path: Path | None = None) -> dict:
    """표가 용어 파일과 같은 판인지 보고, 다르면 맞춘다. 무엇을 했는지 돌려준다.

    돌려주는 값: {"status": "건너뜀" | "넣음", "checksum"(용어 파일의 것), "terms", "aliases", "duration_ms"}
    """
    data, checksum = read_seed(path)
    if data.get("format_version") != SUPPORTED_FORMAT:
        raise RuntimeError(f"용어 파일의 판({data.get('format_version')})을 이 앱은 읽지 못한다(읽는 판 {SUPPORTED_FORMAT})")
    rows = seed_rows(data)
    rows_sum = rows_checksum(rows)          # 파일이 같아도 검색용 칸을 만드는 규칙이 바뀌면 달라진다

    latest = await _latest_load(db)
    if latest is not None and latest.rows_checksum == rows_sum:
        return {"status": "건너뜀", "checksum": checksum, "terms": latest.term_count, "aliases": latest.alias_count,
                "duration_ms": 0}

    started = time.perf_counter()
    # 트랜잭션이 끝날 때 저절로 풀리는 잠금 — 다른 인스턴스는 여기서 기다렸다가, 아래에서 「이미 끝났다」 를 본다.
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOAD_LOCK_KEY})
    latest = await _latest_load(db)
    if latest is not None and latest.rows_checksum == rows_sum:
        await db.rollback()
        return {"status": "건너뜀", "checksum": checksum, "terms": latest.term_count, "aliases": latest.alias_count,
                "duration_ms": 0}

    categories, sources, terms, aliases = rows
    await _upsert(db, GlossaryCategory, categories, "code")
    await _upsert(db, GlossarySource, sources, "code")
    await _upsert(db, GlossaryTerm, terms, "id")
    # 별칭은 용어를 가리키기만 하는 표라 통째로 다시 넣는다 — 이름이 다른 용어로 옮겨 가는 경우까지 한 번에 맞는다.
    await db.execute(delete(GlossaryAlias))
    for start in range(0, len(aliases), 1000):
        await db.execute(pg_insert(GlossaryAlias).values(aliases[start:start + 1000]))
    # 파일에서 사라진 용어 · 분류 · 자료를 지운다(자식인 용어부터).
    await db.execute(delete(GlossaryTerm).where(GlossaryTerm.id.not_in([t["id"] for t in terms])))
    await db.execute(delete(GlossaryCategory).where(GlossaryCategory.code.not_in([c["code"] for c in categories])))
    await db.execute(delete(GlossarySource).where(GlossarySource.code.not_in([s["code"] for s in sources])))

    duration_ms = int((time.perf_counter() - started) * 1000)
    db.add(GlossaryLoad(checksum=checksum, rows_checksum=rows_sum, format_version=data["format_version"],
                        term_count=len(terms), alias_count=len(aliases), category_count=len(categories),
                        source_count=len(sources), duration_ms=duration_ms))
    await db.commit()      # 여기까지가 한 트랜잭션 — 중간에 실패하면 표는 옛 판 그대로다
    return {"status": "넣음", "checksum": checksum, "terms": len(terms), "aliases": len(aliases),
            "duration_ms": duration_ms}


async def ensure_loaded_on_startup() -> dict:
    """앱이 켜질 때 부른다(app/main.py). 세션을 스스로 열고 닫는다."""
    from app.database.postgres import get_session_factory

    async with get_session_factory()() as db:
        return await ensure_loaded(db)


# ─────────────────────────────────────────────────────────────────────
# 조회
# ─────────────────────────────────────────────────────────────────────
def match_rank(query: str, row: dict) -> tuple[int, str] | None:
    """검색 결과 한 줄의 (순위, 어디서 맞았나). 맞지 않으면 None. DB 없이 시험할 수 있게 값만 받는다.

    row 에는 그 용어의 sort_key · chosung · name_text · body_text 가 있어야 한다.
    """
    query_norm = norm(query)
    if not query_norm:
        return None
    if is_chosung_query(query):
        if row["chosung"].startswith(query_norm):
            return 1, "초성"
        return (2, "초성") if query_norm in row["chosung"] else None
    names = row["name_text"]                         # |per|priceearningsratio|주가수익비율|
    if f"|{query_norm}|" in names:
        return 0, "이름"
    if row["sort_key"].startswith(query_norm):
        return 1, "이름"
    if f"|{query_norm}" in names:
        return 2, "이름"
    if (len(query_norm) >= 4 or not query_norm.isascii()) and query_norm in names:
        return 3, "이름"
    body_query = query.strip().lower()                # 본문은 띄어쓰기를 살린 채로 찾는다
    if len(body_query) <= 3 and body_query.isascii() and body_query.isalnum():
        # 짧은 영문은 풀이에서 **낱말로** 있을 때만 — 「per」 가 pro-per-ty · pa-per 에, 「ma」 가 market 에 걸리지 않게.
        # 앞뒤 글자가 영문 · 숫자가 아니면 낱말이다(「PER은」 처럼 한글이 붙은 것은 낱말로 본다).
        in_body = re.search(rf"(?<![a-z0-9]){re.escape(body_query)}(?![a-z0-9])", row["body_text"]) is not None
    else:
        in_body = body_query in row["body_text"]
    return (4, "본문") if in_body else None


#: 이름이 여럿 맞으면 이 차례로 고른다 — 사람이 친 글자에 가장 가까운 이름(약어 · 영어)을 먼저 보여 준다.
_KIND_ORDER = {"약어": 0, "영어": 1, "다른 이름": 2, "화면 키": 3}


def pick_matched_alias(query: str, rank: int, how: str, primary: str, aliases: list[tuple[str, str, str]]) -> dict:
    """검색 결과 한 줄이 **어느 이름으로** 맞았는지 — 화면이 「per → PCE(Personal …)」 처럼 이유를 보여 주게(2026-10-02).

    match_rank 와 같은 기준으로 고른다. aliases 는 (보이는 이름, 종류, 찾기용 모양) 목록 — 대표 이름 줄도 들어 있다.
    맞은 이름을 못 찾으면(본문에서 맞음 · 초성) 대표 이름과 그 까닭(kind)만 준다.
    """
    q = norm(query)
    if how == "초성":
        return {"alias": primary, "kind": "초성"}
    if how == "본문":
        return {"alias": None, "kind": "본문"}
    if rank == 1:                                   # 대표 이름이 검색어로 시작한다(sort_key)
        return {"alias": primary, "kind": ALIAS_KIND_PRIMARY}
    tests = {0: lambda a: a == q, 2: lambda a: a.startswith(q), 3: lambda a: q in a}
    test = tests.get(rank)
    hits = [(a, k) for a, k, an in aliases if test and test(an)]
    if not hits:
        return {"alias": primary, "kind": ALIAS_KIND_PRIMARY}
    hits.sort(key=lambda x: (x[1] != ALIAS_KIND_PRIMARY, _KIND_ORDER.get(x[1], 9), len(x[0])))
    alias, kind = hits[0]
    return {"alias": alias, "kind": kind}


def _item(term: GlossaryTerm, category_name: str) -> dict:
    return {"id": term.id, "term": term.term, "english": term.english, "hanja": term.hanja,
            "category": {"code": term.category_code, "name": category_name}, "summary": term.summary}


async def search(db: AsyncSession, query: str = "", category: str | None = None,
                 limit: int = 30, offset: int = 0) -> dict:
    """용어 목록 · 검색. 검색어가 비면 분류 차례 · 가나다순으로 전부를 나눠 준다."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    query = (query or "").strip()
    query_norm = norm(query)
    stmt = select(GlossaryTerm, GlossaryCategory.name, GlossaryCategory.sort_order).join(
        GlossaryCategory, GlossaryCategory.code == GlossaryTerm.category_code)
    if category:
        stmt = stmt.where(GlossaryTerm.category_code == category)

    if not query_norm:
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await db.execute(stmt.order_by(GlossaryCategory.sort_order, GlossaryTerm.sort_key.collate("C"))
                                 .limit(limit).offset(offset))).all()
        return {"query": "", "category": category, "total": total, "limit": limit, "offset": offset,
                "items": [_item(t, name) for t, name, _ in rows]}

    by_chosung = is_chosung_query(query)
    like = f"%{escape_like(query_norm)}%"
    if by_chosung:
        stmt = stmt.where(GlossaryTerm.chosung.like(like, escape="\\"))
    else:
        body_like = f"%{escape_like(query.lower())}%"      # 본문은 띄어쓰기를 살린 채로 찾는다
        stmt = stmt.where(or_(GlossaryTerm.name_text.like(like, escape="\\"),
                              GlossaryTerm.body_text.like(body_like, escape="\\")))
    # SQL 은 「걸릴 수 있는 줄」 을 넓게 거르고, 순위는 아래 함수 하나가 정한다 — 용어가 수백 개라 다 받아도 가볍고,
    # 순위 규칙을 SQL 이 아니라 DB 없이 시험할 수 있는 곳에 두려는 것이다.
    ranked = []
    for term, name, _ in (await db.execute(stmt)).all():
        hit = match_rank(query, {"sort_key": term.sort_key, "chosung": term.chosung,
                                 "name_text": term.name_text, "body_text": term.body_text})
        if hit is not None:
            ranked.append((hit[0], term.sort_key, {**_item(term, name), "match": hit[1]}))
    ranked.sort(key=lambda x: (x[0], x[1]))
    page = ranked[offset:offset + limit]
    # 보여 줄 줄만 이름을 읽어 「어느 이름으로 맞았나」 를 붙인다(API-GLOS-01 · matched · 2026-10-02).
    ids = [item["id"] for _, _, item in page]
    names: dict[str, list[tuple[str, str, str]]] = {}
    if ids:
        for term_id, alias, kind, alias_norm in (await db.execute(
                select(GlossaryAlias.term_id, GlossaryAlias.alias, GlossaryAlias.kind, GlossaryAlias.alias_norm)
                .where(GlossaryAlias.term_id.in_(ids)))).all():
            names.setdefault(term_id, []).append((alias, kind, alias_norm))
    items = []
    for rank, _, item in page:
        item["matched"] = pick_matched_alias(query, rank, item["match"], item["term"], names.get(item["id"], []))
        items.append(item)
    return {"query": query, "category": category, "total": len(ranked), "limit": limit, "offset": offset,
            "items": items}


async def get_term(db: AsyncSession, name: str) -> dict | None:
    """이름 하나 → 용어 한 건. 대표 이름 · ID · 약어 · 영어 이름 · 화면 키 어느 것으로도 찾는다. 없으면 None."""
    key = norm(name)
    if not key:
        return None
    row = (await db.execute(
        select(GlossaryTerm, GlossaryCategory.name, GlossaryAlias.alias, GlossaryAlias.kind)
        .join(GlossaryAlias, GlossaryAlias.term_id == GlossaryTerm.id)
        .join(GlossaryCategory, GlossaryCategory.code == GlossaryTerm.category_code)
        .where(GlossaryAlias.alias_norm == key))).first()
    if row is None:
        return None
    term, category_name, matched_alias, matched_kind = row
    aliases = (await db.execute(select(GlossaryAlias.alias, GlossaryAlias.kind)
                                .where(GlossaryAlias.term_id == term.id, GlossaryAlias.kind != ALIAS_KIND_PRIMARY)
                                .order_by(GlossaryAlias.kind, GlossaryAlias.alias_norm.collate("C")))).all()
    titles = dict((await db.execute(select(GlossarySource.code, GlossarySource.title))).all())
    return {
        **_item(term, category_name),
        "definition": term.definition, "example": term.example, "caution": term.caution, "formula": term.formula,
        "origin_note": term.origin_note, "app_note": term.app_note,
        "aliases": [{"alias": a, "kind": k} for a, k in aliases],
        "sources": [{"code": c, "title": titles.get(c, c), "lead": c == term.lead_source_code} for c in term.source_codes],
        "notes": [{**n, "source_title": titles.get(n["source"], n["source"])} for n in term.notes],
        # 화면 키나 약어로 찾아왔으면 무엇으로 찾았는지 알려 준다(설명창이 「sharpe → 샤프 비율」 을 보여 줄 수 있게).
        "matched": {"alias": matched_alias, "kind": matched_kind},
    }


async def categories(db: AsyncSession) -> dict:
    """분류 목록과 분류마다의 용어 수."""
    rows = (await db.execute(
        select(GlossaryCategory, func.count(GlossaryTerm.id))
        .outerjoin(GlossaryTerm, GlossaryTerm.category_code == GlossaryCategory.code)
        .group_by(GlossaryCategory.code).order_by(GlossaryCategory.sort_order))).all()
    items = [{"code": c.code, "name": c.name, "description": c.description, "terms": n} for c, n in rows]
    return {"categories": items, "total_terms": sum(i["terms"] for i in items)}


async def meta(db: AsyncSession) -> dict:
    """지금 표에 든 용어사전의 판 — 언제 · 어떤 체크섬 · 몇 개. 파일과 같은 판인지도 함께 알려 준다."""
    latest = await _latest_load(db)
    data, file_checksum = read_seed()
    file_rows = rows_checksum(seed_rows(data))      # 지금 파일 · 지금 규칙으로 넣는다면 들어갈 행
    sources = (await db.execute(select(GlossarySource).order_by(GlossarySource.sort_order))).scalars().all()
    counts: dict[str, int] = {}
    for codes in (await db.execute(select(GlossaryTerm.source_codes))).scalars().all():
        for code in codes:
            counts[code] = counts.get(code, 0) + 1
    return {
        "loaded": latest is not None,
        "checksum": latest.checksum if latest else None,
        "file_checksum": file_checksum,
        "in_sync": bool(latest and latest.rows_checksum == file_rows),   # 거짓이면 앱을 다시 켜야 파일 · 규칙이 반영된다
        "loaded_at": latest.loaded_at.isoformat() if latest else None,
        "format_version": latest.format_version if latest else None,
        "terms": latest.term_count if latest else 0,
        "aliases": latest.alias_count if latest else 0,
        "sources": [{"code": s.code, "title": s.title, "origin": s.origin, "terms": counts.get(s.code, 0)} for s in sources],
    }
