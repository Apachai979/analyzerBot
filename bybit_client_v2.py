from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import time

import pandas as pd
from pybit.unified_trading import HTTP

from config import (
    BYBIT_API_KEY,
    BYBIT_API_SECRET,
    CATEGORY,
    INTERVAL,
    LIMIT,
    TESTNET,
)


VALID_CATEGORIES = {"spot", "linear", "inverse", "option"}
ORDERBOOK_LIMITS = {
    "spot": 200,
    "linear": 500,
    "inverse": 500,
    "option": 25,
}
COMMON_QUOTE_SUFFIXES = (
    "USDT",
    "USDC",
    "USD",
    "BTC",
    "ETH",
    "EUR",
)
KLINE_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
]


class BybitClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        testnet: bool = TESTNET,
        default_category: str = CATEGORY,
        recv_window: int = 5000,
        rate_limit_per_minute: int = 100,
        min_request_interval: float = 0.6,
    ):
        """Создает V5-клиент Bybit с настройками авторизации и локального rate limit."""
        self.api_key = api_key or BYBIT_API_KEY
        self.api_secret = api_secret or BYBIT_API_SECRET
        self.testnet = testnet
        self.default_category = self._normalize_category(default_category)
        self.recv_window = int(recv_window)

        self.rate_limit = max(1, int(rate_limit_per_minute))
        self.rate_window = 60.0
        self.min_request_interval = max(0.0, float(min_request_interval))
        self.request_times = deque(maxlen=self.rate_limit)
        self.last_request_time = 0.0

        self.session: HTTP | None = None
        self._initialize_session()

    def _initialize_session(self) -> None:
        """Инициализирует HTTP-сессию pybit для работы с Bybit Unified Trading API."""
        try:
            self.session = HTTP(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.testnet,
                recv_window=self.recv_window,
            )
        except Exception as error:
            print(f"❌ Ошибка инициализации сессии Bybit: {error}")
            self.session = None

    def _ensure_session(self) -> bool:
        """Гарантирует наличие активной сессии, при необходимости пересоздает ее."""
        if self.session:
            return True

        self._initialize_session()
        return self.session is not None

    def _normalize_category(self, category: str | None) -> str:
        """Проверяет и нормализует торговую категорию Bybit к нижнему регистру."""
        fallback_category = getattr(self, "default_category", "spot")
        normalized = (category or fallback_category or "spot").strip().lower()
        if normalized not in VALID_CATEGORIES:
            raise ValueError(
                f"Unsupported Bybit category: {category!r}. Expected one of {sorted(VALID_CATEGORIES)}"
            )
        return normalized

    def _normalize_symbol(self, symbol: str) -> str:
        """Приводит торговый символ к верхнему регистру и валидирует, что он не пустой."""
        normalized = str(symbol).strip().upper()
        if not normalized:
            raise ValueError("Symbol must not be empty")
        return normalized

    def _normalize_coin(self, symbol_or_coin: str) -> str:
        """Преобразует торговую пару или код актива к коду монеты, например BTCUSDT -> BTC."""
        candidate = self._normalize_symbol(symbol_or_coin)
        for suffix in COMMON_QUOTE_SUFFIXES:
            if candidate.endswith(suffix) and len(candidate) > len(suffix):
                return candidate[: -len(suffix)]
        return candidate

    def _wait_for_rate_limit(self) -> None:
        """Применяет локальное ограничение частоты запросов до отправки вызова в API."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
            current_time = time.time()

        cutoff = current_time - self.rate_window
        while self.request_times and self.request_times[0] <= cutoff:
            self.request_times.popleft()

        if len(self.request_times) >= self.rate_limit:
            sleep_time = self.rate_window - (current_time - self.request_times[0]) + 0.05
            if sleep_time > 0:
                print(f"⏳ Rate limit: ожидание {sleep_time:.2f}s...")
                time.sleep(sleep_time)
                current_time = time.time()
                cutoff = current_time - self.rate_window
                while self.request_times and self.request_times[0] <= cutoff:
                    self.request_times.popleft()

        self.request_times.append(time.time())
        self.last_request_time = time.time()

    def _request(self, method_name: str, **params) -> dict | None:
        """Вызывает метод pybit по имени, применяя rate limit и базовую обработку ошибок."""
        if not self._ensure_session():
            return None

        self._wait_for_rate_limit()

        try:
            method = getattr(self.session, method_name)
        except AttributeError:
            print(f"❌ Метод pybit не найден: {method_name}")
            return None

        try:
            response = method(**params)
        except Exception as error:
            print(f"❌ Ошибка запроса Bybit {method_name}: {error}")
            return None

        if not isinstance(response, dict):
            print(f"❌ Некорректный ответ Bybit для {method_name}: {type(response)!r}")
            return None

        return response

    def _response_ok(self, response: dict | None, action: str) -> bool:
        """Проверяет стандартный ответ Bybit и печатает причину ошибки при retCode != 0."""
        if response is None:
            return False
        if response.get("retCode") == 0:
            return True

        print(f"❌ Ошибка API при {action}: {response.get('retMsg', 'unknown error')}")
        return False

    def _build_kline_dataframe(self, klines: list[list[str]] | list[tuple[str, ...]]) -> pd.DataFrame:
        """Преобразует сырые свечи Bybit в очищенный DataFrame с числовыми колонками."""
        if not klines:
            return pd.DataFrame(columns=KLINE_COLUMNS)

        df = pd.DataFrame(klines, columns=KLINE_COLUMNS)
        for column in KLINE_COLUMNS:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        df = df.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        df = df.sort_values("timestamp")
        df = df.drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        return df

    def _try_number(self, value):
        """Пытается преобразовать строковое значение API в число, сохраняя исходное значение при неудаче."""
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            return value
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return value

        try:
            return float(stripped)
        except ValueError:
            return value

    def _coerce_numbers(self, value):
        """Рекурсивно преобразует числовые строки в числа."""
        if isinstance(value, dict):
            return {key: self._coerce_numbers(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._coerce_numbers(item) for item in value]
        return self._try_number(value)

    def get_klines(
        self,
        symbol: str,
        interval: str = INTERVAL,
        limit: int = LIMIT,
        category: str | None = None,
        start: int | None = None,
        end: int | None = None,
    ) -> pd.DataFrame | None:
        """Получает исторические свечи по инструменту и возвращает их в виде DataFrame."""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            normalized_category = self._normalize_category(category)
            normalized_limit = min(max(1, int(limit)), 1000)

            params = {
                "category": normalized_category,
                "symbol": normalized_symbol,
                "interval": str(interval),
                "limit": normalized_limit,
            }
            if start is not None:
                params["start"] = int(start)
            if end is not None:
                params["end"] = int(end)

            response = self._request("get_kline", **params)
            if not self._response_ok(response, f"получении свечей {normalized_symbol}"):
                return None

            klines = response.get("result", {}).get("list", [])
            return self._build_kline_dataframe(klines)
        except Exception as error:
            print(f"❌ Ошибка при получении данных {symbol}: {error}")
            return None

    def get_klines_until_date(
        self,
        symbol: str,
        interval: str = INTERVAL,
        limit: int = LIMIT,
        until_date: str = "2025-09-09",
        category: str | None = None,
    ) -> pd.DataFrame | None:
        """Загружает свечи батчами до указанной даты и отдает последние limit закрытых записей."""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            normalized_category = self._normalize_category(category)
            target_rows = max(1, int(limit))
            until_dt = datetime.strptime(until_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            until_ts = int(until_dt.timestamp() * 1000)

            collected: list[list[str]] = []
            end_ms = until_ts - 1

            while len(collected) < target_rows:
                batch_limit = min(1000, target_rows - len(collected))
                response = self._request(
                    "get_kline",
                    category=normalized_category,
                    symbol=normalized_symbol,
                    interval=str(interval),
                    limit=batch_limit,
                    end=end_ms,
                )
                if not self._response_ok(response, f"получении исторических свечей {normalized_symbol}"):
                    return None

                rows = response.get("result", {}).get("list", [])
                if not rows:
                    break

                collected.extend(rows)
                oldest_ts = min(int(row[0]) for row in rows)
                next_end = oldest_ts - 1
                if next_end >= end_ms:
                    break
                end_ms = next_end

                if len(rows) < batch_limit:
                    break

            df = self._build_kline_dataframe(collected)
            if df.empty:
                return df

            df = df[df["timestamp"] < until_ts].reset_index(drop=True)
            if len(df) > target_rows:
                df = df.tail(target_rows).reset_index(drop=True)
            return df
        except Exception as error:
            print(f"❌ Ошибка при получении исторических данных {symbol}: {error}")
            return None

    def get_coin_info(self, symbol: str):
        """Возвращает имя монеты, ее код и список поддерживаемых сетей вывода/депозита."""
        try:
            normalized_coin = self._normalize_coin(symbol)
            response = self._request("get_coin_info", coin=normalized_coin)
            if not self._response_ok(response, f"получении информации о токене {normalized_coin}"):
                return None, None, None

            rows = response.get("result", {}).get("rows", [])
            if not rows:
                return None, None, None

            row = next(
                (item for item in rows if str(item.get("coin", "")).upper() == normalized_coin),
                rows[0],
            )
            chains = [chain.get("chain") for chain in row.get("chains", []) if chain.get("chain")]
            return row.get("name"), row.get("coin"), chains
        except Exception as error:
            print(f"❌ Ошибка при получении информации о токене {symbol}: {error}")
            return None, None, None

    def get_orderbook(self, symbol: str, levels: int, whale_size=None, category: str | None = None):
        """Получает стакан и дополнительно считает агрегированные объемы и крупные заявки."""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            normalized_category = self._normalize_category(category)
            requested_levels = max(1, int(levels))
            api_limit = min(max(requested_levels * 3, requested_levels), ORDERBOOK_LIMITS[normalized_category])

            response = self._request(
                "get_orderbook",
                category=normalized_category,
                symbol=normalized_symbol,
                limit=api_limit,
            )
            if not self._response_ok(response, f"получении стакана {normalized_symbol}"):
                return None, None, None, None, None, None

            result = response.get("result", {})
            bids = result.get("b", [])
            asks = result.get("a", [])

            bid_volume = sum(float(bid[1]) for bid in bids[:requested_levels]) if bids else 0.0
            ask_volume = sum(float(ask[1]) for ask in asks[:requested_levels]) if asks else 0.0

            whale_bids = []
            whale_asks = []
            if whale_size is not None:
                whale_threshold = float(whale_size)
                whale_bids = [order for order in bids if float(order[1]) >= whale_threshold]
                whale_asks = [order for order in asks if float(order[1]) >= whale_threshold]

            return bids, asks, bid_volume, ask_volume, whale_bids, whale_asks
        except Exception as error:
            print(f"❌ Ошибка при получении стакана {symbol}: {error}")
            return None, None, None, None, None, None

    def get_current_price(self, symbol: str, category: str | None = None):
        """Возвращает последнюю рыночную цену инструмента по данным тикера."""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            normalized_category = self._normalize_category(category)
            response = self._request(
                "get_tickers",
                category=normalized_category,
                symbol=normalized_symbol,
            )
            if not self._response_ok(response, f"получении цены {normalized_symbol}"):
                return None

            items = response.get("result", {}).get("list", [])
            if not items:
                return None

            return float(items[0]["lastPrice"])
        except Exception as error:
            print(f"❌ Ошибка при получении цены {symbol}: {error}")
            return None

    def get_multiple_prices(self, symbols: list[str], category: str | None = None) -> dict[str, float]:
        """Возвращает словарь последних цен для набора символов в выбранной категории."""
        try:
            normalized_category = self._normalize_category(category)
            normalized_symbols = [self._normalize_symbol(symbol) for symbol in symbols]
            if not normalized_symbols:
                return {}

            if len(normalized_symbols) == 1 or normalized_category == "option":
                prices: dict[str, float] = {}
                for normalized_symbol in normalized_symbols:
                    price = self.get_current_price(normalized_symbol, category=normalized_category)
                    if price is not None:
                        prices[normalized_symbol] = price
                return prices

            response = self._request("get_tickers", category=normalized_category)
            if not self._response_ok(response, "получении списка тикеров"):
                return {}

            target_symbols = set(normalized_symbols)
            prices: dict[str, float] = {}
            for item in response.get("result", {}).get("list", []):
                symbol = str(item.get("symbol", "")).upper()
                if symbol in target_symbols and item.get("lastPrice") not in (None, ""):
                    prices[symbol] = float(item["lastPrice"])

            return prices
        except Exception as error:
            print(f"❌ Ошибка при получении цен: {error}")
            return {}

    def test_connection(self, symbol: str = "BTCUSDT", category: str | None = None) -> bool:
        """Проверяет доступность API простым запросом тикера по выбранному инструменту."""
        try:
            normalized_category = self._normalize_category(category)
            response = self._request(
                "get_tickers",
                category=normalized_category,
                symbol=self._normalize_symbol(symbol),
            )
            if self._response_ok(response, "проверке соединения с Bybit API"):
                print("✅ Соединение с Bybit API установлено успешно")
                return True
            return False
        except Exception as error:
            print(f"❌ Ошибка соединения с Bybit API: {error}")
            return False

    def get_server_time(self):
        """Получает серверное время Bybit и возвращает его в сыром и человекочитаемом виде."""
        try:
            response = self._request("get_server_time")
            if not self._response_ok(response, "получении серверного времени"):
                return None

            result = response.get("result", {})
            time_second = int(result["timeSecond"])
            dt_utc = datetime.fromtimestamp(time_second, tz=timezone.utc)
            dt_local = datetime.fromtimestamp(time_second)

            return {
                "timeSecond": result.get("timeSecond"),
                "timeNano": result.get("timeNano"),
                "time": response.get("time"),
                "datetime_utc": dt_utc.strftime("%d.%m.%Y %H:%M:%S UTC"),
                "datetime_local": dt_local.strftime("%d.%m.%Y %H:%M:%S"),
            }
        except Exception as error:
            print(f"❌ Ошибка получения серверного времени: {error}")
            return None

    def get_wallet_balance(self, accountType: str = "UNIFIED", coin: str | list[str] | None = None):
        """Запрашивает баланс unified-аккаунта и частично нормализует числовые поля ответа."""
        try:
            params = {"accountType": str(accountType).upper()}
            if coin:
                if isinstance(coin, (list, tuple, set)):
                    params["coin"] = ",".join(self._normalize_coin(item) for item in coin)
                else:
                    params["coin"] = self._normalize_coin(str(coin))

            response = self._request("get_wallet_balance", **params)
            if not self._response_ok(response, "получении баланса"):
                return None

            result_list = response.get("result", {}).get("list", [])
            if not result_list:
                return None

            parsed_accounts = []
            for account in result_list:
                parsed_account = {}
                for key, value in account.items():
                    if key == "coin" and isinstance(value, list):
                        parsed_account["coins"] = [
                            {coin_key: self._try_number(coin_value) for coin_key, coin_value in coin_item.items()}
                            for coin_item in value
                        ]
                    else:
                        parsed_account[key] = self._try_number(value)
                parsed_accounts.append(parsed_account)

            if coin:
                requested = (
                    {self._normalize_coin(item) for item in coin}
                    if isinstance(coin, (list, tuple, set))
                    else {self._normalize_coin(str(coin))}
                )
                for account in parsed_accounts:
                    for coin_item in account.get("coins", []):
                        if str(coin_item.get("coin", "")).upper() in requested:
                            return {"account": account, "coin": coin_item, "raw": response}
                return {"account": parsed_accounts[0], "raw": response}

            return {"accounts": parsed_accounts, "raw": response}
        except Exception as error:
            print(f"❌ Ошибка при получении баланса кошелька: {error}")
            return None

    def place_order(self, symbol, side, orderType, qty, price=None, **kwargs):
        """Размещает ордер через V5 API и возвращает краткий результат с идентификаторами ордера."""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            normalized_category = self._normalize_category(kwargs.get("category"))
            normalized_side = str(side).capitalize()
            normalized_order_type = str(orderType).capitalize()

            if normalized_side not in {"Buy", "Sell"}:
                raise ValueError("side must be 'Buy' or 'Sell'")
            if normalized_order_type not in {"Market", "Limit"}:
                raise ValueError("orderType must be 'Market' or 'Limit'")
            if normalized_order_type == "Limit" and price is None:
                raise ValueError("price is required for Limit orders")

            params = {
                "category": normalized_category,
                "symbol": normalized_symbol,
                "side": normalized_side,
                "orderType": normalized_order_type,
                "qty": str(qty),
            }
            if price is not None and normalized_order_type == "Limit":
                params["price"] = str(price)

            optional_params = [
                "isLeverage",
                "marketUnit",
                "slippageToleranceType",
                "slippageTolerance",
                "triggerDirection",
                "orderFilter",
                "triggerPrice",
                "triggerBy",
                "orderIv",
                "timeInForce",
                "positionIdx",
                "orderLinkId",
                "takeProfit",
                "stopLoss",
                "tpTriggerBy",
                "slTriggerBy",
                "reduceOnly",
                "closeOnTrigger",
                "smpType",
                "mmp",
                "tpslMode",
                "tpLimitPrice",
                "slLimitPrice",
                "tpOrderType",
                "slOrderType",
                "bboSideType",
                "bboLevel",
            ]
            for param in optional_params:
                if kwargs.get(param) is not None:
                    params[param] = kwargs[param]

            response = self._request("place_order", **params)
            if response is None:
                return None

            if response.get("retCode") == 0:
                result = response.get("result", {})
                return {
                    "success": True,
                    "orderId": result.get("orderId"),
                    "orderLinkId": result.get("orderLinkId"),
                    "response": response,
                }

            print(f"❌ Ошибка размещения ордера: {response.get('retMsg')}")
            return {
                "success": False,
                "error": response.get("retMsg"),
                "retCode": response.get("retCode"),
                "response": response,
            }
        except Exception as error:
            print(f"❌ Исключение при размещении ордера: {error}")
            return None

    def get_instrument_info(self, symbol: str, category: str | None = None):
        """Возвращает параметры инструмента: шаг цены, шаг количества, min qty и прочее."""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            normalized_category = self._normalize_category(category)

            response = self._request(
                "get_instruments_info",
                category=normalized_category,
                symbol=normalized_symbol,
            )
            if not self._response_ok(response, f"получении параметров инструмента {normalized_symbol}"):
                return None

            items = response.get("result", {}).get("list", [])
            if not items:
                return None

            raw_item = next(
                (item for item in items if str(item.get("symbol", "")).upper() == normalized_symbol),
                items[0],
            )
            item = self._coerce_numbers(raw_item)

            lot = item.get("lotSizeFilter", {}) or {}
            price_filter = item.get("priceFilter", {}) or {}
            leverage_filter = item.get("leverageFilter", {}) or {}

            return {
                "symbol": item.get("symbol"),
                "category": normalized_category,
                "status": item.get("status"),
                "baseCoin": item.get("baseCoin"),
                "quoteCoin": item.get("quoteCoin"),
                "priceScale": item.get("priceScale"),
                "tickSize": price_filter.get("tickSize"),
                "minPrice": price_filter.get("minPrice"),
                "maxPrice": price_filter.get("maxPrice"),
                "qtyStep": lot.get("qtyStep"),
                "minOrderQty": lot.get("minOrderQty"),
                "maxOrderQty": lot.get("maxOrderQty"),
                "maxMktOrderQty": lot.get("maxMktOrderQty"),
                "minNotionalValue": lot.get("minNotionalValue") or lot.get("minOrderAmt"),
                "minLeverage": leverage_filter.get("minLeverage"),
                "maxLeverage": leverage_filter.get("maxLeverage"),
                "raw": item,
            }
        except Exception as error:
            print(f"❌ Ошибка при получении параметров инструмента {symbol}: {error}")
            return None

    def get_open_positions(
        self,
        symbol: str | None = None,
        settleCoin: str | None = None,
        category: str | None = None,
        limit: int = 50,
        active_only: bool = True,
    ):
        """Возвращает список позиций."""
        try:
            normalized_category = self._normalize_category(category)
            params = {
                "category": normalized_category,
                "limit": min(max(1, int(limit)), 200),
            }

            if symbol:
                params["symbol"] = self._normalize_symbol(symbol)
            if settleCoin:
                params["settleCoin"] = self._normalize_coin(settleCoin)

            response = self._request("get_positions", **params)
            if not self._response_ok(response, "получении позиций"):
                return None

            items = response.get("result", {}).get("list", [])
            positions = [self._coerce_numbers(item) for item in items]

            if active_only:
                filtered = []
                for position in positions:
                    size = position.get("size", 0) or 0
                    side = str(position.get("side", "")).capitalize()
                    try:
                        is_active = abs(float(size)) > 0
                    except Exception:
                        is_active = False

                    if is_active and side in {"Buy", "Sell"}:
                        filtered.append(position)
                positions = filtered

            return positions
        except Exception as error:
            print(f"❌ Ошибка при получении позиций: {error}")
            return None

    def get_position(
        self,
        symbol: str,
        category: str | None = None,
        active_only: bool = True,
    ):
        """Возвращает одну позицию по символу."""
        try:
            positions = self.get_open_positions(
                symbol=symbol,
                category=category,
                limit=20,
                active_only=active_only,
            )
            if not positions:
                return None

            normalized_symbol = self._normalize_symbol(symbol)
            for position in positions:
                if str(position.get("symbol", "")).upper() == normalized_symbol:
                    return position
            return None
        except Exception as error:
            print(f"❌ Ошибка при получении позиции {symbol}: {error}")
            return None

    def get_open_orders(
        self,
        symbol: str | None = None,
        baseCoin: str | None = None,
        settleCoin: str | None = None,
        orderId: str | None = None,
        orderLinkId: str | None = None,
        openOnly: int | None = None,
        category: str | None = None,
        limit: int = 50,
    ):
        """Возвращает активные ордера."""
        try:
            normalized_category = self._normalize_category(category)
            params = {
                "category": normalized_category,
                "limit": min(max(1, int(limit)), 50),
            }

            if symbol:
                params["symbol"] = self._normalize_symbol(symbol)
            if baseCoin:
                params["baseCoin"] = self._normalize_coin(baseCoin)
            if settleCoin:
                params["settleCoin"] = self._normalize_coin(settleCoin)
            if orderId:
                params["orderId"] = str(orderId)
            if orderLinkId:
                params["orderLinkId"] = str(orderLinkId)
            if openOnly is not None:
                params["openOnly"] = int(openOnly)

            response = self._request("get_open_orders", **params)
            if not self._response_ok(response, "получении открытых ордеров"):
                return None

            items = response.get("result", {}).get("list", [])
            return [self._coerce_numbers(item) for item in items]
        except Exception as error:
            print(f"❌ Ошибка при получении открытых ордеров: {error}")
            return None

    def get_order_history(
        self,
        symbol: str | None = None,
        baseCoin: str | None = None,
        settleCoin: str | None = None,
        orderId: str | None = None,
        orderLinkId: str | None = None,
        category: str | None = None,
        limit: int = 50,
    ):
        """Возвращает историю ордеров."""
        try:
            normalized_category = self._normalize_category(category)
            params = {
                "category": normalized_category,
                "limit": min(max(1, int(limit)), 50),
            }

            if symbol:
                params["symbol"] = self._normalize_symbol(symbol)
            if baseCoin:
                params["baseCoin"] = self._normalize_coin(baseCoin)
            if settleCoin:
                params["settleCoin"] = self._normalize_coin(settleCoin)
            if orderId:
                params["orderId"] = str(orderId)
            if orderLinkId:
                params["orderLinkId"] = str(orderLinkId)

            response = self._request("get_order_history", **params)
            if not self._response_ok(response, "получении истории ордеров"):
                return None

            items = response.get("result", {}).get("list", [])
            return [self._coerce_numbers(item) for item in items]
        except Exception as error:
            print(f"❌ Ошибка при получении истории ордеров: {error}")
            return None

    def cancel_order(
        self,
        symbol: str,
        orderId: str | None = None,
        orderLinkId: str | None = None,
        category: str | None = None,
    ):
        """Отменяет ордер."""
        try:
            if not orderId and not orderLinkId:
                raise ValueError("orderId or orderLinkId is required")

            params = {
                "category": self._normalize_category(category),
                "symbol": self._normalize_symbol(symbol),
            }
            if orderId:
                params["orderId"] = str(orderId)
            if orderLinkId:
                params["orderLinkId"] = str(orderLinkId)

            response = self._request("cancel_order", **params)
            if response is None:
                return None

            if response.get("retCode") == 0:
                result = response.get("result", {})
                return {
                    "success": True,
                    "orderId": result.get("orderId"),
                    "orderLinkId": result.get("orderLinkId"),
                    "response": response,
                }

            print(f"❌ Ошибка отмены ордера: {response.get('retMsg')}")
            return {
                "success": False,
                "error": response.get("retMsg"),
                "retCode": response.get("retCode"),
                "response": response,
            }
        except Exception as error:
            print(f"❌ Исключение при отмене ордера: {error}")
            return None

    def cancel_all_orders(
        self,
        symbol: str | None = None,
        baseCoin: str | None = None,
        settleCoin: str | None = None,
        category: str | None = None,
    ):
        """Отменяет все активные ордера по фильтру."""
        try:
            params = {"category": self._normalize_category(category)}

            if symbol:
                params["symbol"] = self._normalize_symbol(symbol)
            if baseCoin:
                params["baseCoin"] = self._normalize_coin(baseCoin)
            if settleCoin:
                params["settleCoin"] = self._normalize_coin(settleCoin)

            response = self._request("cancel_all_orders", **params)
            if response is None:
                return None

            if response.get("retCode") == 0:
                result = response.get("result", {})
                return {
                    "success": True,
                    "list": self._coerce_numbers(result.get("list", [])),
                    "response": response,
                }

            print(f"❌ Ошибка массовой отмены ордеров: {response.get('retMsg')}")
            return {
                "success": False,
                "error": response.get("retMsg"),
                "retCode": response.get("retCode"),
                "response": response,
            }
        except Exception as error:
            print(f"❌ Исключение при массовой отмене ордеров: {error}")
            return None

    def amend_order(
        self,
        symbol: str,
        orderId: str | None = None,
        orderLinkId: str | None = None,
        qty=None,
        price=None,
        triggerPrice=None,
        takeProfit=None,
        stopLoss=None,
        category: str | None = None,
        **kwargs,
    ):
        """Изменяет существующий ордер."""
        try:
            if not orderId and not orderLinkId:
                raise ValueError("orderId or orderLinkId is required")

            params = {
                "category": self._normalize_category(category),
                "symbol": self._normalize_symbol(symbol),
            }

            if orderId:
                params["orderId"] = str(orderId)
            if orderLinkId:
                params["orderLinkId"] = str(orderLinkId)
            if qty is not None:
                params["qty"] = str(qty)
            if price is not None:
                params["price"] = str(price)
            if triggerPrice is not None:
                params["triggerPrice"] = str(triggerPrice)
            if takeProfit is not None:
                params["takeProfit"] = str(takeProfit)
            if stopLoss is not None:
                params["stopLoss"] = str(stopLoss)

            optional_params = [
                "tpTriggerBy",
                "slTriggerBy",
                "triggerBy",
                "tpLimitPrice",
                "slLimitPrice",
            ]
            for param in optional_params:
                if kwargs.get(param) is not None:
                    params[param] = kwargs[param]

            if len(params) <= 4:
                raise ValueError("No amend fields provided")

            response = self._request("amend_order", **params)
            if response is None:
                return None

            if response.get("retCode") == 0:
                result = response.get("result", {})
                return {
                    "success": True,
                    "orderId": result.get("orderId"),
                    "orderLinkId": result.get("orderLinkId"),
                    "response": response,
                }

            print(f"❌ Ошибка изменения ордера: {response.get('retMsg')}")
            return {
                "success": False,
                "error": response.get("retMsg"),
                "retCode": response.get("retCode"),
                "response": response,
            }
        except Exception as error:
            print(f"❌ Исключение при изменении ордера: {error}")
            return None

    def set_trading_stop(
        self,
        symbol: str,
        take_profit=None,
        stop_loss=None,
        trailing_stop=None,
        active_price=None,
        position_idx: int = 0,
        tpsl_mode: str = "Full",
        tp_trigger_by: str = "LastPrice",
        sl_trigger_by: str = "LastPrice",
        category: str | None = None,
        **kwargs,
    ):
        """Устанавливает TP/SL/Trailing Stop для позиции."""
        try:
            if take_profit is None and stop_loss is None and trailing_stop is None:
                raise ValueError("At least one of take_profit, stop_loss or trailing_stop is required")

            params = {
                "category": self._normalize_category(category),
                "symbol": self._normalize_symbol(symbol),
                "positionIdx": int(position_idx),
                "tpslMode": str(tpsl_mode),
                "tpTriggerBy": str(tp_trigger_by),
                "slTriggerBy": str(sl_trigger_by),
            }

            if take_profit is not None:
                params["takeProfit"] = str(take_profit)
            if stop_loss is not None:
                params["stopLoss"] = str(stop_loss)
            if trailing_stop is not None:
                params["trailingStop"] = str(trailing_stop)
            if active_price is not None:
                params["activePrice"] = str(active_price)

            optional_params = [
                "tpSize",
                "slSize",
                "tpLimitPrice",
                "slLimitPrice",
                "tpOrderType",
                "slOrderType",
            ]
            for param in optional_params:
                if kwargs.get(param) is not None:
                    params[param] = kwargs[param]

            response = self._request("set_trading_stop", **params)
            if response is None:
                return None

            if response.get("retCode") == 0:
                return {
                    "success": True,
                    "response": response,
                }

            print(f"❌ Ошибка установки trading stop: {response.get('retMsg')}")
            return {
                "success": False,
                "error": response.get("retMsg"),
                "retCode": response.get("retCode"),
                "response": response,
            }
        except Exception as error:
            print(f"❌ Исключение при установке trading stop: {error}")
            return None

    def set_leverage(
        self,
        symbol: str,
        buy_leverage,
        sell_leverage=None,
        category: str | None = None,
    ):
        """Устанавливает плечо для linear/inverse."""
        try:
            normalized_category = self._normalize_category(category)
            if normalized_category not in {"linear", "inverse"}:
                raise ValueError("set_leverage supports only linear/inverse categories")

            response = self._request(
                "set_leverage",
                category=normalized_category,
                symbol=self._normalize_symbol(symbol),
                buyLeverage=str(buy_leverage),
                sellLeverage=str(sell_leverage if sell_leverage is not None else buy_leverage),
            )
            if response is None:
                return None

            if response.get("retCode") == 0:
                return {"success": True, "response": response}

            print(f"❌ Ошибка установки плеча: {response.get('retMsg')}")
            return {
                "success": False,
                "error": response.get("retMsg"),
                "retCode": response.get("retCode"),
                "response": response,
            }
        except Exception as error:
            print(f"❌ Исключение при установке плеча: {error}")
            return None

    def get_executions(
        self,
        symbol: str | None = None,
        orderId: str | None = None,
        orderLinkId: str | None = None,
        startTime: int | None = None,
        endTime: int | None = None,
        execType: str | None = None,
        category: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ):
        """Возвращает исполнения ордеров."""
        try:
            params = {
                "category": self._normalize_category(category),
                "limit": min(max(1, int(limit)), 100),
            }

            if symbol:
                params["symbol"] = self._normalize_symbol(symbol)
            if orderId:
                params["orderId"] = str(orderId)
            if orderLinkId:
                params["orderLinkId"] = str(orderLinkId)
            if startTime is not None:
                params["startTime"] = int(startTime)
            if endTime is not None:
                params["endTime"] = int(endTime)
            if execType:
                params["execType"] = str(execType)
            if cursor:
                params["cursor"] = str(cursor)

            response = self._request("get_executions", **params)
            if not self._response_ok(response, "получении исполнений"):
                return None

            result = response.get("result", {})
            return {
                "list": [self._coerce_numbers(item) for item in result.get("list", [])],
                "nextPageCursor": result.get("nextPageCursor"),
                "category": result.get("category"),
            }
        except Exception as error:
            print(f"❌ Ошибка при получении исполнений: {error}")
            return None

    def get_closed_pnl(
        self,
        symbol: str | None = None,
        startTime: int | None = None,
        endTime: int | None = None,
        category: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ):
        """Возвращает историю closed pnl."""
        try:
            params = {
                "category": self._normalize_category(category),
                "limit": min(max(1, int(limit)), 100),
            }

            if symbol:
                params["symbol"] = self._normalize_symbol(symbol)
            if startTime is not None:
                params["startTime"] = int(startTime)
            if endTime is not None:
                params["endTime"] = int(endTime)
            if cursor:
                params["cursor"] = str(cursor)

            response = self._request("get_closed_pnl", **params)
            if not self._response_ok(response, "получении closed pnl"):
                return None

            result = response.get("result", {})
            return {
                "list": [self._coerce_numbers(item) for item in result.get("list", [])],
                "nextPageCursor": result.get("nextPageCursor"),
                "category": result.get("category"),
            }
        except Exception as error:
            print(f"❌ Ошибка при получении closed pnl: {error}")
            return None

    def get_available_balance(
        self,
        coin: str = "USDT",
        accountType: str = "UNIFIED",
    ):
        """Возвращает доступный баланс по монете."""
        try:
            response = self.get_wallet_balance(accountType=accountType, coin=coin)
            if not response:
                return None

            coin_data = response.get("coin")
            account_data = response.get("account", {})

            available_balance = None
            if coin_data:
                available_balance = (
                    coin_data.get("availableToWithdraw")
                    or coin_data.get("walletBalance")
                    or coin_data.get("equity")
                )

            return {
                "accountType": account_data.get("accountType"),
                "totalEquity": account_data.get("totalEquity"),
                "totalWalletBalance": account_data.get("totalWalletBalance"),
                "totalAvailableBalance": account_data.get("totalAvailableBalance"),
                "coin": coin_data,
                "availableBalance": available_balance,
            }
        except Exception as error:
            print(f"❌ Ошибка при получении доступного баланса: {error}")
            return None

    def close_position_market(
        self,
        symbol: str,
        category: str | None = None,
        position_idx: int | None = None,
    ):
        """Закрывает активную позицию market-ордером."""
        try:
            normalized_category = self._normalize_category(category)
            if normalized_category == "spot":
                print("❌ close_position_market не применяется к spot-позициям")
                return None

            position = self.get_position(
                symbol=symbol,
                category=normalized_category,
                active_only=True,
            )
            if not position:
                return {
                    "success": False,
                    "reason": "NO_ACTIVE_POSITION",
                    "symbol": self._normalize_symbol(symbol),
                }

            size = position.get("size", 0) or 0
            side = str(position.get("side", "")).capitalize()

            try:
                qty = abs(float(size))
            except Exception:
                qty = 0.0

            if qty <= 0 or side not in {"Buy", "Sell"}:
                return {
                    "success": False,
                    "reason": "INVALID_POSITION",
                    "symbol": self._normalize_symbol(symbol),
                    "position": position,
                }

            close_side = "Sell" if side == "Buy" else "Buy"
            actual_position_idx = (
                int(position_idx)
                if position_idx is not None
                else int(position.get("positionIdx", 0) or 0)
            )

            response = self.place_order(
                symbol=self._normalize_symbol(symbol),
                side=close_side,
                orderType="Market",
                qty=str(qty),
                category=normalized_category,
                reduceOnly=True,
                closeOnTrigger=True,
                positionIdx=actual_position_idx,
                timeInForce="IOC",
            )

            return {
                "success": bool(response and response.get("success")),
                "symbol": self._normalize_symbol(symbol),
                "closed_side": close_side,
                "qty": qty,
                "positionIdx": actual_position_idx,
                "position": position,
                "order_response": response,
            }
        except Exception as error:
            print(f"❌ Ошибка при market close позиции {symbol}: {error}")
            return None

    def sync_order_status(
        self,
        symbol: str,
        orderId: str | None = None,
        orderLinkId: str | None = None,
        category: str | None = None,
    ):
        """Синхронизирует статус ордера через open orders и history."""
        try:
            if not orderId and not orderLinkId:
                raise ValueError("orderId or orderLinkId is required")

            normalized_symbol = self._normalize_symbol(symbol)
            normalized_category = self._normalize_category(category)

            open_orders = self.get_open_orders(
                symbol=normalized_symbol,
                orderId=orderId,
                orderLinkId=orderLinkId,
                category=normalized_category,
                limit=50,
            ) or []

            if open_orders:
                order = open_orders[0]
                return {
                    "found": True,
                    "source": "open_orders",
                    "is_open": True,
                    "is_final": False,
                    "status": order.get("orderStatus"),
                    "filled_qty": order.get("cumExecQty", 0),
                    "remaining_qty": order.get("leavesQty"),
                    "avg_price": order.get("avgPrice"),
                    "order": order,
                }

            history_orders = self.get_order_history(
                symbol=normalized_symbol,
                orderId=orderId,
                orderLinkId=orderLinkId,
                category=normalized_category,
                limit=50,
            ) or []

            if history_orders:
                order = history_orders[0]
                final_statuses = {
                    "Filled",
                    "Cancelled",
                    "Rejected",
                    "Deactivated",
                    "PartiallyFilledCanceled",
                }
                status = order.get("orderStatus")
                return {
                    "found": True,
                    "source": "order_history",
                    "is_open": False,
                    "is_final": status in final_statuses,
                    "status": status,
                    "filled_qty": order.get("cumExecQty", 0),
                    "remaining_qty": order.get("leavesQty"),
                    "avg_price": order.get("avgPrice"),
                    "order": order,
                }

            return {
                "found": False,
                "source": None,
                "is_open": False,
                "is_final": False,
                "status": "NOT_FOUND",
                "filled_qty": 0,
                "remaining_qty": None,
                "avg_price": None,
                "order": None,
            }
        except Exception as error:
            print(f"❌ Ошибка при синхронизации статуса ордера: {error}")
            return None

    def sync_position_state(
        self,
        symbol: str,
        category: str | None = None,
    ):
        """Возвращает текущее состояние символа: FLAT / PENDING / OPEN."""
        try:
            normalized_symbol = self._normalize_symbol(symbol)
            normalized_category = self._normalize_category(category)

            position = self.get_position(
                symbol=normalized_symbol,
                category=normalized_category,
                active_only=True,
            )

            open_orders = self.get_open_orders(
                symbol=normalized_symbol,
                category=normalized_category,
                limit=50,
            ) or []

            active_orders = [
                order
                for order in open_orders
                if str(order.get("symbol", "")).upper() == normalized_symbol
            ]

            if position:
                return {
                    "symbol": normalized_symbol,
                    "state": "OPEN",
                    "has_position": True,
                    "position_size": position.get("size", 0),
                    "position_side": position.get("side"),
                    "position": position,
                    "open_orders": active_orders,
                }

            if active_orders:
                return {
                    "symbol": normalized_symbol,
                    "state": "PENDING",
                    "has_position": False,
                    "position_size": 0,
                    "position_side": None,
                    "position": None,
                    "open_orders": active_orders,
                }

            return {
                "symbol": normalized_symbol,
                "state": "FLAT",
                "has_position": False,
                "position_size": 0,
                "position_side": None,
                "position": None,
                "open_orders": [],
            }
        except Exception as error:
            print(f"❌ Ошибка при синхронизации состояния позиции {symbol}: {error}")
            return None

    
bybit_client = BybitClient()


def get_bybit_client() -> BybitClient:
    """Возвращает глобальный экземпляр клиента для повторного использования в проекте."""
    return bybit_client