import contextlib
import csv
import json
import math
from numbers import Real
from pathlib import Path
from typing import Any

import pandas as pd

from analyzes.entry_trigger_1h import EntryTrigger1hConfig, entry_trigger_1h
from analyzes.setup_filter_4h import SetupFilter4hConfig, setup_filter_4h
from analyzes.trend_filter_12h_v2 import TrendFilter12hConfig, trend_filter_12h
from bybit_client_v2 import bybit_client
from config import UNIVERSE_FILTER_MIN_MARKET_CAP, UNIVERSE_FILTER_MIN_VOLUME_24H
from symbol_universe import (
    COMMON_SYMBOLS_FILE,
    load_symbols_from_file,
    refresh_common_symbols,
    write_symbols_file,
)


DYNAMIC_SYMBOLS_FILE = "data/dynamic_symbols.txt"
DEFAULT_REPORT_TSV_FILE = "logs/calibration_report_filtered_symbols_stream.tsv"
DEFAULT_REPORT_TEXT_FILE = "logs/calibration_report_auto.txt"
CALIBRATION_SCHEDULE_STATE_FILE = "data/calibration_schedule_state.json"

AUTO_UPDATE_4H_WINDOW_START_MINUTE = 2
AUTO_UPDATE_4H_WINDOW_END_MINUTE = 5

DEFAULT_TREND_SOFT = 2
DEFAULT_SETUP_SOFT = 6
DEFAULT_ENTRY_SOFT = 5
DEFAULT_ENTRY_MAX_EXTENSION = 1.6

DEFAULT_LIMIT_12H = 400
DEFAULT_LIMIT_4H = 400
DEFAULT_LIMIT_1H = 400


def prepare_ohlcv_for_filter(
    raw_df: pd.DataFrame | None,
    interval_minutes: int,
    drop_incomplete_last_candle: bool = True,
) -> pd.DataFrame:
    """Нормализует свечи для фильтров и убирает незакрытую последнюю свечу."""
    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    df = raw_df.copy()
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.set_index("timestamp")
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.dropna()

    if df.empty:
        return df

    # Предполагается, что timestamp у свечи — это время открытия свечи.
    # Если последняя свеча попадает в текущий незавершённый bucket, удаляем её.
    if drop_incomplete_last_candle:
        now_utc = pd.Timestamp.now(tz="UTC")
        interval_delta = pd.Timedelta(minutes=interval_minutes)
        interval_ns = interval_delta.value
        current_bucket_start = pd.Timestamp(
            (now_utc.value // interval_ns) * interval_ns,
            tz="UTC",
        )
        if df.index[-1] >= current_bucket_start:
            df = df.iloc[:-1]

    return df


def safe_round(value: Any, digits: int = 4) -> Any:
    """Округляет число для отчета, не ломаясь на None/NaN/inf и numpy scalar."""
    if value is None:
        return None
    if isinstance(value, Real):
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, digits)
    return value


def parse_bool(value: Any) -> bool:
    """Преобразует строковое/произвольное значение в bool."""
    return str(value).strip().lower() in {"true", "1", "yes"}


def collect_failed_conditions(conditions: dict[str, bool] | None) -> list[str]:
    """Возвращает список неуспешных условий для компактного отчета."""
    if not conditions:
        return []
    return [key for key, value in conditions.items() if not value]


def collect_passed_conditions(conditions: dict[str, bool] | None) -> list[str]:
    """Возвращает список успешно выполненных условий для подробного human-readable отчета."""
    if not conditions:
        return []
    return [key for key, value in conditions.items() if value]


def load_calibration_schedule_state(
    file_path: str = CALIBRATION_SCHEDULE_STATE_FILE,
) -> dict[str, Any]:
    """Загружает состояние автоматического scheduler для calibration-report."""
    path = Path(file_path)
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_calibration_schedule_state(
    state: dict[str, Any],
    file_path: str = CALIBRATION_SCHEDULE_STATE_FILE,
) -> None:
    """Сохраняет состояние автоматического scheduler для calibration-report."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def is_auto_update_window(now_utc: pd.Timestamp) -> bool:
    """Проверяет, попадает ли текущее UTC-время в окно автозапуска после закрытия 4H свечи."""
    if now_utc.minute < AUTO_UPDATE_4H_WINDOW_START_MINUTE:
        return False
    if now_utc.minute > AUTO_UPDATE_4H_WINDOW_END_MINUTE:
        return False
    return now_utc.hour % 4 == 0


def get_current_4h_close_marker(now_utc: pd.Timestamp) -> str:
    """Возвращает marker текущего 4H-close event в UTC."""
    now_ts = pd.Timestamp(now_utc)
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = now_ts.tz_convert("UTC")

    return now_ts.floor("4h").isoformat()


def build_default_configs(
    trend_soft: int = DEFAULT_TREND_SOFT,
    setup_soft: int = DEFAULT_SETUP_SOFT,
    entry_soft: int = DEFAULT_ENTRY_SOFT,
    entry_max_extension: float = DEFAULT_ENTRY_MAX_EXTENSION,
) -> tuple[TrendFilter12hConfig, SetupFilter4hConfig, EntryTrigger1hConfig]:
    """Создает стандартные конфиги для batch-calibration и автоматического scheduler."""
    return (
        TrendFilter12hConfig(
            min_required_rows=260,
            min_soft_conditions_passed=trend_soft,
        ),
        SetupFilter4hConfig(
            min_required_rows=220,
            min_soft_conditions_passed=setup_soft,
        ),
        EntryTrigger1hConfig(
            min_required_rows=180,
            min_soft_conditions_passed=entry_soft,
            max_extension_from_ema20_atr=entry_max_extension,
        ),
    )


def validate_dynamic_stage(min_stage: str) -> None:
    """Проверяет корректность минимальной стадии для dynamic universe."""
    valid_stages = {"trend", "setup", "entry"}
    if min_stage not in valid_stages:
        raise ValueError(f"Unsupported dynamic min stage: {min_stage!r}")


def resolve_dynamic_rank(
    trend_passed: bool,
    setup_passed: bool,
    entry_action: str,
    min_stage: str,
) -> int | None:
    """Возвращает приоритет символа для dynamic universe или None."""
    validate_dynamic_stage(min_stage)
    if entry_action == "ENTER":
        return 0
    if entry_action == "WAIT_BETTER":
        return 1
    if setup_passed and min_stage in {"trend", "setup"}:
        return 2
    if trend_passed and min_stage == "trend":
        return 3
    return None


def build_dynamic_symbols(report_rows: list[dict[str, Any]], min_stage: str = "setup") -> list[str]:
    """Строит dynamic_symbols из calibration-report, оставляя только актуальные тикеры."""
    validate_dynamic_stage(min_stage)

    ranked_symbols: list[tuple[int, str]] = []
    for row in report_rows:
        if row.get("status") != "ok":
            continue

        trend = row["12H"]
        setup = row["4H"]
        entry = row["1H"]
        rank = resolve_dynamic_rank(
            trend_passed=bool(trend["passed"]),
            setup_passed=bool(setup["passed"]),
            entry_action=str(entry["action"]),
            min_stage=min_stage,
        )
        if rank is not None:
            ranked_symbols.append((rank, row["symbol"]))

    ranked_symbols.sort(key=lambda item: (item[0], item[1]))
    return [symbol for _, symbol in ranked_symbols]


def write_report_tsv_header(writer: csv.writer) -> None:
    """Пишет header для machine-readable TSV calibration report."""
    writer.writerow([
        "symbol",
        "status",
        "trend_passed",
        "trend_soft",
        "setup_passed",
        "setup_state",
        "setup_soft",
        "entry_passed",
        "action",
        "trigger_state",
        "entry_soft",
        "ext_atr",
        "vol_ratio",
        "rr",
        "risk_pct",
        "reason",
    ])


def write_report_tsv_row(writer: csv.writer, row: dict[str, Any]) -> None:
    """Пишет одну строку TSV calibration report."""
    if row.get("status") != "ok":
        writer.writerow([
            row.get("symbol", ""),
            row.get("status", "error"),
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            row.get("reason", ""),
        ])
        return

    trend = row["12H"]
    setup = row["4H"]
    entry = row["1H"]
    writer.writerow([
        row["symbol"],
        row["status"],
        trend["passed"],
        f"{trend['soft_score']}/{trend['soft_score_max']}",
        setup["passed"],
        setup["setup_state"],
        f"{setup['soft_score']}/{setup['soft_score_max']}",
        entry["passed"],
        entry["action"],
        entry["trigger_state"],
        f"{entry['soft_score']}/{entry['soft_score_max']}",
        entry["current_extension_atr"],
        entry["volume_ratio"],
        entry["rr"],
        entry["risk_pct"],
        entry["reason"],
    ])


def write_report_tsv(report_rows: list[dict[str, Any]], output_file: str) -> None:
    """Сохраняет calibration-report в TSV-формате."""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        write_report_tsv_header(writer)
        for row in report_rows:
            write_report_tsv_row(writer, row)


def build_dynamic_symbols_from_report_file(report_file: str, min_stage: str = "setup") -> list[str]:
    """Пересобирает dynamic_symbols из уже готового TSV-отчета без повторного сетевого прогона."""
    validate_dynamic_stage(min_stage)
    report_path = Path(report_file)
    if not report_path.exists():
        raise FileNotFoundError(f"Report file not found: {report_file}")

    ranked_symbols: list[tuple[int, str]] = []
    seen: set[str] = set()
    with report_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if row.get("status") != "ok":
                continue

            symbol = str(row.get("symbol", "")).strip()
            if not symbol or symbol in seen:
                continue

            rank = resolve_dynamic_rank(
                trend_passed=parse_bool(row.get("trend_passed")),
                setup_passed=parse_bool(row.get("setup_passed")),
                entry_action=str(row.get("action", "")).strip(),
                min_stage=min_stage,
            )
            if rank is None:
                continue

            ranked_symbols.append((rank, symbol))
            seen.add(symbol)

    ranked_symbols.sort(key=lambda item: (item[0], item[1]))
    return [symbol for _, symbol in ranked_symbols]


def analyze_symbol(
    symbol: str,
    trend_config: TrendFilter12hConfig,
    setup_config: SetupFilter4hConfig,
    entry_config: EntryTrigger1hConfig,
    limit_12h: int,
    limit_4h: int,
    limit_1h: int,
) -> dict[str, Any]:
    """Прогоняет один символ через 12H -> 4H -> 1H и возвращает compact report row."""
    raw_12h = bybit_client.get_klines(symbol=symbol, interval="720", limit=limit_12h)
    raw_4h = bybit_client.get_klines(symbol=symbol, interval="240", limit=limit_4h)
    raw_1h = bybit_client.get_klines(symbol=symbol, interval="60", limit=limit_1h)

    df_12h = prepare_ohlcv_for_filter(raw_12h, interval_minutes=720)
    df_4h = prepare_ohlcv_for_filter(raw_4h, interval_minutes=240)
    df_1h = prepare_ohlcv_for_filter(raw_1h, interval_minutes=60)

    if df_12h.empty or df_4h.empty or df_1h.empty:
        return {
            "symbol": symbol,
            "status": "missing_data",
            "rows": {"12H": len(df_12h), "4H": len(df_4h), "1H": len(df_1h)},
            "reason": "Missing data on at least one timeframe after cleaning",
        }

    trend_result = trend_filter_12h(df_12h, config=trend_config)
    setup_result = setup_filter_4h(
        df_4h,
        trend_bias_passed=trend_result.passed,
        trend_bias_reason=trend_result.reason,
        config=setup_config,
    )
    entry_result = entry_trigger_1h(df_1h, setup_result=setup_result, config=entry_config)

    trend_hard = trend_result.details.get("hard_conditions", {})
    trend_soft = trend_result.details.get("soft_conditions", {})
    setup_hard = setup_result.details.get("hard_conditions", {})
    setup_soft = setup_result.details.get("soft_conditions", {})
    entry_hard = entry_result.details.get("hard_conditions", {})
    entry_soft = entry_result.details.get("soft_conditions", {})
    entry_last = entry_result.details.get("last_candle", {})

    return {
        "symbol": symbol,
        "status": "ok",
        "rows": {"12H": len(df_12h), "4H": len(df_4h), "1H": len(df_1h)},
        "last_closed": {
            "12H": str(df_12h.index[-1]),
            "4H": str(df_4h.index[-1]),
            "1H": str(df_1h.index[-1]),
        },
        "12H": {
            "passed": trend_result.passed,
            "hard_passed": trend_result.hard_passed,
            "soft_score": trend_result.soft_score,
            "soft_score_max": trend_result.soft_score_max,
            "reason": trend_result.reason,
            "passed_soft": collect_passed_conditions(trend_soft),
            "failed_hard": collect_failed_conditions(trend_hard),
            "failed_soft": collect_failed_conditions(trend_soft),
        },
        "4H": {
            "passed": setup_result.passed,
            "hard_passed": setup_result.hard_passed,
            "setup_state": setup_result.setup_state,
            "soft_score": setup_result.soft_score,
            "soft_score_max": setup_result.soft_score_max,
            "reason": setup_result.reason,
            "passed_soft": collect_passed_conditions(setup_soft),
            "failed_hard": collect_failed_conditions(setup_hard),
            "failed_soft": collect_failed_conditions(setup_soft),
            "volume_ratio": safe_round(setup_result.details.get("last_candle", {}).get("volume_ratio"), 3),
            "current_extension_atr": safe_round(
                setup_result.details.get("pullback", {}).get("current_extension_atr"),
                3,
            ),
        },
        "1H": {
            "passed": entry_result.passed,
            "action": entry_result.action,
            "trigger_state": entry_result.trigger_state,
            "hard_passed": entry_result.hard_passed,
            "soft_score": entry_result.soft_score,
            "soft_score_max": entry_result.soft_score_max,
            "reason": entry_result.reason,
            "passed_soft": collect_passed_conditions(entry_soft),
            "failed_hard": collect_failed_conditions(entry_hard),
            "failed_soft": collect_failed_conditions(entry_soft),
            "volume_ratio": safe_round(entry_last.get("volume_ratio"), 3),
            "current_extension_atr": safe_round(entry_last.get("current_extension_atr"), 3),
            "entry": safe_round(entry_result.entry_price, 6),
            "stop": safe_round(entry_result.stop_loss, 6),
            "take": safe_round(entry_result.take_profit, 6),
            "rr": safe_round(entry_result.reward_risk, 3),
            "risk_pct": safe_round(entry_result.risk_percent, 3),
        },
    }


def build_report_rows(
    symbols: list[str],
    trend_config: TrendFilter12hConfig,
    setup_config: SetupFilter4hConfig,
    entry_config: EntryTrigger1hConfig,
    limit_12h: int = DEFAULT_LIMIT_12H,
    limit_4h: int = DEFAULT_LIMIT_4H,
    limit_1h: int = DEFAULT_LIMIT_1H,
    stream_tsv_output_file: str | None = None,
) -> list[dict[str, Any]]:
    """Строит calibration-report rows для списка символов."""
    report_rows: list[dict[str, Any]] = []
    stream_handle = None
    stream_writer = None
    if stream_tsv_output_file:
        stream_path = Path(stream_tsv_output_file)
        stream_path.parent.mkdir(parents=True, exist_ok=True)
        stream_handle = stream_path.open("w", encoding="utf-8", newline="", buffering=1)
        stream_writer = csv.writer(stream_handle, delimiter="\t")
        write_report_tsv_header(stream_writer)

    try:
        for symbol in symbols:
            try:
                row = analyze_symbol(
                    symbol=symbol,
                    trend_config=trend_config,
                    setup_config=setup_config,
                    entry_config=entry_config,
                    limit_12h=limit_12h,
                    limit_4h=limit_4h,
                    limit_1h=limit_1h,
                )
            except Exception as exc:
                row = {"symbol": symbol, "status": "error", "reason": repr(exc)}

            report_rows.append(row)
            if stream_writer is not None:
                write_report_tsv_row(stream_writer, row)
    finally:
        if stream_handle is not None:
            stream_handle.close()

    return report_rows


def run_calibration_pipeline(
    symbols: list[str],
    *,
    trend_soft: int,
    setup_soft: int,
    entry_soft: int,
    entry_max_extension: float,
    limit_12h: int,
    limit_4h: int,
    limit_1h: int,
    stream_tsv_output_file: str | None = None,
) -> list[dict[str, Any]]:
    """Общий pipeline анализа для scheduler и manual entrypoint."""
    trend_config, setup_config, entry_config = build_default_configs(
        trend_soft=trend_soft,
        setup_soft=setup_soft,
        entry_soft=entry_soft,
        entry_max_extension=entry_max_extension,
    )
    return build_report_rows(
        symbols=symbols,
        trend_config=trend_config,
        setup_config=setup_config,
        entry_config=entry_config,
        limit_12h=limit_12h,
        limit_4h=limit_4h,
        limit_1h=limit_1h,
        stream_tsv_output_file=stream_tsv_output_file,
    )


def print_summary_table(report_rows: list[dict[str, Any]]) -> None:
    """Печатает компактную таблицу по всем символам с разделением OK / NO_DATA / ERROR."""
    headers = [
        "SYMBOL",
        "STATUS",
        "12H",
        "4H",
        "4H_STATE",
        "1H",
        "1H_STATE",
        "EXT_ATR",
        "VOL_R",
        "RR",
        "RISK%",
        "NOTE",
    ]
    rows: list[list[str]] = []

    for row in report_rows:
        status = row.get("status")
        if status == "missing_data":
            rows.append([
                row["symbol"],
                "NO_DATA",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                row.get("reason", "-"),
            ])
            continue
        if status != "ok":
            rows.append([
                row.get("symbol", "-"),
                "ERROR",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
                row.get("reason", "-"),
            ])
            continue

        trend = row["12H"]
        setup = row["4H"]
        entry = row["1H"]
        rows.append([
            row["symbol"],
            "OK",
            f"{'PASS' if trend['passed'] else 'FAIL'} {trend['soft_score']}/{trend['soft_score_max']}",
            f"{'PASS' if setup['passed'] else 'FAIL'} {setup['soft_score']}/{setup['soft_score_max']}",
            setup["setup_state"],
            entry["action"],
            entry["trigger_state"],
            str(entry["current_extension_atr"]),
            str(entry["volume_ratio"]),
            str(entry["rr"]),
            str(entry["risk_pct"]),
            entry["reason"],
        ])

    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]

    def render(cells: list[str]) -> str:
        return " | ".join(cell.ljust(width) for cell, width in zip(cells, widths))

    separator = "-+-".join("-" * width for width in widths)
    print(render(headers))
    print(separator)
    for row in rows:
        print(render(row))


def print_detail_sections(report_rows: list[dict[str, Any]]) -> None:
    """Печатает подробные причины pass/fail для калибровки."""
    for row in report_rows:
        print()
        print(f"=== {row['symbol']} ===")
        if row["status"] != "ok":
            print(f"status={row['status']}")
            print(row.get("reason", "Unknown error"))
            print(f"rows={row.get('rows')}")
            continue

        print(f"rows={row['rows']} | last_closed={row['last_closed']}")
        trend = row["12H"]
        setup = row["4H"]
        entry = row["1H"]

        print(
            f"12H: passed={trend['passed']} hard={trend['hard_passed']} "
            f"soft={trend['soft_score']}/{trend['soft_score_max']} reason={trend['reason']}"
        )
        if trend.get("passed_soft"):
            print(f"  passed_soft={trend['passed_soft']}")
        if trend["failed_hard"] or trend["failed_soft"]:
            print(f"  failed_hard={trend['failed_hard']} | failed_soft={trend['failed_soft']}")

        print(
            f"4H: passed={setup['passed']} state={setup['setup_state']} hard={setup['hard_passed']} "
            f"soft={setup['soft_score']}/{setup['soft_score_max']} ext_atr={setup['current_extension_atr']} "
            f"vol_ratio={setup['volume_ratio']}"
        )
        print(f"  reason={setup['reason']}")
        if setup.get("passed_soft"):
            print(f"  passed_soft={setup['passed_soft']}")
        if setup["failed_hard"] or setup["failed_soft"]:
            print(f"  failed_hard={setup['failed_hard']} | failed_soft={setup['failed_soft']}")

        print(
            f"1H: passed={entry['passed']} action={entry['action']} state={entry['trigger_state']} "
            f"hard={entry['hard_passed']} soft={entry['soft_score']}/{entry['soft_score_max']} "
            f"ext_atr={entry['current_extension_atr']} vol_ratio={entry['volume_ratio']}"
        )
        print(f"  reason={entry['reason']}")
        if entry.get("passed_soft"):
            print(f"  passed_soft={entry['passed_soft']}")
        if entry["failed_hard"] or entry["failed_soft"]:
            print(f"  failed_hard={entry['failed_hard']} | failed_soft={entry['failed_soft']}")
        if entry["entry"] is not None:
            print(
                f"  trade=entry:{entry['entry']} stop:{entry['stop']} "
                f"take:{entry['take']} rr:{entry['rr']} risk_pct:{entry['risk_pct']}"
            )


def emit_report(
    report_rows: list[dict[str, Any]],
    *,
    symbols_count: int,
    trend_soft: int,
    setup_soft: int,
    entry_soft: int,
    entry_max_extension: float,
    common_output_file: str | None = None,
    dynamic_output_file: str | None = None,
    dynamic_min_stage: str | None = None,
    include_details: bool = False,
) -> None:
    """Печатает calibration-report в stdout или в redirected file handle."""
    print("Calibration config:")
    print(
        f"trend_soft={trend_soft} | setup_soft={setup_soft} | "
        f"entry_soft={entry_soft} | entry_max_extension={entry_max_extension}"
    )
    print(f"symbols_count={symbols_count}")
    if common_output_file:
        print(f"common_symbols_file={common_output_file}")
    if dynamic_output_file and dynamic_min_stage:
        print(f"dynamic_symbols_file={dynamic_output_file} | min_stage={dynamic_min_stage}")
    print()
    print_summary_table(report_rows)
    if include_details:
        print()
        print("Detailed sections:")
        print_detail_sections(report_rows)


def write_human_report(
    report_rows: list[dict[str, Any]],
    output_file: str,
    *,
    symbols_count: int,
    trend_soft: int,
    setup_soft: int,
    entry_soft: int,
    entry_max_extension: float,
    common_output_file: str | None = None,
    dynamic_output_file: str | None = None,
    dynamic_min_stage: str | None = None,
    include_details: bool = True,
) -> None:
    """Сохраняет подробный human-readable calibration-report в текстовый файл."""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", buffering=1) as file_handle:
        with contextlib.redirect_stdout(file_handle):
            emit_report(
                report_rows,
                symbols_count=symbols_count,
                trend_soft=trend_soft,
                setup_soft=setup_soft,
                entry_soft=entry_soft,
                entry_max_extension=entry_max_extension,
                common_output_file=common_output_file,
                dynamic_output_file=dynamic_output_file,
                dynamic_min_stage=dynamic_min_stage,
                include_details=include_details,
            )


def run_scheduled_calibration(now_utc: pd.Timestamp | None = None) -> dict[str, Any]:
    """Автоматически обновляет filtered/dynamic symbols по расписанию без CLI-задач."""
    now_ts = pd.Timestamp.now(tz="UTC") if now_utc is None else pd.Timestamp(now_utc)
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = now_ts.tz_convert("UTC")

    if not is_auto_update_window(now_ts):
        return {"ran": False, "reason": "outside_auto_update_window", "now_utc": now_ts.isoformat()}

    state = load_calibration_schedule_state()
    current_close_marker = get_current_4h_close_marker(now_ts)
    current_date = now_ts.date().isoformat()

    should_refresh_filtered = state.get("last_filtered_refresh_date") != current_date
    dynamic_due_by_4h = state.get("last_dynamic_refresh_close") != current_close_marker
    should_update_dynamic = dynamic_due_by_4h or should_refresh_filtered

    if not should_update_dynamic:
        return {
            "ran": False,
            "reason": "already_processed_current_window",
            "now_utc": now_ts.isoformat(),
            "close_marker": current_close_marker,
        }

    if should_refresh_filtered:
        refresh_common_symbols(output_file=COMMON_SYMBOLS_FILE)
        state["last_filtered_refresh_date"] = current_date

    try:
        symbols = load_symbols_from_file(COMMON_SYMBOLS_FILE)
    except FileNotFoundError:
        symbols = []

    if not symbols:
        state["last_attempt_at"] = now_ts.isoformat()
        save_calibration_schedule_state(state)
        return {"ran": False, "reason": "filtered_symbols_empty", "now_utc": now_ts.isoformat()}

    trend_soft = DEFAULT_TREND_SOFT
    setup_soft = DEFAULT_SETUP_SOFT
    entry_soft = DEFAULT_ENTRY_SOFT
    entry_max_extension = DEFAULT_ENTRY_MAX_EXTENSION

    report_rows = run_calibration_pipeline(
        symbols=symbols,
        trend_soft=trend_soft,
        setup_soft=setup_soft,
        entry_soft=entry_soft,
        entry_max_extension=entry_max_extension,
        limit_12h=DEFAULT_LIMIT_12H,
        limit_4h=DEFAULT_LIMIT_4H,
        limit_1h=DEFAULT_LIMIT_1H,
    )
    dynamic_symbols = build_dynamic_symbols(report_rows, min_stage="setup")
    write_symbols_file(DYNAMIC_SYMBOLS_FILE, dynamic_symbols)
    write_report_tsv(report_rows, DEFAULT_REPORT_TSV_FILE)
    write_human_report(
        report_rows,
        output_file=DEFAULT_REPORT_TEXT_FILE,
        symbols_count=len(symbols),
        trend_soft=trend_soft,
        setup_soft=setup_soft,
        entry_soft=entry_soft,
        entry_max_extension=entry_max_extension,
        common_output_file=COMMON_SYMBOLS_FILE if should_refresh_filtered else None,
        dynamic_output_file=DYNAMIC_SYMBOLS_FILE,
        dynamic_min_stage="setup",
        include_details=True,
    )

    state["last_dynamic_refresh_close"] = current_close_marker
    state["last_run_at"] = now_ts.isoformat()
    save_calibration_schedule_state(state)

    return {
        "ran": True,
        "reason": "scheduled_calibration_completed",
        "now_utc": now_ts.isoformat(),
        "close_marker": current_close_marker,
        "refreshed_filtered": should_refresh_filtered,
        "updated_dynamic": True,
        "symbols_count": len(symbols),
        "dynamic_symbols_count": len(dynamic_symbols),
        "report_file": DEFAULT_REPORT_TEXT_FILE,
        "tsv_file": DEFAULT_REPORT_TSV_FILE,
    }


def run_manual_calibration(
    *,
    symbols: list[str] | None = None,
    symbols_file: str | None = None,
    refresh_common_first: bool = False,
    update_dynamic_symbols: bool = False,
    dynamic_min_stage: str = "setup",
    common_output_file: str = COMMON_SYMBOLS_FILE,
    dynamic_output_file: str = DYNAMIC_SYMBOLS_FILE,
    universe_min_market_cap: float = float(UNIVERSE_FILTER_MIN_MARKET_CAP),
    universe_min_volume_24h: float = float(UNIVERSE_FILTER_MIN_VOLUME_24H),
    include_stablecoins: bool = False,
    limit_12h: int = DEFAULT_LIMIT_12H,
    limit_4h: int = DEFAULT_LIMIT_4H,
    limit_1h: int = DEFAULT_LIMIT_1H,
    trend_soft: int = DEFAULT_TREND_SOFT,
    setup_soft: int = DEFAULT_SETUP_SOFT,
    entry_soft: int = DEFAULT_ENTRY_SOFT,
    entry_max_extension: float = DEFAULT_ENTRY_MAX_EXTENSION,
    output_file: str | None = None,
    tsv_output_file: str | None = None,
    rebuild_dynamic_from_report: str | None = None,
    stream_tsv_output_file: str | None = None,
    include_details: bool = False,
) -> dict[str, Any]:
    """Программный entrypoint для batch-calibration без CLI."""
    resolved_symbols = list(symbols or [])
    if refresh_common_first:
        refreshed_symbols = refresh_common_symbols(
            output_file=common_output_file,
            min_market_cap=universe_min_market_cap,
            min_volume_24h=universe_min_volume_24h,
            exclude_stablecoins=not include_stablecoins,
        )
        resolved_symbols.extend(refreshed_symbols)
    if symbols_file:
        resolved_symbols.extend(load_symbols_from_file(symbols_file))
    if (update_dynamic_symbols or refresh_common_first) and not symbols and not symbols_file:
        resolved_symbols.extend(load_symbols_from_file(common_output_file))
    resolved_symbols = list(dict.fromkeys(resolved_symbols))

    if not resolved_symbols and not rebuild_dynamic_from_report:
        raise ValueError("No symbols provided. Pass symbols directly or use symbols_file.")

    report_rows: list[dict[str, Any]] = []
    if resolved_symbols:
        report_rows = run_calibration_pipeline(
            symbols=resolved_symbols,
            trend_soft=trend_soft,
            setup_soft=setup_soft,
            entry_soft=entry_soft,
            entry_max_extension=entry_max_extension,
            limit_12h=limit_12h,
            limit_4h=limit_4h,
            limit_1h=limit_1h,
            stream_tsv_output_file=stream_tsv_output_file,
        )

    dynamic_symbols: list[str] | None = None
    if update_dynamic_symbols:
        if rebuild_dynamic_from_report:
            dynamic_symbols = build_dynamic_symbols_from_report_file(
                report_file=rebuild_dynamic_from_report,
                min_stage=dynamic_min_stage,
            )
        else:
            dynamic_symbols = build_dynamic_symbols(report_rows, min_stage=dynamic_min_stage)
        write_symbols_file(dynamic_output_file, dynamic_symbols)

    if tsv_output_file:
        write_report_tsv(report_rows, tsv_output_file)

    if output_file:
        write_human_report(
            report_rows,
            output_file=output_file,
            symbols_count=len(resolved_symbols),
            trend_soft=trend_soft,
            setup_soft=setup_soft,
            entry_soft=entry_soft,
            entry_max_extension=entry_max_extension,
            common_output_file=common_output_file if refresh_common_first else None,
            dynamic_output_file=dynamic_output_file if update_dynamic_symbols else None,
            dynamic_min_stage=dynamic_min_stage if update_dynamic_symbols else None,
            include_details=include_details,
        )
    else:
        if report_rows:
            emit_report(
                report_rows,
                symbols_count=len(resolved_symbols),
                trend_soft=trend_soft,
                setup_soft=setup_soft,
                entry_soft=entry_soft,
                entry_max_extension=entry_max_extension,
                common_output_file=common_output_file if refresh_common_first else None,
                dynamic_output_file=dynamic_output_file if update_dynamic_symbols else None,
                dynamic_min_stage=dynamic_min_stage if update_dynamic_symbols else None,
                include_details=include_details,
            )

    return {
        "report_rows": report_rows,
        "symbols": resolved_symbols,
        "dynamic_symbols": dynamic_symbols,
        "output_file": output_file,
        "tsv_output_file": tsv_output_file,
        "stream_tsv_output_file": stream_tsv_output_file,
    }