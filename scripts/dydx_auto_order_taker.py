import logging
import os
import random
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import Field

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import MarketDict, OrderType, PositionAction, TradeType
from hummingbot.core.data_type.order_candidate import PerpetualOrderCandidate
from hummingbot.core.event.events import MarketOrderFailureEvent, OrderFilledEvent
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase


class DydxAutoOrderTakerConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    controllers_config: List[str] = []

    # Market and connector
    taker_connector: str = Field(default="dydx_v4_perpetual", description="Taker account connector")
    trading_pair: str = Field(default="ETH-USD", description="Local market-making trading pair")

    # External reference market (if unset, paint against the local mid)
    external_connector: Optional[str] = Field(default="binance_perpetual", description="External reference exchange")
    external_trading_pair: Optional[str] = Field(default="ETH-USDT", description="External reference trading pair")

    # Paint interval (seconds)
    paint_interval: float = Field(default=30.0, description="Paint interval in seconds")
    # Random paint jitter (e.g. 0–5s, to simulate retail flow)
    interval_jitter: float = Field(default=5.0, description="Random jitter in seconds added to each paint interval")

    # Size per taker tick
    trade_amount: Decimal = Field(default=Decimal("1.0"), description="Size per paint fill")
    trade_amount_min: Decimal = Field(default=Decimal("0.5"), description="Random size lower bound")
    trade_amount_max: Decimal = Field(default=Decimal("1.5"), description="Random size upper bound")
    # Max net inventory per side (flatten when reached)
    max_inventory_limit: Decimal = Field(default=Decimal("10.0"), description="Max net inventory per side")

    # Max allowed price deviation (e.g. 0.05 = 5%)
    max_price_deviation_pct: Decimal = Field(default=Decimal("0.05"), description="Max allowed book price deviation")

    def update_markets(self, markets: MarketDict) -> MarketDict:
        markets[self.taker_connector] = markets.get(self.taker_connector, set()) | {self.trading_pair}
        if self.external_connector and self.external_trading_pair:
            markets[self.external_connector] = markets.get(self.external_connector, set()) | {self.external_trading_pair}
        return markets


class DydxAutoOrderTaker(StrategyV2Base):
    """
    dYdX v4 perpetual auto-taker / self-trade paint script (Auto Order Taker)
    1. Watch local dYdX book depth and an optional external reference price;
    2. Periodically take resting quotes at the target level to produce continuous K-line prints and volume;
    3. Rebalance inventory so one-sided exposure does not accumulate.
    """

    def __init__(self, connectors: Dict[str, ConnectorBase], config: DydxAutoOrderTakerConfig):
        super().__init__(connectors, config)
        self.config = config
        self._next_paint_timestamp = 0.0
        self._current_inventory = Decimal("0")
        self._total_trades_count = 0
        self._total_volume_quote = Decimal("0")

    def on_tick(self):
        if not self._is_all_connectors_ready():
            return

        if self.current_timestamp >= self._next_paint_timestamp:
            self._execute_kline_paint()
            # Schedule the next paint timestamp (with jitter)
            jitter = random.uniform(0, float(self.config.interval_jitter))
            self._next_paint_timestamp = self.current_timestamp + float(self.config.paint_interval) + jitter

    def _is_all_connectors_ready(self) -> bool:
        taker_conn = self.connectors.get(self.config.taker_connector)
        if not taker_conn or not taker_conn.ready:
            return False

        if self.config.external_connector and self.config.external_trading_pair:
            ext_conn = self.connectors.get(self.config.external_connector)
            if not ext_conn or not ext_conn.ready:
                return False
        return True

    def _get_target_price(self) -> Optional[Decimal]:
        """
        Return the current target reference price:
        external mid if configured, otherwise the local book mid.
        """
        if self.config.external_connector and self.config.external_trading_pair:
            ext_conn = self.connectors.get(self.config.external_connector)
            if ext_conn:
                mid = ext_conn.get_mid_price(self.config.external_trading_pair)
                if mid and not mid.is_nan():
                    return mid

        taker_conn = self.connectors.get(self.config.taker_connector)
        return taker_conn.get_mid_price(self.config.trading_pair)

    def _execute_kline_paint(self):
        """
        Core paint logic:
        1. Check whether inventory is over the limit;
        2. Choose BUY or SELL for this tick;
        3. Take the book so a real fill is produced.
        """
        taker_conn = self.connectors.get(self.config.taker_connector)
        target_price = self._get_target_price()

        best_bid = taker_conn.get_price(self.config.trading_pair, False)  # best bid
        best_ask = taker_conn.get_price(self.config.trading_pair, True)   # best ask

        if best_bid.is_nan() or best_ask.is_nan() or target_price is None or target_price.is_nan():
            self.logger().warning("[AUTO_TAKER] Book or target price is not ready; skip this paint.")
            return

        self.logger().info(
            f"[AUTO_TAKER] Book state: BestBid={best_bid:.4f}, BestAsk={best_ask:.4f}, TargetPrice={target_price:.4f} | "
            f"net inventory={self._current_inventory:.2f}"
        )

        # Prefer inventory rebalance: if net long/short exceeds the limit, take the opposite side
        # and flatten 80%–100% of the current position.
        if abs(self._current_inventory) >= self.config.max_inventory_limit:
            rebalance_ratio = random.uniform(0.8, 1.0)
            target_rebalance_amount = abs(self._current_inventory) * Decimal(str(rebalance_ratio))
            trade_amount = taker_conn.quantize_order_amount(self.config.trading_pair, target_rebalance_amount)
            
            if self._current_inventory > 0:
                self.logger().info(f"[AUTO_TAKER REBALANCE] Inventory too long ({self._current_inventory}) -> selling a large size to flatten {trade_amount}...")
                self._submit_taker_order(TradeType.SELL, best_bid, trade_amount)
            else:
                self.logger().info(f"[AUTO_TAKER REBALANCE] Inventory too short ({self._current_inventory}) -> buying a large size to flatten {trade_amount}...")
                self._submit_taker_order(TradeType.BUY, best_ask, trade_amount)
            return

        # Normal paint logic (choose buy or sell)
        # Draw a randomized taker size
        random_amount = random.uniform(float(self.config.trade_amount_min), float(self.config.trade_amount_max))
        trade_amount = taker_conn.quantize_order_amount(self.config.trading_pair, Decimal(str(random_amount)))

        # If the target is above the local mid, buy to lift; otherwise sell to press
        mid_price = (best_bid + best_ask) / Decimal("2")
        if target_price > mid_price:
            trade_type = TradeType.BUY
            order_price = best_ask
        elif target_price < mid_price:
            trade_type = TradeType.SELL
            order_price = best_bid
        else:
            # If the target equals mid, paint randomly either way
            trade_type = TradeType.BUY if random.random() > 0.5 else TradeType.SELL
            order_price = best_ask if trade_type == TradeType.BUY else best_bid

        self.logger().info(
            f"[AUTO_TAKER EXECUTE] >>> Submitting paint fill: {trade_type.name} {trade_amount} @ {order_price} "
            f"(target={target_price:.4f})"
        )
        self._submit_taker_order(trade_type, order_price, trade_amount)

    def _submit_taker_order(self, trade_type: TradeType, price: Decimal, amount: Decimal):
        """
        Submit a MARKET order so the fill is always taker.
        """
        try:
            if trade_type == TradeType.BUY:
                self.buy(
                    connector_name=self.config.taker_connector,
                    trading_pair=self.config.trading_pair,
                    amount=amount,
                    order_type=OrderType.MARKET,
                    price=price,
                    position_action=PositionAction.OPEN
                )
            else:
                self.sell(
                    connector_name=self.config.taker_connector,
                    trading_pair=self.config.trading_pair,
                    amount=amount,
                    order_type=OrderType.MARKET,
                    price=price,
                    position_action=PositionAction.OPEN
                )
        except Exception as e:
            self.logger().error(f"[AUTO_TAKER ERROR] Order submit failed: {str(e)}", exc_info=True)

    def did_fill_order(self, event: OrderFilledEvent):
        """
        Record the fill and update inventory.
        """
        self._total_trades_count += 1
        trade_vol = event.amount * event.price
        self._total_volume_quote += trade_vol

        if event.trade_type == TradeType.BUY:
            self._current_inventory += event.amount
        else:
            self._current_inventory -= event.amount

        msg = (
            f"[AUTO_TAKER SUCCESS] Fill complete! {event.trade_type.name} {event.amount} {event.trading_pair} @ "
            f"{event.price} (paint fills: {self._total_trades_count}, volume: {self._total_volume_quote:.2f} USD, "
            f"net inventory: {self._current_inventory:.2f})"
        )
        self.log_with_clock(logging.INFO, msg)

    def did_fail_order(self, event: MarketOrderFailureEvent):
        self.logger().error(f"[AUTO_TAKER FAILED] Paint order failed: {event.order_id}, type: {event.order_type}")
