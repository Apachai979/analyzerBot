import requests
import json
import os
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Файл для хранения подписчиков
SUBSCRIBERS_FILE = "data/telegram_subscribers.json"


def load_subscribers():
    """Загружает список подписчиков из файла"""
    if not os.path.exists(SUBSCRIBERS_FILE):
        # Создаем файл с текущим chat_id из конфига (для обратной совместимости)
        initial_subscribers = [TELEGRAM_CHAT_ID] if TELEGRAM_CHAT_ID else []
        save_subscribers(initial_subscribers)
        return initial_subscribers
    
    try:
        with open(SUBSCRIBERS_FILE, 'r', encoding='utf-8') as f:
            subscribers = json.load(f)
            return subscribers if isinstance(subscribers, list) else []
    except Exception as e:
        print(f"❌ Ошибка загрузки подписчиков: {e}")
        return [TELEGRAM_CHAT_ID] if TELEGRAM_CHAT_ID else []


def save_subscribers(subscribers):
    """Сохраняет список подписчиков в файл"""
    try:
        os.makedirs(os.path.dirname(SUBSCRIBERS_FILE), exist_ok=True)
        with open(SUBSCRIBERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(subscribers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Ошибка сохранения подписчиков: {e}")


def add_subscriber(chat_id):
    """Добавляет нового подписчика"""
    subscribers = load_subscribers()
    if chat_id not in subscribers:
        subscribers.append(chat_id)
        save_subscribers(subscribers)
        print(f"✅ Новый подписчик добавлен: {chat_id}")
        return True
    return False


def remove_subscriber(chat_id):
    """Удаляет подписчика"""
    subscribers = load_subscribers()
    if chat_id in subscribers:
        subscribers.remove(chat_id)
        save_subscribers(subscribers)
        print(f"✅ Подписчик удален: {chat_id}")
        return True
    return False


def process_telegram_updates():
    """
    Обрабатывает входящие команды от пользователей (polling)
    Команды:
    - /start - подписаться на рассылку
    - /stop - отписаться от рассылки
    - /status - проверить статус подписки
    """
    if not TELEGRAM_BOT_TOKEN:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        
        if not data.get('ok'):
            return
        
        for update in data.get('result', []):
            if 'message' not in update:
                continue
            
            message = update['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            # Обработка команд
            if text == '/start':
                is_new = add_subscriber(chat_id)
                if is_new:
                    send_direct_message(
                        chat_id,
                        "🎯 <b>Добро пожаловать!</b>\n\n"
                        "Вы подписались на торговые сигналы Range Trading Bot.\n\n"
                        "📊 Вы будете получать уведомления о:\n"
                        "• Сигналах BUY/SELL с высокой уверенностью\n"
                        "• Анализе объемов и дивергенций\n"
                        "• Уровнях входа, стоп-лосса и тейк-профита\n\n"
                        "Команды:\n"
                        "/stop - отписаться от рассылки\n"
                        "/status - проверить статус подписки",
                        parse_mode="HTML"
                    )
                else:
                    send_direct_message(chat_id, "✅ Вы уже подписаны на рассылку!", parse_mode="HTML")
                
                # Подтверждаем обработку update
                offset = update['update_id'] + 1
                requests.get(f"{url}?offset={offset}", timeout=5)
            
            elif text == '/stop':
                is_removed = remove_subscriber(chat_id)
                if is_removed:
                    send_direct_message(
                        chat_id,
                        "👋 Вы отписались от рассылки.\n\n"
                        "Для возобновления подписки отправьте /start",
                        parse_mode="HTML"
                    )
                else:
                    send_direct_message(chat_id, "ℹ️ Вы не были подписаны.", parse_mode="HTML")
                
                offset = update['update_id'] + 1
                requests.get(f"{url}?offset={offset}", timeout=5)
            
            elif text == '/status':
                subscribers = load_subscribers()
                if chat_id in subscribers:
                    send_direct_message(
                        chat_id,
                        f"✅ <b>Статус: ПОДПИСАН</b>\n\n"
                        f"Всего подписчиков: {len(subscribers)}\n"
                        f"Ваш Chat ID: <code>{chat_id}</code>",
                        parse_mode="HTML"
                    )
                else:
                    send_direct_message(
                        chat_id,
                        "❌ <b>Статус: НЕ ПОДПИСАН</b>\n\n"
                        "Для подписки отправьте /start",
                        parse_mode="HTML"
                    )
                
                offset = update['update_id'] + 1
                requests.get(f"{url}?offset={offset}", timeout=5)
    
    except Exception as e:
        # Тихо игнорируем ошибки polling (не критично)
        pass


def send_direct_message(chat_id, text, parse_mode=None):
    """Отправляет сообщение конкретному пользователю"""
    if not TELEGRAM_BOT_TOKEN:
        print(f"❌ TELEGRAM_BOT_TOKEN не задан!")
        return False
    
    # Защита от слишком длинных сообщений (Telegram лимит 4096 символов)
    MAX_LENGTH = 4000
    if len(text) > MAX_LENGTH:
        text = text[:MAX_LENGTH] + "\n\n... (обрезано)"
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    
    # Добавляем parse_mode только если указан (для команд /start, /status)
    if parse_mode:
        payload["parse_mode"] = parse_mode
    
    try:
        response = requests.post(url, data=payload, timeout=10)
        response_data = response.json()
        
        if not response_data.get('ok'):
            error_desc = response_data.get('description', 'Unknown error')
            print(f"❌ Telegram API error [{chat_id}]: {error_desc}")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Ошибка отправки в Telegram [{chat_id}]: {e}")
        return False


def send_telegram_message(text):
    """
    Отправляет сообщение ВСЕМ подписчикам
    (для торговых сигналов и массовых уведомлений)
    Возвращает True если хотя бы одному подписчику доставлено
    """
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Не задан TELEGRAM_BOT_TOKEN")
        return False
    
    subscribers = load_subscribers()
    
    if not subscribers:
        print("⚠️ Нет подписчиков для рассылки")
        return False
    
    print(f"📨 Отправка сообщения {len(subscribers)} подписчикам...")
    
    success_count = 0
    failed_chats = []
    
    for chat_id in subscribers:
        if send_direct_message(chat_id, text):
            success_count += 1
        else:
            failed_chats.append(chat_id)
    
    if success_count > 0:
        print(f"✅ Сообщение отправлено {success_count}/{len(subscribers)} подписчикам")
        return True
    else:
        print(f"❌ Сообщение НЕ отправлено ни одному подписчику!")
        if failed_chats:
            print(f"❌ Проблемные подписчики: {failed_chats}")
        return False


def send_emergency_alert(error_type, symbol=None, details=None):
    """
    АВАРИЙНАЯ СИСТЕМА УВЕДОМЛЕНИЙ
    Отправляет короткое простое сообщение об ошибке
    Гарантированно доставляется (без HTML, короткое)
    
    error_type: 'ANALYSIS', 'TELEGRAM', 'API', 'CRITICAL'
    """
    if not TELEGRAM_BOT_TOKEN:
        return False
    
    subscribers = load_subscribers()
    if not subscribers:
        return False
    
    # Короткие простые сообщения (без спецсимволов)
    messages = {
        'ANALYSIS': f"ALERT: Analysis error{f' ({symbol})' if symbol else ''}",
        'TELEGRAM': "ALERT: Telegram send failed",
        'API': f"ALERT: API error{f' ({symbol})' if symbol else ''}",
        'CRITICAL': "ALERT: Critical system error"
    }
    
    message = messages.get(error_type, "ALERT: Unknown error")
    
    # Добавляем детали если есть (максимум 100 символов)
    if details:
        clean_details = str(details)[:100].replace('<', '').replace('>', '')
        message += f"\nDetails: {clean_details}"
    
    print(f"🚨 EMERGENCY ALERT: {message}")
    
    success = False
    for chat_id in subscribers:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": message}
            response = requests.post(url, data=payload, timeout=5)
            if response.json().get('ok'):
                success = True
        except:
            pass
    
    return success