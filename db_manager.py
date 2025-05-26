# db_manager.py
import asyncpg # ใช้ asyncpg สำหรับการทำงานแบบ asynchronous กับ discord.py
import logging
import os
from dotenv import load_dotenv
from datetime import datetime

# โหลด Connection String จาก .env
load_dotenv()
DATABASE_URL = os.getenv("POSTGRES_CONNECTION_STRING")

log = logging.getLogger(__name__)

# --- Global Connection Pool ---
# การสร้าง pool ครั้งเดียวแล้วใช้ซ้ำจะดีกว่าการสร้าง connection ทุกครั้ง
# แต่จะสร้างใน Cog หรือ function หลักของ bot แล้วส่งต่อมาให้ db_manager ก็ได้
# ในที่นี้จะลองสร้าง pool เมื่อมีการเรียกใช้ฟังก์ชันครั้งแรก (แบบง่าย)
_pool = None

async def get_pool():
    """สร้างหรือคืนค่า connection pool ที่มีอยู่"""
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            log.critical("ไม่พบ POSTGRES_CONNECTION_STRING ใน .env ไฟล์!")
            raise ValueError("POSTGRES_CONNECTION_STRING is not set.")
        try:
            log.info("กำลังสร้าง PostgreSQL connection pool...")
            _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
            log.info("PostgreSQL connection pool สร้างสำเร็จแล้ว")
        except Exception as e:
            log.exception("เกิดข้อผิดพลาดในการสร้าง PostgreSQL connection pool")
            raise # ส่งต่อ exception
    return _pool

async def close_pool():
    """ปิด connection pool (ควรเรียกตอนบอทปิดตัว)"""
    global _pool
    if _pool:
        log.info("กำลังปิด PostgreSQL connection pool...")
        await _pool.close()
        _pool = None
        log.info("PostgreSQL connection pool ปิดแล้ว")


async def initialize_database():
    """สร้างตารางที่จำเป็นถ้ายังไม่มี"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # --- ตาราง discord_users ---
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS discord_users (
                    user_id BIGINT PRIMARY KEY,         -- <--- BIGINT
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    avatar_url TEXT,
                    first_seen_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            log.info("ตรวจสอบ/สร้างตาราง 'discord_users' เรียบร้อยแล้ว")

            # --- ตาราง voice_channel_logs ---
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS voice_channel_logs (
                    log_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES discord_users(user_id) ON DELETE CASCADE, -- <--- BIGINT
                    action TEXT NOT NULL,
                    channel_id BIGINT NOT NULL,        -- <--- BIGINT
                    channel_name TEXT NOT NULL,
                    from_channel_id BIGINT,            -- <--- BIGINT (NULLABLE)
                    from_channel_name TEXT,
                    "timestamp" TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)
            log.info("ตรวจสอบ/สร้างตาราง 'voice_channel_logs' เรียบร้อยแล้ว")
            # สร้าง Index เพื่อเพิ่มความเร็วในการ query (Optional but recommended)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_voice_logs_user_id ON voice_channel_logs(user_id);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_voice_logs_timestamp ON voice_channel_logs("timestamp");
            """)
            log.info("ตรวจสอบ/สร้าง Indexes สำหรับ 'voice_channel_logs' เรียบร้อยแล้ว")

async def upsert_discord_user(user_id: int, username: str, display_name: str, avatar_url: str = None):
    """
    เพิ่มผู้ใช้ใหม่หรืออัปเดตข้อมูลผู้ใช้ที่มีอยู่ (ชื่อ, avatar, last_seen_at).
    first_seen_at จะถูกตั้งค่าเมื่อ insert เท่านั้น
    """
    pool = await get_pool()
    current_time = datetime.utcnow() # ใช้ UTC สำหรับ timestamp ใน DB
    async with pool.acquire() as conn:
        # ลองดึง first_seen_at เดิม ถ้ามี
        # เราต้องการเก็บ first_seen_at เดิมไว้ ถ้าผู้ใช้มีอยู่แล้ว
        # และอัปเดตเฉพาะ username, display_name, avatar_url, last_seen_at
        await conn.execute("""
            INSERT INTO discord_users (user_id, username, display_name, avatar_url, first_seen_at, last_seen_at)
            VALUES ($1, $2, $3, $4, $5, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                display_name = EXCLUDED.display_name,
                avatar_url = EXCLUDED.avatar_url,
                last_seen_at = $5;
        """, str(user_id), username, display_name, avatar_url, current_time) # Cast user_id to str
        # log.debug(f"Upserted user: ID={user_id}, Name={display_name}") # อาจจะ log มากไป

async def add_voice_log(user_id: int, action: str, channel_id: int, channel_name: str,
                        from_channel_id: int = None, from_channel_name: str = None):
    """เพิ่ม Log การเข้า-ออกช่องเสียง"""
    pool = await get_pool()
    current_time = datetime.utcnow() # ใช้ UTC
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO voice_channel_logs (user_id, action, channel_id, channel_name, from_channel_id, from_channel_name, "timestamp")
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, str(user_id), action, str(channel_id), channel_name, str(from_channel_id) if from_channel_id is not None else None, from_channel_name, current_time) # Cast user_id, channel_id, from_channel_id to str
        log.info(f"บันทึก Voice Log: User {user_id} action '{action}' on channel '{channel_name}' ({channel_id})")

# ตัวอย่างฟังก์ชันสำหรับดึงข้อมูล (ถ้าต้องการ)
async def get_user_voice_logs(user_id: int, limit: int = 10):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT log_id, action, channel_name, "timestamp"
            FROM voice_channel_logs
            WHERE user_id = $1
            ORDER BY "timestamp" DESC
            LIMIT $2
        """, str(user_id), limit) # Cast user_id to str
        return rows

# --- ฟังก์ชันสำหรับ setup และ teardown pool ใน bot หลัก ---
# async def setup_db_pool():
#     await get_pool() # เรียกเพื่อให้ pool ถูกสร้าง

# async def teardown_db_pool():
#     await close_pool()