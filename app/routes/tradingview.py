"""TradingView 연동 API.

- POST /api/webhooks/tradingview        : TradingView 알림 Webhook 수신 (세션 불필요, 본문 token=API 키)
- GET  /api/tradingview/webhook-info     : Webhook URL·알림 메시지 템플릿
- GET  /api/tradingview/signals          : 수신 신호 이력
- POST /api/tradingview/compare          : Strategy Tester 결과 ↔ LEAN 백테스트 교차 검증
- GET  /api/tradingview/comparisons      : 비교 이력
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.postgres import get_pg_session
from app.lib.jwt_auth import get_current_user_any
from app.models import StrategyComparison
from app.services import notification
from app.services import tradingview as tv
from app.services import xval_ledger
from app.services.audit import audit
from app.services.lean_backtest import STRATEGY_LABELS, LeanBacktestError, service as lean_service
from app.routes.openapi import _check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tradingview"])


def _uid(user: dict) -> uuid.UUID:
    return uuid.UUID(str(user["id"]))


def _paper_initial_cash() -> float | None:
    """모의투자 시작 금액(오준영 님 자동매매 모듈의 상수) — 읽기만 한다. 못 읽으면 None."""
    try:
        from app.services import auto_trade
        return float(auto_trade._INITIAL_CAPITAL)
    except Exception:
        logger.warning("모의투자 시작 금액을 읽지 못했습니다", exc_info=True)
        return None


def _log_reject(code: str, status: int, message: str, ip: str | None = None) -> None:
    """거부한 요청을 남긴다 — 보낸 쪽 주소와 까닭만. token 은 어떤 경우에도 적지 않는다(설계 3.6 #1)."""
    logger.warning("tradingview webhook %s status=%s ip=%s: %s", code, status, ip or "-", message)


async def _read_body(request: Request, limit: int) -> bytes:
    """본문을 limit 바이트까지만 읽는다 — Content-Length 를 속이거나 쪼개 보내도(chunked) 넘으면 413."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, {"error": "PAYLOAD_TOO_LARGE", "message": f"본문이 {limit}바이트를 넘습니다."})
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, {"error": "PAYLOAD_TOO_LARGE", "message": f"본문이 {limit}바이트를 넘습니다."})
    return bytes(buf)


async def _after_response(result: dict) -> None:
    """응답을 돌려준 뒤에 하는 일 — 감사 기록과 사용자 알림. 느린 채널이 TradingView 의 3초 제한을 넘기지 않게 한다(설계 3.6 #7)."""
    sig = result["signal"]
    try:
        await audit(result["user_id"], "", "tradingview.webhook", {k: sig[k] for k in ("symbol", "side", "quantity", "status")})
    except Exception as exc:  # 기록 실패가 응답을 바꾸지 않는다
        logger.warning("tradingview webhook audit 실패: %s", exc)
    if sig["status"] == "duplicate":
        return  # 같은 알림이 또 왔다는 이유로 사용자에게 알림을 다시 보내지 않는다
    try:
        label = {"BUY": "매수", "SELL": "매도"}.get(sig["side"], "알림")
        price_suffix = " @ {:,.0f}".format(sig["signal_price"]) if sig["signal_price"] else ""
        text = (f"📡 [TradingView] {label} 신호 수신 — {sig['symbol']} {sig['quantity']}주"
                f"{price_suffix}"
                f"\n전략: {sig['strategy'] or '-'} · 처리: {sig['status']} · {sig['message']}")
        await notification.dispatch(text, html_message=text.replace("\n", "\n\n"), subject=f"[TradingView] {label} 신호 – {sig['symbol']}",
                                    user_id=result["user_id"], kind="tradingview_signal", ref=result["notification_ref"])
    except Exception as exc:
        logger.warning("tradingview webhook 알림 전달 실패: %s", exc)


@router.post("/api/webhooks/tradingview")
async def tradingview_webhook(request: Request, background: BackgroundTasks, db: AsyncSession = Depends(get_pg_session)):
    """TradingView 알림 Webhook. 본문은 JSON(권장) 또는 'key=value' 텍스트.

    검사 순서(설계 3.6): 발신 IP → 본문 크기 → 형식 → 토큰 → 분당 제한 → 필수 칸 · 지연 · 중복 · 주문.
    기록을 넣은 뒤 바로 응답하고, 감사 기록 · 알림은 응답 뒤에 한다.
    """
    peer = request.client.host if request.client else ""
    ip = tv.client_ip(request.headers.get("x-forwarded-for", ""), peer, settings.TRADINGVIEW_TRUSTED_PROXY_HOPS)
    # 발신 IP 허용 목록 (운영: TRADINGVIEW_ENFORCE_IP=true) — 본문을 읽기 전에 막는다
    if settings.TRADINGVIEW_ENFORCE_IP:
        allowed = {a.strip() for a in settings.TRADINGVIEW_ALLOWED_IPS.split(",") if a.strip()}
        if not ip or ip not in allowed:
            _log_reject("rejected_ip", 403, "허용되지 않은 발신 IP", ip)
            raise HTTPException(403, {"error": "FORBIDDEN", "message": f"허용되지 않은 발신 IP: {ip or '확인 불가'}"})
    try:
        raw = await _read_body(request, settings.TRADINGVIEW_MAX_BODY_BYTES)
    except HTTPException as exc:
        _log_reject("rejected_size", exc.status_code, "본문 크기 상한 초과", ip)
        raise
    if not raw.strip():
        _log_reject("rejected_format", 400, "빈 본문", ip)
        raise HTTPException(400, {"error": "BAD_REQUEST", "message": "본문이 비어 있습니다."})
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
    except Exception:
        # TradingView 기본 메시지가 JSON이 아닐 때: "token=..., ticker=..., action=buy" 형태 허용
        payload = {}
        for part in raw.decode("utf-8", "ignore").replace("\n", ",").split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                payload[k.strip()] = v.strip()
        if not payload:
            _log_reject("rejected_format", 400, "본문을 해석할 수 없음", ip)
            raise HTTPException(400, {"error": "BAD_REQUEST", "message": "JSON 본문을 해석할 수 없습니다."})
    try:
        key = await tv.resolve_user_by_token(db, str(payload.get("token") or payload.get("api_key") or ""))
    except tv.WebhookError as exc:
        await db.rollback()
        _log_reject(exc.code, exc.status, str(exc), ip)
        raise HTTPException(exc.status, {"error": "UNAUTHORIZED" if exc.status == 401 else "BAD_REQUEST", "message": str(exc)})
    if not await _check_rate_limit(f"tv:{key.id}", settings.TRADINGVIEW_RATE_LIMIT_MAX):
        _log_reject("rejected_rate", 429, f"키 {str(key.id)[:8]} 분당 제한", ip)
        raise HTTPException(429, {"error": "RATE_LIMITED", "message": f"분당 {settings.TRADINGVIEW_RATE_LIMIT_MAX}회 알림 제한을 초과했습니다."})
    result = await tv.handle_alert(db, payload, key=key)
    await db.commit()
    sig = result["signal"]
    if sig["status"] == "rejected_format":
        _log_reject("rejected_format", 400, sig["message"], ip)
        raise HTTPException(400, {"error": "BAD_REQUEST", "message": sig["message"]})
    background.add_task(_after_response, result)
    resp = {"ok": sig["status"] in ("filled", "alert", "duplicate"), "status": sig["status"], "message": sig["message"],
            "symbol": sig["symbol"], "side": sig["side"], "quantity": sig["quantity"], "fill_price": sig["fill_price"]}
    if sig.get("first_status"):
        resp["first_status"] = sig["first_status"]
    return resp


@router.get("/api/tradingview/webhook-info")
async def webhook_info(request: Request, user=Depends(get_current_user_any)):
    base = str(request.base_url).rstrip("/")
    public = getattr(settings, "PUBLIC_BASE_URL", "") or base
    return {
        "webhook_url": f"{public}/api/webhooks/tradingview",
        "alert_template": tv.ALERT_TEMPLATE,
        "alert_template_text": json.dumps(tv.ALERT_TEMPLATE, ensure_ascii=False, indent=2),
        "notes": [
            "TradingView 알림 만들기 › 알림 액션 › Webhook URL 에 위 주소를 넣고, 메시지 칸에 템플릿 JSON을 붙여 넣으세요.",
            "token 값은 모의투자 › Open API 화면에서 발급한 API 키입니다(발급 시 1회만 표시).",
            "action 이 buy/sell 이고 contracts ≥ 1 이면 모의계좌에 시장가 체결(source=TRADINGVIEW), 그 외는 알림만 전달합니다. "
            "주문이 되는 알림에는 signal_id 또는 bar_time(판단 시각)이 꼭 필요합니다(strategy_id 가 없으면 strategy 이름으로 대신하며, 위 템플릿을 그대로 쓰면 들어갑니다).",
            "같은 알림(같은 strategy_id · strategy_version · 종목 · 방향 · signal_id 또는 bar_time)이 또 오면 주문 없이 '중복' 줄만 남기고 첫 줄의 중복 횟수를 올립니다.",
            f"알림을 보낸 시각(sent_at, 있을 때만 잼)이 받은 시각보다 {settings.TRADINGVIEW_MAX_DELAY_SEC}초 넘게 늦으면 주문하지 않고 '늦음'으로 기록합니다. "
            f"본문은 {settings.TRADINGVIEW_MAX_BODY_BYTES}바이트까지, 3초 안에 응답합니다.",
            "TradingView Webhook은 공개 URL(HTTPS 권장)만 호출할 수 있습니다. 로컬 개발 시 ngrok 등으로 터널링하세요.",
        ],
    }


@router.get("/api/tradingview/signals")
async def signals(limit: int = Query(50, ge=1, le=200), user=Depends(get_current_user_any),
                  db: AsyncSession = Depends(get_pg_session)):
    return {"signals": await tv.list_signals(db, _uid(user), limit)}


class TvMetricsBody(BaseModel):
    net_profit_pct: float | None = None
    max_drawdown_pct: float | None = None
    total_trades: int | None = None
    win_rate_pct: float | None = None
    sharpe_ratio: float | None = None


class LedgerTolerance(BaseModel):
    """대사표 허용 오차 — 사전등록한 값만 넣는다. 비우면 그 칸은 「기록만」(설계서 3.4)."""
    layer0_close_bp: float | None = Field(None, ge=0)
    layer1_min_match_pct: float | None = Field(None, ge=0, le=100)
    layer2_date_days: float | None = Field(None, ge=0)
    layer2_price_bp: float | None = Field(None, ge=0)
    layer2_qty_pct: float | None = Field(None, ge=0)
    layer3_cost_bp: float | None = Field(None, ge=0)
    source: str | None = Field(None, max_length=200, description="허용 오차의 출처(예: #333 최종 판)")


class EngineDeclaration(BaseModel):
    """한 엔진이 선언하는 설정 — 두 엔진이 다르게 선언한 항목만 어긋남의 원인 후보가 된다."""
    entry_mode: str | None = Field(None, max_length=20)
    exit_mode: str | None = Field(None, max_length=20)
    judge: str | None = Field(None, max_length=20)
    sizing: str | None = Field(None, max_length=40)
    slippage_bp: float | None = Field(None, ge=0)
    roundtrip_cost_bp: float | None = Field(None, ge=0, description="수수료+세금 왕복(슬리피지 제외)")
    cost_note: str | None = Field(None, max_length=120)


class LedgerContext(BaseModel):
    tv: EngineDeclaration | None = None
    lean: EngineDeclaration | None = None
    rule_def_first_bar_differs: bool = False


class CompareBody(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    strategy: str = Field("ma_cross", description="buy_hold | ma_cross | dca | momentum")
    start_date: date
    end_date: date
    initial_cash: float = Field(10_000_000, ge=1_000, description="세 엔진(TradingView · LEAN · 모의)이 같은 시작 금액 — 기본 1,000만 원")
    short_window: int = Field(20, ge=2, le=120)
    long_window: int = Field(60, ge=5, le=300)
    dca_interval_days: int = Field(21, ge=1, le=120)
    breakout_window: int = Field(20, ge=5, le=120)
    tv_metrics: TvMetricsBody | None = None
    tv_trades_csv: str | None = Field(None, description="Strategy Tester 거래 목록 CSV 원문")
    tv_signal_csv: str | None = Field(None, description="차트 데이터 CSV의 SignalState_Entry/Exit 열")
    tolerance: LedgerTolerance | None = Field(None, description="줄 단위 대사표 허용 오차(없으면 기록만)")
    ledger_context: LedgerContext | None = Field(None, description="두 엔진의 선언된 설정 차이(원인 코드용)")
    repro: dict[str, str] | None = Field(None, description="대사표 머리 재현 기록(카드 sha256 · 데이터 기준일 · 코드 커밋 등)")


@router.post("/api/tradingview/compare")
async def compare(body: CompareBody, user=Depends(get_current_user_any), db: AsyncSession = Depends(get_pg_session)):
    """TradingView Strategy Tester 성과를 LEAN 백테스트와 교차 검증한다."""
    if body.strategy not in STRATEGY_LABELS:
        raise HTTPException(422, f"strategy는 {', '.join(STRATEGY_LABELS)} 중 하나여야 합니다.")
    if body.start_date >= body.end_date:
        raise HTTPException(422, "종료일은 시작일보다 뒤여야 합니다.")

    # 1) TradingView 지표
    tv_metrics: dict = {}
    if body.tv_trades_csv and body.tv_trades_csv.strip():
        try:
            tv_metrics = tv.parse_trade_list_csv(body.tv_trades_csv)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    if body.tv_metrics:
        manual = {k: v for k, v in body.tv_metrics.model_dump().items() if v is not None}
        tv_metrics = {**tv_metrics, **manual, "source": (tv_metrics.get("source", "") + " + " if tv_metrics else "") + "직접 입력"} if manual else tv_metrics
    tv_fills = tv_metrics.pop("fills", [])
    tv_signals = []
    if body.tv_signal_csv and body.tv_signal_csv.strip():
        try:
            tv_signals = tv.parse_signal_csv(body.tv_signal_csv)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if tv_signals and body.strategy != "ma_cross":
            raise HTTPException(
                422,
                "현재 날짜별 신호 CSV 비교는 ma_cross 전략에서만 지원합니다.",
            )
    if not tv_metrics and not tv_signals:
        raise HTTPException(
            422,
            "TradingView 성과, 거래 목록 CSV 또는 신호 CSV 중 하나는 필요합니다.",
        )

    # 2) LEAN 백테스트 (동일 종목·기간·전략)
    ticker = body.ticker.strip().upper()
    if ticker.isdigit() and len(ticker) == 6:
        ticker += ".KS"
    try:
        lean_res = await lean_service.run(
            ticker=ticker, start_date=body.start_date, end_date=body.end_date,
            compare_start_date=body.start_date, compare_end_date=body.end_date, initial_cash=body.initial_cash,
            strategy=body.strategy, short_window=body.short_window, long_window=body.long_window,
            dca_interval_days=body.dca_interval_days, breakout_window=body.breakout_window,
        )
    except LeanBacktestError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"LEAN 백테스트 실행 오류: {exc}")

    lean_metrics = tv.lean_metrics_from_result(lean_res)
    has_metrics_input = bool(tv_metrics)
    has_signal_input = bool(tv_signals)

    if has_metrics_input:
        result = tv.compare_metrics(tv_metrics, lean_metrics, ticker, body.strategy)
        performance_status = (
            "unavailable" if result.get("verdict") == "비교 불가" else "compared"
        )
        result["performance_comparison"] = {
            "status": performance_status,
            "verdict": result.get("verdict"),
        }
        if performance_status == "unavailable":
            result["performance_comparison"]["reason"] = (
                "비교 가능한 성과지표가 충분하지 않습니다."
            )
    else:
        result = {
            "ticker": ticker,
            "strategy": body.strategy,
            "verdict": "신호 비교 전용",
            "rows": [],
            "diff": {},
            "causes": [],
            "tradingview": {},
            "lean": {},
            "performance_comparison": {
                "status": "not_requested",
                "reason": "성과 입력이 없어 성과 비교를 수행하지 않았습니다.",
            },
        }

    if tv_fills:
        result["fill_comparison"] = tv.compare_fills(
            tv_fills, lean_res.get("lean_fills") or []
        )
        if result["fill_comparison"]["status"] != "compared":
            result["causes"].append(
                result["fill_comparison"].get(
                    "reason", "개별 체결 비교를 수행할 수 없습니다."
                )
            )
    else:
        result["fill_comparison"] = {
            "status": "not_requested",
            "reason": "거래 목록 CSV가 제공되지 않아 체결 비교를 수행하지 않았습니다.",
        }

    if has_signal_input:
        result["signal_comparison"] = tv.compare_signals(
            tv_signals, lean_res.get("lean_signals") or []
        )
        if result["signal_comparison"]["status"] != "compared":
            result["causes"].append(
                result["signal_comparison"].get(
                    "reason", "신호 비교를 수행할 수 없습니다."
                )
            )
    else:
        result["signal_comparison"] = {
            "status": "not_requested",
            "reason": "신호 CSV가 제공되지 않아 신호 비교를 수행하지 않았습니다.",
        }

    # 줄 단위 대사표(①-11) — compare_fills 는 그대로 두고 새 키로 붙인다
    if tv_fills:
        result["reconcile_table"] = xval_ledger.build_ledger(
            tv_fills,
            lean_res.get("lean_fills") or [],
            signal_result=result["signal_comparison"],
            tolerance=body.tolerance.model_dump(exclude_none=True) if body.tolerance else None,
            context=body.ledger_context.model_dump(exclude_none=True) if body.ledger_context else None,
            repro=body.repro,
            engine_settings=xval_ledger.engine_settings_report(
                lean_initial_cash=body.initial_cash,
                paper_initial_cash=_paper_initial_cash(),
                when=body.end_date,
            ),
        )
    else:
        result["reconcile_table"] = {
            "status": "not_requested",
            "reason": "거래 목록 CSV가 제공되지 않아 줄 단위 대사표를 만들지 않았습니다.",
        }

    result["strategy_label"] = STRATEGY_LABELS.get(body.strategy, body.strategy)
    result["period"] = {
        "start": body.start_date.isoformat(),
        "end": body.end_date.isoformat(),
    }
    result["lean_points"] = lean_res.get("points", [])

    # 성과 이력에는 실제 성과 비교 요청만 저장한다.
    if has_metrics_input:
        row = StrategyComparison(
            user_id=_uid(user),
            ticker=ticker,
            strategy=body.strategy,
            start_date=body.start_date.isoformat(),
            end_date=body.end_date.isoformat(),
            verdict=result["verdict"],
            tv_metrics=tv_metrics,
            lean_metrics={
                k: v for k, v in lean_metrics.items()
                if k != "lean_statistics"
            },
            diff=result["diff"],
            causes=result["causes"],
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        result["id"] = str(row.id)
        result["saved_to_performance_history"] = True
    else:
        result["id"] = None
        result["saved_to_performance_history"] = False

    await audit(user["id"], user.get("client_id", ""), "tradingview.compare",
                {"ticker": ticker, "strategy": body.strategy, "verdict": result["verdict"]})
    return result


@router.get("/api/tradingview/comparisons")
async def comparisons(limit: int = Query(30, ge=1, le=200), user=Depends(get_current_user_any),
                      db: AsyncSession = Depends(get_pg_session)):
    return {"comparisons": await tv.list_comparisons(db, _uid(user), limit)}
