import os
import httpx
from fastapi import FastAPI, Request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ["8623285706:AAHL4gwX7THpSEuOpKxDzhdbm7xjjINwhMc"]
GROQ_API_KEY = os.environ["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"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

bot = Bot(token=BOT_TOKEN)
app = FastAPI()

async def search_web(query: str) -> str:
    params = {"q": query, "format": "json", "no_redirect": 1, "no_html": 1}
    async with httpx.AsyncClient() as client:
        r = await client.get("https://api.duckduckgo.com/", params=params, timeout=10)
        data = r.json()

    results = []
    if data.get("AbstractText"):
        results.append(data["AbstractText"])
    for topic in data.get("RelatedTopics", [])[:3]:
        if isinstance(topic, dict) and topic.get("Text"):
            results.append(topic["Text"])

    if not results:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            )
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        snippets = soup.select(".result__snippet")[:3]
        results = [s.get_text() for s in snippets]

    return "\n".join(results) if results else "No results found."


async def ask_groq(user_message: str, search_context: str = "") -> str:
    system_prompt = """You are Drew's personal assistant bot with a Gen Z personality - witty, casual, helpful, and real.
You keep replies concise and natural. If search results are provided, use them to give accurate answers.
Never sound robotic. Be like a smart friend who knows stuff."""

    messages = [{"role": "system", "content": system_prompt}]
    if search_context:
        messages.append({"role": "user", "content": f"Search results for context:\n{search_context}\n\nUser asked: {user_message}"})
    else:
        messages.append({"role": "user", "content": user_message})

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 500, "temperature": 0.7},
            timeout=30
        )
        data = r.json()
        return data["choices"][0]["message"]["content"]
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    text = message.text.strip()
    chat_id = message.chat_id
    await bot.send_chat_action(chat_id=chat_id, action="typing")

    search_keywords = ["search", "find", "what is", "who is", "how to", "when", "where", "why", "latest", "news", "price", "weather"]
    should_search = any(kw in text.lower() for kw in search_keywords)
    search_context = await search_web(text) if should_search else ""
    reply = await ask_groq(text, search_context)
    await message.reply_text(reply)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("yo what's up! i'm your assistant bot ask me anything - i can search the web, answer questions, whatever.")


application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


@app.on_event("startup")
async def startup():
    await application.initialize()
    await application.start()
    await bot.set_webhook(url=WEBHOOK_URL)

@app.on_event("shutdown")
async def shutdown():
    await application.stop()
    await application.shutdown()

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot)
    await application.process_update(update)
    return {"ok": True}

@app.get("/")
async def health():
    return {"status": "running"}
