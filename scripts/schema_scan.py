"""데이터베이스 스키마 실측 추출기 — ERD·데이터 사전의 출처.

왜 이 파일이 있는가
-------------------
표 스키마를 문서에 손으로 옮겨 적으면, 칸 하나가 바뀌는 순간 그 문서는 조용히
거짓이 된다. 읽는 사람은 틀렸다는 것을 알 방법이 없다. 그래서 ERD 와 데이터 사전의
**모든 숫자와 칸 이름을 이 스크립트가 만든다.** 문서는 이 출력을 붙여 넣은 것이고,
의심스러우면 다시 돌리면 된다.

    python scripts/schema_scan.py           # 사람이 읽는 요약
    python scripts/schema_scan.py --md      # 데이터 사전용 마크다운
    python scripts/schema_scan.py --erd     # Mermaid ERD
    python scripts/schema_scan.py --json    # 기계용

두 데이터베이스를 갈라 본다
---------------------------
이 프로젝트에는 성격이 다른 DB 가 둘 있고, **확실도가 다르다.**

| DB | 무엇 | 추출 방법 | 확실도 |
|---|---|---|---|
| 수집기 `market.sqlite3` | 시세·배당·지수 원자료 | 실제 파일을 열어 읽음 | 🟢 **실측** |
| 앱 PostgreSQL | 사용자·주문·대화 | SQLAlchemy 모델 정의 | 🟡 **정의** |

🟡 가 붙는 이유는 하나다 — **모델에 그렇게 적혀 있다는 것이지, 실제 DB 가 그 모양이라는
뜻이 아니다.** 운영 DB 에 마이그레이션이 덜 돌았으면 실물은 다를 수 있다. 그래서 이
스크립트는 alembic 마이그레이션도 따로 읽어 **모델과 대조하고, 어긋나면 보고한다.**
대조가 통과해도 "실제 DB 를 봤다"가 되지는 않는다. 그건 `alembic check` 의 일이다.

한계 — 이 스크립트가 판정하지 않는 것
------------------------------------
- **값이 맞는지**는 보지 않는다. 칸이 있다는 것과 그 칸에 옳은 값이 들어 있다는 것은
  다르다(예: `price_adjusted.adj_clpr` 의 052670 오염 · Issue #55).
- **쓰이는지**도 보지 않는다. 아무도 읽지 않는 칸도 똑같이 세어 준다.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
수집기_DB = ROOT / "data" / "collector" / "market.sqlite3"
모델_디렉터리 = ROOT / "app" / "models"
ALEMBIC_디렉터리 = ROOT / "alembic" / "versions"


@dataclass
class 칸:
    이름: str
    타입: str
    널허용: bool
    기본값: str | None = None
    기본키: bool = False
    외래키: str | None = None      # "표.칸" 형식
    설명: str = ""                  # DDL 주석 또는 모델 소스 주석에서 추출


@dataclass
class 표:
    이름: str
    출처: str                       # "수집기" | "앱"
    확실도: str                     # "실측" | "정의"
    칸들: list[칸] = field(default_factory=list)
    행수: int | None = None         # 실측한 경우만. 정의만 아는 경우 None
    인덱스: list[str] = field(default_factory=list)
    설명: str = ""

    @property
    def 기본키칸(self) -> list[str]:
        return [c.이름 for c in self.칸들 if c.기본키]

    @property
    def 외래키들(self) -> list[tuple[str, str]]:
        """(내 칸, 상대 표.칸)"""
        return [(c.이름, c.외래키) for c in self.칸들 if c.외래키]


# ─────────────────────────────────────────────────────────────────────
# 1. 수집기 DB — 실제 SQLite 파일에서 읽는다 🟢 실측
# ─────────────────────────────────────────────────────────────────────

def _ddl_주석_추출(ddl: str) -> dict[str, str]:
    """CREATE TABLE 문에서 칸별 `-- 주석` 을 뽑는다.

    SQLite 는 CREATE 문을 **원문 그대로** 저장하므로 주석이 살아 있다. 이 프로젝트의
    DDL 은 칸 정의 오른쪽에 한국어 설명을 달아 두었고(`collector/db.py`), 그것이 곧
    데이터 사전의 설명 칸이 된다. 손으로 옮겨 적지 않는 이유가 이것이다.

    두 자리의 주석을 모두 본다:

    - **칸 줄 오른쪽** 주석 → 그 칸의 설명
    - **줄 전체가 주석**인 줄 → **바로 다음에 오는 칸**의 설명 (여러 줄이면 이어 붙임)

    🔴 앞 칸이 아니라 **다음 칸**이다. 첫 판에서 이것을 앞 칸에 붙였다가 `benchmark_index`
    의 설명이 한 칸씩 밀려, `variant` 칸에 `ret` 의 설명이 달렸다(2026-09-21). 이 DDL 은
    긴 설명을 칸 **위**에 적는 스타일이다.
    """
    설명: dict[str, str] = {}
    쌓인주석: list[str] = []
    for 줄 in ddl.splitlines():
        벗긴 = 줄.strip()
        if not 벗긴 or 벗긴.upper().startswith(("CREATE", "PRIMARY KEY", "UNIQUE", "FOREIGN KEY")):
            continue
        if 벗긴.startswith("--"):
            쌓인주석.append(벗긴.lstrip("-").strip())
            continue
        칸이름 = 벗긴.split()[0].strip('",')
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", 칸이름):
            쌓인주석 = []
            continue
        조각 = list(쌓인주석)
        쌓인주석 = []
        if "--" in 벗긴:
            조각.append(벗긴.split("--", 1)[1].strip())
        설명[칸이름] = " ".join(x for x in 조각 if x).strip()
    return 설명


def 수집기_스키마() -> list[표]:
    if not 수집기_DB.exists():
        return []
    conn = sqlite3.connect(f"file:{수집기_DB}?mode=ro", uri=True)
    표들: list[표] = []
    행 = conn.execute(
        "select name, sql from sqlite_master where type='table' "
        "and name not like 'sqlite_%' order by name"
    ).fetchall()
    for 표이름, ddl in 행:
        주석 = _ddl_주석_추출(ddl or "")
        칸들: list[칸] = []
        for _, 칸이름, 타입, 널아님, 기본값, pk in conn.execute(
            f'PRAGMA table_info("{표이름}")'
        ):
            칸들.append(칸(
                이름=칸이름, 타입=타입 or "?", 널허용=not 널아님,
                기본값=기본값, 기본키=bool(pk), 설명=주석.get(칸이름, ""),
            ))
        # 외래키 — 이 DB 는 선언하지 않지만, 있으면 읽는다
        for _, _, 상대표, 내칸, 상대칸, *_ in conn.execute(
            f'PRAGMA foreign_key_list("{표이름}")'
        ):
            for c in 칸들:
                if c.이름 == 내칸:
                    c.외래키 = f"{상대표}.{상대칸}"
        인덱스 = [r[1] for r in conn.execute(f'PRAGMA index_list("{표이름}")')
                  if not r[1].startswith("sqlite_autoindex")]
        행수 = conn.execute(f'select count(*) from "{표이름}"').fetchone()[0]
        표들.append(표(이름=표이름, 출처="수집기", 확실도="실측",
                      칸들=칸들, 행수=행수, 인덱스=sorted(인덱스)))
    conn.close()
    return 표들


def 수집기_정의와_실물_대조(수집기표들: list[표]) -> dict[str, Any]:
    """`collector/db.py` 의 SCHEMA 상수와 **실제 파일**을 맞대어 본다.

    상수에 없는 표가 실물에 있을 수 있다 — 다른 모듈이 따로 만든 경우다. 그런 표는
    스키마를 한곳에서 읽을 수 없다는 뜻이라 적어 둔다.
    """
    소스 = (ROOT / "collector" / "db.py").read_text(encoding="utf-8")
    상수표 = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", 소스))
    실물표 = {t.이름 for t in 수집기표들}
    기타: dict[str, str] = {}
    for p in sorted((ROOT / "collector").rglob("*.py")):
        if p.name == "db.py":
            continue
        for 이름 in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)",
                              p.read_text(encoding="utf-8")):
            기타[이름] = str(p.relative_to(ROOT)).replace("\\", "/")
    return {
        "db_py_상수": sorted(상수표),
        "실물": sorted(실물표),
        "상수에_없는_실물표": sorted(실물표 - 상수표),
        "다른_모듈이_만드는_표": 기타,
        "정의만_있고_실물없음": sorted(상수표 - 실물표),
    }


# ─────────────────────────────────────────────────────────────────────
# 2. 앱 DB — SQLAlchemy 모델 정의에서 읽는다 🟡 정의
# ─────────────────────────────────────────────────────────────────────

def _모델_주석_추출() -> dict[tuple[str, str], str]:
    """모델 소스에서 `칸: Mapped[...]` 줄의 주석을 (표, 칸) 으로 모은다.

    칸 **위 줄**의 `#` 주석과 **오른쪽** 주석을 모두 본다. 이 프로젝트는 위에 다는
    쪽이 많다(예: `orders.cost_basis`).
    """
    결과: dict[tuple[str, str], str] = {}
    for p in sorted(모델_디렉터리.glob("*.py")):
        현재표: str | None = None
        위주석: list[str] = []
        for 줄 in p.read_text(encoding="utf-8").splitlines():
            벗긴 = 줄.strip()
            m = re.match(r'__tablename__\s*=\s*["\'](\w+)["\']', 벗긴)
            if m:
                현재표, 위주석 = m.group(1), []
                continue
            if 벗긴.startswith("#"):
                위주석.append(벗긴.lstrip("#").strip())
                continue
            m = re.match(r"(\w+)\s*:\s*Mapped\[", 벗긴)
            if m and 현재표:
                설명 = " ".join(위주석)
                꼬리 = 줄.split("mapped_column", 1)[-1]
                if "#" in 꼬리:
                    설명 = (설명 + " " + 꼬리.rsplit("#", 1)[1].strip()).strip()
                if 설명:
                    결과[(현재표, m.group(1))] = 설명
            위주석 = []
    return 결과


def 앱_스키마() -> list[표]:
    sys.path.insert(0, str(ROOT))
    from app.models.base import Base                      # noqa: E402
    import app.models.user, app.models.trading            # noqa: E402,F401
    import app.models.paper, app.models.chat              # noqa: E402,F401
    import app.models.misc, app.models.reference          # noqa: E402,F401

    주석 = _모델_주석_추출()
    표들: list[표] = []
    for 이름, t in sorted(Base.metadata.tables.items()):
        칸들: list[칸] = []
        for c in t.columns:
            fk = None
            if c.foreign_keys:
                fk = next(iter(c.foreign_keys)).target_fullname
            기본값 = None
            if c.server_default is not None:
                기본값 = str(getattr(c.server_default, "arg", c.server_default))
            elif c.default is not None:
                기본값 = str(getattr(c.default, "arg", c.default))
            칸들.append(칸(
                이름=c.name, 타입=str(c.type), 널허용=c.nullable,
                기본값=기본값, 기본키=c.primary_key, 외래키=fk,
                설명=c.comment or 주석.get((이름, c.name), ""),
            ))
        인덱스 = sorted(i.name for i in t.indexes if i.name)
        표들.append(표(이름=이름, 출처="앱", 확실도="정의", 칸들=칸들, 인덱스=인덱스))
    return 표들


def _upgrade_본문(소스: str) -> str:
    """마이그레이션 파일에서 `upgrade()` 함수 본문만 잘라낸다.

    `downgrade()` 가 나오면 거기서 끊는다. 함수가 없으면 빈 문자열을 준다 —
    파일 전체를 돌려주면 `downgrade` 의 drop 이 섞여 상쇄된다.
    """
    m = re.search(r"^def upgrade\(", 소스, re.MULTILINE)
    if not m:
        return ""
    뒤 = 소스[m.end():]
    끝 = re.search(r"^def \w+\(", 뒤, re.MULTILINE)
    return 뒤[: 끝.start()] if 끝 else 뒤


def alembic_대조(앱표들: list[표]) -> dict[str, Any]:
    """마이그레이션이 만드는 표와 모델이 선언한 표를 맞대어 본다.

    ⚠️ **정적 파싱이다.** `op.create_table("x"` 같은 문자열을 세는 것이라, 변수로
    표 이름을 넘기거나 조건문 안에서 만들면 놓친다. 그래서 이 대조가 통과해도
    "실제 DB 가 모델과 같다"는 뜻이 되지 않는다 — 그 판정은 `alembic check` 의 일이다.

    🔴 **`upgrade()` 본문만 읽는다.** 마이그레이션 파일에는 `downgrade()` 가 함께 있고
    거기에는 방금 만든 표를 되돌리는 `op.drop_table` 이 그대로 들어 있다. 파일 전체를
    세면 만든 것과 지운 것이 **전부 상쇄되어 "만드는 표 0개"** 가 나온다. 2026-09-21
    이 스캐너의 첫 판에서 실제로 그렇게 나왔고, 26개 표가 몽땅 "마이그레이션에 없음"
    으로 잘못 보고됐다.
    """
    만든표: set[str] = set()
    지운표: set[str] = set()
    파일들 = sorted(ALEMBIC_디렉터리.glob("*.py"))
    for p in 파일들:
        전체 = p.read_text(encoding="utf-8")
        소스 = _upgrade_본문(전체)
        만든표 |= set(re.findall(r'op\.create_table\(\s*["\'](\w+)["\']', 소스))
        지운표 |= set(re.findall(r'op\.drop_table\(\s*["\'](\w+)["\']', 소스))
    모델표 = {t.이름 for t in 앱표들}
    남은표 = 만든표 - 지운표
    return {
        "마이그레이션_파일": [p.name for p in 파일들],
        "마이그레이션이_만드는_표": sorted(남은표),
        "모델이_선언한_표": sorted(모델표),
        "모델에만_있음": sorted(모델표 - 남은표),
        "마이그레이션에만_있음": sorted(남은표 - 모델표),
        "일치": sorted(모델표 & 남은표),
    }


# ─────────────────────────────────────────────────────────────────────
# 3. 출력
# ─────────────────────────────────────────────────────────────────────

def 논리관계_추론(표들: list[표]) -> list[dict[str, Any]]:
    """선언되지 않은 관계를 **칸 이름으로** 추론한다.

    수집기 DB 는 외래키를 하나도 선언하지 않는다. 대량 적재를 순서와 무관하게 하려면
    제약이 방해가 되기 때문인데, 그 대가로 **표끼리 어떻게 이어지는지가 스키마에
    적혀 있지 않다.** 실제로는 `srtn_cd`(종목코드)와 `bas_dt`(기준일)로 이어져 있다.

    그래서 여러 표의 **기본키에 공통으로 나타나는 칸**을 연결 축으로 본다.

    ⚠️ **이것은 추론이지 선언이 아니다.** 같은 이름이라고 같은 뜻이라는 보장은 DB 에
    없다. 값이 실제로 맞물리는지는 이 스크립트가 보지 않는다 — 이름만 본다.
    """
    축: dict[str, list[str]] = {}
    for t in 표들:
        for c in t.칸들:
            if c.기본키:
                축.setdefault(c.이름, []).append(t.이름)
    return [{"칸": 칸이름, "표": sorted(표목록), "표수": len(표목록)}
            for 칸이름, 표목록 in sorted(축.items())
            if len(표목록) >= 2]


def _타입짧게(t: str) -> str:
    return t.replace("DOUBLE PRECISION", "FLOAT").replace("CHARACTER VARYING", "VARCHAR")


def 사람용출력(수집기: list[표], 앱: list[표], 대조1: dict, 대조2: dict) -> None:
    print("― 데이터베이스 스키마 실측 ―\n")
    총행 = sum(t.행수 or 0 for t in 수집기)
    총칸_수 = sum(len(t.칸들) for t in 수집기)
    총칸_앱 = sum(len(t.칸들) for t in 앱)
    print(f"  수집기 SQLite  🟢 실측   표 {len(수집기):>2}개 · 칸 {총칸_수:>3}개 · {총행:>12,}행")
    print(f"  앱 PostgreSQL  🟡 정의   표 {len(앱):>2}개 · 칸 {총칸_앱:>3}개 · 행수는 모델로 알 수 없음\n")

    print(f"  {'표':26} {'칸':>3} {'행':>12}  대표 설명")
    print("  " + "─" * 92)
    for t in 수집기:
        설명 = next((c.설명 for c in t.칸들 if c.설명), "")[:40]
        print(f"  {t.이름:26} {len(t.칸들):>3} {t.행수:>12,}  {설명}")
    print()
    for t in 앱:
        설명 = next((c.설명 for c in t.칸들 if c.설명), "")[:40]
        print(f"  {t.이름:26} {len(t.칸들):>3} {'—':>12}  {설명}")
    print()

    print("  ― 설명이 붙어 있는 칸 ―")
    print("  (DDL 주석·모델 주석에서 자동으로 딸려 온다. 코드에 주석이 없으면 사전도 빈칸이다)")
    for 이름, 표들 in (("수집기", 수집기), ("앱", 앱)):
        칸전부 = [c for t in 표들 for c in t.칸들]
        있음 = [c for c in 칸전부 if c.설명.strip()]
        빈표 = [t.이름 for t in 표들 if not any(c.설명.strip() for c in t.칸들)]
        비율 = len(있음) * 100 // len(칸전부) if 칸전부 else 0
        print(f"  {이름:5} {len(있음):>3}/{len(칸전부):<3} ({비율:>2}%)"
              f"   설명이 한 칸도 없는 표 {len(빈표)}개")
    print()

    print("  ― 정의와 실물이 어긋나는 곳 ―")
    어긋남 = False
    if 대조1.get("상수에_없는_실물표"):
        어긋남 = True
        for 이름 in 대조1["상수에_없는_실물표"]:
            만든곳 = 대조1["다른_모듈이_만드는_표"].get(이름, "찾지 못함")
            print(f"  ⚠️ `{이름}` — collector/db.py SCHEMA 에 없다. 만드는 곳: {만든곳}")
    if 대조1.get("정의만_있고_실물없음"):
        어긋남 = True
        print(f"  ⚠️ SCHEMA 에는 있는데 실물에 없는 표: "
              f"{', '.join(대조1['정의만_있고_실물없음'])}")
    if 대조2.get("모델에만_있음"):
        어긋남 = True
        print(f"  ⚠️ 모델에만 있고 마이그레이션이 만들지 않는 표 "
              f"({len(대조2['모델에만_있음'])}개):")
        print(f"     {', '.join(대조2['모델에만_있음'])}")
    if 대조2.get("마이그레이션에만_있음"):
        어긋남 = True
        print(f"  ⚠️ 마이그레이션에만 있고 모델에 없는 표: "
              f"{', '.join(대조2['마이그레이션에만_있음'])}")
    if not 어긋남:
        print("  ✅ 어긋나는 곳 없음")
    print()
    print("  ⚠️ 이 출력은 「칸이 있는가」이지 「값이 옳은가」가 아니다.")
    print("     값 오염은 따로 본다 (예: price_adjusted.adj_clpr · Issue #55).")


def 사전마크다운(수집기: list[표], 앱: list[표]) -> None:
    총행 = sum(t.행수 or 0 for t in 수집기)
    print("> 실측: `python scripts/schema_scan.py --md`")
    print(f"> 수집기 {len(수집기)}표 {총행:,}행 🟢 실측 · 앱 {len(앱)}표 🟡 모델 정의")
    for 구역, 표들, 배지 in (("수집기 DB (SQLite)", 수집기, "🟢 실측"),
                              ("앱 DB (PostgreSQL)", 앱, "🟡 정의")):
        print(f"\n## {구역} — {배지}")
        for t in 표들:
            행 = f" · **{t.행수:,}행**" if t.행수 is not None else ""
            print(f"\n### `{t.이름}`{행}\n")
            if t.기본키칸:
                print(f"기본키: {' + '.join(f'`{c}`' for c in t.기본키칸)}\n")
            print("| 칸 | 타입 | NULL | 기본값 | 키 | 설명 |")
            print("|---|---|:--:|---|:--:|---|")
            for c in t.칸들:
                키 = "PK" if c.기본키 else ("FK" if c.외래키 else "")
                기본값 = f"`{c.기본값}`" if c.기본값 else ""
                널 = "" if c.널허용 else "NOT NULL"
                설명 = c.설명.replace("|", "\\|")
                if c.외래키:
                    설명 = (f"→ `{c.외래키}` " + 설명).strip()
                print(f"| `{c.이름}` | {_타입짧게(c.타입)} | {널} | {기본값} | {키} | {설명} |")
            if t.인덱스:
                print(f"\n인덱스: {', '.join(f'`{i}`' for i in t.인덱스)}")


def erd출력(수집기: list[표], 앱: list[표]) -> None:
    """Mermaid ERD. 칸이 너무 많으면 읽을 수 없으므로 **키와 대표 칸만** 그린다.

    전체 칸은 데이터 사전이 맡는다. 여기서 보여야 하는 것은 *표끼리 어떻게 이어지는가*다.
    """
    for 제목, 표들 in (("수집기 DB — 시세·배당·지수 🟢 실측", 수집기),
                        ("앱 DB — 사용자·주문·대화 🟡 모델 정의", 앱)):
        print(f"\n### {제목}\n")
        print("```mermaid")
        print("erDiagram")
        for t in 표들:
            print(f"  {t.이름} {{")
            보일칸 = [c for c in t.칸들 if c.기본키 or c.외래키][:6]
            보인이름 = {c.이름 for c in 보일칸}
            나머지 = [c for c in t.칸들 if c.이름 not in 보인이름][:4]
            for c in 보일칸 + 나머지:
                타입 = re.sub(r"\W+", "_", _타입짧게(c.타입)).strip("_")[:16] or "x"
                키 = "PK" if c.기본키 else ("FK" if c.외래키 else "")
                print(f"    {타입} {c.이름} {키}".rstrip())
            숨김 = len(t.칸들) - len(보일칸) - len(나머지)
            if 숨김 > 0:
                print(f"    _ 외{숨김}칸")
            print("  }")
        for t in 표들:
            for 내칸, 상대 in t.외래키들:
                상대표 = 상대.split(".")[0]
                print(f'  {상대표} ||--o{{ {t.이름} : "{내칸}"')
        print("```")
        축 = 논리관계_추론(표들)
        if 축 and not any(t.외래키들 for t in 표들):
            print("\n이 DB 는 **외래키를 선언하지 않는다.** 위 그림에 연결선이 없는 이유다. "
                  "실제로는 아래 칸들이 표를 잇는 축이다 — 선언이 아니라 **이름으로 추론한 것**이다.\n")
            print("| 연결 축 | 이 칸을 기본키로 쓰는 표 |")
            print("|---|---|")
            for a in 축:
                print(f"| `{a['칸']}` ({a['표수']}표) | {', '.join(f'`{n}`' for n in a['표'])} |")


def main() -> int:
    ap = argparse.ArgumentParser(description="DB 스키마 실측 추출기")
    ap.add_argument("--md", action="store_true", help="데이터 사전용 마크다운")
    ap.add_argument("--erd", action="store_true", help="Mermaid ERD")
    ap.add_argument("--json", action="store_true", help="JSON")
    args = ap.parse_args()

    수집기 = 수집기_스키마()
    앱 = 앱_스키마()
    대조1 = 수집기_정의와_실물_대조(수집기) if 수집기 else {}
    대조2 = alembic_대조(앱)

    if args.json:
        print(json.dumps({
            "수집기": [asdict(t) for t in 수집기],
            "앱": [asdict(t) for t in 앱],
            "수집기_대조": 대조1, "alembic_대조": 대조2,
        }, ensure_ascii=False, indent=2))
    elif args.md:
        사전마크다운(수집기, 앱)
    elif args.erd:
        erd출력(수집기, 앱)
    else:
        사람용출력(수집기, 앱, 대조1, 대조2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
