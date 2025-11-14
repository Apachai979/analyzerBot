import requests
from telegram_utils import send_telegram_message

def contains_negative_keywords(text):
    """Проверяет, содержит ли текст ключевые слова 'нет' или 'не стоит' (без учета регистра)"""
    keywords = ["нет", "не стоит"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)

def ask_deepseek(summary_text, symbol=None, api_key="sk-22a1eb998bfe4ecd96797b1bcd28d70e"):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f'Проанализируй эти данные: {summary_text}. И дай мне ответ стоит ли вкладываться в эту монету, короткий лаконичный ответ жду от тебя.'}
        ]
    }
    try:
        response = requests.post(url, json=data, headers=headers)
        result = response.json()
        if "choices" in result and result["choices"]:
            content = result["choices"][0]["message"]["content"]
            if not contains_negative_keywords(content):
                send_telegram_message(f"✅ DeepSeek ответ по монете {symbol}: {content}")
        else:
            print(f"❌ DeepSeek API вернул ошибку: {result}")
    except Exception as e:
        print(f"❌ Ошибка запроса к DeepSeek: {e}")