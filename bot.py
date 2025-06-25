import os
import asyncio
import logging # <<< เพิ่ม logging
from dotenv import load_dotenv
import discord
from discord.ext import commands
import db_manager

# --- ตั้งค่า Logging ---
# ตั้งค่าพื้นฐานเพื่อให้เห็น log จาก Cog อื่นๆ ด้วย
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
log = logging.getLogger(__name__) # Logger สำหรับ bot.py

# Load environment variables from .env file
load_dotenv()

# Get the bot token from the environment variables
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') # ยังคงเช็คเพื่อให้แน่ใจว่ามีสำหรับ Image Cog

if not BOT_TOKEN:
    log.critical("!!! ข้อผิดพลาด: ไม่พบ DISCORD_BOT_TOKEN ใน .env ไฟล์")
    exit()
if not GEMINI_API_KEY:
     log.warning("!!! คำเตือน: ไม่พบ GEMINI_API_KEY ใน .env ไฟล์, Image Analyzer Cog อาจไม่ทำงาน")


# --- ตั้งค่า Intents ---
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True           # <<< สำคัญสำหรับ voice logging และ bidding เพื่อดึงข้อมูล member
intents.voice_states = True      # <<< สำคัญสำหรับ voice logging
intents.message_content = True   # <<< สำคัญสำหรับ image analyzer (และอาจจะคำสั่งบางอย่าง)
intents.dm_messages = True       # <<< สำคัญสำหรับ image analyzer ใน DM

# --- สร้าง Bot Instance ---
bot = commands.Bot(command_prefix="!", intents=intents)

# --- รายการ Cogs ที่จะโหลด ---
# ใส่ชื่อไฟล์ cog (ไม่ต้องมี .py)
INITIAL_EXTENSIONS = [
    'image_analyzer_cog',  # Cog วิเคราะห์รูปภาพ
    'voice_logging_cog',   # Cog สำหรับ Voice Log ที่สร้างใหม่
    # 'bidding_cog',         # <<< คอมเมนต์ออกเพื่อ disable Bidding System ชั่วคราว
    'tts_scheduler_cog',
    'bidrune_cog',  # Cog สำหรับระบบประมูล Rune
]

# --- ฟังก์ชันหลักสำหรับ Setup และ รันบอท ---
async def main():
    # --- เริ่มต้น Connection Pool ---
    try:
        log.info("--- กำลัง initialize PostgreSQL connection pool ---")
        await db_manager.get_pool() # เรียกเพื่อให้ pool ถูกสร้างและเก็บไว้ใน db_manager
        log.info("✅ PostgreSQL connection pool initialized.")
    except Exception as e:
        log.critical(f"❌ ไม่สามารถ initialize PostgreSQL connection pool: {e}. บอทอาจทำงานไม่ถูกต้อง.")
        # คุณอาจจะต้องการให้บอทหยุดทำงานถ้าเชื่อมต่อ DB ไม่ได้
        # return
    async with bot: # ใช้ async with bot เพื่อจัดการการเชื่อมต่อและ cleanup
        # โหลด Cogs ทั้งหมด
        log.info("--- กำลังโหลด Extensions ---")
        for extension in INITIAL_EXTENSIONS:
            try:
                await bot.load_extension(extension)
                log.info(f"✅ โหลด Extension '{extension}' สำเร็จ")
            except commands.ExtensionNotFound:
                log.error(f"❌ ไม่พบ Extension '{extension}'")
            except commands.ExtensionAlreadyLoaded:
                log.warning(f"⚠️ Extension '{extension}' ถูกโหลดไปแล้ว")
            except commands.NoEntryPointError:
                 log.error(f"❌ Extension '{extension}' ไม่มีฟังก์ชัน setup()")
            except Exception as e:
                log.exception(f"❌ เกิดข้อผิดพลาดในการโหลด Extension '{extension}': {e}") # ใช้ exception logger
                # คุณอาจจะอยากให้บอทหยุดทำงานถ้า Cog สำคัญโหลดไม่สำเร็จ
                # raise e

        log.info("--- Extensions ทั้งหมดถูกประมวลผล ---")

        # ไม่ต้องเรียก setup_bidding_system หรือ setup_voice_logging ที่นี่แล้ว

        # รันบอท
        try:
            log.info("--- กำลังเริ่มการทำงานของบอท ---")
            await bot.start(BOT_TOKEN)
        except discord.LoginFailure:
            log.critical("!!! ข้อผิดพลาด: Discord Token ไม่ถูกต้อง โปรดตรวจสอบในไฟล์ .env")
        except Exception as e:
            log.exception(f"!!! เกิดข้อผิดพลาดร้ายแรงในการรันบอท: {e}")
        finally:
            # --- ปิด Connection Pool เมื่อบอทหยุดทำงาน ---
            log.info("--- กำลังปิด PostgreSQL connection pool ---")
            await db_manager.close_pool()
            log.info("✅ PostgreSQL connection pool closed.")

# --- Event on_ready ---
@bot.event
async def on_ready():
    # on_ready อาจถูกเรียกหลายครั้ง ไม่ควรใส่ logic การ setup หนักๆ ที่นี่
    # การโหลด Cog และ add_view ใน on_ready ของ Cog นั้นเหมาะสมกว่า
    print("-" * 30)
    log.info(f'Bot is ready.')
    log.info(f'Logged in as: {bot.user.name} (ID: {bot.user.id})')
    log.info(f'Discord.py Version: {discord.__version__}')
    log.info(f'Connected to {len(bot.guilds)} servers.')
    # แสดงสถานะ "Watching" หรือ "Listening" (Optional)
    try:
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="the logs & bids"))
        log.info("ตั้งค่า activity ของบอทสำเร็จ")
    except Exception as e:
        log.warning(f"ไม่สามารถตั้งค่า activity ของบอทได้: {e}")

    print("-" * 30)
    log.info("บอทพร้อมทำงาน!")


# --- รัน main function ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("--- กำลังปิดบอท (ได้รับ KeyboardInterrupt) ---")
    except Exception as e:
        # จับข้อผิดพลาดที่อาจเกิดขึ้นนอก main loop (ไม่น่าเกิด แต่ใส่ไว้กันเหนียว)
        log.exception(f"!!! เกิดข้อผิดพลาดร้ายแรงนอก main asyncio loop: {e}")