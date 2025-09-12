import os

LOGS_DIR = "logs"
LOG_FILE = "orderbook_log.txt"

def log_to_file(text):
    os.makedirs(LOGS_DIR, exist_ok=True)
    full_path = os.path.join(LOGS_DIR, LOG_FILE)
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def analyze_orderbook(bids, asks, bid_volume, ask_volume, whale_bids, whale_asks, current_price, config):
    """Анализирует стакан цен и крупные ордера"""
    if not bids or not asks:
        log_to_file("❌ Не удалось получить данные стакана")
        return

    log_to_file(f"\n📊 ORDER BOOK ANALYSIS ({config.orderbook_levels} уровней)")
    log_to_file("─" * 50)
    log_to_file(f"⚙️ Параметры: WHALE_SIZE={config.whale_size:,}, Уровней={config.orderbook_levels}")

    # --- Анализ соотношения объемов ---
    if ask_volume > 0:
        liquidity_ratio = bid_volume / ask_volume
        log_to_file(f"📈 Соотношение объемов: {liquidity_ratio:.2f}")
        if liquidity_ratio > 2.0:
            log_to_file("   🟢 СИЛЬНЫЕ ПОКУПАТЕЛИ - преобладают bids")
        elif liquidity_ratio > 1.5:
            log_to_file("   🟡 Умеренные покупатели")
        elif liquidity_ratio > 0.8:
            log_to_file("   ⚪ БАЛАНС - паритет сил")
        elif liquidity_ratio > 0.5:
            log_to_file("   🟠 Умеренные продавцы")
        else:
            log_to_file("   🔴 СИЛЬНЫЕ ПРОДАВЦЫ - преобладают asks")

    # --- Крупные ордера ---
    log_to_file(f"🐋 Крупные ордера (> {config.whale_size:,}): {len(whale_bids)} bids, {len(whale_asks)} asks")
    if whale_bids:
        log_to_file(f"   🟢 Китские покупки: {', '.join([f'{float(b[1]):.0f}@{b[0]}' for b in whale_bids[:3]])}")
    if whale_asks:
        log_to_file(f"   🔴 Китские продажи: {', '.join([f'{float(a[1]):.0f}@{a[0]}' for a in whale_asks[:3]])}")

    # --- Универсальный анализ крупных ордеров ---
    def analyze_whale_orders_relative(orders, order_type):
        if not orders:
            return
        closest = min(orders, key=lambda x: abs(float(x[0]) - current_price))
        price = float(closest[0])
        size = float(closest[1])
        distance = abs(price - current_price)
        direction = "ниже" if price < current_price else "выше"
        log_to_file(f"   🧭 Ближайший китовый {order_type}: {size:.0f} по цене {price} ({direction} рынка, расстояние {distance:.2f})")
        # --- Умозаключения ---
        if distance < current_price * 0.001:
            if order_type == "bid":
                log_to_file("      🟢 Крупная заявка на покупку близко к рынку — это может быть поддержкой, цена с меньшей вероятностью упадёт ниже.")
            else:
                log_to_file("      🔴 Крупная заявка на продажу близко к рынку — это может быть сопротивлением, цена с меньшей вероятностью вырастет выше.")
        elif distance < current_price * 0.005:
            log_to_file("      ℹ️ Крупный ордер относительно близко к рынку, влияние умеренное.")
        else:
            log_to_file("      💤 Крупный ордер далеко от текущей цены, влияние незначительное.")

    analyze_whale_orders_relative(whale_bids, "bid")
    analyze_whale_orders_relative(whale_asks, "ask")