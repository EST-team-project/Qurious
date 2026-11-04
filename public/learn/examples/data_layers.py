"""원문 · 정제 · 파생 세 층 — 원문을 지문과 함께 남기면 정규화가 틀려도 다시 만들 수 있다는 것을 보이는 예제.

실행    python data_layers.py        (표준 라이브러리만 · 네트워크 없음)
자료    모두 합성 — 종목 코드 111111 · 222222 와 가격은 손으로 정한 값이다(실제 시세가 아니다)
구성    원문 층 raw   응답 바이트를 그대로 압축해 두고, 압축 전 바이트의 sha256 을 함께 둔다
        정제 층 silver 원문을 규칙대로 읽어 만든 표 — 한 행마다 어느 원문에서 나왔는지(raw_sha256)를 둔다
        파생 층 gold   정제 표에서 계산한 일수익률 — 정제 표를 덮어쓰지 않고 따로 둔다

흐름    ① 같은 입력은 같은 지문   ② 정규화 규칙이 틀렸을 때 원문에서 다시 정제   ③ 파생 표는 지우고 다시 만들어도 같다
        ④ 원문이 조용히 바뀌면 지문이 잡는다   ⑤ 지문이 같다고 값이 옳은 것은 아니다
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3


def make_body(close_a: str, close_b: str, dt: str) -> bytes:
    """출처가 내려주는 응답을 흉내 낸다 — 종가는 문자열이고 천 단위 쉼표가 섞여 온다."""
    items = [
        {"basDt": dt, "srtnCd": "111111", "clpr": close_a},
        {"basDt": dt, "srtnCd": "222222", "clpr": close_b},
    ]
    return json.dumps({"items": items}, ensure_ascii=False).encode("utf-8")


def open_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript("""
    CREATE TABLE raw    (target TEXT PRIMARY KEY, body BLOB, sha256 TEXT);
    CREATE TABLE silver (dt TEXT, code TEXT, close INTEGER, raw_sha256 TEXT, PRIMARY KEY (dt, code));
    CREATE TABLE gold   (dt TEXT, code TEXT, ret REAL, PRIMARY KEY (dt, code));
    """)
    return con


def save_raw(con: sqlite3.Connection, target: str, body: bytes) -> str:
    """응답 바이트 그대로 + 압축 전 바이트의 지문. mtime=0 이라 같은 입력은 같은 압축 바이트가 나온다."""
    digest = hashlib.sha256(body).hexdigest()
    con.execute("INSERT OR REPLACE INTO raw VALUES (?,?,?)", (target, gzip.compress(body, mtime=0), digest))
    return digest


def load_raw(con: sqlite3.Connection, target: str) -> tuple[bytes, str]:
    """꺼낼 때마다 지문을 다시 계산한다. 다르면 조용히 넘어가지 않고 멈춘다."""
    packed, digest = con.execute("SELECT body, sha256 FROM raw WHERE target=?", (target,)).fetchone()
    body = gzip.decompress(packed)
    if hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("원문 손상")
    return body, digest


def normalize_v1(body: bytes):
    """일부러 틀린 규칙 — 쉼표가 든 값은 읽지 못하고 0 으로 둔다."""
    for it in json.loads(body)["items"]:
        c = it["clpr"]
        yield it["basDt"], it["srtnCd"], int(c) if c.isdigit() else 0


def normalize_v2(body: bytes):
    """고친 규칙 — 쉼표를 지우고 읽는다."""
    for it in json.loads(body)["items"]:
        yield it["basDt"], it["srtnCd"], int(it["clpr"].replace(",", ""))


def build_silver(con: sqlite3.Connection, normalize) -> None:
    """정제 표를 원문에서 통째로 다시 만든다. 네트워크를 타지 않는다."""
    con.execute("DELETE FROM silver")
    for (target,) in con.execute("SELECT target FROM raw ORDER BY target").fetchall():
        body, digest = load_raw(con, target)
        for dt, code, close in normalize(body):
            con.execute("INSERT OR REPLACE INTO silver VALUES (?,?,?,?)", (dt, code, close, digest))


def build_gold(con: sqlite3.Connection) -> None:
    """파생 표는 정제 표만 읽는다. 지우고 다시 만들어도 같은 값이 나와야 한다."""
    con.execute("DELETE FROM gold")
    prev: dict[str, int] = {}
    for dt, code, close in con.execute("SELECT dt, code, close FROM silver ORDER BY dt, code").fetchall():
        before = prev.get(code)
        ret = None if not before else round(close / before - 1, 4)     # 앞 종가가 0 이면 계산하지 않는다
        if before is not None:
            con.execute("INSERT INTO gold VALUES (?,?,?)", (dt, code, ret))
        prev[code] = close


def show_gold(con: sqlite3.Connection) -> list:
    return con.execute("SELECT code, ret FROM gold ORDER BY code").fetchall()


def main() -> None:
    con = open_db()
    # 합성 응답 두 날치 — 111111 의 종가에는 천 단위 쉼표가 들어 있다
    d1 = save_raw(con, "price/20261102", make_body("70,000", "180000", "20261102"))
    save_raw(con, "price/20261103", make_body("71,400", "177000", "20261103"))
    again = hashlib.sha256(make_body("70,000", "180000", "20261102")).hexdigest()
    print(f"① 같은 입력의 지문이 같다: {d1 == again} | 지문 길이 {len(d1)}")

    build_silver(con, normalize_v1)
    build_gold(con)
    print("② 규칙 v1 (쉼표 값을 0 으로 읽음)")
    print("  정제 표 종가", con.execute("SELECT code, close FROM silver WHERE dt='20261102'").fetchall())
    print("  파생 표 일수익률", show_gold(con))

    build_silver(con, normalize_v2)              # 규칙을 고치고 원문에서 다시 — 다시 받지 않는다
    build_gold(con)
    print("  규칙 v2 로 원문에서 다시 정제한 뒤")
    print("  정제 표 종가", con.execute("SELECT code, close FROM silver WHERE dt='20261102'").fetchall())
    print("  파생 표 일수익률", show_gold(con))

    first = show_gold(con)
    build_gold(con)                              # 파생 표만 지우고 다시 만든다
    print(f"③ 파생 표를 지우고 다시 만들어도 같다: {first == show_gold(con)}")

    lineage = con.execute("SELECT DISTINCT raw_sha256 FROM silver WHERE dt='20261102'").fetchone()[0]
    print(f"  정제 행에서 원문으로 거슬러 가기: {lineage == d1}")

    # ④ 원문이 조용히 바뀌었다 — 압축은 멀쩡하지만 내용이 다른 바이트로 바뀌었고 지문은 그대로다
    swapped = make_body("70,000", "999999", "20261102")
    con.execute("UPDATE raw SET body=? WHERE target='price/20261102'", (gzip.compress(swapped, mtime=0),))
    try:
        load_raw(con, "price/20261102")
    except ValueError as exc:
        print(f"④ 바뀐 원문을 꺼내면: {exc}")

    # ⑤ 처음부터 틀린 값을 받았다면 지문도 그 틀린 값의 것이다
    wrong = make_body("70,000", "-5", "20261104")
    save_raw(con, "price/20261104", wrong)
    body, _ = load_raw(con, "price/20261104")
    print(f"⑤ 지문 검사는 통과한다: {body == wrong} | 그래도 종가 -5 는 옳은 값이 아니다")


if __name__ == "__main__":
    main()
