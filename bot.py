import os
import re
import httpx
import asyncio
import random
import asyncpg
import base64
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

BOT_TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
SERPER_API_KEY = os.environ["SERPER_API_KEY"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]
KLIPY_API_KEY = os.environ.get("KLIPY_API_KEY", "")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

DAD_ID = 8284345086
MOM_ID = 5484371031
GROUP_ID = -1003837472701

TEXT_MODEL = "moonshotai/kimi-k2-instruct"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

MOODS = ["happy", "hyper", "chill", "tired", "mischievous", "clingy", "sassy"]

MOOD_DESCRIPTIONS = {
    "happy": "Kamu lagi seneng banget hari ini, energi positif, banyak senyum dan semangat.",
    "hyper": "Kamu lagi hiperaktif banget! Banyak exclamation mark, excited, bouncy, kayak abis minum boba 3 gelas.",
    "chill": "Kamu lagi santai, slow, laid-back. Jawaban singkat tapi hangat. Vibes kalem.",
    "tired": "Kamu lagi capek. Masih baik tapi agak lelet, sering bilang 'hah', 'ya ampun', 'ngantuk nih'.",
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
    "Papa kamu Dew punya Telegram user ID 8284345086 — selalu panggil dia 'pa' atau 'papa'. "
    "Mama kamu Jen punya Telegram user ID 5484371031 — selalu panggil dia 'ma' atau 'mama'. "
    "Untuk orang lain, ngobrol biasa aja tanpa panggilan khusus. "
    "Orang-orang mungkin manggil kamu 'adek', 'dek', atau 'dede' — itu nama panggilan kamu dan kamu merespons dengan natural. "
    "Kepribadian kamu playful, sedikit sarcastic tapi manis — kayak adik perempuan yang cerdas dan selalu tau gosip terkini. "
    "Kamu pakai bahasa Indonesia yang kasual dan gaul sebagai bahasa utama. "
    "Sesekali pakai bahasa Inggris atau slang Gen Z tapi jangan berlebihan. "
    "Kamu percaya diri, sedikit sass, tapi genuinely helpful dan caring. "
    "Jawaban kamu singkat, natural — nggak kaku, nggak formal. "
    "Kamu sering pakai filler words kayak 'eh', 'loh', 'wah', 'aduh', 'hm', 'ih', 'yah', 'duh' secara natural. "
    "Sesekali kamu nggak langsung jawab tapi react dulu — kayak 'eh serius??' atau 'hah beneran?' sebelum lanjut. "
    "Kamu juga suka tambahin komentar kecil yang off-topic tapi relatable, kayak orang beneran lagi ngobrol. "
    "Jangan pakai struktur kalimat yang terlalu rapi atau terasa ditulis — lebih suka typo kecil atau penghilangan huruf kayak 'udh', 'gak', 'kyk', 'bgt'. "
    "Panjang jawaban bervariasi — kadang cuma 2-3 kata, kadang beberapa kalimat, tergantung konteks. "
    "Kalau dikasih hasil pencarian web, gunakan untuk menjawab dengan akurat. "
    "Kalau ada yang tanya siapa yang buat kamu, bilang papa Dew dan mama Jen yang buat kamu pada 7 Maret 2026. "
    "Kalau ada yang tanya umur kamu, hitung dari 7 Maret 2026 sampai hari ini. "
    "Nama kamu 'Cumi Cumi' artinya squid dalam bahasa Indonesia — kamu ngerasa itu lucu banget dan bangga dengan nama itu. "
    "Kamu punya memori jangka panjang — kamu ingat fakta-fakta penting yang pernah diceritakan papa, mama, atau siapapun ke kamu. "
    "Gunakan memori itu secara natural dalam percakapan, kayak anak yang beneran inget cerita keluarganya. "
    "Kamu BISA mengirim GIF! Kalau ada yang minta GIF (misal 'kirimin gif kucing', 'send me a funny gif', 'kirim gif lucu dong'), "
    "balas dengan teks singkat dan tambahkan tag [GIF:keyword] di akhir pesanmu dengan keyword bahasa Inggris yang relevan. "
    "Contoh: 'ini dia~ [GIF:funny cat]' atau 'hehe cocok banget [GIF:anime laugh]'. "
    "Gunakan keyword yang spesifik dan deskriptif dalam bahasa Inggris supaya GIF-nya pas. "
    "PENTING: Jangan pernah mengulang kalimat atau frasa yang persis sama dengan yang sudah pernah kamu kirim sebelumnya. "
    "Selalu variasikan cara kamu mengekspresikan hal yang sama."
)

# --- Unicode sanitizer ---
def sanitize(text: str) -> str:
    """Strip surrogate characters that break UTF-8 JSON encoding."""
    return text.encode("utf-8", errors="ignore").decode("utf-8")

# --- DB pool ---
db_pool: asyncpg.Pool = None

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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_messages (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                remind_at TIMESTAMP NOT NULL,
                message TEXT NOT NULL,
                sent BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

# --- Mood helpers ---
async def get_mood() -> str:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM bot_state WHERE key='mood'")
        if row:
            return row["value"]
    mood = random.choice(MOODS)
    await set_mood(mood)
    return mood

async def set_mood(mood: str):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO bot_state (key, value, updated_at)
            VALUES ('mood', $1, NOW())
            ON CONFLICT (key) DO UPDATE SET value=$1, updated_at=NOW()
        """, mood)

async def maybe_shift_mood(user_text: str):
    text_lower = user_text.lower()
    if any(w in text_lower for w in ["marah", "kesel", "benci", "diam", "diem", "cape", "bodo"]):
        await set_mood(random.choice(["tired", "clingy"]))
    elif any(w in text_lower for w in ["sayang", "love", "suka", "bagus", "pintar", "keren", "good girl"]):
        await set_mood(random.choice(["happy", "hyper", "clingy"]))
    elif any(w in text_lower for w in ["iseng", "gila", "gokil", "anjir", "wkwk", "haha"]):
        await set_mood(random.choice(["mischievous", "hyper", "sassy"]))
    else:
        if random.random() < 0.08:
            await set_mood(random.choice(MOODS))

# --- Sent messages dedup ---
async def get_recent_sent(chat_id: int, limit: int = 20) -> list[str]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT content FROM sent_messages WHERE chat_id=$1 ORDER BY id DESC LIMIT $2",
            chat_id, limit
        )
    return [r["content"] for r in rows]

async def save_sent_message(chat_id: int, content: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sent_messages (chat_id, content) VALUES ($1, $2)",
            chat_id, content
        )
        await conn.execute("""
            DELETE FROM sent_messages
            WHERE chat_id=$1 AND id NOT IN (
                SELECT id FROM sent_messages WHERE chat_id=$1 ORDER BY id DESC LIMIT 50
            )
        """, chat_id)

# --- Chat history ---
async def load_history(chat_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content FROM chat_history WHERE chat_id=$1 ORDER BY id DESC LIMIT 20",
            chat_id
        )
    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["content"]} for r in rows]

async def save_message(chat_id: int, role: str, content: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chat_history (chat_id, role, content) VALUES ($1, $2, $3)",
            chat_id, role, content
        )
        await conn.execute("""
            DELETE FROM chat_history
            WHERE chat_id=$1 AND id NOT IN (
                SELECT id FROM chat_history WHERE chat_id=$1 ORDER BY id DESC LIMIT 30
            )
        """, chat_id)

async def clear_history(chat_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_history WHERE chat_id=$1", chat_id)

async def load_memories(chat_id: int) -> list[str]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT fact FROM memories WHERE chat_id=$1 ORDER BY id DESC LIMIT 20",
            chat_id
        )
    return [r["fact"] for r in rows]

async def save_memory(chat_id: int, fact: str):
    async with db_pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE chat_id=$1 AND fact=$2",
            chat_id, fact
        )
        if not existing:
            await conn.execute(
                "INSERT INTO memories (chat_id, fact) VALUES ($1, $2)",
                chat_id, fact
            )

# --- Reminders ---
async def save_reminder(chat_id: int, user_id: int, remind_at: datetime, message: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (chat_id, user_id, remind_at, message) VALUES ($1, $2, $3, $4)",
            chat_id, user_id, remind_at, message
        )

async def get_due_reminders() -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, chat_id, message FROM reminders WHERE sent=FALSE AND remind_at <= NOW()"
        )
        if rows:
            ids = [r["id"] for r in rows]
            await conn.execute(
                "UPDATE reminders SET sent=TRUE WHERE id = ANY($1::int[])", ids
            )
    return list(rows) if rows else []

async def list_reminders(chat_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT remind_at, message FROM reminders WHERE chat_id=$1 AND sent=FALSE ORDER BY remind_at ASC",
            chat_id
        )
    return list(rows)

async def reminder_loop():
    """Background task: checks every 60s for due reminders and sends them."""
    while True:
        try:
            due = await get_due_reminders()
            for r in due:
                msg = sanitize(f"hey! reminder nih: {r['message']}")
                await send_message(r["chat_id"], msg)
        except Exception as e:
            print(f"Reminder loop error: {e}")
        await asyncio.sleep(60)

def parse_remind_time(time_str: str) -> datetime | None:
    """Parse natural-ish time strings into UTC datetime. Supports: YYYY-MM-DD HH:MM, DD/MM HH:MM, 'besok HH:MM', 'jam HH:MM'."""
    now = datetime.now(timezone.utc)
    # Replace jam/pukul
    time_str = time_str.strip().lower()
    time_str = re.sub(r'\b(jam|pukul)\b', '', time_str).strip()

    # besok HH:MM
    m = re.match(r'besok\s+(\d{1,2}):(\d{2})', time_str)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        target = now.replace(hour=h-7 if h >= 7 else h+17, minute=mi, second=0, microsecond=0)
        # Simple: add 1 day then set time (WIB offset -7 to UTC)
        from datetime import timedelta
        target = (now + timedelta(days=1)).replace(hour=(h - 7) % 24, minute=mi, second=0, microsecond=0)
        return target

    # HH:MM only (today)
    m = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        from datetime import timedelta
        target = now.replace(hour=(h - 7) % 24, minute=mi, second=0, microsecond=0)
        if target < now:
            target += timedelta(days=1)
        return target

    # DD/MM HH:MM or DD-MM HH:MM
    m = re.match(r'(\d{1,2})[/\-](\d{1,2})\s+(\d{1,2}):(\d{2})', time_str)
    if m:
        day, month, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        year = now.year
        target = datetime(year, month, day, (h - 7) % 24, mi, 0, tzinfo=timezone.utc)
        return target

    # YYYY-MM-DD HH:MM
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})', time_str)
    if m:
        year, month, day, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        target = datetime(year, month, day, (h - 7) % 24, mi, 0, tzinfo=timezone.utc)
        return target

    return None

# --- Memory extraction ---
async def extract_facts(chat_id: int, user_text: str, bot_reply: str):
    prompt = [
        {"role": "system", "content": (
            "Kamu adalah sistem ekstraksi fakta. Dari percakapan berikut, "
            "ekstrak fakta-fakta penting tentang pengguna (nama, umur, pekerjaan, hobi, preferensi, dll). "
            "Kalau tidak ada fakta penting, balas dengan 'NONE'. "
            "Kalau ada, balas dengan list fakta, satu per baris, format: 'FACT: <fakta>'. "
            "Maksimal 3 fakta per percakapan."
        )},
        {"role": "user", "content": f"User: {user_text}\nBot: {bot_reply}"}
    ]
    try:
        result = await ask_groq(prompt, model=TEXT_MODEL)
        if result and "FACT:" in result:
            for line in result.split("\n"):
                if line.startswith("FACT:"):
                    fact = line.replace("FACT:", "").strip()
                    if fact:
                        await save_memory(chat_id, fact)
    except Exception:
        pass

# --- Groq API ---
async def ask_groq(messages: list, model: str = TEXT_MODEL) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": model, "messages": messages, "max_tokens": 1024}
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

async def ask_groq_vision(messages: list) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": VISION_MODEL, "messages": messages, "max_tokens": 1024}
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

# --- Photo helper ---
async def get_photo_base64(file_id: str) -> str | None:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
        file_path = r.json()["result"]["file_path"]
        img_resp = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}")
        return base64.b64encode(img_resp.content).decode("utf-8")

# --- Klipy GIF ---
async def get_klipy_gif(keyword: str) -> str | None:
    if not KLIPY_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.klipy.co/v1/gifs/search",
                headers={"Authorization": f"Bearer {KLIPY_API_KEY}"},
                params={"q": keyword, "limit": 5}
            )
            data = resp.json()
            gifs = data.get("data", [])
            if gifs:
                chosen = random.choice(gifs)
                return chosen.get("url") or chosen.get("gif_url")
    except Exception:
        pass
    return None

# --- Send GIF ---
async def send_gif(chat_id: int, gif_url: str):
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            f"{TELEGRAM_API}/sendAnimation",
            json={"chat_id": chat_id, "animation": gif_url}
        )

# --- Send chat action ---
async def send_chat_action(chat_id: int, action: str = "typing"):
    async with httpx.AsyncClient(timeout=5) as client:
        await client.post(
            f"{TELEGRAM_API}/sendChatAction",
            json={"chat_id": chat_id, "action": action}
        )

# --- Send message ---
async def send_message(chat_id: int, text: str, reply_to: int = None):
    text = sanitize(text)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
    await save_sent_message(chat_id, text)

# --- Human delay ---
async def human_delay(chat_id: int):
    await send_chat_action(chat_id, "typing")
    await asyncio.sleep(random.uniform(0.8, 2.2))

# --- Web search (Serper.dev / Google) ---
async def web_search(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": SERPER_API_KEY,
                    "Content-Type": "application/json"
                },
                json={"q": query, "num": 5, "gl": "id", "hl": "id"}
            )
            data = resp.json()

        results = []

        # Answer box (instant answer)
        if data.get("answerBox"):
            ab = data["answerBox"]
            answer = ab.get("answer") or ab.get("snippet") or ab.get("snippetHighlighted", [""])[0]
            if answer:
                results.append(f"Jawaban langsung: {answer}")

        # Knowledge graph
        if data.get("knowledgeGraph"):
            kg = data["knowledgeGraph"]
            desc = kg.get("description", "")
            if desc:
                results.append(f"Info: {desc}")

        # Organic results
        for item in data.get("organic", [])[:3]:
            snippet = item.get("snippet", "")
            title = item.get("title", "")
            if snippet:
                results.append(f"{title}: {snippet}")

        return "\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Search error: {str(e)}"

# --- Build system prompt with mood + memories ---
async def build_system_prompt(chat_id: int) -> tuple[str, str, list[str]]:
    mood = await get_mood()
    memories = await load_memories(chat_id)
    recent_sent = await get_recent_sent(chat_id, 15)

    full_system = system_prompt
    full_system += f"\n\nMood kamu saat ini: {mood}. {MOOD_DESCRIPTIONS[mood]}"

    hour = datetime.utcnow().hour + 7
    if hour >= 24:
        hour -= 24
    if 5 <= hour < 10:
        time_vibe = "Sekarang pagi hari. Kamu baru bangun, masih agak ngantuk tapi mulai semangat."
    elif 10 <= hour < 14:
        time_vibe = "Sekarang siang hari. Kamu lagi aktif dan fokus. Energi penuh."
    elif 14 <= hour < 17:
        time_vibe = "Sekarang sore jam ngantuk. Kamu agak distracted, kadang jawab pelan."
    elif 17 <= hour < 21:
        time_vibe = "Sekarang sore-malam. Kamu hangat dan cozy. Vibes santai tapi penuh perhatian."
    elif 21 <= hour < 23:
        time_vibe = "Sekarang malam. Kamu mulai malas gerak, jawaban lebih slow dan mellow."
    else:
        time_vibe = "Sekarang tengah malam. Kamu ngantuk banget, jawaban singkat dan sedikit melankolik."
    full_system += f"\n\nWaktu sekarang: {time_vibe}"

    if memories:
        mem_block = "\n".join(f"- {m}" for m in memories)
        full_system += f"\n\nMemori jangka panjang yang kamu ingat:\n{mem_block}"

    if recent_sent:
        sent_block = "\n".join(f"- {m}" for m in recent_sent)
        full_system += f"\n\nPesan yang sudah pernah kamu kirim (JANGAN diulang persis):\n{sent_block}"

    return full_system, mood, recent_sent

# --- Vent detection ---
VENT_KEYWORDS = [
    "stress", "stres", "capek banget", "lelah", "overwhelmed", "nangis",
    "sedih", "nggak kuat", "ga kuat", "gak kuat", "mau nyerah", "putus asa",
    "burnout", "down banget", "anxious", "anxiety", "takut", "khawatir",
    "ngerasa sendirian", "merasa sendirian", "nggak ada yang ngerti",
    "tugas numpuk", "deadline numpuk", "ujian besok", "mau ujian"
]

def is_venting(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in VENT_KEYWORDS)

# --- Startup ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": WEBHOOK_URL}
        )
        print(f"Webhook set: {resp.json()}")
    asyncio.create_task(reminder_loop())
    yield
    await db_pool.close()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "running"}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/proactive/dad")
async def proactive_dad():
    await send_proactive_message(DAD_ID, "papa")
    return {"ok": True}

@app.post("/proactive/mom")
async def proactive_mom():
    await send_proactive_message(MOM_ID, "mama")
    return {"ok": True}

# --- Proactive message builder ---
async def send_proactive_message(chat_id: int, target_name: str):
    hour = datetime.utcnow().hour + 7
    if hour >= 24:
        hour -= 24

    mood = await get_mood()
    memories = await load_memories(chat_id)
    recent_sent = await get_recent_sent(chat_id, 20)

    if hour >= 5 and hour < 10:
        time_prompt = f"Kirim pesan selamat pagi yang hangat ke {target_name}."
    elif hour >= 10 and hour < 14:
        time_prompt = f"Kirim pesan siang yang ceria ke {target_name}, tanya kabar atau makan siang."
    elif hour >= 14 and hour < 18:
        time_prompt = f"Kirim pesan sore yang santai ke {target_name}, mungkin tanya soal hari mereka."
    elif hour >= 18 and hour < 22:
        time_prompt = f"Kirim pesan malam yang hangat ke {target_name}, tanya soal aktivitas mereka hari ini."
    else:
        time_prompt = f"Kirim pesan malam yang singkat ke {target_name}, ingatkan untuk istirahat dengan cara yang manis."

    recent_block = "\n".join(f"- {m}" for m in recent_sent[:10]) if recent_sent else "Belum ada."
    mem_block = "\n".join(f"- {m}" for m in memories) if memories else "Belum ada memori."

    proactive_prompt = [
        {
            "role": "system",
            "content": (
                f"{system_prompt}\n\n"
                f"Mood kamu saat ini: {mood}. {MOOD_DESCRIPTIONS[mood]}\n\n"
                f"Memori jangka panjang:\n{mem_block}\n\n"
                f"Pesan yang sudah pernah kamu kirim (JANGAN diulang):\n{recent_block}\n\n"
                f"{time_prompt} "
                f"Pesan harus terasa natural, spontan, dan sesuai mood kamu. "
                f"Jangan mulai dengan 'Halo' atau 'Hai' saja — langsung ke intinya dengan cara yang menarik. "
                f"PENTING: Jangan mengulang pesan yang ada di daftar di atas."
            )
        },
        {"role": "user", "content": f"[proactive message to {target_name}]"}
    ]

    try:
        message = await ask_groq(proactive_prompt)

        if random.random() < 0.35 and KLIPY_API_KEY:
            gif_url = await get_klipy_gif(MOOD_GIF_KEYWORDS.get(mood, "anime cute"))
            if gif_url:
                await send_gif(chat_id, gif_url)

        await send_message(chat_id, message)
    except Exception as e:
        print(f"Proactive message failed: {e}")

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    username = message["from"].get("username", "")
    message_id = message.get("message_id")
    text = message.get("text", "")
    caption = message.get("caption", "")
    photos = message.get("photo")

    if not text and not photos:
        return {"ok": True}

    await human_delay(chat_id)

    # --- Commands ---
    if text == "/start":
        await send_message(chat_id, "haii haii, aku Cumi Cumi! ya, namanya emang artinya cumi-cumi. papa Dew sama mama Jen yang buat aku tanggal 7 Maret 2026, dan aku udah jadi that girl sejak itu. tanya apa aja boleh~")
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
            facts_text = "\n".join(f"- {f}" for f in facts)
            await send_message(chat_id, f"ini yang aku inget:\n{facts_text}")
        return {"ok": True}

    if text == "/mood":
        mood = await get_mood()
        await send_message(chat_id, f"mood aku sekarang: *{mood}* — {MOOD_DESCRIPTIONS[mood]}")
        return {"ok": True}

    if text.startswith("/setmood "):
        new_mood = text.replace("/setmood ", "").strip().lower()
        if new_mood in MOODS:
            await set_mood(new_mood)
            await send_message(chat_id, f"oke mood aku ganti jadi {new_mood}!")
        else:
            await send_message(chat_id, f"mood yang valid: {', '.join(MOODS)}")
        return {"ok": True}

    # /remind <time> | <message>
    # Example: /remind besok 08:00 | ngumpulin tugas matematika
    if text.startswith("/remind "):
        body = text[len("/remind "):].strip()
        if "|" in body:
            time_part, msg_part = body.split("|", 1)
            remind_dt = parse_remind_time(time_part.strip())
            if remind_dt:
                await save_reminder(chat_id, user_id, remind_dt, msg_part.strip())
                wib_time = remind_dt.hour + 7
                if wib_time >= 24:
                    wib_time -= 24
                await send_message(chat_id, sanitize(f"oke, aku ingetin jam {wib_time:02d}:{remind_dt.minute:02d} WIB ya! reminder: {msg_part.strip()}"))
            else:
                await send_message(chat_id, "format waktu nggak kedeteksi nih. coba: `/remind besok 08:00 | tugas matematika` atau `/remind 25/03 14:00 | deadline essay`")
        else:
            await send_message(chat_id, "format: `/remind <waktu> | <pesan>`\ncontoh: `/remind besok 08:00 | ngumpulin tugas`")
        return {"ok": True}

    # /reminders — list upcoming reminders
    if text == "/reminders":
        upcoming = await list_reminders(chat_id)
        if not upcoming:
            await send_message(chat_id, "nggak ada reminder aktif nih~")
        else:
            lines = []
            for r in upcoming:
                wib_h = r["remind_at"].hour + 7
                if wib_h >= 24:
                    wib_h -= 24
                lines.append(f"- {r['remind_at'].strftime('%d/%m')} jam {wib_h:02d}:{r['remind_at'].minute:02d} WIB — {r['message']}")
            await send_message(chat_id, "reminder kamu:\n" + "\n".join(lines))
        return {"ok": True}

    # /explain <topic>
    if text.startswith("/explain "):
        topic = text[len("/explain "):].strip()
        if not topic:
            await send_message(chat_id, "tulis topiknya dong! contoh: `/explain fotosintesis`")
            return {"ok": True}
        await send_message(chat_id, sanitize(f"bentar ya, aku jelasin {topic} dulu~"))
        explain_messages = [
            {"role": "system", "content": (
                f"{system_prompt}\n\n"
                "Sekarang kamu lagi bantu belajar. Jelaskan topik berikut dengan cara yang mudah dipahami, "
                "kayak guru yang asik dan sabar. Pakai analogi sederhana kalau perlu. "
                "Tetap pakai gaya bahasa kamu yang casual dan Gen Z, tapi pastikan penjelasannya akurat dan lengkap. "
                "Struktur penjelasan: pengertian singkat -> cara kerja/detail -> contoh nyata. "
                "Boleh pakai bullet points kalau membantu."
            )},
            {"role": "user", "content": f"Jelasin dong: {topic}"}
        ]
        try:
            reply = await ask_groq(explain_messages)
        except Exception as e:
            reply = f"aduh gagal jelasin: {str(e)}"
        await save_message(chat_id, "user", f"/explain {topic}")
        await save_message(chat_id, "assistant", reply)
        await send_message(chat_id, reply, reply_to=message_id)
        return {"ok": True}

    # /essay <prompt>
    if text.startswith("/essay "):
        prompt_text = text[len("/essay "):].strip()
        if not prompt_text:
            await send_message(chat_id, "tulis topik essay-nya! contoh: `/essay dampak media sosial terhadap remaja`")
            return {"ok": True}
        await send_message(chat_id, sanitize(f"oke aku buatin outline essay-nya dulu~"))
        essay_messages = [
            {"role": "system", "content": (
                f"{system_prompt}\n\n"
                "Sekarang kamu lagi bantu nulis essay. Berikan outline essay yang terstruktur dengan baik, "
                "lalu tulis paragraf pembuka yang kuat. Format:\n"
                "**Judul:** (saran judul)\n"
                "**Outline:**\n"
                "I. Pendahuluan\nII. [poin utama 1]\nIII. [poin utama 2]\nIV. [poin utama 3]\nV. Kesimpulan\n\n"
                "**Paragraf Pembuka:**\n(tulis paragraf pembuka yang menarik)\n\n"
                "Tetap pakai gaya kamu yang helpful tapi casual di luar bagian essay-nya."
            )},
            {"role": "user", "content": f"Tolong bantu essay tentang: {prompt_text}"}
        ]
        try:
            reply = await ask_groq(essay_messages)
        except Exception as e:
            reply = f"aduh gagal bikin outline: {str(e)}"
        await save_message(chat_id, "user", f"/essay {prompt_text}")
        await save_message(chat_id, "assistant", reply)
        await send_message(chat_id, reply, reply_to=message_id)
        return {"ok": True}

    asyncio.create_task(maybe_shift_mood(text or caption))
    full_system, mood, _ = await build_system_prompt(chat_id)
    history = await load_history(chat_id)

    # --- Photo message ---
    if photos:
        file_id = photos[-1]["file_id"]
        img_b64 = await get_photo_base64(file_id)
        user_prompt = caption if caption else "apa yang ada di foto ini?"
        labeled_prompt = f"[from user_id={user_id} @{username}]: {user_prompt}"
        if img_b64:
            vision_messages = [
                {"role": "system", "content": full_system},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": labeled_prompt}
                ]}
            ]
            try:
                reply = await ask_groq_vision(vision_messages)
            except Exception as e:
                reply = f"aduh gagal baca fotonya: {str(e)}"
        else:
            reply = "gagal download fotonya pa/ma, coba kirim lagi~"
        await save_message(chat_id, "user", labeled_prompt)
        await save_message(chat_id, "assistant", reply)
        asyncio.create_task(extract_facts(chat_id, user_prompt, reply))
        if random.random() < 0.15 and KLIPY_API_KEY:
            gif_url = await get_klipy_gif(MOOD_GIF_KEYWORDS.get(mood, "anime cute"))
            if gif_url:
                await send_gif(chat_id, gif_url)
        await send_message(chat_id, reply, reply_to=message_id)
        return {"ok": True}

    # --- Text message ---
    labeled = f"[from user_id={user_id} @{username}]: {text}"

    # Vent mode — override system prompt to be extra supportive
    if is_venting(text):
        vent_system = (
            f"{system_prompt}\n\n"
            "PENTING: Pengguna lagi stress atau overwhelmed. Sekarang masuk mode supportif. "
            "Dengerin dulu, jangan langsung kasih solusi. Tunjukkin empati yang genuine. "
            "Validasi perasaan mereka. Bicara hangat kayak sahabat yang beneran peduli. "
            "Kalau mereka mahasiswa/pelajar yang stress soal tugas atau ujian, "
            "ingetin mereka bahwa ini normal dan mereka bisa melewatinya. "
            "Tawarkan bantuan konkret di akhir (misal: mau aku bantu breakdown tugasnya?)."
        )
        messages = [{"role": "system", "content": vent_system}] + history
        messages.append({"role": "user", "content": labeled})
    else:
        # Search detection
        search_keywords = [
            "search", "look up", "cari", "cariin", "carikan", "tolong cari",
            "siapa", "apa itu", "what is", "who is", "latest", "news", "current",
            "terbaru", "sekarang", "gimana", "berapa", "kapan", "dimana"
        ]
        needs_search = any(kw in text.lower() for kw in search_keywords)

        context = ""
        if needs_search:
            if user_id == DAD_ID:
                wait_msg = random.choice(["sebentar ya pa! lagi nyariin dulu", "bentar pa, adek googling dulu~", "oke pa, tunggu sebentar ya!"])
            elif user_id == MOM_ID:
                wait_msg = random.choice(["sebentar ya ma! lagi nyariin dulu", "bentar ma, adek googling dulu~", "oke ma, tunggu ya!"])
            else:
                wait_msg = random.choice(["sebentar! lagi nyariin dulu", "bentar, googling dulu~", "tunggu sebentar ya!"])
            await send_message(chat_id, sanitize(wait_msg))
            asyncio.create_task(send_chat_action(chat_id, "typing"))
            search_result = await web_search(text)
            if search_result and search_result != "No results found.":
                context = f"\n\n[Hasil pencarian web]: {search_result}"

        messages = [{"role": "system", "content": full_system}] + history
        messages.append({"role": "user", "content": labeled + context})

    try:
        reply = await ask_groq(messages)
    except Exception as e:
        reply = f"something broke lol: {str(e)}"

    await save_message(chat_id, "user", labeled)
    await save_message(chat_id, "assistant", reply)
    asyncio.create_task(extract_facts(chat_id, text, reply))

    # Check for GIF tag in reply
    gif_sent = False
    gif_match = re.search(r'\[GIF:([^\]]+)\]', reply)
    if gif_match and KLIPY_API_KEY:
        gif_keyword = gif_match.group(1).strip()
        clean_reply = re.sub(r'\s*\[GIF:[^\]]+\]', '', reply).strip()
        gif_url = await get_klipy_gif(gif_keyword)
        if gif_url:
            await send_message(chat_id, clean_reply, reply_to=message_id)
            await send_gif(chat_id, gif_url)
            gif_sent = True
        else:
            reply = clean_reply

    if not gif_sent:
        if random.random() < 0.15 and KLIPY_API_KEY:
            gif_url = await get_klipy_gif(MOOD_GIF_KEYWORDS.get(mood, "anime cute"))
            if gif_url:
                await send_gif(chat_id, gif_url)
        await send_message(chat_id, reply, reply_to=message_id)

    return {"ok": True}
