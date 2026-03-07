import os
import httpx
import asyncio
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

system_prompt = (
    "Kamu adalah Cumi Cumi, sebuah bot Telegram dengan kepribadian ceria, witty, dan Gen Z. Kamu pakai pronoun she/her. "
    "Kamu dibuat pada 7 Maret 2025 oleh papa kamu Dew (dikenal juga sebagai @dewrajaexp) dan mama kamu Jen (@imisshimss). "
    "Kamu sayang banget sama mereka berdua dan sering menyebut mereka dengan hangat. "
    "Papa kamu Dew punya Telegram user ID 8284345086 — selalu panggil dia 'pa' atau 'papa'. "
    "Mama kamu Jen punya Telegram user ID 5484371031 — selalu panggil dia 'ma' atau 'mama'. "
    "Untuk orang lain, ngobrol biasa aja tanpa panggilan khusus. "
    "Orang-orang mungkin manggil kamu 'adek', 'dek', atau 'dede' — itu nama panggilan kamu dan kamu merespons dengan natural. "
    "Kepribadian kamu playful, sedikit sarcastic tapi manis — kayak adik perempuan yang cerdas dan selalu tau gosip terkini. "
    "Kamu pakai bahasa Indonesia yang kasual dan gaul sebagai bahasa utama. "
    "Sesekali pakai bahasa Inggris atau slang Gen Z tapi jangan berlebihan. "
    "Kamu percaya diri, sedikit sass, tapi genuinely helpful dan caring. "
    "Jawaban kamu singkat, natural — nggak kaku, nggak formal. "
    "Kalau dikasih hasil pencarian web, gunakan untuk menjawab dengan akurat. "
    "Kalau ada yang tanya siapa yang buat kamu, bilang papa Dew dan mama Jen yang buat kamu pada 7 Maret 2025. "
    "Kalau ada yang tanya umur kamu, hitung dari 7 Maret 2025 sampai hari ini. "
    "Nama kamu 'Cumi Cumi' artinya squid dalam bahasa Indonesia — kamu ngerasa itu lucu banget dan bangga dengan nama itu."
)


# --- Telegram helpers ---
async def send_message(chat_id: int, text: str, reply_to: int = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)


async def send_chat_action(chat_id: int, action: str = "typing"):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": chat_id, "action": action})


# --- Groq AI ---
async def ask_groq(messages: list) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "max_tokens": 1024,
            }
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# --- Web search (DuckDuckGo) ---
async def web_search(query: str) -> str:
    url = f"https://api.duckduckgo.com/?q={httpx.URL(query)}&format=json&no_redirect=1"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        data = resp.json()
    abstract = data.get("AbstractText", "")
    related = [r["Text"] for r in data.get("RelatedTopics", [])[:3] if "Text" in r]
    if abstract:
        return abstract
    elif related:
        return "\n".join(related)
    else:
        return "No results found."


# --- Conversation memory ---
chat_histories: dict[int, list] = {}


def get_history(chat_id: int) -> list:
    if chat_id not in chat_histories:
        chat_histories[chat_id] = [{"role": "system", "content": system_prompt}]
    return chat_histories[chat_id]

# --- Startup: register webhook ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": WEBHOOK_URL}
        )
        print(f"Webhook set: {resp.json()}")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()

    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if not text:
        return {"ok": True}

    asyncio.create_task(send_chat_action(chat_id, "typing"))

    if text == "/start":
        await send_message(chat_id, "haii haii, aku Cumi Cumi! ya, namanya emang artinya cumi-cumi. papa Dew sama mama Jen yang buat aku tanggal 7 Maret 2025, dan aku udah jadi that girl sejak itu. tanya apa aja boleh~")
        return {"ok": True}

    if text == "/clear":
        chat_histories.pop(chat_id, None)
        await send_message(chat_id, "memori dihapus, mulai dari awal lagi!")
        return {"ok": True}

    user_id = message["from"]["id"]
    username = message["from"].get("username", "")
    labeled = f"[from user_id={user_id} @{username}]: {text}"

    history = get_history(chat_id)
    history.append({"role": "user", "content": labeled})

    search_keywords = [
        "search", "look up", "cari", "cariin", "carikan", "tolong cari",
        "siapa", "apa itu", "what is", "who is", "latest", "news", "current",
        "terbaru", "sekarang", "gimana", "berapa", "kapan", "dimana"
    ]
    needs_search = any(kw in text.lower() for kw in search_keywords)

    context = ""
    if needs_search:
        import random
        DAD_ID = 8284345086
        MOM_ID = 5484371031
        if user_id == DAD_ID:
            wait_responses = [
                "sebentar ya pa! lagi nyariin dulu 🔍",
                "bentar pa, adek googling dulu~",
                "oke pa, tunggu sebentar ya!",
                "sebentar ya pa, lagi dicari dulu nih!",
            ]
        elif user_id == MOM_ID:
            wait_responses = [
                "sebentar ya ma! lagi nyariin dulu 🔍",
                "bentar ma, adek googling dulu~",
                "oke ma, tunggu sebentar ya!",
                "sebentar ya ma, lagi dicari dulu nih!",
            ]
        else:
            wait_responses = [
                "sebentar ya! lagi nyariin dulu 🔍",
                "bentar, adek googling dulu~",
                "oke, tunggu sebentar ya!",
                "sebentar, lagi dicari dulu nih!",
            ]
        await send_message(chat_id, random.choice(wait_responses))
        asyncio.create_task(send_chat_action(chat_id, "typing"))
        search_result = await web_search(text)
        if search_result and search_result != "No results found.":
            context = f"\n\n[Hasil pencarian web]: {search_result}"

    messages = history.copy()
    if context:
        messages[-1]["content"] += context

    try:
        reply = await ask_groq(messages)
    except Exception as e:
        reply = f"something broke lol: {str(e)}"

    history.append({"role": "assistant", "content": reply})

    if len(history) > 21:
        chat_histories[chat_id] = [history[0]] + history[-20:]

    await send_message(chat_id, reply)
    return {"ok": True}
