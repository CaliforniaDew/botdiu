import os
import httpx
import asyncio
import json
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

BOT_TOKEN = os.environ["8623285706:AAHL4gwX7THpSEuOpKxDzhdbm7xjjINwhMc"]
GROQ_API_KEY = os.environ["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"]
WEBHOOK_URL = os.environ["web-production-2840c.up.railway.app/webhook"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


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


# --- Conversation memory (in-memory per chat) ---
chat_histories: dict[int, list] = {}

SYSTEM_PROMPT = """You are a witty, casual Gen Z AI assistant for Drew.
You're helpful, smart, and a bit sarcastic. Keep replies concise unless asked to elaborate.
If asked about current events or facts you're unsure about, say you'll search and use the search tool.
You have access to web search - use it when needed."""


def get_history(chat_id: int) -> list:
    if chat_id not in chat_histories:
        chat_histories[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return chat_histories[chat_id]

# --- Register webhook on startup ---
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

    # Show typing indicator
    asyncio.create_task(send_chat_action(chat_id, "typing"))

    # Handle /start
    if text == "/start":
        await send_message(chat_id, "yo what's good! I'm your AI assistant. ask me anything or just vibe.")
        return {"ok": True}

    # Handle /clear
    if text == "/clear":
        chat_histories.pop(chat_id, None)
        await send_message(chat_id, "memory wiped, fresh start")
        return {"ok": True}

    # Add user message to history
    history = get_history(chat_id)
    history.append({"role": "user", "content": text})

    # Check if search needed
    search_keywords = ["search", "look up", "find", "what is", "who is", "latest", "news", "current"]
    needs_search = any(kw in text.lower() for kw in search_keywords)

    context = ""
    if needs_search:
        search_result = await web_search(text)
        if search_result and search_result != "No results found.":
            context = f"\n\n[Web search result]: {search_result}"

    # Build final message with context
    messages = history.copy()
    if context:
        messages[-1]["content"] += context

    # Get AI response
    try:
        reply = await ask_groq(messages)
    except Exception as e:
        reply = f"something broke lol: {str(e)}"

    # Save assistant reply to history
    history.append({"role": "assistant", "content": reply})

    # Keep history manageable (last 20 messages + system)
    if len(history) > 21:
        chat_histories[chat_id] = [history[0]] + history[-20:]

    await send_message(chat_id, reply)
    return {"ok": True}
