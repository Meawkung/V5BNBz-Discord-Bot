# voice_logging_cog.py
import discord
from discord.ext import commands
import os
import time
from datetime import datetime, timezone, timedelta
import logging

# ตั้งค่า logger สำหรับ Cog นี้
log = logging.getLogger(__name__)

# --- ค่าคงที่ ---
# ย้าย ID ต่างๆ มาไว้ตรงนี้เพื่อให้แก้ไขง่าย
MONITORED_VOICE_CHANNEL_IDS = [1250561983305224222, 1135925419753869312, 1251996192699711599] # #GLMain, #GLSub, Overun
NOTIFICATION_TEXT_CHANNEL_IDS = [1264562975851810847] # Channel สำหรับแจ้งเตือน

# --- ฟังก์ชันช่วยเหลือ (Helper Functions) ---
# เก็บฟังก์ชันเหล่านี้ไว้ที่ระดับบนสุดของไฟล์ หรือจะย้ายเป็น private method ใน class ก็ได้ (_ชื่อฟังก์ชัน)

def _get_unix_timestamp():
    """Return current Unix epoch timestamp."""
    return int(time.time())

def _get_human_readable_timestamp(unix_timestamp):
    """Convert Unix epoch timestamp to human-readable format adjusted to GMT+7."""
    gmt7 = timezone(timedelta(hours=7))
    dt = datetime.fromtimestamp(unix_timestamp, gmt7)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def _get_current_date():
    """Return current date as a string."""
    # ใช้เวลา GMT+7 สำหรับชื่อโฟลเดอร์/ไฟล์ เพื่อให้ตรงกับ timestamp
    gmt7 = timezone(timedelta(hours=7))
    return datetime.now(gmt7).strftime('%Y-%m-%d')

def _get_log_folder(channel_name):
    """Return the path to the log folder, creating it if it doesn't exist."""
    # ใช้ชื่อ channel ที่ปลอดภัยสำหรับชื่อโฟลเดอร์ (แทนที่อักขระพิเศษ)
    safe_channel_name = "".join(c if c.isalnum() else "_" for c in channel_name)
    log_folder = os.path.join('logged', safe_channel_name, _get_current_date())
    try:
        if not os.path.exists(log_folder):
            os.makedirs(log_folder)
            log.info(f"สร้างโฟลเดอร์ log: {log_folder}")
    except OSError as e:
        log.error(f"ไม่สามารถสร้างโฟลเดอร์ log '{log_folder}': {e}")
        return None # คืนค่า None ถ้าสร้างไม่ได้
    return log_folder

def _get_log_filename(channel_name, log_type):
    """Generate log file name based on the current date and log type."""
    log_folder = _get_log_folder(channel_name)
    if log_folder is None:
        return None # ส่งต่อค่า None ถ้าสร้างโฟลเดอร์ไม่ได้
    safe_channel_name = "".join(c if c.isalnum() else "_" for c in channel_name)
    return os.path.join(log_folder, f'{log_type}_log_{safe_channel_name}_{_get_current_date()}.txt')

def _get_combined_log_filename(channel_name):
    """Generate combined log file name based on the current date."""
    log_folder = _get_log_folder(channel_name)
    if log_folder is None:
        return None
    safe_channel_name = "".join(c if c.isalnum() else "_" for c in channel_name)
    return os.path.join(log_folder, f'combined_log_{safe_channel_name}_{_get_current_date()}.txt')

def _write_log(filename, message):
    """เขียนข้อความลงไฟล์ log อย่างปลอดภัย"""
    if filename is None:
        log.error("ไม่สามารถเขียน log ได้เนื่องจาก filename เป็น None")
        return
    try:
        with open(filename, 'a', encoding='utf-8') as f:
            f.write(message + '\n')
    except IOError as e:
        log.error(f"ไม่สามารถเขียนไฟล์ log '{filename}': {e}")
    except Exception as e:
        log.exception(f"เกิดข้อผิดพลาดที่ไม่คาดคิดขณะเขียน log '{filename}': {e}")

# --- คลาส Cog ---
class VoiceLoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.monitored_channels = set(MONITORED_VOICE_CHANNEL_IDS) # ใช้ set เพื่อการค้นหาที่เร็วขึ้น
        self.notification_channels = NOTIFICATION_TEXT_CHANNEL_IDS
        log.info(f"VoiceLoggingCog: โหลดสำเร็จ ตรวจสอบช่องเสียง: {self.monitored_channels}")
        log.info(f"VoiceLoggingCog: แจ้งเตือนไปยังช่องข้อความ: {self.notification_channels}")

    async def send_notification_embed(self, embed):
        """ส่ง Embed ไปยังช่องทางแจ้งเตือนทั้งหมด"""
        for channel_id in self.notification_channels:
            channel = self.bot.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    log.warning(f"ไม่มีสิทธิ์ส่งข้อความในช่องแจ้งเตือน: {channel.name} ({channel_id})")
                except discord.HTTPException as e:
                    log.error(f"เกิดข้อผิดพลาด HTTP ขณะส่งการแจ้งเตือนไปยัง {channel.name} ({channel_id}): {e}")
            elif not channel:
                log.warning(f"ไม่พบช่องทางแจ้งเตือน ID: {channel_id}")
            else:
                 log.warning(f"ID ช่องทางแจ้งเตือน {channel_id} ไม่ใช่ TextChannel: {type(channel)}")


    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """ทำงานเมื่อสถานะเสียงของสมาชิกเปลี่ยนแปลง"""
        # ไม่สนใจถ้าไม่มีการย้ายช่อง หรือถ้า member เป็นบอท
        if before.channel == after.channel or member.bot:
            return

        unix_timestamp = _get_unix_timestamp()
        human_readable_timestamp = _get_human_readable_timestamp(unix_timestamp)

        nickname = member.nick if member.nick else member.name
        display_name = f"{nickname} ({member.name})" if member.nick and member.nick != member.name else member.name

        log_message = None
        embed = None
        channel_involved = None # ช่องที่ใช้สร้างชื่อไฟล์ log

        # --- ตรวจสอบการเข้าร่วมช่องที่ตรวจสอบ ---
        if after.channel is not None and after.channel.id in self.monitored_channels:
            channel_involved = after.channel
            if before.channel is None: # เข้าร่วม Discord ครั้งแรก หรือเข้ามาจากสถานะไม่ได้เชื่อมต่อ
                log_message = f'{human_readable_timestamp} 👋 {display_name} joined {after.channel.name}'
                title = "Member Joined Voice Channel"
                description = f"👋 {member.mention} joined **{after.channel.name}**"
                embed_color = discord.Color.green()
                footer_text = "Joined"
            elif before.channel.id not in self.monitored_channels: # ย้ายมาจากช่องที่ไม่ถูกตรวจสอบ
                log_message = f'{human_readable_timestamp} ➡️ {display_name} moved into {after.channel.name} (from {before.channel.name})'
                title = "Member Entered Monitored Channel"
                description = f"➡️ {member.mention} entered **{after.channel.name}** (from {before.channel.name})"
                embed_color = discord.Color.blue() # สีฟ้าสำหรับการเข้ามา
                footer_text = "Entered"
            else: # ย้ายระหว่างช่องที่ถูกตรวจสอบ
                log_message = f'✈️ {human_readable_timestamp} {display_name} moved from {before.channel.name} to {after.channel.name}'
                title = "Member Moved Between Monitored Channels"
                description = f"✈️ {member.mention} moved from **{before.channel.name}** to **{after.channel.name}**"
                embed_color = discord.Color.purple() # สีม่วงสำหรับการย้ายภายใน
                footer_text = "Moved (Internal)"

        # --- ตรวจสอบการออกจากช่องที่ตรวจสอบ ---
        elif before.channel is not None and before.channel.id in self.monitored_channels:
            channel_involved = before.channel
            if after.channel is None: # ออกจาก Discord หรือตัดการเชื่อมต่อ
                log_message = f'{human_readable_timestamp} 🚪 {display_name} left {before.channel.name}'
                title = "Member Left Voice Channel"
                description = f"🚪 {member.mention} left **{before.channel.name}**"
                embed_color = discord.Color.red()
                footer_text = "Left"
            elif after.channel.id not in self.monitored_channels: # ย้ายไปยังช่องที่ไม่ถูกตรวจสอบ
                 log_message = f'{human_readable_timestamp} ⬅️ {display_name} moved out of {before.channel.name} (to {after.channel.name})'
                 title = "Member Left Monitored Channel"
                 description = f"⬅️ {member.mention} left **{before.channel.name}** (to {after.channel.name})"
                 embed_color = discord.Color.orange() # สีส้มสำหรับการออกไป
                 footer_text = "Exited"
            # กรณี ย้ายระหว่างช่องที่ตรวจสอบ ถูกจัดการในเงื่อนไขแรกแล้ว

        # --- สร้าง Log และ Embed ถ้ามีการเปลี่ยนแปลงที่เกี่ยวข้อง ---
        if log_message and channel_involved:
            log.info(log_message) # ใช้ logger แทน print

            # เขียน Log (แยก join/leave ตามชื่อไฟล์เดิม แต่ใช้ log_message เดียวกัน)
            log_type = 'join' if after.channel == channel_involved else 'leave'
            individual_log_filename = _get_log_filename(channel_involved.name, log_type)
            _write_log(individual_log_filename, log_message)

            # เขียน Log รวม
            combined_log_filename = _get_combined_log_filename(channel_involved.name)
            _write_log(combined_log_filename, log_message)

            # สร้าง Embed
            embed = discord.Embed(
                title=title,
                description=description,
                color=embed_color,
                timestamp=datetime.fromtimestamp(unix_timestamp, tz=timezone.utc) # ใช้ UTC สำหรับ timestamp ใน embed
            )
            embed.set_author(
                name=display_name,
                icon_url=member.display_avatar.url # ใช้ display_avatar เพื่อรองรับ avatar ประจำ server
            )
            embed.set_footer(text=f"{footer_text} • Channel ID: {channel_involved.id}") # เพิ่ม ID ช่องใน footer
            embed.add_field(name="User ID", value=member.id, inline=False)

            # ส่ง Embed แจ้งเตือน
            await self.send_notification_embed(embed)


# --- ฟังก์ชัน Setup สำหรับ Cog ---
# ต้องเป็น async function ชื่อ setup และรับ bot instance
async def setup(bot: commands.Bot):
    """Loads the VoiceLoggingCog."""
    try:
        await bot.add_cog(VoiceLoggingCog(bot))
        log.info("VoiceLoggingCog: Setup complete, Cog added to bot.")
    except Exception as e:
        log.exception("VoiceLoggingCog: Failed to load Cog.") # ใช้ log.exception เพื่อดู traceback
        # อาจจะ raise ซ้ำเพื่อให้ bot หลักรู้ว่าโหลดไม่สำเร็จ
        # raise e