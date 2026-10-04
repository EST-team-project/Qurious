"""크롤 조각의 벡터 DB 점 ID 와 옛 점 정리.

왜 따로 두나
    크롤링한 글은 `app/services/crawl.py`(강사님 기초 코드)의 `_store_qdrant` 가 조각마다 Qdrant 점 하나로 넣는다.
    예전에는 점 ID 를 파이썬 내장 ``hash()`` 로 만들었는데, 이 값은 프로세스마다 다르다(PYTHONHASHSEED).
    그래서 앱을 다시 켜고 같은 글을 다시 모으면 **같은 조각이 새 점으로 하나 더 쌓였다** — 2026-09-17 옛 분석
    A11(크롤링 · 인제스트)이 PYTHONHASHSEED 0 · 1 · 2 에서 값이 셋 다 다른 것을 재고 적어 둔 결함이다.
    수집 DB 쪽(`crawled_docs`)은 주소를 키로 덮어쓰는데 벡터 DB 만 쌓여, 채팅 근거 검색에 같은 글이 여러 번 걸렸다.

    강사님 파일에는 부르는 줄만 두고 규칙은 이 파일에 둔다 — 다음 기초 코드 반영(3-way) 때 부딪히는 줄을 줄이려고.

규칙
    점 ID = sha256(주소 · 조각 번호) 앞 15자를 정수로. 근거 문서 색인(`kb_text.chunk_id`) · 번역 적재
    (`translation_ingest._chunk_id`)와 같은 생각이다 — 내용이 아니라 **자리**(어느 주소의 몇째 조각)로 만든다.
    15자 = 60비트라 Qdrant 정수 ID(부호 없는 64비트)에 들어간다.

    같은 주소를 다시 모으면 이번에 쓴 점만 남기고 나머지(글이 짧아져 남은 꼬리 · 예전 hash() ID 로 쌓인 중복)를
    지운다. 이번에 쓴 점이 하나도 없으면(임베딩 서버가 꺼져 전부 실패) 지우지 않는다 — 옛 근거라도 남기는 편이
    「모으다 실패해서 근거가 사라짐」 보다 낫다.
"""
from __future__ import annotations

import hashlib


def crawl_point_id(url: str, chunk_index: int) -> int:
    """크롤 조각의 Qdrant 점 ID — 같은 주소의 같은 번째 조각은 어느 프로세스에서나 같은 값."""
    raw = f"{url}\x1f{chunk_index}"   # \x1f(단위 구분 문자) — 주소 끝 숫자와 조각 번호가 붙어 같은 글자가 되는 것을 막는다
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:15], 16)


async def prune_stale_points(client, collection: str, url: str, keep_ids: list[int]) -> None:
    """같은 주소의 점 가운데 이번에 쓰지 않은 것을 지운다.

    거르는 키는 크롤 조각 payload 의 맨 위 ``url`` 이다(`_store_qdrant` 가 meta 를 펼쳐 넣는다). 문서 올리기(LangChain)가
    넣는 점은 payload 가 ``metadata`` 아래에 있어 이 거름에 걸리지 않는다 — 같은 컬렉션이라도 서로 지우지 않는다.
    """
    if not url or not keep_ids:
        return
    from qdrant_client.http.models import FieldCondition, Filter, FilterSelector, HasIdCondition, MatchValue

    await client.delete(
        collection_name=collection,
        points_selector=FilterSelector(filter=Filter(
            must=[FieldCondition(key="url", match=MatchValue(value=url))],
            must_not=[HasIdCondition(has_id=keep_ids)],
        )),
    )
