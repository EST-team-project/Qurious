from fastapi import APIRouter

from app.config import settings
from app.services.brokers import stock_coin_trade_gateway as gateway

router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    """공개 헬스. quant 블록은 운영 확인용 비민감 플래그만 노출한다(키·계좌 없음)."""
    return {
        "status": "ok",
        "service": "금융 AI Agent",
        "quant": {
            "cycle_sec": int(settings.QUANT_CYCLE_SEC),
            "aggressive_mode": bool(settings.QUANT_AGGRESSIVE_MODE),
            "aggressive_interval": settings.QUANT_AGGRESSIVE_CANDLE_INTERVAL if settings.QUANT_AGGRESSIVE_MODE else None,
            "kis_paper_batch": bool(settings.KIS_PAPER_BATCH_ENABLED),
            # 설정 글자가 아니라 실거래 관문을 지난 값 — 승인 없이 real 을 적어도 「실전」 으로 보이지 않게(Qurious 10-08)
            "kis_environment": gateway.environment(),
        },
    }
