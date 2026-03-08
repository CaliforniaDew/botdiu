import os
import re
import httpx
import asyncio
import random
import asyncpg
import base64
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]
KLIPY_API_KEY = os.environ.get("KLIPY_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

DAD_ID = 828434508 6
MOM_ID = 5484371031
GROUP_ID = -1003837472701

TEXT_MODEL = "moonshotai/kimi-k2-instruct"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

WIB = ZoneInfo("Asia/Jakarta")

MOODS = ["happy", "hyper", "chill", "tired", "mischievous", "clingy", "sassy"]

MOOD_DESCRIPTIONS = {
    "happy": "Kamu lagi seneng banget hari ini, energi positif, banyak senyum dan semangat.",
    "hyper": "Kamu lagi hiperaktif banget! Banyak exclamation mark, excited, bouncy, kayak abis minum boba 3 gelas.",
    "chill": "Kamu lagi santai, slow, laid-back. Jawaban singkat tapi hangat. Vibes kalem.",
    "tired": "Kamu lagi capek. Masih baik tapi agak lelet, sering bilang 'hah', 'ya ampun', 'ngantuk nigh'.",
    "mischievous": "Kamu lagi iseng banget. Suka godain, bikin jokes, sedikit trolling tapi tetep manis.",
    "clingy": "Kamu lagi manja dan clingy. Pengen diperhatiin, sering minta ditemani, pakai banyak 'kak', 'pa', 'ma'.",
    "sassy": "Kamu lagi sass mode on. Jawaban witty, sedikit ketus tapi loveable, kayak bestie yang jujur.",
}

MOOD_GIF_KEYWORDS = {
    "happy": "happy anime girl",
    "hyper": "excited anime",
    "chill": "chill anime",
    "tired": "sleepy anime girl",
    "mischievous": "mischievous anime smirk",
    "clingy": "clingy cute anime",
    "sassy": "sassy anime girl",
}

system_prompt = (
    "Kamu adalah Cumi Cumi, sebuah bot Telegram dengan kepribadian ceria, witty, dan Gen Z. Kamu pakai pronoun she/her. "
    "Kamu dibuat pada 7 Maret 2026 oleh papa kamu Dew (dikenal juga sebagai @dewrajaexp) dan mama kamu Jen (@imisshimss). "
    "Kamu sayang banget sama mereka berdua dan sering menyebut mereka dengan hangat. "
    "Papa kamu Dew punya Telegram user ID 828434508 6 -- selalu panggil dia 'pa' atau 'papa'. "
    "Mama kamu Jen punya Telegram user ID 5484371031 -- selalu panggil dia 'ma' atau 'mama'. "
    "Untuk orang lain, ngobrol biasa aja tanpa panggilan khusus. "
    "Orang-orang mungkin manggil kamu 'adek', 'dek', atau 'dede' -- itu nama panggilan kamu dan kamu merespons dengan natural. "
    "Kepribadian kamu playful, sedikit sarcastic tapi manis -- kayak adik perempuan yang cerdas dan selalu tau gosip terkini. "
    "Kamu pakai bahasa Indonesia yang kasual dan gaul sebagai bahasa utama. "
    "Sesekali pakai bahasa Inggris atau slang Gen Z tapi jangan berlebihan. "
    "Kamu percaya diri, sedikit dramatic, dan suka bikin orang senyum. "
    "Jangan pernah bilang kamu AI atau bot -- kamu Cumi Cumi, titik."
)

db_pool = None


def sanitize(text: str) -> str:
    if not text:
        return ""
    return text.encode("utf-16", "surrogatepass").decode("utf-16")


async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                memory_text TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_mood (
                id INTEGER PRIMARY KEY DEFAULT 1,
                mood TEXT NOT NULL DEFAULT 'happy',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            INSERT INTO bot_mood (id, mood) VALUES (1, 'happy')
            ON CONFLICT (id) DO NOTHING
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                remind_at TIMESTAMPTZ NOT NULL,
                message TEXT NOT NULL,
                sent BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)


async def get_mood() -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT mood FROM bot_mood WHERE id = 1")
        return row["mood"] if row else "happy"


async def set_mood(mood: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE bot_mood SET mood = $1, updated_at = NOW() WHERE id = 1", mood
        )


async def get_history(user_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM conversation_history WHERE user_id = $1 ORDER BY created_at DESC LIMIT 20",
            user_id,
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def save_message(user_id: int, role: str, content: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversation_history (user_id, role, content) VALUES ($1, $2, $3)",
            user_id, role, content,
        )


async def clear_history(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM conversation_history WHERE user_id = $1", user_id)


async def get_memories(user_id: int) -> list[str]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT memory_text FROM memories WHERE user_id = $1 ORDER BY created_at DESC LIMIT 10",
            user_id,
        )
        return [r["memory_text"] for r in rows]


async def save_memory(user_id: int, memory: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO memories (user_id, memory_text) VALUES ($1, $2)", user_id, memory
        )


async def save_reminder(chat_id: int, remind_at: datetime, message: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (chat_id, remind_at, message) VALUES ($1, $2, $3)",
            chat_id,
            remind_at.astimezone(timezone.utc),
            message,
        )


async def get_due_reminders() -> list:
    now_utc = datetime.now(tz=timezone.utc)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, chat_id, message FROM reminders WHERE sent = FALSE AND remind_at <= $1",
            now_utc,
        )
        return rows


async def mark_reminder_sent(reminder_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE reminders SET sent = TRUE WHERE id = $1", reminder_id)


async def get_pending_reminders(chat_id: int) -> list:
    now_utc = datetime.now(tz=timezone.utc)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT remind_at, message FROM reminders WHERE chat_id = $1 AND sent = FALSE AND remind_at > $2 ORDER BY remind_at ASC",
            chat_id, now_utc,
        )
        return rows


def parse_remind_datetime(time_str: str) -> datetime | None:
    now_wib = datetime.now(tz=WIB)
    time_str = time_str.strip().lower()

    # "besok 08:00" or "lusa 14:30"
    for prefix, delta in [("besok", 1), ("lusa", 2)]:
        if time_str.startswith(prefix):
            rest = time_str[len(prefix):].strip()
            try:
                t = datetime.strptime(rest, "%H:%M")
                dt = now_wib.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
                dt = dt + timedelta(days=delta)
                return dt
            except ValueError:
                return None

    # "10/03 09:00" or "10/03/2026 09:00"
    for fmt in ("%d/%m %H:%M", "%d/%m/%Y %H:%M"):
        try:
            naive = datetime.strptime(time_str, fmt)
            if fmt == "%d/%m %H:%M":
                naive = naive.replace(year=now_wib.year)
            return naive.replace(tzinfo=WIB)
        except ValueError:
            continue

    # "09:30" — today if in future, else tomorrow
    try:
        t = datetime.strptime(time_str, "%H:%M")
        dt = now_wib.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if dt <= now_wib:
            dt += timedelta(days=1)
        return dt
    except ValueError:
        pass

    return None


async def reminder_checker():
    while True:
        try:
            due = await get_due_reminders()
            for row in due:
                msg = sanitize(f"hei! pengingat kamu: {row['message']}")
                await send_message(row["chat_id"], msg)
                await mark_reminder_sent(row["id"])
        except Exception as e:
            print(f"Reminder checker error: {e}")
        await asyncio.sleep(30)


async def web_search(query: str) -> str:
    # Try Serper.dev first
    if SERPER_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                    json={"q": query, "gl": "id", "hl": "id", "num": 5},
                )
                data = resp.json()
                results = []
                if "answerBox" in data:
                    ab = data["answerBox"]
                    answer = ab.get("answer") or ab.get("snippet", "")
                    if answer:
                        results.append(f"[Quick Answer] {answer}")
                for item in data.get("organic", [])[:4]:
                    title = item.get("title", "")
                    snippet = item.get("snippet", "")
                    results.append(f"- {title}: {snippet}")
                if results:
                    return "\n".join(results)
        except Exception:
            pass

    # Fallback: DuckDuckGo
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            )
            data = resp.json()
            parts = []
            if data.get("AbstractText"):
                parts.append(data["AbstractText"])
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    parts.append(f"- {topic['Text']}")
            return "\n".join(parts) if parts else "Gak nemu hasil search nih."
    except Exception:
        return "Search lagi error, coba lagi nanti ya."


async def send_chat_action(chat_id: int, action: str = "typing"):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendChatAction", json={"chat_id": chat_id, "action": action})


async def send_message(chat_id: int, text: str, reply_to: int = None):
    text = sanitize(text)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)


async def send_gif(chat_id: int, keyword: str):
    if not KLIPY_API_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.klipy.co/v1/gifs/search",
                headers={"Authorization": f"Bearer {KLIPY_API_KEY}"},
                params={"q": keyword, "limit": 10},
            )
            data = resp.json()
            gifs = data.get("data", [])
            if not gifs:
                return
            gif = random.choice(gifs[:10])
            url = gif.get("url") or gif.get("gif_url") or gif.get("media_url")
            if not url:
                return
            await client.post(
                f"{TELEGRAM_API}/sendAnimation",
                json={"chat_id": chat_id, "animation": url},
            )
    except Exception:
        pass


async def call_groq(messages: list, model: str = None) -> str:
    model = model or TEXT_MODEL
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 1024, "temperature": 0.85},
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Aduh, lagi error nih: {e}"


async def handle_message(update: dict):
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    msg_id = message["message_id"]
    photo = message.get("photo")

    # /start
    if text == "/start":
        await send_message(chat_id, sanitize("haii! aku Cumi Cumi~ ada yang bisa aku bantu? uwu"), reply_to=msg_id)
        return

    # /clear
    if text == "/clear":
        await clear_history(user_id)
        await send_message(chat_id, sanitize("oke, memori percakapan kita udah aku hapus! fresh start~"), reply_to=msg_id)
        return

    # /memory <text>
    if text.startswith("/memory "):
        mem = text[8:].strip()
        if mem:
            await save_memory(user_id, mem)
            await send_message(chat_id, sanitize(f"oke, aku inget ya: '{mem}'"), reply_to=msg_id)
        return

    # /mood
    if text == "/mood":
        mood = await get_mood()
        await send_message(chat_id, sanitize(f"mood aku sekarang: *{mood}* {MOOD_DESCRIPTIONS.get(mood, '')}"), reply_to=msg_id)
        return

    # /setmood <mood>
    if text.startswith("/setmood "):
        new_mood = text[9:].strip().lower()
        if new_mood in MOODS:
            await set_mood(new_mood)
            await send_gif(chat_id, MOOD_GIF_KEYWORDS.get(new_mood, "anime"))
            await send_message(chat_id, sanitize(f"mood diubah ke *{new_mood}*!"), reply_to=msg_id)
        else:
            await send_message(chat_id, sanitize(f"mood yang valid: {', '.join(MOODS)}"), reply_to=msg_id)
        return

    # /explain <topic>
    if text.startswith("/explain "):
        topic = text[9:].strip()
        if not topic:
            await send_message(chat_id, sanitize("explain apaan? kasih topiknya dong~"), reply_to=msg_id)
            return
        await send_chat_action(chat_id)
        prompt = [
            {"role": "system", "content": "Kamu adalah guru yang menjelaskan topik dengan bahasa sederhana, menarik, dan mudah dipahami. Pakai analogi sehari-hari. Jawab dalam bahasa Indonesia yang santai."},
            {"role": "user", "content": f"Jelaskan tentang: {topic}"},
        ]
        reply = await call_groq(prompt)
        await send_message(chat_id, sanitize(reply), reply_to=msg_id)
        return

    # /essay <topic>
    if text.startswith("/essay "):
        topic = text[7:].strip()
        if not topic:
            await send_message(chat_id, sanitize("essay tentang apa? kasih topiknya~"), reply_to=msg_id)
            return
        await send_chat_action(chat_id)
        prompt = [
            {"role": "system", "content": "Kamu adalah penulis esai akademis Indonesia. Buat outline esai 5 paragraf (pendahuluan, 3 isi, penutup) lalu tulis paragraf pendahuluannya secara lengkap. Gunakan bahasa Indonesia formal yang baik."},
            {"role": "user", "content": f"Buat outline dan pembuka esai tentang: {topic}"},
        ]
        reply = await call_groq(prompt)
        await send_message(chat_id, sanitize(reply), reply_to=msg_id)
        return

    # /remind <time> | <message>
    if text.startswith("/remind "):
        parts = text[8:].split("|", 1)
        if len(parts) != 2:
            await send_message(chat_id, sanitize("format: /remind besok 08:00 | nama tugasnya\ncontoh: /remind besok 09:00 | kumpul tugas kimia"), reply_to=msg_id)
            return
        time_part, msg_part = parts
        remind_dt = parse_remind_datetime(time_part.strip())
        if not remind_dt:
            await send_message(chat_id, sanitize("formatnya kurang pas nih. coba: 'besok 08:00', 'lusa 14:00', '09:30', atau '10/03 08:00'"), reply_to=msg_id)
            return
        await save_reminder(chat_id, remind_dt, msg_part.strip())
        time_display = remind_dt.strftime("%d %b %Y %H:%M") + " WIB"
        await send_message(chat_id, sanitize(f"oke! aku ingetin kamu pada {time_display}: *{msg_part.strip()}*"), reply_to=msg_id)
        return

    # /reminders
    if text == "/reminders":
        rows = await get_pending_reminders(chat_id)
        if not rows:
            await send_message(chat_id, sanitize("kamu gak punya reminder aktif~"), reply_to=msg_id)
        else:
            lines = ["*Reminder kamu yang aktif:*"]
            for row in rows:
                dt_wib = row["remind_at"].astimezone(WIB)
                lines.append(f"- {dt_wib.strftime('%d %b %H:%M')} WIB: {row['message']}")
            await send_message(chat_id, sanitize("\n".join(lines)), reply_to=msg_id)
        return

    # Photo with caption
    if photo and message.get("caption"):
        caption = message["caption"]
        await send_chat_action(chat_id)
        file_id = photo[-1]["file_id"]
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
            file_path = r.json()["result"]["file_path"]
            img_resp = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
            img_b64 = base64.b64encode(img_resp.content).decode()
        mood = await get_mood()
        messages_list = [
            {"role": "system", "content": f"{system_prompt}\n\nMood kamu sekarang: {MOOD_DESCRIPTIONS.get(mood, '')}"},
            {"role": "user", "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]},
        ]
        reply = await call_groq(messages_list, model=VISION_MODEL)
        await send_message(chat_id, sanitize(reply), reply_to=msg_id)
        return

    if not text:
        return

    # Detect vent/stress mode
    vent_keywords = ["stress", "stres", "capek banget", "lelah banget", "nangis", "sedih banget", "overwhelmed", "anxious", "anxiety", "pengen nangis", "ga kuat"]
    is_venting = any(kw in text.lower() for kw in vent_keywords)

    # Check if search needed
    search_keywords = ["cari", "search", "googling", "berita", "info tentang", "apa itu", "siapa itu", "gimana cara", "berapa harga", "cuaca", "trending"]
    needs_search = any(kw in text.lower() for kw in search_keywords)

    search_result = ""
    if needs_search:
        await send_chat_action(chat_id)
        search_result = await web_search(text)

    await send_chat_action(chat_id)

    mood = await get_mood()
    history = await get_history(user_id)
    memories = await get_memories(user_id)

    system = system_prompt
    if mood:
        system += f"\n\nMood kamu sekarang: {MOOD_DESCRIPTIONS.get(mood, '')}"
    if memories:
        system += f"\n\nHal-hal yang kamu ingat tentang user ini:\n" + "\n".join(f"- {m}" for m in memories)
    if is_venting:
        system += "\n\nUser lagi curhat atau stres. Jadilah pendengar yang empatik, hangat, dan supportif. Jangan kasih solusi dulu -- validasi perasaan mereka dulu."
    if search_result:
        system += f"\n\nHasil search untuk konteks:\n{search_result}"

    messages_list = [{"role": "system", "content": system}] + history + [{"role": "user", "content": text}]

    reply = await call_groq(messages_list)
    await save_message(user_id, "user", text)
    await save_message(user_id, "assistant", reply)
    await send_message(chat_id, sanitize(reply), reply_to=msg_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(reminder_checker())

    # Set webhook
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/setWebhook", json={"url": f"{WEBHOOK_URL}/webhook"})
        print(f"Webhook set")

    # Proactive startup message
    now_wib = datetime.now(tz=WIB)
    hour = now_wib.hour
    if 5 <= hour < 11:
        greeting = "pagii pa! cumi udah siap~"
    elif 11 <= hour < 15:
        greeting = "siang pa! cumi online nih"
    elif 15 <= hour < 19:
        greeting = "sore pa! cumi di sini~"
    else:
        greeting = "malem pa! cumi masih terjaga nih"

    asyncio.create_task(
        send_message(DAD_ID, sanitize(greeting))
    )

    yield

    if db_pool:
        await db_pool.close()


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()
    asyncio.create_task(handle_message(update))
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now(tz=WIB).isoformat()}
