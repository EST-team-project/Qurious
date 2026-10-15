"""모델 비교 API — /api/model-compare (화면 키 `ml-compare` · ML·딥러닝 › 모델 비교 · 2026-10-15)

한 종목의 수집 일봉(수정주가)으로 강사님 모델 8개와 기준선 넷을 시간 순서 검증(워크포워드 · 간격)으로 견준다 —
겹별 점수 · 균형 정확도 · 기준선별 차이 · 95% 구간 · 판정(기준선 셋 모두보다 뚜렷할 때만) · 쉬운 문장 · 출처 · 고지.

- GET  /api/model-compare            : 기다렸다가 결과만(스크립트 · 점검용) — 아래 작업 · 캐시를 같이 쓴다
- GET  /api/model-compare/choices    : 화면이 고르는 값(기간 · 관리자 손잡이 범위)과 관리자 여부 — 계산하지 않는다
- POST /api/model-compare/jobs       : 계산 시작 — 자료 지문이 같은 저장본이 있으면 곧바로 결과(200), 없으면 앱 안 작업(202)
- GET  /api/model-compare/jobs/{id}  : 진행(모델 k / 8 · 겹 f / 5 · 지난 시간 · 보통 시간) · 끝나면 결과

옛 화면은 강사님 `GET /api/ml/compare`(교차검증이 미래 자료로 학습 · 기준선 없음 · 「7종」 인데 모델 8개)를 불렀다 —
그 길은 강사님 코드라 그대로 두고 화면만 이 API 로 옮긴다. 계산 · 문장 · 기준값 · 인자 검사는 `app/services/model_compare.py`,
작업 · 캐시는 `app/services/model_compare_jobs.py` 한 곳. 로그인한 사람만 · 겹 수 · 간격은 관리자만(서비스가 403) ·
할 일(명령)은 관리자 답에만 · 계산을 띄우는 POST 는 화면 머리글이 있어야 한다(SameSite 쿠키 위에 한 겹 더).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.lib.session import get_current_user
from app.services import model_compare, model_compare_jobs

router = APIRouter(prefix="/api/model-compare", tags=["model-compare"])

_SPLITS = model_compare.N_SPLITS_RANGE
ACTION_HEADER = "X-Qurious-Action"
ACTION_VALUE = "model-compare"
_SYMBOL_DOC = "국내 주식 6자리 종목 코드(.KS · .KQ 를 붙여도 된다)"
_PERIOD_DOC = f"{' · '.join(model_compare.PERIODS)} — 1y 는 계산만 하고 판정하지 않는다(시험 자료가 적음)"
_SPLITS_DOC = f"겹 수 — 관리자만 · {_SPLITS[0]} ~ {_SPLITS[1]} · 비우면 {model_compare.N_SPLITS}"
_GAP_DOC = (f"학습 끝과 시험 시작 사이 비우는 거래일 — 관리자만 · 라벨 기간 − 1 ~ {model_compare.GAP_MAX} · "
            f"비우면 라벨 기간({model_compare.HORIZON})")


class ModelCompareJobBody(BaseModel):
    symbol: str = Field("005930", max_length=12, description=_SYMBOL_DOC)
    period: str = Field("2y", max_length=3, description=_PERIOD_DOC)
    n_splits: Optional[int] = Field(None, description=_SPLITS_DOC)
    gap: Optional[int] = Field(None, description=_GAP_DOC)


def _admin(user) -> bool:
    return "admin" in user.get("roles", [])


def _require_screen_action(
    request: Request,
    x_qurious_action: Optional[str] = Header(None, alias=ACTION_HEADER, description=f"화면에서 보낸 요청 표시 — 값 「{ACTION_VALUE}」"),
):
    # 계산을 띄우는 요청에만 — 다른 사이트의 폼 · 단순 요청은 이 머리글을 붙일 수 없다(수집 요청과 같은 꼴 · OWASP CSRF)
    if x_qurious_action != ACTION_VALUE:
        raise HTTPException(403, {"code": "screen_only", "message": f"화면에서 보낸 요청만 받습니다 — {ACTION_HEADER}: "
                                                                    f"{ACTION_VALUE} 머리글이 필요합니다"})
    site = request.headers.get("sec-fetch-site")
    if site and site != "same-origin":
        raise HTTPException(403, {"code": "cross_site", "message": "다른 사이트에서 온 요청은 받지 않습니다"})


@router.get("", summary="모델 비교 — 기다렸다가 결과(시간 순서 검증 · 기준선 넷 · 판정 · 수집 시세 · 저장본 재사용)")
async def model_compare_route(
    symbol: str = Query("005930", max_length=12, description=_SYMBOL_DOC),
    period: str = Query("2y", max_length=3, description=_PERIOD_DOC),   # 3 — 「6mo」 · 「10y」 도 서비스까지 와서 우리 말로 422
    n_splits: Optional[int] = Query(None, description=_SPLITS_DOC),
    gap: Optional[int] = Query(None, description=_GAP_DOC),
    user=Depends(get_current_user),
):
    admin = _admin(user)
    try:
        return await model_compare_jobs.compute(symbol, period, n_splits, gap, admin)
    except model_compare.ModelCompareError as e:
        raise HTTPException(status_code=e.status, detail=e.detail(admin)) from None


@router.get("/choices", summary="모델 비교 — 고르기 값(기간 · 관리자 손잡이 범위)과 관리자 여부")
async def model_compare_choices(user=Depends(get_current_user)):
    return {"choices": model_compare.choices(), "admin": _admin(user), "model_count": len(model_compare.MODEL_NAMES)}


@router.post("/jobs", summary="모델 비교 계산 시작 — 저장본이 맞으면 결과(200) · 아니면 앱 안 작업(202)")
async def model_compare_job_start(body: ModelCompareJobBody, response: Response, user=Depends(get_current_user),
                                  _screen=Depends(_require_screen_action)):
    admin = _admin(user)
    try:
        out = await model_compare_jobs.start(body.symbol, body.period, body.n_splits, body.gap, admin)
    except model_compare.ModelCompareError as e:
        raise HTTPException(status_code=e.status, detail=e.detail(admin)) from None
    response.status_code = 200 if out["status"] == "done" else 202
    return out


@router.get("/jobs/{job_id}", summary="모델 비교 계산 진행 — 몇째 모델 · 몇째 겹(실제로 센 값) · 지난 시간 · 끝나면 결과")
async def model_compare_job_status(job_id: str, user=Depends(get_current_user)):
    admin = _admin(user)
    try:
        return model_compare_jobs.status(job_id)
    except model_compare.ModelCompareError as e:
        raise HTTPException(status_code=e.status, detail=e.detail(admin)) from None
