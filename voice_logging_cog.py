# voice_logging_cog.py
import discord
from discord.ext import commands
import os
import time
from datetime import datetime, timezone, timedelta
import logging
# --- Import db_manager ---
import db_manager  # ใช้ import db_manager เพราะไฟล์อยู่ใน root เดียวกัน

log = logging.getLogger(__name__)

# --- ค่าคงที่ ---
# ย้าย ID ต่างๆ มาไว้ตรงนี้เพื่อให้แก้ไขง่าย
MONITORED_VOICE_CHANNEL_IDS = [1250561983305224222, 1135925419753869312, 1251996192699711599] # #GLMain, #GLSub, Overun
NOTIFICATION_TEXT_CHANNEL_IDS = [1264562975851810847] # Channel สำหรับแจ้งเตือน

# --- ฟังก์ชันช่วยเหลือสำหรับ Timestamp (ยังใช้สำหรับ Embed) ---
def _get_unix_timestamp_for_embed():
    return int(time.time())

def _get_human_readable_timestamp_for_embed(unix_timestamp):
    gmt7 = timezone(timedelta(hours=7))
    dt = datetime.fromtimestamp(unix_timestamp, gmt7)
    return dt.strftime('%Y-%m-%d %H:%M:%S GMT+7')


# --- คลาส Cog ---
class VoiceLoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.monitored_channels = set(MONITORED_VOICE_CHANNEL_IDS) # ใช้ set เพื่อการค้นหาที่เร็วขึ้น
        self.notification_channels = NOTIFICATION_TEXT_CHANNEL_IDS
        log.info(f"VoiceLoggingCog: โหลดสำเร็จ ตรวจสอบช่องเสียง: {self.monitored_channels}")

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
    async def on_ready(self):
        """
        (Optional) เรียก initialize_database เมื่อ Cog พร้อม
        เพื่อให้แน่ใจว่าตารางถูกสร้างก่อนเริ่มใช้งาน
        """
        try:
            if not hasattr(self.bot, '_db_initialized') or not self.bot._db_initialized:
                log.info("VoiceLoggingCog: กำลัง initialize database...")
                await db_manager.initialize_database()
                self.bot._db_initialized = True
                log.info("VoiceLoggingCog: Database initialized สำเร็จ")
        except Exception as e:
            log.exception("VoiceLoggingCog: เกิดข้อผิดพลาดระหว่าง initialize_database ใน on_ready")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """ทำงานเมื่อสถานะเสียงของสมาชิกเปลี่ยนแปลง"""
        # ไม่สนใจถ้าไม่มีการย้ายช่อง หรือถ้า member เป็นบอท
        if before.channel == after.channel or member.bot:
            return

        # --- ดึงข้อมูลผู้ใช้สำหรับ Database และ Embed ---
        user_id = member.id
        username_for_db = member.name
        display_name_for_db = member.display_name
        avatar_url_for_db = str(member.display_avatar.url) if member.display_avatar else None

        # --- Upsert ข้อมูลผู้ใช้เข้า DB ---
        try:
            await db_manager.upsert_discord_user(
                user_id,
                username_for_db,
                display_name_for_db,
                avatar_url_for_db
            )
        except Exception as e:
            log.exception(f"เกิดข้อผิดพลาดขณะ upsert user ID {user_id} ({display_name_for_db}) เข้า database")

        unix_timestamp_embed = _get_unix_timestamp_for_embed()
        action_type = None
        title = ""
        description = ""
        embed_color = discord.Color.default()
        footer_text = ""
        channel_involved_id = None
        channel_involved_name = None
        from_channel_id_db = None
        from_channel_name_db = None

        # --- ตรวจสอบการเปลี่ยนแปลง ---
        if after.channel is not None and after.channel.id in self.monitored_channels:
            channel_involved_id = after.channel.id
            channel_involved_name = after.channel.name

            if before.channel is None:
                action_type = "JOIN"
                title = "Member Joined Voice Channel"
                description = f"👋 {member.mention} joined **{after.channel.name}**"
                embed_color = discord.Color.green()
                footer_text = "Joined"
            elif before.channel.id not in self.monitored_channels:
                action_type = "MOVE_IN"
                title = "Member Entered Monitored Channel"
                description = f"➡️ {member.mention} entered **{after.channel.name}** (from *{before.channel.name}*)"
                embed_color = discord.Color.blue()
                footer_text = "Entered"
                from_channel_id_db = before.channel.id
                from_channel_name_db = before.channel.name
            else:
                action_type = "MOVE_INTERNAL"
                title = "Member Moved Between Monitored Channels"
                description = f"✈️ {member.mention} moved from **{before.channel.name}** to **{after.channel.name}**"
                embed_color = discord.Color.purple()
                footer_text = "Moved (Internal)"
                from_channel_id_db = before.channel.id
                from_channel_name_db = before.channel.name

        elif before.channel is not None and before.channel.id in self.monitored_channels:
            channel_involved_id = before.channel.id
            channel_involved_name = before.channel.name

            if after.channel is None:
                action_type = "LEAVE"
                title = "Member Left Voice Channel"
                description = f"🚪 {member.mention} left **{before.channel.name}**"
                embed_color = discord.Color.red()
                footer_text = "Left"
            elif after.channel.id not in self.monitored_channels:
                action_type = "MOVE_OUT"
                title = "Member Left Monitored Channel"
                description = f"⬅️ {member.mention} left **{before.channel.name}** (to *{after.channel.name}*)"
                embed_color = discord.Color.orange()
                footer_text = "Exited"

        if action_type and channel_involved_id and channel_involved_name:
            log_message_for_console = f"{action_type}: User {display_name_for_db} ({user_id}) in channel '{channel_involved_name}' ({channel_involved_id})"
            if from_channel_name_db:
                log_message_for_console += f" from '{from_channel_name_db}' ({from_channel_id_db})"
            log.info(log_message_for_console)

            # --- บันทึก Log เข้า Database ---
            try:
                await db_manager.add_voice_log(
                    user_id=user_id,
                    action=action_type,
                    channel_id=channel_involved_id,
                    channel_name=channel_involved_name,
                    from_channel_id=from_channel_id_db,
                    from_channel_name=from_channel_name_db
                )
            except Exception as e:
                log.exception(f"เกิดข้อผิดพลาดขณะบันทึก voice log เข้า database สำหรับ user ID {user_id}")

            # --- สร้าง Embed สำหรับแจ้งเตือน ---
            embed = discord.Embed(
                title=title,
                description=description,
                color=embed_color,
                timestamp=datetime.fromtimestamp(unix_timestamp_embed, tz=timezone.utc)
            )
            embed.set_author(
                name=display_name_for_db,
                icon_url=avatar_url_for_db if avatar_url_for_db else member.default_avatar.url
            )
            embed.set_footer(text=f"{footer_text} • User ID: {user_id}")
            embed.add_field(name="Channel", value=f"{channel_involved_name} (`{channel_involved_id}`)", inline=False)

            await self.send_notification_embed(embed)


# --- ฟังก์ชัน Setup สำหรับ Cog ---
# ต้องเป็น async function ชื่อ setup และรับ bot instance
async def setup(bot: commands.Bot):
    """Loads the VoiceLoggingCog."""
    try:
        import os
        if not os.getenv("POSTGRES_CONNECTION_STRING"):
            log.error("VoiceLoggingCog: ไม่สามารถโหลดได้เนื่องจาก POSTGRES_CONNECTION_STRING ไม่ได้ถูกตั้งค่าใน .env")
            return
        await bot.add_cog(VoiceLoggingCog(bot))
        log.info("VoiceLoggingCog: Setup complete, Cog added to bot.")
    except Exception as e:
        log.exception("VoiceLoggingCog: Failed to load Cog.")