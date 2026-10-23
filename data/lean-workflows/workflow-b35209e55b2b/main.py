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

class YFinanceMovingAverageCrossAlgorithm(QCAlgorithm):
    def initialize(self):
        self.set_start_date(2024, 1, 2)
        self.set_end_date(2024, 3, 29)
        self.set_cash(1000000)
        self.asset = self.add_data(YFPrice, "YF", Resolution.DAILY).symbol
        # 커스텀 데이터의 기본 lot size(1주)는 cash/price < 1 인 경우 SetHoldings()를 0으로 만든다.
        # 아주 작은 lot size를 지정해 소수 단위 포지션을 허용한다.
        self.securities[self.asset].symbol_properties = SymbolProperties("", "USD", 1, 0.01, 0.0000001, "")
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
