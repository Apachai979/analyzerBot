from analyzes.multi_timeframe_ma_analysis import (
    analyze_ma_signals,
    calculate_macd,
    analyze_volume,
    calculate_bollinger_bands,
    log_to_file,
    calculate_bollinger_bands_1D
)
from analyzes.atr_rsi_stochastic import calculate_rsi, calculate_atr, calculate_stochastic

def adjust_periods_for_history(df, fast_period, slow_period, lookback_periods, min_required=6):
    """
    Если данных мало, уменьшает периоды индикаторов до максимально возможных.
    Если данных достаточно — возвращает исходные периоды.
    """
    available = len(df)
    if df is None or available < min_required:
        return None
    min_period = max(fast_period, slow_period, lookback_periods)
    if available >= min_period + 2:
        # Данных достаточно для стандартных периодов
        return fast_period, slow_period, lookback_periods
    # Если данных мало — уменьшаем периоды
    fast_period = max(2, int(available * 0.3))
    slow_period = max(3, int(available * 0.95))
    lookback_periods = max(2, available // 2)
    return fast_period, slow_period, lookback_periods

def analyze_1d_ma_macd_volume(df, symbol="UNKNOWN"):
    """
    Анализирует дневные сигналы SMA/EMA (50, 200), MACD, Volume и Bollinger Bands (SMA).
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    
    fast_period = 50
    slow_period = 200
    lookback_periods = 100

    adjusted = adjust_periods_for_history(df, fast_period, slow_period, lookback_periods)
    if adjusted is None:
        print(f"{datetime.now()} | {symbol} | Слишком мало данных для анализа {ma_type}\n")
        return None
    fast_period, slow_period, lookback_periods = adjusted
    if slow_period < 30:
        print(f"{datetime.now()} | {symbol} | Слишком мало данных для анализа {ma_type}\n")
        return None
    # SMA/EMA анализ
    sma_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [1D]", ma_type="SMA")
    ema_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [1D]", ma_type="EMA")

    # MACD анализ
    macd_df = calculate_macd(df.copy(), fast_period=12, slow_period=26, signal_period=9, symbol=f"{symbol} [1D]") 
    macd_action = macd_df.attrs.get('action') if hasattr(macd_df, 'attrs') else None
    
    # Volume анализ
    volume_res = analyze_volume(df.copy(), volume_ma_period=20, symbol=f"{symbol} [1D]")

    # Bollinger Bands анализ на SMA
    bb_sma_df = calculate_bollinger_bands_1D(df.copy(), period=20, num_std=2, ma_type="EMA", symbol=f"{symbol} [1D]", trend_direction=f"{sma_result['signal']}")
    bb_sma_signal = bb_sma_df['bb_signal'].iloc[-1] if not bb_sma_df.empty else None

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 1D MA/MACD/Volume/BB Analysis ===\n"
        f"SMA(50/200) {sma_result.get('signal','n/a') if sma_result else 'n/a'}, {sma_result.get('bar','n/a') if sma_result else 'n/a'}, {sma_result.get('price_position','n/a') if sma_result else 'n/a'}, {sma_result.get('is_confidently_above_ema200','n/a') if sma_result else 'n/a'}, {sma_result.get('trading_verdict','n/a') if sma_result else 'n/a'}\n"
        f"EMA(50/200) {ema_result.get('signal','n/a') if ema_result else 'n/a'}, {ema_result.get('bar','n/a') if ema_result else 'n/a'}, {ema_result.get('price_position','n/a') if ema_result else 'n/a'}, {ema_result.get('is_confidently_above_ema200','n/a') if ema_result else 'n/a'}, {ema_result.get('trading_verdict','n/a') if ema_result else 'n/a'}\n"
        f"MACD сигнал: {macd_df.attrs.get('summary_signal')}, details: {macd_df.attrs.get('summary_details')}, action: {macd_df.attrs.get('action')}\n"
        f"Bollinger Bands SMA сигнал: {bb_sma_signal}\n"
        f"Объем: {volume_res.get('current_volume', 'n/a')} vs средний {volume_res.get('avg_volume', 'n/a')}\n"
        f"Сигнал по объему: {volume_res.get('signal', 'n/a')}, action: {volume_res.get('action', 'n/a')}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("ma_macd_volume_1d_log.txt", summary)

    return {
        "sma_result": sma_result,
        "ema_result": ema_result,
        "macd_action": macd_action,  # Добавляем action от MACD
        "volume_result": volume_res,
        "bb_sma_signal": bb_sma_signal,
        "summary": summary
    }

def analyze_12h_correction_strategy(df, trend_1d, symbol="UNKNOWN"):
    """
    Детальная стратегия анализа 12h с системой "светофора".
    
    Args:
        df: DataFrame с данными 12h
        trend_1d: Тренд с 1D ("BULLISH" или "BEARISH")
        symbol: Название инструмента
    
    Returns:
        dict: Результаты анализа с итоговым действием (STOP/ATTENTION/GO)
    """
    from analyzes.multi_timeframe_ma_analysis import calculate_ema
    
    if len(df) < 50:
        return None
    
    # Определяем ожидаемое поведение на 12h
    expected_12h_direction = "DOWN" if trend_1d == "BULLISH" else "UP"
    
    # === АНАЛИЗ ПРЕДЫДУЩИХ СВЕЧЕЙ (ПОДТВЕРЖДЕНИЕ ДВИЖЕНИЯ) ===
    # Проверяем последние 3-4 свечи для подтверждения тренда коррекции/отскока
    
    current_price = df['close'].iloc[-1]
    prev_price_1 = df['close'].iloc[-2]
    prev_price_2 = df['close'].iloc[-3]
    prev_price_3 = df['close'].iloc[-4] if len(df) >= 4 else None
    
    # Подтверждение направления движения
    trend_confirmation = False
    trend_strength = 0  # 0-3 баллов за подтверждение тренда
    correction_type = ""  # "GRADUAL" (постепенная) или "SHARP" (резкая)
    
    if trend_1d == "BULLISH":
        # Ожидаем коррекцию ВНИЗ на 12H (цены должны были снижаться)
        
        # Вариант 1: Постепенная коррекция (несколько падающих свечей)
        candles_down = 0
        if prev_price_1 < prev_price_2:
            candles_down += 1
        if prev_price_2 and prev_price_3 and prev_price_2 < prev_price_3:
            candles_down += 1
            
        # Вариант 2: Резкая коррекция (одна мощная медвежья свеча)
        # Проверяем саму свечу (open → close), а не просто разницу цен закрытия
        prev_open = df['open'].iloc[-2]
        prev_close = df['close'].iloc[-2]
        prev_high = df['high'].iloc[-2]
        prev_low = df['low'].iloc[-2]
        
        # Размер тела свечи (не путать с диапазоном high-low)
        prev_candle_body = abs(prev_close - prev_open) / prev_open * 100
        is_bearish_prev = prev_close < prev_open  # Медвежья свеча (красная)
        
        # Резкая коррекция = мощная медвежья свеча >3% + цена действительно упала
        is_sharp_correction = (prev_candle_body > 3.0 and 
                              is_bearish_prev and 
                              prev_price_1 < prev_price_2)
        
        # Принимаем ЛЮБОЙ из вариантов
        if candles_down >= 1:
            trend_confirmation = True
            trend_strength = candles_down
            correction_type = "GRADUAL"
        elif is_sharp_correction:
            # Одна мощная медвежья свеча вниз - тоже валидная коррекция
            trend_confirmation = True
            trend_strength = 1
            correction_type = "SHARP"
        
    else:  # trend_1d == "BEARISH"
        # Ожидаем отскок ВВЕРХ на 12H (цены должны были расти)
        
        # Вариант 1: Постепенный отскок (несколько растущих свечей)
        candles_up = 0
        if prev_price_1 > prev_price_2:
            candles_up += 1
        if prev_price_2 and prev_price_3 and prev_price_2 > prev_price_3:
            candles_up += 1
            
        # Вариант 2: Резкий отскок (одна мощная бычья свеча)
        # Проверяем саму свечу (open → close), а не просто разницу цен закрытия
        prev_open = df['open'].iloc[-2]
        prev_close = df['close'].iloc[-2]
        prev_high = df['high'].iloc[-2]
        prev_low = df['low'].iloc[-2]
        
        # Размер тела свечи
        prev_candle_body = abs(prev_close - prev_open) / prev_open * 100
        is_bullish_prev = prev_close > prev_open  # Бычья свеча (зеленая)
        
        # Резкий отскок = мощная бычья свеча >3% + цена действительно выросла
        is_sharp_bounce = (prev_candle_body > 3.0 and 
                          is_bullish_prev and 
                          prev_price_1 > prev_price_2)
        
        # Принимаем ЛЮБОЙ из вариантов
        if candles_up >= 1:
            trend_confirmation = True
            trend_strength = candles_up
            correction_type = "GRADUAL"
        elif is_sharp_bounce:
            # Одна мощная бычья свеча вверх - тоже валидный отскок
            trend_confirmation = True
            trend_strength = 1
            correction_type = "SHARP"
    
    # Если нет подтверждения движения - не анализируем дальше
    if not trend_confirmation:
        prev_price_3_text = f"{prev_price_3:.4f}" if prev_price_3 else "n/a"
        summary = (
            f"=== 12H СТРАТЕГИЯ КОРРЕКЦИИ ===\n"
            f"Тренд 1D: {trend_1d}\n"
            f"Ожидаем на 12H: {expected_12h_direction}\n"
            f"\n⚠️ ОТКЛОНЕНО: Нет подтверждения движения в ожидаемом направлении\n"
            f"Последние 3 свечи не показывают четкой коррекции/отскока.\n"
            f"Цены: {prev_price_3_text} → {prev_price_2:.4f} → {prev_price_1:.4f} → {current_price:.4f}\n"
            f"Нет ни постепенного движения, ни резкой коррекционной свечи (>3%)\n"
            f"\n🔴 ДЕЙСТВИЕ: НЕ ВХОДИТЬ - Дождитесь подтверждения тренда\n"
            f"---\n"
        )
        log_to_file("12h_correction_strategy_log.txt", summary)
        return {
            "action": "STOP",
            "signal_strength": 0,
            "signals": ["⚠️ Нет подтверждения движения коррекции/отскока"],
            "trend_confirmation": False,
            "summary": summary
        }
    
    # === ИНДИКАТОРЫ ===
    
    # 1. EMA (20, 50) - анализ отскока
    ema20 = calculate_ema(df, 20)
    ema50 = calculate_ema(df, 50)
    
    ema20_current = ema20.iloc[-1]
    ema50_current = ema50.iloc[-1]
    
    # Расстояние до EMA
    distance_to_ema20 = abs(current_price - ema20_current) / ema20_current * 100
    distance_to_ema50 = abs(current_price - ema50_current) / ema50_current * 100
    
    # 2. MACD - поиск дивергенции и разворота
    macd_df = calculate_macd(df.copy(), fast_period=12, slow_period=26, signal_period=9, symbol=f"{symbol} [12H]")
    macd_hist = macd_df['macd_hist']
    
    current_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2]
    prev_hist_2 = macd_hist.iloc[-3] if len(macd_hist) > 2 else None
    hist_diff = current_hist - prev_hist
    
    macd_action = macd_df.attrs.get('action') if hasattr(macd_df, 'attrs') else None
    
    # 3. RSI (14) - зоны перепроданности/перекупленности
    rsi_log, rsi_series = calculate_rsi(df, period=14)
    current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None
    prev_rsi = rsi_series.iloc[-2] if len(rsi_series) > 1 else None
    prev_rsi_2 = rsi_series.iloc[-3] if len(rsi_series) > 2 else None
    
    # 4. Stochastic (14,3,3) - пересечения
    stoch_log, stoch_df = calculate_stochastic(df.copy(), k_period=14, d_period=3)
    stoch_k = stoch_df['stoch_k'].iloc[-1] if not stoch_df.empty else None
    stoch_d = stoch_df['stoch_d'].iloc[-1] if not stoch_df.empty else None
    prev_stoch_k = stoch_df['stoch_k'].iloc[-2] if len(stoch_df) > 1 else None
    prev_stoch_d = stoch_df['stoch_d'].iloc[-2] if len(stoch_df) > 1 else None
    
    # 5. Bollinger Bands
    bb_df = calculate_bollinger_bands(df.copy(), period=20, num_std=2, ma_type="EMA", symbol=f"{symbol} [12H]")
    bb_upper = bb_df['bb_upper'].iloc[-1]
    bb_lower = bb_df['bb_lower'].iloc[-1]
    bb_middle = bb_df['bb_middle'].iloc[-1]
    
    # 6. Volume анализ
    volume_res = analyze_volume(df.copy(), volume_ma_period=20, symbol=f"{symbol} [12H]")
    volume_ratio = volume_res.get('volume_ratio', 1.0)
    
    # 7. Анализ текущей свечи
    current_open = df['open'].iloc[-1]
    current_close = df['close'].iloc[-1]
    is_bullish_candle = current_close > current_open
    candle_size = abs(current_close - current_open) / current_open * 100
    
    # Анализ предыдущих свечей для подтверждения разворота
    prev_open_1 = df['open'].iloc[-2]
    prev_close_1 = df['close'].iloc[-2]
    prev_candle_bullish = prev_close_1 > prev_open_1
    
    prev_open_2 = df['open'].iloc[-3]
    prev_close_2 = df['close'].iloc[-3]
    
    # === ПОДСЧЕТ СИГНАЛОВ ===
    signals = []
    signal_strength = 0
    
    # Добавляем бонус за подтверждение тренда (до 2 баллов)
    if correction_type == "SHARP":
        # Резкая коррекция - даем бонус за силу движения
        signals.append(f"✅✅ Подтверждение: РЕЗКАЯ коррекция {expected_12h_direction} (мощная свеча >3%)")
        signal_strength += 2
    elif trend_strength >= 2:
        signals.append(f"✅✅ Подтверждение: {trend_strength} свечи показывают четкое движение {expected_12h_direction}")
        signal_strength += 2
    elif trend_strength == 1:
        signals.append(f"✅ Подтверждение: движение {expected_12h_direction} подтверждено")
        signal_strength += 1
    
    if trend_1d == "BULLISH":
        # БЫЧИЙ СЦЕНАРИЙ 1D - ищем завершение коррекции вниз
        # Требуем: 1) Была коррекция вниз (подтверждено выше)
        #          2) Текущая свеча показывает разворот вверх
        
        # 1. MACD: гистограмма растет после падения или бычья дивергенция
        # Проверяем, что гистограмма росла последние 2 свечи (подтверждение)
        if hist_diff > 0 and current_hist < 0:
            # Проверяем подтверждение от предыдущей свечи
            if prev_hist_2 is not None and prev_hist > prev_hist_2:
                signals.append("✅✅ MACD: Гистограмма СТАБИЛЬНО растет 2+ свечи!")
                signal_strength += 2
            else:
                signals.append("✅ MACD: Гистограмма начинает расти")
                signal_strength += 1
        if macd_action == "BUY":
            signals.append("✅ MACD: Сигнал на покупку")
            signal_strength += 1
            
        # 2. RSI: выход из зоны перепроданности
        # Требуем подтверждение: RSI был низким 2+ свечи, затем начал расти
        if current_rsi is not None:
            if current_rsi < 30:
                # Проверяем, сколько свечей RSI был низким
                rsi_low_candles = 1
                if prev_rsi and prev_rsi < 30:
                    rsi_low_candles += 1
                if prev_rsi_2 and prev_rsi_2 < 30:
                    rsi_low_candles += 1
                
                if rsi_low_candles >= 2:
                    signals.append(f"✅✅ RSI: В зоне перепроданности {rsi_low_candles} свечи!")
                    signal_strength += 2
                else:
                    signals.append("✅ RSI: В зоне перепроданности (<30)")
                    signal_strength += 1
            elif prev_rsi and prev_rsi < 30 and current_rsi > 30:
                # Выход из зоны - проверяем, что RSI действительно рос
                if prev_rsi_2 and prev_rsi_2 < prev_rsi:
                    signals.append("✅✅✅ RSI: УВЕРЕННЫЙ ВЫХОД из зоны перепроданности!")
                    signal_strength += 3
                else:
                    signals.append("✅✅ RSI: ВЫХОД из зоны перепроданности!")
                    signal_strength += 2
                
        # 3. Stochastic: пересечение снизу вверх в зоне перепроданности
        if stoch_k and stoch_d and prev_stoch_k and prev_stoch_d:
            if prev_stoch_k < prev_stoch_d and stoch_k > stoch_d:
                if stoch_k < 20:
                    signals.append("✅✅ Stochastic: ЗОЛОТОЙ КРЕСТ в зоне перепроданности!")
                    signal_strength += 2
                else:
                    signals.append("✅ Stochastic: Бычье пересечение")
                    signal_strength += 1
                    
        # 4. EMA: отскок от EMA20 или EMA50
        # Требуем: цена была НИЖЕ EMA, теперь отскакивает вверх
        if distance_to_ema20 < 1.0 and is_bullish_candle:
            # Проверяем, что предыдущая свеча была ближе/ниже EMA
            if prev_close_1 < current_price:
                signals.append("✅✅ EMA: ПОДТВЕРЖДЕННЫЙ отскок от EMA20!")
                signal_strength += 2
            else:
                signals.append("✅ EMA: Отскок от EMA20")
                signal_strength += 1
        elif distance_to_ema50 < 1.5 and is_bullish_candle:
            if prev_close_1 < current_price:
                signals.append("✅✅✅ EMA: ПОДТВЕРЖДЕННЫЙ отскок от EMA50!")
                signal_strength += 3
            else:
                signals.append("✅✅ EMA: Отскок от EMA50!")
                signal_strength += 2
            
        # 5. Bollinger Bands: отскок от нижней полосы
        # Требуем: была внизу несколько свечей, сейчас отскок
        if current_price <= bb_lower and is_bullish_candle:
            # Проверяем, что предыдущие свечи были у нижней полосы
            if prev_close_1 <= bb_lower or prev_close_2 <= bb_lower:
                signals.append("✅✅✅ BB: СИЛЬНЫЙ отскок от нижней полосы с подтверждением!")
                signal_strength += 3
            else:
                signals.append("✅✅ BB: Отскок от нижней полосы!")
                signal_strength += 2
        elif current_price <= bb_middle and is_bullish_candle:
            if prev_close_1 < current_price:
                signals.append("✅✅ BB: ПОДТВЕРЖДЕННЫЙ отскок от средней линии!")
                signal_strength += 2
            else:
                signals.append("✅ BB: Отскок от средней линии")
                signal_strength += 1
            
        # 6. Volume: высокий объем на бычьей свече
        # Требуем: СИЛЬНУЮ бычью свечу с высоким объемом (подтверждение разворота)
        if volume_ratio > 1.5 and is_bullish_candle and candle_size > 1.5:
            # Проверяем, что предыдущая свеча была медвежьей (подтверждение разворота)
            if not prev_candle_bullish:
                signals.append("✅✅✅ Volume: Высокий объем на РАЗВОРОТЕ (медвежья→бычья)!")
                signal_strength += 3
            else:
                signals.append("✅✅ Volume: Высокий объем на сильной бычьей свече!")
                signal_strength += 2
            
    else:  # trend_1d == "BEARISH"
        # МЕДВЕЖИЙ СЦЕНАРИЙ 1D - ищем завершение отскока вверх
        # Требуем: 1) Был отскок вверх (подтверждено выше)
        #          2) Текущая свеча показывает разворот вниз
        
        # 1. MACD: гистограмма падает после роста или медвежья дивергенция
        # Проверяем, что гистограмма падала последние 2 свечи (подтверждение)
        if hist_diff < 0 and current_hist > 0:
            # Проверяем подтверждение от предыдущей свечи
            if prev_hist_2 is not None and prev_hist < prev_hist_2:
                signals.append("✅✅ MACD: Гистограмма СТАБИЛЬНО падает 2+ свечи!")
                signal_strength += 2
            else:
                signals.append("✅ MACD: Гистограмма начинает падать")
                signal_strength += 1
        if macd_action == "SELL":
            signals.append("✅ MACD: Сигнал на продажу")
            signal_strength += 1
            
        # 2. RSI: выход из зоны перекупленности
        # Требуем подтверждение: RSI был высоким 2+ свечи, затем начал падать
        if current_rsi is not None:
            if current_rsi > 70:
                # Проверяем, сколько свечей RSI был высоким
                rsi_high_candles = 1
                if prev_rsi and prev_rsi > 70:
                    rsi_high_candles += 1
                if prev_rsi_2 and prev_rsi_2 > 70:
                    rsi_high_candles += 1
                
                if rsi_high_candles >= 2:
                    signals.append(f"✅✅ RSI: В зоне перекупленности {rsi_high_candles} свечи!")
                    signal_strength += 2
                else:
                    signals.append("✅ RSI: В зоне перекупленности (>70)")
                    signal_strength += 1
            elif prev_rsi and prev_rsi > 70 and current_rsi < 70:
                # Выход из зоны - проверяем, что RSI действительно падал
                if prev_rsi_2 and prev_rsi_2 > prev_rsi:
                    signals.append("✅✅✅ RSI: УВЕРЕННЫЙ ВЫХОД из зоны перекупленности!")
                    signal_strength += 3
                else:
                    signals.append("✅✅ RSI: ВЫХОД из зоны перекупленности!")
                    signal_strength += 2
                
        # 3. Stochastic: пересечение сверху вниз в зоне перекупленности
        if stoch_k and stoch_d and prev_stoch_k and prev_stoch_d:
            if prev_stoch_k > prev_stoch_d and stoch_k < stoch_d:
                if stoch_k > 80:
                    signals.append("✅✅ Stochastic: МЕРТВЫЙ КРЕСТ в зоне перекупленности!")
                    signal_strength += 2
                else:
                    signals.append("✅ Stochastic: Медвежье пересечение")
                    signal_strength += 1
                    
        # 4. EMA: отскок вниз от EMA20 или EMA50
        # Требуем: цена была ВЫШЕ EMA, теперь отскакивает вниз
        if distance_to_ema20 < 1.0 and not is_bullish_candle:
            # Проверяем, что предыдущая свеча была выше/дальше от EMA
            if prev_close_1 > current_price:
                signals.append("✅✅ EMA: ПОДТВЕРЖДЕННЫЙ отскок вниз от EMA20!")
                signal_strength += 2
            else:
                signals.append("✅ EMA: Отскок вниз от EMA20")
                signal_strength += 1
        elif distance_to_ema50 < 1.5 and not is_bullish_candle:
            if prev_close_1 > current_price:
                signals.append("✅✅✅ EMA: ПОДТВЕРЖДЕННЫЙ отскок вниз от EMA50!")
                signal_strength += 3
            else:
                signals.append("✅✅ EMA: Отскок вниз от EMA50!")
                signal_strength += 2
            
        # 5. Bollinger Bands: отскок вниз от верхней полосы
        # Требуем: была вверху несколько свечей, сейчас отскок вниз
        if current_price >= bb_upper and not is_bullish_candle:
            # Проверяем, что предыдущие свечи были у верхней полосы
            if prev_close_1 >= bb_upper or prev_close_2 >= bb_upper:
                signals.append("✅✅✅ BB: СИЛЬНЫЙ отскок вниз от верхней полосы с подтверждением!")
                signal_strength += 3
            else:
                signals.append("✅✅ BB: Отскок вниз от верхней полосы!")
                signal_strength += 2
        elif current_price >= bb_middle and not is_bullish_candle:
            if prev_close_1 > current_price:
                signals.append("✅✅ BB: ПОДТВЕРЖДЕННЫЙ отскок вниз от средней линии!")
                signal_strength += 2
            else:
                signals.append("✅ BB: Отскок вниз от средней линии")
                signal_strength += 1
            
        # 6. Volume: высокий объем на медвежьей свече
        # Требуем: СИЛЬНУЮ медвежью свечу с высоким объемом (подтверждение разворота)
        if volume_ratio > 1.5 and not is_bullish_candle and candle_size > 1.5:
            # Проверяем, что предыдущая свеча была бычьей (подтверждение разворота)
            if prev_candle_bullish:
                signals.append("✅✅✅ Volume: Высокий объем на РАЗВОРОТЕ (бычья→медвежья)!")
                signal_strength += 3
            else:
                signals.append("✅✅ Volume: Высокий объем на сильной медвежьей свече!")
                signal_strength += 2
    
    # === ОПРЕДЕЛЕНИЕ ДЕЙСТВИЯ (СВЕТОФОР) ===
    # Новая шкала: с учетом подтверждений можно набрать до 20+ баллов
    # STOP: 0-4 балла (очень слабые сигналы или нет подтверждения)
    # ATTENTION: 5-8 баллов (есть некоторые сигналы, но мало подтверждений)
    # GO: 9+ баллов (множественные подтвержденные сигналы)
    
    if signal_strength == 0:
        action = "STOP"
        action_emoji = "🔴"
        action_text = "НЕ ВХОДИТЬ - Коррекция/отскок не завершен"
    elif signal_strength <= 4:
        action = "STOP"
        action_emoji = "🔴"
        action_text = "НЕ ВХОДИТЬ - Слишком мало подтвержденных сигналов"
    elif signal_strength <= 8:
        action = "ATTENTION"
        action_emoji = "🟡"
        action_text = "ВНИМАНИЕ - Готовимся к входу, смотрим 4H"
    else:
        action = "GO"
        action_emoji = "🟢"
        action_text = "ВПЕРЕД - Множественные подтвержденные сигналы, переходим на 4H!"
    
    # Формируем резюме
    rsi_text = f"{current_rsi:.2f}" if current_rsi is not None else "n/a"
    prev_rsi_text = f"{prev_rsi:.2f}" if prev_rsi is not None else "n/a"
    stoch_k_text = f"{stoch_k:.2f}" if stoch_k is not None else "n/a"
    stoch_d_text = f"{stoch_d:.2f}" if stoch_d is not None else "n/a"
    volume_ratio_text = f"{volume_ratio:.2f}" if volume_ratio is not None else "n/a"
    candle_type_text = "🟢 Бычья" if is_bullish_candle else "🔴 Медвежья"
    
    summary = (
        f"=== 12H СТРАТЕГИЯ КОРРЕКЦИИ ===\n"
        f"Тренд 1D: {trend_1d}\n"
        f"Ожидаем на 12H: {expected_12h_direction}\n"
        f"✅ Подтверждение движения: {trend_strength} свечи ({correction_type})\n"
        f"Последние цены: {prev_price_2:.4f} → {prev_price_1:.4f} → {current_price:.4f}\n"
        f"\n📊 СИГНАЛЫ ({signal_strength} баллов):\n"
        f"{chr(10).join(signals) if signals else 'Нет сигналов'}\n"
        f"\n{action_emoji} ДЕЙСТВИЕ: {action_text}\n"
        f"\n📈 ДЕТАЛИ:\n"
        f"RSI: {rsi_text} (prev: {prev_rsi_text})\n"
        f"Stochastic %K: {stoch_k_text}, %D: {stoch_d_text}\n"
        f"MACD Action: {macd_action}\n"
        f"Volume Ratio: {volume_ratio_text}\n"
        f"Цена vs EMA20: {distance_to_ema20:.2f}%, vs EMA50: {distance_to_ema50:.2f}%\n"
        f"Текущая свеча: {candle_type_text} ({candle_size:.2f}%)\n"
        f"---\n"
    )
    
    log_to_file("12h_correction_strategy_log.txt", summary)
    
    return {
        "action": action,
        "signal_strength": signal_strength,
        "trend_confirmation": trend_confirmation,
        "trend_strength": trend_strength,
        "correction_type": correction_type,
        "signals": signals,
        "rsi": current_rsi,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "macd_action": macd_action,
        "volume_ratio": volume_ratio,
        "summary": summary
    }

def analyze_4h_bb_stoch_ma_volume(df, symbol="UNKNOWN"):
    """
    Анализирует 4h сигналы: Bollinger Bands, Stochastic (14,3,3), RSI (14), Volume, SMA/EMA (20).
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    ma_period = 20
    bb_period = 20
    bb_num_std = 2
    stoch_k_period = 14
    stoch_d_period = 3
    stoch_smooth = 3
    rsi_period = 14
    volume_ma_period = 20

    # Bollinger Bands (SMA)
    bb_sma_df = calculate_bollinger_bands(df.copy(), period=bb_period, num_std=bb_num_std, ma_type="SMA", symbol=f"{symbol} [4H]")
    bb_sma_signal = bb_sma_df['bb_signal'].iloc[-1] if not bb_sma_df.empty else None

    # Stochastic (14,3,3)
    stoch_log, stoch_df = calculate_stochastic(df.copy(), k_period=stoch_k_period, d_period=stoch_d_period)
    stoch_k = stoch_df['stoch_k'].iloc[-1] if not stoch_df.empty else None
    stoch_d = stoch_df['stoch_d'].iloc[-1] if not stoch_df.empty else None

    # RSI (14)
    rsi_log, rsi_series = calculate_rsi(df, period=rsi_period)
    last_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None

    # Volume
    volume_res = analyze_volume(df, volume_ma_period=volume_ma_period, symbol=f"{symbol} [4H]")

    # SMA/EMA (20)
    sma_result = analyze_ma_signals(df.copy(), ma_period, ma_period, 40, symbol=f"{symbol} [4H]", ma_type="SMA")
    ema_result = analyze_ma_signals(df.copy(), ma_period, ma_period, 40, symbol=f"{symbol} [4H]", ma_type="EMA")

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 4H BB/Stochastic/MA/Volume Analysis ===\n"
        f"Bollinger Bands SMA сигнал: {bb_sma_signal}\n"
        f"Stochastic %K: {stoch_k:.2f if stoch_k is not None else 'n/a'}, %D: {stoch_d:.2f if stoch_d is not None else 'n/a'}\n"
        f"RSI: {last_rsi:.2f if last_rsi is not None else 'n/a'}\n"
        f"SMA(20) сигнал: {sma_result['signal'] if sma_result else 'n/a'}\n"
        f"EMA(20) сигнал: {ema_result['signal'] if ema_result else 'n/a'}\n"
        f"Объем: {volume_res.get('current_volume', 'n/a')} vs средний {volume_res.get('avg_volume', 'n/a')}\n"
        f"Сигнал по объему: {volume_res.get('signal', 'n/a')}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("bb_stoch_ma_volume_4h_log.txt", summary)

    return {
        "bb_sma_signal": bb_sma_signal,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "rsi": last_rsi,
        "sma_result": sma_result,
        "ema_result": ema_result,
        "volume_result": volume_res,
        "summary": summary
    }   
    
def analyze_1h_ema_macd_atr_rsi(df, symbol="UNKNOWN"):
    """
    Анализирует 1h сигналы: EMA(9, 20), MACD (fast), ATR, RSI.
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    fast_period = 9
    slow_period = 20
    lookback_periods = 40

    # EMA анализ
    ema_result = analyze_ma_signals(df.copy(), fast_period, slow_period, lookback_periods, symbol=f"{symbol} [1H]", ma_type="EMA")

    # MACD анализ (быстрые настройки)
    macd_df = calculate_macd(df.copy(), fast_period=6, slow_period=13, signal_period=4, symbol=f"{symbol} [1H]")
    last_macd = macd_df['macd'].iloc[-1] if not macd_df.empty else None
    last_signal = macd_df['macd_signal'].iloc[-1] if not macd_df.empty else None
    if last_macd is not None and last_signal is not None:
        if last_macd > last_signal:
            macd_signal = "BUY"
        elif last_macd < last_signal:
            macd_signal = "SELL"
        else:
            macd_signal = "NEUTRAL"
    else:
        macd_signal = None

    # ATR анализ
    from analyzes.atr_rsi_stochastic import calculate_atr, calculate_rsi
    atr_log, atr_res = calculate_atr(df, period=14)
    atr_value = atr_res["current_atr"] if atr_res else None
    atr_pct = atr_res["current_atr_pct"] if atr_res else None
    volatility = atr_res["volatility"] if atr_res else None

    # RSI анализ
    rsi_log, rsi_series = calculate_rsi(df, period=14)
    last_rsi = rsi_series.iloc[-1] if not rsi_series.empty else None
    if last_rsi is not None:
        if last_rsi >= 70:
            rsi_state = "ПЕРЕКУПЛЕННОСТЬ"
        elif last_rsi <= 30:
            rsi_state = "ПЕРЕПРОДАННОСТЬ"
        else:
            rsi_state = "НЕЙТРАЛЬНО"
    else:
        rsi_state = "n/a"

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 1H EMA/MACD/ATR/RSI Analysis ===\n"
        f"EMA(9/20) сигнал: {ema_result['signal'] if ema_result else 'n/a'}\n"
        f"MACD (fast) сигнал: {macd_signal}\n"
        f"ATR: {atr_value:.4f if atr_value is not None else 'n/a'}, %: {atr_pct:.2f if atr_pct is not None else 'n/a'}, Волатильность: {volatility}\n"
        f"RSI: {last_rsi:.2f if last_rsi is not None else 'n/a'} ({rsi_state})\n"
        f"---\n"
    )

    # Логирование
    log_to_file("ema_macd_atr_rsi_1h_log.txt", summary)

    return {
        "ema_result": ema_result,
        "macd_signal": macd_signal,
        "atr": atr_value,
        "atr_pct": atr_pct,
        "volatility": volatility,
        "rsi": last_rsi,
        "rsi_state": rsi_state,
        "summary": summary
    }
    
def analyze_15m_stoch_ema_volume(df, symbol="UNKNOWN"):
    """
    Анализирует 15m сигналы: Stochastic (5,3,3), EMA(9), Volume.
    Возвращает словарь с результатами и кратким текстовым резюме.
    """
    stoch_k_period = 5
    stoch_d_period = 3
    stoch_smooth = 3
    ema_period = 9
    volume_ma_period = 20

    # Stochastic (5,3,3)
    from analyzes.atr_rsi_stochastic import calculate_stochastic
    stoch_log, data = calculate_stochastic(df.copy(), k_period=stoch_k_period, d_period=stoch_d_period)
    stoch_k = data['stoch_k'].iloc[-1] if not data.empty else None
    stoch_d = data['stoch_d'].iloc[-1] if not data.empty else None

    # EMA(9)
    from analyzes.multi_timeframe_ma_analysis import calculate_ema
    ema_series = calculate_ema(df['close'], ema_period)
    last_ema = ema_series.iloc[-1] if not ema_series.empty else None
    last_price = df['close'].iloc[-1] if not df.empty else None
    if last_ema is not None and last_price is not None:
        if last_price > last_ema:
            ema_signal = "BUY"
        elif last_price < last_ema:
            ema_signal = "SELL"
        else:
            ema_signal = "NEUTRAL"
    else:
        ema_signal = "n/a"

    # Volume
    from analyzes.multi_timeframe_ma_analysis import analyze_volume
    volume_res = analyze_volume(df, volume_ma_period=volume_ma_period, symbol=f"{symbol} [15m]")

    # Формируем краткое текстовое резюме
    summary = (
        f"=== 15m Stochastic/EMA/Volume Analysis ===\n"
        f"Stochastic %K: {stoch_k:.2f if stoch_k is not None else 'n/a'}, %D: {stoch_d:.2f if stoch_d is not None else 'n/a'}\n"
        f"EMA(9) сигнал: {ema_signal}\n"
        f"Объем: {volume_res.get('current_volume', 'n/a')} vs средний {volume_res.get('avg_volume', 'n/a')}\n"
        f"Сигнал по объему: {volume_res.get('signal', 'n/a')}\n"
        f"---\n"
    )

    # Логирование
    log_to_file("stoch_ema_volume_15m_log.txt", summary)

    return {
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "ema_signal": ema_signal,
        "volume_result": volume_res,
        "summary": summary
    }