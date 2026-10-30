"""전략 공급원: 기본은 domain-rag-lab HTTP API, 명시한 fixed_test는 가상계좌 고정 입력.

종목 선정 화면의 전략 드롭다운(list_strategies)과 사이클의 규칙 평가(get_strategy)가 사용한다.
원격이 없거나 실패해도 시험 입력으로 자동 대체하지 않는다. 선택한 공급원에서 카드를 못 읽으면 None/[]다.
"""
from __future__ import annotations

import logging
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, Any]] = {}
_transport: httpx.AsyncBaseTransport | None = None
_FIXED_CARD = Path(__file__).resolve().parents[2] / "docs/phase-3/02-design/system/예시/strategy-card-ma-cross-v1.json"
_FIXED_SHA256 = "50e0429740078e0b19aaa458cb394faefecc6e75073531f2fae985a87e8a0583"


def is_fixed_test() -> bool:
    return settings.STRATEGY_SPEC_SOURCE == "fixed_test"


def _fixed_card() -> dict | None:
    # 고정 입력을 합격 전략으로 취급하거나 같은 판의 규칙을 조용히 바꾸지 않는다.
    try:
        raw = _FIXED_CARD.read_bytes()
        if hashlib.sha256(raw).hexdigest() != _FIXED_SHA256:
            return None
        return json.loads(raw)
    except (OSError, ValueError):
        return None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def is_configured() -> bool:
    if is_fixed_test():
        return _fixed_card() is not None
    return bool(settings.DOMAIN_RAG_LAB_BASE_URL)


def clear_cache() -> None:
    _cache.clear()


async def _get(path: str) -> Any | None:
    if is_fixed_test() or not is_configured():
        return None
    now = time.time()
    hit = _cache.get(path)
    if hit and hit[0] > now:
        return hit[1]
    headers = {"Accept": "application/json"}
    if settings.DOMAIN_RAG_LAB_API_KEY:
        headers["X-API-Key"] = settings.DOMAIN_RAG_LAB_API_KEY
    try:
        async with httpx.AsyncClient(base_url=settings.DOMAIN_RAG_LAB_BASE_URL.rstrip("/"), headers=headers, timeout=10, transport=_transport) as cli:
            response = await cli.get(path)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("domain-rag-lab 전략 API 실패 (%s): %s", path, exc)
        return None  # 만료된 카드를 주문 판단에 다시 사용하지 않는다.
    _cache[path] = (now + max(0, settings.STRATEGY_SPEC_CACHE_TTL), data)
    return data


async def list_strategies() -> list[dict[str, Any]]:
    if is_fixed_test():
        card = _fixed_card()
        return [{**card, "test_only": True, "source": "fixed_test"}] if card else []
    data = await _get("/backtests/strategies")
    return list((data or {}).get("strategies") or [])


async def get_strategy(strategy_id: str, version: int | None = None) -> dict[str, Any] | None:
    if not strategy_id:
        return None
    if is_fixed_test():
        card = _fixed_card()
        if (card and strategy_id == card["strategy_id"]
                and (version is None or type(version) is int and version == card["version"])):
            return card
        return None
    path = f"/backtests/strategies/{strategy_id}" + (f"/versions/{version}" if version else "")
    data = await _get(path)
    if not isinstance(data, dict) or data.get("strategy_id") != strategy_id:
        return None
    if type(data.get("version")) is not int or data["version"] < 1:
        return None
    if version is not None and data["version"] != version:
        return None
    return data
