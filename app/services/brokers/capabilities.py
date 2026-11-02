"""현재 연결 코드의 지원 범위. 증권사 전체 API의 지원 여부와 구분한다."""
from app.services.brokers import stock_coin_trade_gateway as gateway


def execution_capabilities(row=None):
    direct = bool(row and row.broker == "kis" and row.paper and not gateway.is_configured())
    retry = direct or (gateway.is_configured() and gateway.environment() == "paper")
    return {
        "monitoring": "server_polling",
        "broker_hosted_stop": False,
        "supported_gateway_order_types": ["LIMIT", "MARKET"],
        "cancelled_sell_retry": retry,
        "direct_paper_cancel": direct,
        "retry_timing_note": ("현재 매도 대기시간이 재주문 허용 시간보다 길거나 같아, 같은 매도 직후의 잔량 재주문은 실행되지 않습니다."
                              if direct and (row.risk_cooldown_min or 0) >= float((row.quant_execution_policy or {}).get("retry_window_min", 15)) else ""),
        "retry_note": ("취소가 확정된 개인 KIS 모의 지정가 매도의 전략 보유 잔량만 원 지정가로 재주문합니다. 자동 재주문은 설정을 켠 경우에만 실행합니다."
                       if direct else "취소가 확인된 게이트웨이 모의 지정가 매도의 잔량만 재주문합니다."
                       if retry else "재주문은 체결 상태를 추적하는 게이트웨이 모의 경로에서만 동작합니다. 현재 연결에서는 실행하지 않습니다."),
        "stop_note": "현재 연결은 서버 주기 판단 방식입니다. 증권사 상주 감시·스탑지정가 주문은 연결하지 않았습니다.",
    }
