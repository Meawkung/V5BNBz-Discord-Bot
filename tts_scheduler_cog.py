# tts_scheduler_cog.py
import discord
from discord.ext import commands, tasks
import asyncio
import datetime
from gtts import gTTS
import os
import logging
from typing import Optional, List, Dict # Ensure Optional is imported

# ตั้งค่า logger สำหรับ Cog นี้
log = logging.getLogger(__name__)

FFMPEG_PATH = os.getenv("FFMPEG_PATH") # Get path from .env
# Optional: Check if path was found
if not FFMPEG_PATH:
    log.warning("FFMPEG_PATH not found in .env file. Relying on system PATH.")
    # You could set FFMPEG_PATH = "ffmpeg" here to explicitly use the PATH default
else:
    log.info(f"Using FFmpeg path from environment variable: {FFMPEG_PATH}")

# ตั้งค่า path ชั่วคราวสำหรับไฟล์ TTS (ควรอยู่ใน directory ที่ bot มีสิทธิ์เขียน)
TEMP_TTS_DIR = "temp_tts"
if not os.path.exists(TEMP_TTS_DIR):
    try:
        os.makedirs(TEMP_TTS_DIR)
        log.info(f"สร้าง directory ชั่วคราวสำหรับ TTS: {TEMP_TTS_DIR}")
    except OSError as e:
        log.error(f"ไม่สามารถสร้าง directory {TEMP_TTS_DIR}: {e}")
        # อาจจะต้อง fallback ไปใช้ directory ปัจจุบัน หรือหยุดการทำงานถ้าจำเป็น
        TEMP_TTS_DIR = "." # Fallback to current directory

class TextToSpeechSchedulerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # --- ตั้งค่าสำหรับ Scheduled Task ---
        # ตั้งค่าโซนเวลา GMT+7
        self.gmt7 = datetime.timezone(datetime.timedelta(hours=7))
        # ตั้งเวลาที่ต้องการให้ประกาศ (ชั่วโมง, นาที, วินาที ใน GMT+7)
        self.scheduled_time = datetime.time(21, 26, 00, tzinfo=self.gmt7)
        # ID ของ Guild (Server) เป้าหมาย
        self.target_guild_id = 719548826834436133       # <<< ใส่ Guild ID ของคุณ
        # ID ของ Voice Channel เป้าหมาย
        self.target_voice_channel_id = 1280895030780887163 # <<< ใส่ Voice Channel ID ของคุณ
        # ข้อความที่จะให้พูด
        self.tts_message = "MOB in one minute" # <<< ข้อความของคุณ
        # --- สถานะการทำงาน ---
        self.is_playing = False # Flag ป้องกันการเล่นเสียงซ้อนกันจาก Task หลัก
        self.current_voice_client = None # เก็บ voice client ที่ใช้งานอยู่ (สำหรับ task หลัก)
        # เริ่ม task loop
        self.tts_task_loop.start()
        log.info("TTS Scheduler Cog initialized and task loop started.")
        log.info(f"Scheduled time (GMT+7): {self.scheduled_time.strftime('%H:%M:%S')}")
        log.info(f"Target Guild ID: {self.target_guild_id}")
        log.info(f"Target Voice Channel ID: {self.target_voice_channel_id}")

    def cog_unload(self):
        """Called when the Cog is unloaded."""
        self.tts_task_loop.cancel()
        log.info("TTS Scheduler task loop cancelled.")
        # พยายาม disconnect ถ้ายังเชื่อมต่ออยู่ (จาก task หลัก)
        if self.current_voice_client and self.current_voice_client.is_connected():
            # การ disconnect อาจต้องทำใน async context, อาจจะยุ่งยากตอน unload
            # อาจจะต้องใช้ asyncio.ensure_future หรือวิธีอื่น
            log.warning("Bot is unloading, attempting to disconnect lingering voice client (may require manual check).")
            # self.bot.loop.create_task(self.current_voice_client.disconnect(force=True)) # อาจไม่ทำงาน reliably ตอน unload

    @tasks.loop(seconds=1) # ตรวจสอบทุก 1 วินาที (ปรับได้ตามความเหมาะสม)
    async def tts_task_loop(self):
        """Task loop to check the time and trigger TTS."""
        # รอให้ bot พร้อมก่อนเริ่มทำงาน
        await self.bot.wait_until_ready()

        # ดึงเวลาปัจจุบันในโซน GMT+7
        now_gmt7 = datetime.datetime.now(self.gmt7)
        current_time = now_gmt7.time()

        # เปรียบเทียบเฉพาะ ชั่วโมง นาที วินาที (ไม่สน microsecond)
        target_hms = (self.scheduled_time.hour, self.scheduled_time.minute, self.scheduled_time.second)
        current_hms = (current_time.hour, current_time.minute, current_time.second)

        # log.debug(f"TTS Check: Current Time (GMT+7): {current_time.strftime('%H:%M:%S')}, Target: {self.scheduled_time.strftime('%H:%M:%S')}")

        # ตรวจสอบว่าถึงเวลาหรือยัง และยังไม่ได้กำลังเล่นเสียงอยู่
        if current_hms == target_hms and not self.is_playing:
            log.info(f"Scheduled time {self.scheduled_time.strftime('%H:%M:%S')} reached. Attempting TTS.")
            self.is_playing = True # ตั้ง flag ว่ากำลังจะเล่น
            await self.connect_and_speak()
            # หลังจากเรียก connect_and_speak, is_playing จะถูกตั้งเป็น False ใน after_play_cleanup
            # เพิ่ม delay เล็กน้อยหลังเล่นเสร็จ เพื่อป้องกันการ trigger ซ้ำในวินาทีเดียวกัน (ถ้า loop เร็ว)
            await asyncio.sleep(2)

    @tts_task_loop.before_loop
    async def before_tts_task_loop(self):
        """Wait until the bot is ready before starting the loop."""
        await self.bot.wait_until_ready()
        log.info("TTS Scheduler: Bot is ready. Task loop will now check the time.")

    async def connect_and_speak(self):
        """Connects to the target voice channel and speaks the message."""
        guild = self.bot.get_guild(self.target_guild_id)
        if not guild:
            log.error(f"Cannot find target guild with ID: {self.target_guild_id}")
            self.is_playing = False # Reset flag if guild not found
            return

        voice_channel = guild.get_channel(self.target_voice_channel_id)
        if not voice_channel or not isinstance(voice_channel, discord.VoiceChannel):
            log.error(f"Cannot find target voice channel or it's not a voice channel. ID: {self.target_voice_channel_id}")
            self.is_playing = False # Reset flag
            return

        # ตรวจสอบว่า bot เชื่อมต่อ voice ใน guild นี้อยู่แล้วหรือไม่
        self.current_voice_client = guild.voice_client
        try:
            if self.current_voice_client and self.current_voice_client.is_connected():
                if self.current_voice_client.channel != voice_channel:
                    log.info(f"Moving voice client to target channel: {voice_channel.name}")
                    await self.current_voice_client.move_to(voice_channel)
                else:
                    log.info(f"Already connected to the target channel: {voice_channel.name}")
            else:
                log.info(f"Connecting to voice channel: {voice_channel.name}")
                self.current_voice_client = await voice_channel.connect(timeout=20.0, reconnect=True)

            if not self.current_voice_client:
                 log.error("Failed to establish voice connection.")
                 self.is_playing = False
                 return

            # ป้องกันการเล่นซ้อน ถ้า voice client กำลังเล่นอย่างอื่นอยู่ (อาจไม่จำเป็นถ้า is_playing จัดการดีแล้ว)
            if self.current_voice_client.is_playing():
                log.warning("Voice client is already playing something. Skipping scheduled TTS for now.")
                # ไม่ควรตั้ง is_playing เป็น False ที่นี่ เพราะเรายังอยู่ในช่วงเวลาที่ควรจะเล่น
                # แต่การเล่นครั้งนี้ถูกข้ามไป รอ loop ถัดไป
                return

            # สร้างไฟล์ TTS
            # ใช้ ID เฉพาะสำหรับ task นี้ เพื่อไม่ให้ชนกับ test command
            tts_filename = os.path.join(TEMP_TTS_DIR, f"scheduled_tts_{self.target_voice_channel_id}.mp3")
            log.info(f"Generating scheduled TTS audio: '{self.tts_message}'")
            try:
                tts = gTTS(text=self.tts_message, lang='th', slow=False)
                await self.bot.loop.run_in_executor(None, tts.save, tts_filename)
                log.info(f"Saved scheduled TTS audio to: {tts_filename}")
            except Exception as e:
                log.exception("Failed to generate scheduled TTS audio.")
                self.is_playing = False # Reset flag on failure
                # พยายาม disconnect ถ้าเพิ่งต่อเข้าไป
                if self.current_voice_client.is_connected(): await self.current_voice_client.disconnect(force=True)
                self.current_voice_client = None
                return

            # เล่นไฟล์เสียง
            if os.path.exists(tts_filename):
                log.info(f"Playing scheduled TTS in {voice_channel.name}")
                # Pass self.after_play_cleanup as the callback
                source = discord.FFmpegPCMAudio(tts_filename, executable=FFMPEG_PATH)
                self.current_voice_client.play(source, after=self.after_play_cleanup)
            else:
                log.error(f"Scheduled TTS file not found after generation: {tts_filename}")
                self.is_playing = False # Reset flag
                if self.current_voice_client.is_connected(): await self.current_voice_client.disconnect(force=True)
                self.current_voice_client = None


        except discord.Forbidden:
            log.error(f"No permission to join/move to voice channel {voice_channel.name}")
            self.is_playing = False
        except asyncio.TimeoutError:
             log.error(f"Timed out connecting/moving to voice channel {voice_channel.name}")
             self.is_playing = False
        except discord.ClientException as e:
             log.error(f"Discord ClientException during scheduled TTS connection/play: {e}")
             self.is_playing = False
             # Attempt cleanup if possible
             if self.current_voice_client and self.current_voice_client.is_connected():
                 try: await self.current_voice_client.disconnect(force=True)
                 except: pass
             self.current_voice_client = None
        except Exception as e:
            log.exception("An unexpected error occurred during connect_and_speak.")
            self.is_playing = False
            if self.current_voice_client and self.current_voice_client.is_connected():
                 try: await self.current_voice_client.disconnect(force=True)
                 except: pass
            self.current_voice_client = None

    def after_play_cleanup(self, error: Optional[Exception]):
        """Callback function executed after scheduled TTS playback finishes or errors."""
        if error:
            log.error(f'Scheduled TTS Player error: {error}')
        else:
            log.info("Scheduled TTS playback finished successfully.")

        # --- Cleanup scheduled TTS file ---
        tts_filename = os.path.join(TEMP_TTS_DIR, f"scheduled_tts_{self.target_voice_channel_id}.mp3")
        try:
            if os.path.exists(tts_filename):
                os.remove(tts_filename)
                log.info(f"Deleted scheduled TTS file: {tts_filename}")
        except Exception as e_clean:
            log.error(f"Error deleting scheduled TTS file {tts_filename}: {e_clean}")

        # --- Reset playing flag ---
        # ควรจะ reset flag หลังจาก cleanup เสร็จสิ้น
        self.is_playing = False
        log.info("Reset is_playing flag to False.")

        # --- Optional: Disconnect after scheduled play? ---
        # ตัดสินใจว่าจะให้ disconnect หรืออยู่ต่อ
        # ถ้าต้องการให้ออกเลย:
        # if self.current_voice_client and self.current_voice_client.is_connected():
        #     log.info("Disconnecting after scheduled TTS playback.")
        #     # Need to schedule disconnect in the main loop
        #     self.bot.loop.create_task(self.current_voice_client.disconnect(force=False))
        # self.current_voice_client = None # Clear reference

        # ถ้าต้องการให้อยู่ต่อ ไม่ต้องทำอะไรตรงนี้ self.current_voice_client ยังคงอยู่


    # --- TEST COMMAND ---
    @commands.command(name="testtts")
    @commands.guild_only() # Command should only be used in a server
    async def test_tts_command(self, ctx: commands.Context, *, text_to_speak: str):
        """
        (Testing) Speaks the given text in your current voice channel.
        Example: !testtts สวัสดีทุกคน
        """
        # 1. Check if user is in a voice channel
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("You need to be in a voice channel to use this command.")
            return

        voice_channel = ctx.author.voice.channel
        guild = ctx.guild

        # 2. Check if text is provided
        if not text_to_speak:
            await ctx.send("Please provide the text you want me to speak. Usage: `!testtts <your text>`")
            return

        # 3. Get or establish voice connection
        test_voice_client = guild.voice_client # Get the bot's current voice client in this guild
        is_new_connection = False # Flag to know if we initiated the connection

        # Check if bot is already playing (potentially the scheduled task or another test)
        if test_voice_client and test_voice_client.is_playing():
             await ctx.send("I'm already speaking in a voice channel. Please wait.")
             return

        if test_voice_client and test_voice_client.is_connected():
            # If already connected, move to the user's channel if different
            if test_voice_client.channel != voice_channel:
                try:
                    await test_voice_client.move_to(voice_channel)
                    log.info(f"TestTTS: Moved voice client to {voice_channel.name}")
                except asyncio.TimeoutError:
                    await ctx.send(f"Timed out trying to move to {voice_channel.name}.")
                    return
                except discord.ClientException as e:
                    log.error(f"TestTTS: ClientException during move: {e}")
                    await ctx.send(f"Could not move to voice channel: {e}")
                    return
        else:
            # If not connected, try to connect
            try:
                log.info(f"TestTTS: Connecting to voice channel: {voice_channel.name}")
                test_voice_client = await voice_channel.connect(timeout=15.0) # Added timeout
                is_new_connection = True # We initiated this connection
                log.info(f"TestTTS: Connected voice client to {voice_channel.name}")
            except discord.Forbidden:
                log.error(f"TestTTS: No permission to join {voice_channel.name}")
                await ctx.send(f"I don't have permission to join {voice_channel.name}.")
                return
            except asyncio.TimeoutError:
                log.error(f"TestTTS: Timed out connecting to {voice_channel.name}")
                await ctx.send(f"Timed out trying to connect to {voice_channel.name}.")
                return
            except discord.ClientException as e:
                 log.error(f"TestTTS: ClientException during connect: {e}")
                 await ctx.send(f"Voice connection error: {e}")
                 # Ensure client is None if connection failed mid-way
                 test_voice_client = None
                 return

        # Double check connection and client validity
        if not test_voice_client or not test_voice_client.is_connected():
             log.error("TestTTS: Failed to establish or verify voice connection.")
             await ctx.send("Failed to establish voice connection.")
             return

        # 4. Generate TTS audio file
        # Use a unique temporary filename based on message ID
        temp_filename = os.path.join(TEMP_TTS_DIR, f"test_tts_{ctx.message.id}.mp3")
        try:
            log.info(f"TestTTS: Generating audio for: '{text_to_speak}'")
            tts = gTTS(text=text_to_speak, lang='th', slow=False) # Assuming Thai
            await self.bot.loop.run_in_executor(None, tts.save, temp_filename)
            log.info(f"TestTTS: Saved temporary audio file: {temp_filename}")
        except Exception as e:
            log.exception(f"TestTTS: Failed to generate TTS audio")
            await ctx.send(f"Sorry, I couldn't generate the speech audio: {e}")
            # Attempt to disconnect only if we created the connection for this test
            if is_new_connection and test_voice_client.is_connected():
                await test_voice_client.disconnect(force=True)
            return

        # 5. Play the audio file
        try:
            # --- Define the cleanup callback function FOR THE TEST ---
            def after_test_playback(error):
                log_prefix = "TestTTS Cleanup: "
                if error:
                    log.error(f'{log_prefix}Player error: {error}')
                else:
                    log.info(f"{log_prefix}Playback finished.")

                # --- Cleanup Task ---
                async def cleanup_tasks():
                    # a. Delete the temporary file
                    try:
                        if os.path.exists(temp_filename):
                            os.remove(temp_filename)
                            log.info(f"{log_prefix}Deleted temporary file: {temp_filename}")
                        else:
                            log.warning(f"{log_prefix}File not found for deletion: {temp_filename}")
                    except Exception as e_clean:
                        log.error(f"{log_prefix}Error deleting file {temp_filename}: {e_clean}")

                    # b. Disconnect if this command initiated the connection
                    # Make sure we are referencing the correct client potentially captured by closure
                    vc_to_disconnect = guild.voice_client # Get current client state
                    if is_new_connection and vc_to_disconnect and vc_to_disconnect.is_connected():
                       log.info(f"{log_prefix}Disconnecting voice client initiated by this command.")
                       try:
                           await vc_to_disconnect.disconnect(force=False)
                           log.info(f"{log_prefix}Disconnected voice client.")
                       except Exception as e_disc:
                           log.error(f"{log_prefix}Error disconnecting voice client: {e_disc}")
                    elif not is_new_connection:
                         log.info(f"{log_prefix}Keeping existing voice connection intact.")

                self.bot.loop.create_task(cleanup_tasks())
            # --- End of cleanup callback definition ---

            source = discord.FFmpegPCMAudio(temp_filename, executable=FFMPEG_PATH)
            test_voice_client.play(source, after=after_test_playback) # Use the specific cleanup for test
            log.info(f"TestTTS: Playing '{text_to_speak}' in {voice_channel.name}")
            await ctx.send(f"Okay, speaking: \"{text_to_speak}\" in {voice_channel.mention}", delete_after=20) # Give confirmation

        except discord.ClientException as e:
            log.error(f"TestTTS: Discord ClientException during playback: {e}")
            await ctx.send(f"Could not play the audio: {e}")
            # Cleanup file and maybe disconnect if we initiated
            try: os.remove(temp_filename)
            except: pass
            if is_new_connection and test_voice_client.is_connected(): await test_voice_client.disconnect(force=True)
        except Exception as e:
            log.exception(f"TestTTS: Unexpected error during playback initiation")
            await ctx.send("An unexpected error occurred while trying to play the speech.")
            # Cleanup file and maybe disconnect if we initiated
            try: os.remove(temp_filename)
            except: pass
            if is_new_connection and test_voice_client.is_connected(): await test_voice_client.disconnect(force=True)


# --- ฟังก์ชัน Setup สำหรับ Cog ---
async def setup(bot: commands.Bot):
    """Loads the TextToSpeechSchedulerCog."""
    try:
        # Ensure FFmpeg is available before adding cog (optional check)
        # try:
        #     process = await asyncio.create_subprocess_shell('ffmpeg -version', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        #     stdout, stderr = await process.communicate()
        #     if process.returncode != 0:
        #         log.error("FFmpeg not found or not executable. TTS functionality will likely fail.")
        #     else:
        #         log.info("FFmpeg found.")
        # except FileNotFoundError:
        #      log.error("FFmpeg command not found. Install FFmpeg and ensure it's in the system PATH.")

        await bot.add_cog(TextToSpeechSchedulerCog(bot))
        log.info("TTS Scheduler Cog: Setup complete, Cog added to bot.")
    except Exception as e:
        log.exception("TTS Scheduler Cog: Failed to load Cog.")
        # raise e