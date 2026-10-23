from AlgorithmImports import *
from QuantConnect.Python import PythonData
from QuantConnect import Globals, SubscriptionTransportMedium
from QuantConnect.Data import SubscriptionDataSource
import os
from datetime import datetime, timedelta

class YFPrice(PythonData):
    def get_source(self, config, date, is_live):
        return SubscriptionDataSource(os.path.join(Globals.DataFolder, "prices.csv"), SubscriptionTransportMedium.LocalFile)
    def reader(self, config, line, date, is_live):
        if line.startswith("date"):
            return None
        d, close = line.split(",")
        item = YFPrice()
        item.symbol = config.symbol
        item.time = datetime.strptime(d, "%Y-%m-%d")
        item.end_time = item.time + timedelta(days=1)
        item.value = float(close)
        return item

class KrxFeeModel(FeeModel):
    tax_schedule = [('1900-01-01', 0.0015), ('2019-06-03', 0.001), ('2021-01-01', 0.0008), ('2023-01-01', 0.0005), ('2024-01-01', 0.0003), ('2025-01-01', 0.0), ('2026-01-01', 0.0005)]
    base_rate = 0.000176923
    rural_rate = 0.0015
    def get_order_fee(self, parameters):
        order = parameters.order
        security = parameters.security
        gross = abs(float(security.price) * float(order.absolute_quantity))
        rate = self.base_rate
        if order.direction == OrderDirection.SELL:
            trade_date = order.time.date()
            transfer_rate = self.tax_schedule[0][1]
            for effective_date, candidate_rate in self.tax_schedule:
                if trade_date >= datetime.strptime(effective_date, '%Y-%m-%d').date():
                    transfer_rate = candidate_rate
            rate += transfer_rate + self.rural_rate
        return OrderFee(CashAmount(gross * rate, 'KRW'))


class YFinanceMovingAverageCrossAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2024, 1, 2)
        self.set_end_date(2024, 3, 29)
        self.set_account_currency('KRW', 1000000)
        self.asset = self.add_data(YFPrice, "YF", Resolution.DAILY).symbol
        # 커스텀 데이터의 기본 lot size(1주)는 cash/price < 1 인 경우 SetHoldings()를 0으로 만든다.
        # 아주 작은 lot size를 지정해 소수 단위 포지션을 허용한다.
        self.securities[self.asset].symbol_properties = SymbolProperties("", "KRW", 1, 0.01, 0.0000001, "")
        self.securities[self.asset].set_fee_model(KrxFeeModel())
        self.securities[self.asset].set_slippage_model(ConstantSlippageModel(0.001))
        self.short_window = 5
        self.long_window = 20
        self.prices = []
        self.set_warm_up(timedelta(days=self.long_window * 2 + 15), Resolution.DAILY)

    def on_data(self, data):
        if not data.contains_key(self.asset):
            return
        self.prices.append(float(data[self.asset].value))
        self.prices = self.prices[-self.long_window:]
        if len(self.prices) < self.long_window or self.is_warming_up:
            return
        short_ma = sum(self.prices[-self.short_window:]) / self.short_window
        long_ma = sum(self.prices) / self.long_window
        if short_ma > long_ma and not self.portfolio.invested:
            self.set_holdings(self.asset, 1)
        elif short_ma <= long_ma and self.portfolio.invested:
            self.liquidate(self.asset)
