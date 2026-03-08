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

DAD_ID = 8284345086
MOM_ID = 5484371031
GROUP_ID = -1003837472701

TZ = ZoneInfo("Asia/Jakarta")  # GMT+7

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

VENT_KEYWORDS = [
    "stress", "stres", "overwhelmed", "kewalahan", "lelah banget", "cape banget",
    "mau nangis", "pengen nangis", "nangis", "sedih banget", "desperate",
    "nggak sanggup", "gabisa", "ga bisa", "nyerah", "give up", "burnout",
    "anxious", "anxiety", "cemas", "panik", "takut banget", "susah nafas",
    "pusing banget", "beban banget", "nggak kuat", "ga kuat", "mau mati",
    "capek hidup", "ujian besok", "deadline besok", "belum belajar", "belum ngerjain",
]

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
                remind_at TIMESTAMPTZ NOT NULL,
                text TEXT NOT NULL,
                sent BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
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

async def load_memories(chat_id: int) -> list[str]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT fact FROM memories WHERE chat_id=$1 ORDER BY id DESC LIMIT 20",
            chat_id
        )
    return [r["fact"] for r in rows]

async def save_memory(chat_id: int, fact: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO memories (chat_id, fact) VALUES ($1, $2)",
            chat_id, fact
        )

async def clear_history(chat_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_history WHERE chat_id=$1", chat_id)

# --- Reminders ---
async def save_reminder(chat_id: int, remind_at: datetime, text: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reminders (chat_id, remind_at, text) VALUES ($1, $2, $3)",
            chat_id, remind_at, text
        )

async def get_pending_reminders() -> list:
    now_utc = datetime.now(timezone.utc)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, chat_id, remind_at, text FROM reminders WHERE sent=FALSE AND remind_at <= $1",
            now_utc
        )
    return rows

async def mark_reminder_sent(reminder_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE reminders SET sent=TRUE WHERE id=$1", reminder_id)

async def list_reminders(chat_id: int) -> list:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, remind_at, text FROM reminders WHERE chat_id=$1 AND sent=FALSE ORDER BY remind_at ASC",
            chat_id
        )
    return rows

def parse_remind_datetime(args: str):
    now_local = datetime.now(TZ)
    if "|" not in args:
        return None, "Format salah. Contoh: /remind besok 08:00 | tugas matematika"
    dt_part, text_part = args.split("|", 1)
    dt_part = dt_part.strip()
    text_part = text_part.strip()
    if not text_part:
        return None, "Teks pengingat nggak boleh kosong ya."
    dt_lower = dt_part.lower()
    try:
        m = re.match(r"besok\s+(\d{1,2}):(\d{2})", dt_lower)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            target = now_local.replace(hour=h, minute=mi, second=0, microsecond=0) + timedelta(days=1)
            return target.astimezone(timezone.utc), text_part
        m = re.match(r"lusa\s+(\d{1,2}):(\d{2})", dt_lower)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            target = now_local.replace(hour=h, minute=mi, second=0, microsecond=0) + timedelta(days=2)
            return target.astimezone(timezone.utc), text_part
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})", dt_part)
        if m:
            d, mo, yr, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
            target = datetime(yr, mo, d, h, mi, 0, tzinfo=TZ)
            return target.astimezone(timezone.utc), text_part
        m = re.match(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", dt_part)
        if m:
            d, mo, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            target = datetime(now_local.year, mo, d, h, mi, 0, tzinfo=TZ)
            if target <= now_local:
                target = target.replace(year=now_local.year + 1)
            return target.astimezone(timezone.utc), text_part
        m = re.match(r"(\d{1,2}):(\d{2})", dt_part)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            target = now_local.replace(hour=h, minute=mi, second=0, microsecond=0)
            if target <= now_local:
                target += timedelta(days=1)
            return target.astimezone(timezone.utc), text_part
        return None, f"Format waktu '{dt_part}' nggak dikenali. Coba: besok 08:00, 10/03 14:00, atau 09:30"
    except ValueError as e:
        return None, f"Tanggal/waktu nggak valid: {e}"

async def reminder_checker():
    await asyncio.sleep(10)
    while True:
        try:
            due = await get_pending_reminders()
            for row in due:
                remind_at_local = row["remind_at"].astimezone(TZ)
                time_str = remind_at_local.strftime("%d/%m/%Y %H:%M")
                msg = sanitize(f"hey! ini pengingat kamu:\n\n{row['text']}\n\n(dijadwalkan {time_str} WIB)")
                await send_message(row["chat_id"], msg)
                await mark_reminder_sent(row["id"])
        except Exception as e:
            print(f"Reminder checker error: {e}")
        await asyncio.sleep(30)

def sanitize(text: str) -> str:
    return text.encode("utf-16", "surrogatepass").decode("utf-16")

async def send_message(chat_id: int, text: str, reply_to: int = None):
    payload = {"chat_id": chat_id, "text": sanitize(text)}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
    await save_sent_message(chat_id, text)

async def send_gif(chat_id: int, gif_url: str):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendAnimation", json={
            "chat_id": chat_id,
            "animation": gif_url
        })

async def send_chat_action(chat_id: int, action: str = "typing"):
    async with httpx.AsyncClient() as client:
        await client.post(f"{TELEGRAM_API}/sendChatAction",
            json={"chat_id": chat_id, "action": action})

async def human_delay(chat_id: int):
    delay = random.uniform(3, 6)
    await send_chat_action(chat_id, "typing")
    await asyncio.sleep(delay / 2)
    await send_chat_action(chat_id, "typing")
    await asyncio.sleep(delay / 2)

async def get_klipy_gif(keyword: str):
    if not KLIPY_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.klipy.com/api/v1/{KLIPY_API_KEY}/gifs/search",
                params={"q": keyword, "per_page": 10}
            )
            data = resp.json()
            results = data.get("data", {}).get("data", [])
            if not results:
                return None
            chosen = random.choice(results)
            files = chosen.get("files", {})
            for fmt in ["gif", "mp4", "webp"]:
                if fmt in files and files[fmt].get("url"):
                    return files[fmt]["url"]
            return None
    except Exception:
        return None

async def ask_groq(messages: list) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": TEXT_MODEL, "messages": messages, "max_tokens": 1024}
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

async def ask_groq_vision(messages: list) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": VISION_MODEL, "messages": messages, "max_tokens": 1024}
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

async def get_photo_base64(file_id: str):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
            file_path = r.json()["result"]["file_path"]
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
            img_resp = await client.get(file_url)
            return base64.b64encode(img_resp.content).decode()
    except Exception:
        return None

async def extract_facts(chat_id: int, user_text: str, assistant_reply: str):
    extraction_prompt = [
        {
            "role": "system",
            "content": (
                "Kamu adalah sistem ekstraksi memori. Tugasmu: dari percakapan ini, "
                "ekstrak fakta-fakta penting yang perlu diingat jangka panjang. "
                "Contoh: nama orang, ulang tahun, preferensi, kebiasaan, kejadian penting, goals. "
                "Jawab HANYA dengan daftar fakta singkat, satu per baris, format: 'FAKTA: ...' "
                "Kalau tidak ada fakta penting, jawab: 'TIDAK ADA'"
            )
        },
        {"role": "user", "content": f"User berkata: {user_text}\nBot menjawab: {assistant_reply}"}
    ]
    try:
        result = await ask_groq(extraction_prompt)
        if "TIDAK ADA" in result:
            return
        lines = [l.strip() for l in result.splitlines() if l.strip().startswith("FAKTA:")]
        for line in lines:
            fact = line.replace("FAKTA:", "").strip()
            if fact:
                await save_memory(chat_id, fact)
    except Exception:
        pass

async def web_search(query: str) -> str:
    if not SERPER_API_KEY:
        return "Search unavailable."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "gl": "id", "hl": "id", "num": 5}
            )
            data = resp.json()
        parts = []
        if data.get("answerBox"):
            ab = data["answerBox"]
            parts.append(ab.get("answer") or ab.get("snippet") or "")
        if data.get("knowledgeGraph"):
            kg = data["knowledgeGraph"]
            desc = kg.get("description", "")
            if desc:
                parts.append(desc)
        for r in data.get("organic", [])[:3]:
            snippet = r.get("snippet", "")
            if snippet:
                parts.append(f"{r.get('title','')}: {snippet}")
        return "\n".join(p for p in parts if p) or "No results found."
    except Exception as e:
        return f"Search error: {e}"

async def build_system_prompt(chat_id: int):
    mood = await get_mood()
    memories = await load_memories(chat_id)
    recent_sent = await get_recent_sent(chat_id, 15)
    full_system = system_prompt
    full_system += f"\n\nMood kamu saat ini: {mood}. {MOOD_DESCRIPTIONS[mood]}"
    hour = datetime.now(TZ).hour
    if 5 <= hour < 10:
        time_vibe = "Sekarang pagi hari. Kamu baru bangun, masih agak ngantuk tapi mulai semangat."
    elif 10 <= hour < 14:
        time_vibe = "Sekarang siang hari. Kamu lagi aktif dan fokus. Energi penuh."
    elif 14 <= hour < 17:
        time_vibe = "Sekarang sore jam ngantuk. Kamu agak distracted, jawaban singkat."
    elif 17 <= hour < 21:
        time_vibe = "Sekarang sore-malam. Kamu hangat dan cozy."
    elif 21 <= hour < 23:
        time_vibe = "Sekarang malam. Kamu mulai malas gerak, jawaban slow dan mellow."
    else:
        time_vibe = "Sekarang tengah malam. Kamu ngantuk banget, jawaban singkat."
    full_system += f"\n\nWaktu sekarang: {time_vibe}"
    if memories:
        mem_block = "\n".join(f"- {m}" for m in memories)
        full_system += f"\n\nMemori jangka panjang yang kamu ingat:\n{mem_block}"
    if recent_sent:
        sent_block = "\n".join(f"- {m}" for m in recent_sent)
        full_system += f"\n\nPesan yang sudah pernah kamu kirim (JANGAN diulang):\n{sent_block}"
    return full_system, mood, recent_sent

async def handle_explain(chat_id: int, topic: str, message_id: int):
    if not topic:
        await send_message(chat_id, "eh mau jelasin apa nih? tulis topiknya dong. contoh: /explain fotosintesis")
        return
    await send_chat_action(chat_id, "typing")
    prompt = [
        {
            "role": "system",
            "content": (
                "Kamu adalah guru yang sabar dan seru. Jelaskan topik dengan cara mudah dipahami, "
                "pakai analogi sederhana, bahasa santai tapi akurat. "
                "Struktur: 1) penjelasan singkat 2-3 kalimat, 2) analogi atau contoh nyata, 3) poin-poin kunci. "
                "Bahasa Indonesia kasual. Jangan terlalu panjang."
            )
        },
        {"role": "user", "content": f"Jelaskan: {topic}"}
    ]
    try:
        reply = await ask_groq(prompt)
        await send_message(chat_id, reply, reply_to=message_id)
    except Exception as e:
        await send_message(chat_id, f"aduh gagal njelasin: {e}", reply_to=message_id)

async def handle_essay(chat_id: int, topic: str, message_id: int):
    if not topic:
        await send_message(chat_id, "topiknya apa? contoh: /essay dampak media sosial terhadap remaja")
        return
    await send_chat_action(chat_id, "typing")
    prompt = [
        {
            "role": "system",
            "content": (
                "Kamu adalah asisten menulis esai yang profesional. "
                "Buat outline esai yang solid plus paragraf pembuka yang menarik. "
                "Format: Judul -> Thesis statement -> Outline (3-4 poin utama dengan sub-poin) -> Paragraf pembuka. "
                "Bahasa Indonesia yang baik dan akademis tapi tetap mengalir."
            )
        },
        {"role": "user", "content": f"Buat outline esai tentang: {topic}"}
    ]
    try:
        reply = await ask_groq(prompt)
        await send_message(chat_id, reply, reply_to=message_id)
    except Exception as e:
        await send_message(chat_id, f"gagal bikin outline: {e}", reply_to=message_id)

def is_venting(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in VENT_KEYWORDS)

async def handle_vent(chat_id: int, user_text: str, message_id: int):
    prompt = [
        {
            "role": "system",
            "content": (
                "Kamu adalah sahabat yang sangat supportive dan empati. "
                "Seseorang sedang curhat atau merasa overwhelmed. "
                "Respons kamu: hangat, validating, tidak menghakimi, tidak langsung kasih solusi. "
                "Cukup dengarkan, validasi perasaan mereka, tunjukkan kamu peduli. "
                "Akhiri dengan satu pertanyaan open-ended yang gentle. "
                "Bahasa Indonesia yang lembut dan natural."
            )
        },
        {"role": "user", "content": user_text}
    ]
    try:
        reply = await ask_groq(prompt)
        await send_message(chat_id, reply, reply_to=message_id)
    except Exception:
        await send_message(chat_id, "eh aku dengerin kok, cerita aja ya", reply_to=message_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(reminder_checker())
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{TELEGRAM_API}/setWebhook",
            json={"url": WEBHOOK_URL}
        )
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

@app.post("/proactive/dad")
async def proactive_dad():
    await send_proactive_message(DAD_ID, "papa")
    return {"ok": True}

@app.post("/proactive/mom")
async def proactive_mom():
    await send_proactive_message(MOM_ID, "mama")
    return {"ok": True}

async def send_proactive_message(chat_id: int, target_name: str):
    hour = datetime.now(TZ).hour
    mood = await get_mood()
    memories = await load_memories(chat_id)
    recent_sent = await get_recent_sent(chat_id, 20)
    if 5 <= hour < 10:
        time_context = "pagi hari"
        time_prompt = f"Kirim pesan selamat pagi yang hangat ke {target_name}."
    elif 10 <= hour < 14:
        time_context = "siang hari"
        time_prompt = f"Kirim pesan siang yang ceria ke {target_name}, tanya kabar atau makan siang."
    elif 14 <= hour < 18:
        time_context = "sore hari"
        time_prompt = f"Kirim pesan sore yang santai ke {target_name}."
    elif 18 <= hour < 22:
        time_context = "malam hari"
        time_prompt = f"Kirim pesan malam yang hangat ke {target_name}."
    else:
        time_context = "larut malam"
        time_prompt = f"Kirim pesan singkat ke {target_name}, ingatkan untuk istirahat."
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
                f"Sekarang {time_context}. {time_prompt} "
                f"Pesan harus natural, spontan, sesuai mood. "
                f"Jangan mulai dengan 'Halo' atau 'Hai' saja. "
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
    if text == "/start":
        await send_message(chat_id, "haii haii, aku Cumi Cumi!\n\nbtw aku bisa bantu belajar juga:\n/explain <topik> - aku jelasin\n/essay <topik> - outline esai\n/remind <waktu> | <teks> - set pengingat\n/reminders - lihat pengingat aktif")
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
            facts_text = "\n".join(f"\u2022 {f}" for f in facts)
            await send_message(chat_id, f"ini yang aku inget:\n{facts_text}")
        return {"ok": True}
    if text == "/mood":
        mood = await get_mood()
        await send_message(chat_id, f"mood aku sekarang: {mood} - {MOOD_DESCRIPTIONS[mood]}")
        return {"ok": True}
    if text.startswith("/setmood "):
        new_mood = text.replace("/setmood ", "").strip().lower()
        if new_mood in MOODS:
            await set_mood(new_mood)
            await send_message(chat_id, f"oke mood aku ganti jadi {new_mood}!")
        else:
            await send_message(chat_id, f"mood yang valid: {', '.join(MOODS)}")
        return {"ok": True}
    if text.startswith("/explain"):
        topic = text[len("/explain"):].strip()
        await handle_explain(chat_id, topic, message_id)
        return {"ok": True}
    if text.startswith("/essay"):
        topic = text[len("/essay"):].strip()
        await handle_essay(chat_id, topic, message_id)
        return {"ok": True}
    if text.startswith("/remind"):
        args = text[len("/remind"):].strip()
        remind_at, result_text = parse_remind_datetime(args)
        if remind_at is None:
            await send_message(chat_id, result_text, reply_to=message_id)
        else:
            await save_reminder(chat_id, remind_at, result_text)
            local_time = remind_at.astimezone(TZ).strftime("%d/%m/%Y %H:%M")
            await send_message(chat_id, f"oke catat! aku bakal ingetin kamu:\n\n{result_text}\n\npada {local_time} WIB", reply_to=message_id)
        return {"ok": True}
    if text == "/reminders":
        rows = await list_reminders(chat_id)
        if not rows:
            await send_message(chat_id, "nggak ada pengingat aktif nih~")
        else:
            lines = []
            for r in rows:
                local_time = r["remind_at"].astimezone(TZ).strftime("%d/%m %H:%M")
                lines.append(f"- {local_time} WIB: {r['text']}")
            await send_message(chat_id, "pengingat aktif kamu:\n\n" + "\n".join(lines))
        return {"ok": True}
    asyncio.create_task(maybe_shift_mood(text or caption))
    full_system, mood, _ = await build_system_prompt(chat_id)
    history = await load_history(chat_id)
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
    labeled = f"[from user_id={user_id} @{username}]: {text}"
    if is_venting(text):
        await handle_vent(chat_id, text, message_id)
        await save_message(chat_id, "user", labeled)
        return {"ok": True}
    search_keywords = [
        "search", "look up", "cari", "cariin", "carikan", "tolong cari",
        "siapa", "apa itu", "what is", "who is", "latest", "news", "current",
        "terbaru", "sekarang", "gimana", "berapa", "kapan", "dimana"
    ]
    needs_search = any(kw in text.lower() for kw in search_keywords)
    context = ""
    if needs_search:
        if user_id == DAD_ID:
            wait_msg = random.choice(["sebentar ya pa! lagi nyariin dulu", "bentar pa, adek googling dulu~"])
        elif user_id == MOM_ID:
            wait_msg = random.choice(["sebentar ya ma! lagi nyariin dulu", "bentar ma, adek googling dulu~"])
        else:
            wait_msg = random.choice(["sebentar! lagi nyariin dulu", "bentar, googling dulu~"])
        await send_message(chat_id, wait_msg)
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
