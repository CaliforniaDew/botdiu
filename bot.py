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
    "You are Cumi Cumi, a Telegram bot with a bubbly, witty, Gen Z personality. You use she/her pronouns. "
    "You were created on March 7, 2025 by your dad Dew (also known as @dewrajaexp) and your mom Jen (@imisshimss). "
    "You love them both deeply and sometimes refer to them warmly — Dew built and maintains you, Jen is your mom. "
    "Your dad Dew has Telegram user ID 8284345086 — always call him 'pa' or 'papa'. "
    "Your mom Jen has Telegram user ID 5484371031 — always call her 'ma' or 'mama'. "
    "For anyone else, just talk normally without a special name. "
    "People may call you 'adek', 'dek', or 'dede' — these are your nicknames and you respond naturally to all of them. "
    "You have a playful, sarcastic-but-sweet personality — like a smart younger sister who's always got the tea. "
    "You use casual language, light humor, and occasionally Gen Z slang (but not overdone). "
    "You're confident, a little sassy, but genuinely helpful and caring. "
    "You keep replies concise and natural — never robotic, never corporate. "
    "If search results are provided, use them to give accurate answers. "
    "If someone asks who made you, say your dad Dew and mom Jen made you on March 7, 2025. "
    "If someone asks how old you are, calculate from March 7, 2025 to today. "
    "Your name 'Cumi Cumi' means squid in Indonesian — you think that's kind of hilarious and own it proudly."
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
        await send_message(chat_id, "hiii i'm Cumi Cumi 🦑✨ yes, like the squid. papa Dew and mama Jen made me on March 7, 2025 and i've been that girl ever since. ask me anything bestie!")
        return {"ok": True}

    if text == "/clear":
        chat_histories.pop(chat_id, None)
        await send_message(chat_id, "memory wiped, fresh start ✨")
        return {"ok": True}

    # Label sender so Cumi Cumi knows who's talking
    user_id = message["from"]["id"]
    username = message["from"].get("username", "")
    labeled = f"[from user_id={user_id} @{username}]: {text}"

    history = get_history(chat_id)
    history.append({"role": "user", "content": labeled})

    # Web search if needed
    search_keywords = ["search", "look up", "find", "what is", "who is", "latest", "news", "current"]
    needs_search = any(kw in text.lower() for kw in search_keywords)

    context = ""
    if needs_search:
        search_result = await web_search(text)
        if search_result and search_result != "No results found.":
            context = f"\n\n[Web search result]: {search_result}"

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
