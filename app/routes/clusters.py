"""종목 군집화 API — /api/clusters (화면 키 `ml-cluster` · ML·딥러닝 › 종목 군집화 · 2026-10-14)

- GET /api/clusters : 자동매매 31종목(업종과 견줌) 또는 분봉 수집 종목(401 — ETF 제외)을 지난 1 · 2 · 3년 총수익 일간 수익률로
  묶는다 — 같이 움직인 묶음(상관 거리 · 계층 군집) 또는 위험 · 수익 특성 묶음(KMeans) · 실루엣으로 묶음 수 · 지도 · 쉬운 문장

옛 화면은 강사님 `POST /api/ml/cluster`(기술 지표 평균 KMeans k=3 고정 · 종목마다 시세를 차례로 불러 약 20초)를 불렀다 —
그 길은 강사님 코드라 그대로 두고 화면만 이 API 로 옮긴다. 계산 · 문장 · 기준값은 `app/services/stock_clusters.py` 한 곳.
로그인한 사람만 · 할 일(명령)은 관리자 답에만.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.lib.session import get_current_user
from app.services import stock_clusters

router = APIRouter(prefix="/api/clusters", tags=["clusters"])


@router.get("", summary="종목 군집화 — 같이 움직인 묶음 · 위험 · 수익 특성 묶음(수집 시세)")
async def clusters_route(
    universe: str = Query("quant31", max_length=8, description="quant31(자동매매 31종목 · 업종과 견줌) · u401(분봉 수집 종목)"),
    period: str = Query("3y", max_length=2, description="1y · 2y · 3y — 기본 3년(묶음이 업종 꼴로 또렷한 편 · Figma 결정 그림과 같은 기본)"),
    method: str = Query("movement", max_length=8, description="movement(같이 움직임 · 상관 거리) · profile(위험 · 수익 특성)"),
    k: int = Query(0, ge=0, le=stock_clusters.K_MAX, description="묶음 수 — 0 이면 실루엣 점수가 가장 높은 값"),
    user=Depends(get_current_user),
):
    admin = "admin" in user.get("roles", [])
    try:
        return await asyncio.to_thread(stock_clusters.read_clusters, universe, period, method, k, admin)
    except stock_clusters.ClusterError as e:
        raise HTTPException(status_code=e.status, detail=e.detail(admin)) from None
