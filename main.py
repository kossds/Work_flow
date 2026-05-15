import os
import time
import requests
from flask import Flask, render_template, request, jsonify
import openai
import re

app = Flask(__name__)

# --- Настройки ---
YANDEX_CLOUD_FOLDER = os.environ.get("YANDEX_CLOUD_FOLDER", "b1gpvvhplebkh4tnl6sn")
YANDEX_TEXT_API_KEY = os.environ.get("YANDEX_TEXT_API_KEY", "AQVNwD5r3qweKSaIRlUT6c2QkV3BPoKF58THGVC0")
YANDEX_TEXT_MODEL = os.environ.get("YANDEX_TEXT_MODEL", "deepseek-v32/latest")
YANDEX_IMAGE_API_KEY = os.environ.get("YANDEX_IMAGE_API_KEY", "AQVNzh2_RZ8beEQE1sB9SjiE_R0zWNlHyDbD5tXY")

text_client = openai.OpenAI(
    api_key=YANDEX_TEXT_API_KEY,
    base_url="https://ai.api.cloud.yandex.net/v1",
    project=YANDEX_CLOUD_FOLDER
)

# --- Классификатор изображений ---
def is_image_request(prompt: str) -> bool:
    prompt_lower = prompt.lower().strip()
    triggers = [
        "нарисуй", "создай изображение", "сгенерируй картинку",
        "изобрази", "картинка", "изображение", "нарисуй мне",
        "создай картину", "покажи картинку", "picture of",
        "generate image", "draw", "create an image", "visualize"
    ]
    for t in triggers:
        if t in prompt_lower:
            return True
    if re.match(r"^(изображение|image|img):", prompt_lower):
        return True
    return False

# --- Генерация текста (увеличенный контекст + лучшая структура) ---
def generate_text(prompt: str) -> str:
    try:
        response = text_client.chat.completions.create(
            model=f"gpt://{YANDEX_CLOUD_FOLDER}/{YANDEX_TEXT_MODEL}",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты — продвинутый AI-ассистент. Отвечай на русском, подробно и развёрнуто. "
                        "Структурируй ответ: используй заголовки (начинай с ##), списки (начинай с -), "
                        "выделяй важное **жирным шрифтом**. Не менее 3-4 абзацев, раскрывай тему полностью."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,   # больше креативности, но остаётся полезным
            max_tokens=2000     # в 4 раза больше предыдущего
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Ошибка генерации текста: {e}"

# --- Генерация изображения (асинхронный YandexART) ---
def generate_image_yandex(prompt: str):
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/imageGenerationAsync"
    headers = {
        "Authorization": f"Api-Key {YANDEX_IMAGE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "modelUri": f"art://{YANDEX_CLOUD_FOLDER}/yandex-art/latest",
        "generationOptions": {
            "seed": int(time.time() * 1000) % 2147483647,
            "aspectRatio": {"widthRatio": "1", "heightRatio": "1"}
        },
        "messages": [{"weight": "1", "text": prompt}]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"YandexART error {resp.status_code}: {resp.text}")
            return None
        operation_id = resp.json().get("id")
        if not operation_id:
            print("YandexART: не получил ID операции")
            return None
        print(f"Операция {operation_id} запущена, ожидаю результат...")
        check_url = f"https://llm.api.cloud.yandex.net/operations/{operation_id}"
        for _ in range(24):
            time.sleep(5)
            check_resp = requests.get(check_url, headers=headers, timeout=10)
            if check_resp.status_code != 200:
                continue
            data = check_resp.json()
            if data.get("done"):
                img_b64 = data.get("response", {}).get("image")
                if img_b64:
                    return f"data:image/png;base64,{img_b64}"
                else:
                    return None
        print("Таймаут ожидания генерации")
        return None
    except Exception as e:
        print(f"YandexART exception: {e}")
        return None

# --- Простое преобразование Markdown в HTML для красивого отображения ---
def markdown_to_html(text: str) -> str:
    # Заголовки (##)
    text = re.sub(r'^## (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
    # Жирный (**текст**)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Курсив (*текст*)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    # Списки (строки, начинающиеся с -)
    text = re.sub(r'^- (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    # Оборачиваем li в ul (простая реализация)
    if '<li>' in text:
        text = text.replace('<li>', '<ul><li>')
        text = text.replace('</li>', '</li></ul>')
        # Убираем лишние </ul><ul> между элементами
        text = text.replace('</li></ul><ul><li>', '</li><li>')
    # Переносы строк в <br>, кроме уже обработанных тегов
    text = text.replace('\n', '<br>')
    return text

# --- Маршруты ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Пустой запрос"}), 400

    print(f"\nЗапрос: '{prompt}'")

    if is_image_request(prompt):
        img_src = generate_image_yandex(prompt)
        if not img_src:
            return jsonify({"error": "Не удалось сгенерировать изображение."}), 500
        print("YandexART успешно сгенерировал.")
        return jsonify({"type": "image", "content": img_src})
    else:
        text = generate_text(prompt)
        formatted = markdown_to_html(text)
        return jsonify({"type": "text", "content": formatted})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("\n=== Сервер запущен ===")
    app.run(host="0.0.0.0", port=port, debug=False)