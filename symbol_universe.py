from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bybit_client_v2 import bybit_client
from coinmarketcap_client import get_coinmarketcap_data
from config import (
    MIN_MARKET_CAP,
    UNIVERSE_FILTER_EXCLUDE_STABLECOINS,
    UNIVERSE_FILTER_MIN_MARKET_CAP,
    UNIVERSE_FILTER_MIN_VOLUME_24H,
)


COMMON_SYMBOLS_FILE = "data/common_symbols.txt"
LEGACY_FILTERED_SYMBOLS_FILE = "data/filtered_symbols.txt"
UNIVERSE_SYNC_LOG_FILE = "logs/universe_sync_report.txt"


def load_symbols_from_file(file_path: str) -> list[str]:
    """Загружает символы из текстового файла, по одному символу на строку."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Symbols file not found: {file_path}")

    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        symbol = line.strip()
        if symbol:
            symbols.append(symbol)
    return list(dict.fromkeys(symbols))


def write_symbols_file(file_path: str, symbols: list[str]) -> None:
    """Сохраняет список символов по одному на строку."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handle:
        for symbol in symbols:
            file_handle.write(f"{symbol}\n")


def load_common_symbols(file_path: str = COMMON_SYMBOLS_FILE) -> list[str]:
    """Возвращает общий список символов для всех стратегий."""
    try:
        return load_symbols_from_file(file_path)
    except FileNotFoundError:
        if file_path == COMMON_SYMBOLS_FILE:
            try:
                return load_symbols_from_file(LEGACY_FILTERED_SYMBOLS_FILE)
            except FileNotFoundError:
                return []
        return []


def append_universe_sync_log(
    *,
    output_file: str,
    total_spot_symbols: int,
    eligible_symbols: int,
    min_market_cap: float,
    min_volume_24h: float,
    exclude_stablecoins: bool,
    log_file: str = UNIVERSE_SYNC_LOG_FILE,
) -> None:
    """Пишет компактную запись о последнем обновлении общего universe."""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{timestamp} | total_spot_symbols={total_spot_symbols} | "
            f"eligible_symbols={eligible_symbols} | min_market_cap={min_market_cap} | "
            f"min_volume_24h={min_volume_24h} | exclude_stablecoins={exclude_stablecoins} | "
            f"common_symbols_file={output_file}\n"
        )


def get_base_currency(symbol: str) -> str | None:
    """Возвращает базовую валюту для USDT-пары."""
    return symbol[:-4] if symbol.endswith("USDT") else None


def chunked(items: list[str], chunk_size: int) -> Iterator[list[str]]:
    """Разбивает список на чанки фиксированного размера."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    for index in range(0, len(items), chunk_size):
        yield items[index:index + chunk_size]


def fetch_spot_usdt_symbols() -> list[str]:
    """Получает актуальный список торгуемых спотовых USDT-пар с Bybit."""
    session = getattr(bybit_client, "session", None)
    if session is None:
        return []

    symbols: list[str] = []
    cursor: str | None = None

    while True:
        params: dict[str, Any] = {"category": "spot", "limit": 1000}
        if cursor:
            params["cursor"] = cursor

        try:
            response = session.get_instruments_info(**params)
        except Exception:
            return []

        if not isinstance(response, dict) or response.get("retCode") != 0:
            return []

        result = response.get("result", {}) or {}
        instruments = result.get("list", []) or []
        for item in instruments:
            symbol = str(item.get("symbol", "")).strip().upper()
            quote_coin = str(item.get("quoteCoin", "")).strip().upper()
            status = str(item.get("status", "")).strip().upper()
            if symbol and quote_coin == "USDT" and status == "TRADING":
                symbols.append(symbol)

        cursor = result.get("nextPageCursor") or None
        if not cursor:
            break

    return list(dict.fromkeys(symbols))


def get_coinmarketcap_data_batched(
    symbols: list[str],
    batch_size: int = 80,
) -> dict[str, dict[str, Any]]:
    """Получает данные CMC по символам батчами, чтобы не упираться в лимиты URL/API."""
    results: dict[str, dict[str, Any]] = {}
    for batch in chunked(symbols, batch_size):
        batch_data = get_coinmarketcap_data(batch)
        if not batch_data:
            continue
        results.update(batch_data)
    return results


def should_keep_symbol_by_market_data(
    market_data: dict[str, Any] | None,
    min_market_cap: float,
    min_volume_24h: float,
    exclude_stablecoins: bool,
) -> bool:
    """Применяет market-cap и ликвидностный фильтр к символу по данным CMC."""
    if not market_data:
        return False

    if market_data.get("is_fiat"):
        return False

    tags = {str(tag).strip().lower() for tag in (market_data.get("tags") or [])}
    if exclude_stablecoins and "stablecoin" in tags:
        return False

    market_cap = float(market_data.get("market_cap", 0) or 0)
    volume_24h = float(market_data.get("volume_24h", 0) or 0)
    return market_cap >= min_market_cap and volume_24h >= min_volume_24h


def refresh_common_symbols(
    output_file: str = COMMON_SYMBOLS_FILE,
    min_market_cap: float = UNIVERSE_FILTER_MIN_MARKET_CAP,
    min_volume_24h: float = UNIVERSE_FILTER_MIN_VOLUME_24H,
    exclude_stablecoins: bool = UNIVERSE_FILTER_EXCLUDE_STABLECOINS,
) -> list[str]:
    """Формирует общий список спотовых USDT-пар Bybit по market cap и объему CMC."""
    spot_symbols = fetch_spot_usdt_symbols()
    if not spot_symbols:
        append_universe_sync_log(
            output_file=output_file,
            total_spot_symbols=0,
            eligible_symbols=0,
            min_market_cap=min_market_cap,
            min_volume_24h=min_volume_24h,
            exclude_stablecoins=exclude_stablecoins,
        )
        return []

    cmc_data = get_coinmarketcap_data_batched(spot_symbols)
    eligible_coins: list[dict[str, Any]] = []
    for symbol in spot_symbols:
        base_currency = get_base_currency(symbol)
        if base_currency is None:
            continue

        market_data = cmc_data.get(base_currency)
        if not should_keep_symbol_by_market_data(
            market_data=market_data,
            min_market_cap=min_market_cap,
            min_volume_24h=min_volume_24h,
            exclude_stablecoins=exclude_stablecoins,
        ):
            continue

        eligible_coins.append(
            {
                "symbol": symbol,
                "market_cap": float(market_data.get("market_cap", 0) or 0),
                "volume_24h": float(market_data.get("volume_24h", 0) or 0),
            }
        )

    eligible_coins.sort(key=lambda item: (item["market_cap"], item["volume_24h"]), reverse=True)
    common_symbols = [coin["symbol"] for coin in eligible_coins]
    write_symbols_file(output_file, common_symbols)
    append_universe_sync_log(
        output_file=output_file,
        total_spot_symbols=len(spot_symbols),
        eligible_symbols=len(common_symbols),
        min_market_cap=min_market_cap,
        min_volume_24h=min_volume_24h,
        exclude_stablecoins=exclude_stablecoins,
    )
    return common_symbols


def refresh_filtered_symbols(
    output_file: str = COMMON_SYMBOLS_FILE,
    min_market_cap: float = UNIVERSE_FILTER_MIN_MARKET_CAP,
    min_volume_24h: float = UNIVERSE_FILTER_MIN_VOLUME_24H,
    exclude_stablecoins: bool = UNIVERSE_FILTER_EXCLUDE_STABLECOINS,
) -> list[str]:
    """Совместимость со старым именем API: обновляет общий список символов."""
    return refresh_common_symbols(
        output_file=output_file,
        min_market_cap=min_market_cap,
        min_volume_24h=min_volume_24h,
        exclude_stablecoins=exclude_stablecoins,
    )


FILTERED_SYMBOLS_FILE = COMMON_SYMBOLS_FILE