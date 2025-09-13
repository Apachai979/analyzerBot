import os

LOGS_DIR = "logs"
LOG_FILE = "orderbook_log.txt"

def log_to_file(text):
    os.makedirs(LOGS_DIR, exist_ok=True)
    full_path = os.path.join(LOGS_DIR, LOG_FILE)
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def analyze_whale_orders_relative(orders, order_type, current_price, conclusions):
    if not orders:
        return
    closest = min(orders, key=lambda x: abs(float(x[0]) - current_price))
    price = float(closest[0])
    size = float(closest[1])
    distance = abs(price - current_price)
    direction = "ниже" if price < current_price else "выше"
    msg = f"🧭 Ближайший китовый {order_type}: {size:.0f} по цене {price} ({direction} рынка, расстояние {distance:.2f})"
    log_to_file(msg)
    conclusions.append(msg)
    # --- Умозаключения ---
    if distance < current_price * 0.001:
        if order_type == "bid":
            concl = "🟢 Крупная заявка на покупку близко к рынку — поддержка."
        else:
            concl = "🔴 Крупная заявка на продажу близко к рынку — сопротивление."
    elif distance < current_price * 0.005:
        concl = "ℹ️ Крупный ордер относительно близко к рынку, влияние умеренное."
    else:
        concl = "💤 Крупный ордер далеко от текущей цены, влияние незначительное."
    log_to_file(concl)
    conclusions.append(concl)

def analyze_orderbook(bids, asks, bid_volume, ask_volume, whale_bids, whale_asks, current_price, config, symbol):
    """Анализирует стакан цен и крупные ордера и возвращает итоговое резюме"""
    conclusions = []
    log_lines = []
    def log(text):
        log_to_file(text)
        log_lines.append(text)

    if not bids or not asks:
        log("❌ Не удалось получить данные стакана")
        conclusions.append("❌ Нет данных стакана")
        return "\n".join(conclusions)

    log(f"\n📊 ORDER BOOK ANALYSIS ({config.orderbook_levels} уровней)")
    log("─" * 50)
    log(f"⚙️ Параметры: WHALE_SIZE={config.whale_size:,}, Уровней={config.orderbook_levels}, Монета={symbol}")

    # --- Анализ соотношения объемов ---
    volume_info = f"Объем BID: {bid_volume:.0f}, Объем ASK: {ask_volume:.0f}, Соотношение: {bid_volume / ask_volume:.2f}" if ask_volume > 0 else "Нет данных по объёмам"
    log(volume_info)
    conclusions.append(volume_info)

    if ask_volume > 0:
        liquidity_ratio = bid_volume / ask_volume
        # В conclusions только аналитика:
        if liquidity_ratio > 2.0:
            concl = "🟢 СИЛЬНЫЕ ПОКУПАТЕЛИ - преобладают bids"
        elif liquidity_ratio > 1.5:
            concl = "🟡 Умеренные покупатели"
        elif liquidity_ratio > 0.8:
            concl = "⚪ БАЛАНС - паритет сил"
        elif liquidity_ratio > 0.5:
            concl = "🟠 Умеренные продавцы"
        else:
            concl = "🔴 СИЛЬНЫЕ ПРОДАВЦЫ - преобладают asks"
        log("   " + concl)
        conclusions.append(concl)

    # --- Крупные ордера ---
    msg = f"🐋 Крупные ордера (> {config.whale_size:,}): {len(whale_bids)} bids, {len(whale_asks)} asks"
    log(msg)
    if whale_bids:
        bids_msg = f"   🟢 Китские покупки: {', '.join([f'{float(b[1]):.0f}@{b[0]}' for b in whale_bids[:3]])}"
        log(bids_msg)
    if whale_asks:
        asks_msg = f"   🔴 Китские продажи: {', '.join([f'{float(a[1]):.0f}@{a[0]}' for a in whale_asks[:3]])}"
        log(asks_msg)

    analyze_whale_orders_relative(whale_bids, "bid", current_price, conclusions)
    analyze_whale_orders_relative(whale_asks, "ask", current_price, conclusions)

    # --- Итоговое резюме ---
    summary = "\n📋 Итоговые умозаключения по символу {}:\n".format(symbol) + "\n".join(conclusions)
    log(summary)
    return summary