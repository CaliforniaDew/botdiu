import os
import httpx
import asyncio
import random
import asyncpg
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
DAD_ID = 8284345086
MOM_ID = 5484371031

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

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                fact TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

async def load_history(chat_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM chat_history WHERE chat_id=$1 ORDER BY id DESC LIMIT 20", chat_id)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

async def save_message(chat_id, role, content):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO chat_history (chat_id, role, content) VALUES ($1,$2,$3)", chat_id, role, content)
        await conn.execute("""
            DELETE FROM chat_history WHERE chat_id=$1 AND id NOT IN (
                SELECT id FROM chat_history WHERE chat_id=$1 ORDER BY id DESC LIMIT 30)
        """, chat_id)

async def load_memories(chat_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT fact FROM memories WHERE chat_id=$1 ORDER BY id DESC LIMIT 20", chat_id)
    return [r["fact"] for r in rows]

async def save_memory(chat_id, fact):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO memories (chat_id, fact) VALUES ($1,$2)", chat_id, fact)

async def clear_history(chat_id):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_history WHERE chat_id=$1", chat_id)

# --- Telegram helpers ---
async def send_message(chat_id, text, reply_to=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)

async def send_chat_action(chat_id, action="typing"):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": chat_id, "action": action})

# --- Groq AI ---
async def ask_groq(messages):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 1024}
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

# --- Fact extraction ---
async def extract_facts(chat_id, user_text, assistant_reply):
    extraction_prompt = [
        {"role": "system", "content": (
            "Kamu adalah sistem ekstraksi memori. Tugasmu: dari percakapan ini, "
            "ekstrak fakta-fakta penting yang perlu diingat jangka panjang. "
            "Contoh: nama orang, ulang tahun, preferensi, kebiasaan, kejadian penting, goals. "
            "Jawab HANYA dengan daftar fakta singkat, satu per baris, format: 'FAKTA: ...' "
            "Kalau tidak ada fakta penting, jawab: 'TIDAK ADA'")},
        {"role": "user", "content": f"User berkata: {user_text}\nBot menjawab: {assistant_reply}"}
    ]
    try:
        result = await ask_groq(extraction_prompt)
        if "TIDAK ADA" in result:
            return
        for line in result.splitlines():
            if line.strip().startswith("FAKTA:"):
                fact = line.replace("FAKTA:", "").strip()
                if fact:
                    await save_memory(chat_id, fact)
    except Exception:
        pass

# --- Web search ---
async def web_search(query):
    url = f"https://api.duckduckgo.com/?q={httpx.URL(query)}&format=json&no_redirect=1"
    async with httpx.AsyncClient(timeout=10) as client:
        data = (await client.get(url)).json()
    abstract = data.get("AbstractText", "")
    related = [r["Text"] for r in data.get("RelatedTopics", [])[:3] if "Text" in r]
    return abstract or ("\n".join(related) if related else "No results found.")

# --- Startup ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{TELEGRAM_API}/setWebhook", json={"url": WEBHOOK_URL})
        print(f"Webhook set: {resp.json()}")
    yield
    await db_pool.close()

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
    user_id = message["from"]["id"]
    username = message["from"].get("username", "")

    if not text:
        return {"ok": True}

    asyncio.create_task(send_chat_action(chat_id, "typing"))

    if text == "/start":
        await send_message(chat_id, "haii haii, aku Cumi Cumi! ya, namanya emang artinya cumi-cumi. papa Dew sama mama Jen yang buat aku tanggal 7 Maret 2025, dan aku udah jadi that girl sejak itu. tanya apa aja boleh~")
        return {"ok": True}

    if text == "/clear":
        await clear_history(chat_id)
        await send_message(chat_id, "memori sesi dihapus, mulai dari awal lagi!")
        return {"ok": True}

    if text == "/memory":
        facts = await load_memories(chat_id)
        if not facts:
            await send_message(chat_id, "belum ada memori tersimpan nih~")
        else:
            facts_text = "\n".join(f"• {f}" for f in facts)
            await send_message(chat_id, f"ini yang aku inget:\n{facts_text}")
        return {"ok": True}

    labeled = f"[from user_id={user_id} @{username}]: {text}"
    history = await load_history(chat_id)
    memories = await load_memories(chat_id)

    full_system = system_prompt
    if memories:
        mem_block = "\n".join(f"- {m}" for m in memories)
        full_system += f"\n\nMemori jangka panjang yang kamu ingat:\n{mem_block}"

    messages = [{"role": "system", "content": full_system}] + history

    search_keywords = [
        "search", "look up", "cari", "cariin", "carikan", "tolong cari",
        "siapa", "apa itu", "what is", "who is", "latest", "news", "current",
        "terbaru", "sekarang", "gimana", "berapa", "kapan", "dimana"
    ]
    needs_search = any(kw in text.lower() for kw in search_keywords)

    context = ""
    if needs_search:
        if user_id == DAD_ID:
            waits = ["sebentar ya pa! lagi nyariin dulu", "bentar pa, adek googling dulu~", "oke pa, tunggu sebentar ya!"]
        elif user_id == MOM_ID:
            waits = ["sebentar ya ma! lagi nyariin dulu", "bentar ma, adek googling dulu~", "oke ma, tunggu sebentar ya!"]
        else:
            waits = ["sebentar ya! lagi nyariin dulu", "bentar, adek googling dulu~", "oke, tunggu sebentar ya!"]
        await send_message(chat_id, random.choice(waits))
        asyncio.create_task(send_chat_action(chat_id, "typing"))
        result = await web_search(text)
        if result and result != "No results found.":
            context = f"\n\n[Hasil pencarian web]: {result}"

    messages.append({"role": "user", "content": labeled + context})

    try:
        reply = await ask_groq(messages)
    except Exception as e:
        reply = f"something broke lol: {str(e)}"

    await save_message(chat_id, "user", labeled)
    await save_message(chat_id, "assistant", reply)
    asyncio.create_task(extract_facts(chat_id, text, reply))
    await send_message(chat_id, reply)
    return {"ok": True}
