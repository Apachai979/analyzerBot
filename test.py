import requests

url = "https://api.deepseek.com/v1/chat/completions"
api_key = "sk-22a1eb998bfe4ecd96797b1bcd28d70e"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

data = {
    "model": "deepseek-chat",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Напиши код на Python для сортировки списка."}
    ]
}

response = requests.post(url, json=data, headers=headers)
print(response.json())