# tts_scheduler_cog.py
import discord
from discord.ext import commands
import asyncio
import datetime
from gtts import gTTS
import os
import logging
import json # <<< สำหรับอ่านไฟล์ JSON
from typing import Optional, List, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler # <<< Import Scheduler
from apscheduler.triggers.cron import CronTrigger         # <<< Import Cron Trigger

log = logging.getLogger(__name__)

# --- ค่าคงที่ ---
TEMP_TTS_DIR = "temp_tts" # โฟลเดอร์เก็บไฟล์ TTS ชั่วคราว
SCHEDULE_FILENAME = "tts_schedule.json" # ชื่อไฟล์ตารางเวลา
DEFAULT_LANG = 'en' # ภาษาเริ่มต้นสำหรับ gTTS

# สร้าง directory ชั่วคราวถ้ายังไม่มี
if not os.path.exists(TEMP_TTS_DIR):
    try:
        os.makedirs(TEMP_TTS_DIR)
        log.info(f"สร้าง directory ชั่วคราวสำหรับ TTS: {TEMP_TTS_DIR}")
    except OSError as e:
        log.error(f"ไม่สามารถสร้าง directory {TEMP_TTS_DIR}: {e}")
        TEMP_TTS_DIR = "." # Fallback ใช้ directory ปัจจุบัน

class TextToSpeechSchedulerCog(commands.Cog):
    """
    A Cog that schedules Text-to-Speech announcements in a specific voice channel
    based on a schedule loaded from a JSON file, using APScheduler.
    Also provides a command to test TTS manually.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # --- ตั้งค่า Timezone (สำคัญมาก!) ---
        try:
            # ตัวอย่าง GMT+7
            self.default_timezone = datetime.timezone(datetime.timedelta(hours=7), name="GMT+7")
            log.info(f"Using timezone: {self.default_timezone.tzname(None)}")
        except Exception:
            log.exception("Failed to create timezone object. Using system default (might be UTC).")
            self.default_timezone = None # ใช้ค่า default ของ APScheduler (น่าจะเป็น UTC)

        # --- ตั้งค่าเป้าหมาย (ควรตั้งจาก config หรือ env var ในอนาคต) ---
        self.target_guild_id = 719548826834436133       # <<< ใส่ Guild ID ของคุณ
        self.target_voice_channel_id = 1280895030780887163 # <<< ใส่ Voice Channel ID ของคุณ
        self.ffmpeg_path = os.getenv("FFMPEG_PATH") # โหลด Path FFMPEG จาก .env

        # --- สถานะภายใน ---
        self.is_playing = False # Flag รวม ป้องกันการเล่นเสียงซ้อนจากทุก Job/Test
        self.current_voice_client: Optional[discord.VoiceClient] = None
        self.job_lock = asyncio.Lock() # Lock ป้องกัน race condition ตอน Job/Test ทำงานพร้อมกัน

        # --- โหลดตารางเวลาจากไฟล์ ---
        self.jobs_schedule_data = self._load_schedule_from_file()
        if not self.jobs_schedule_data:
            log.warning("ไม่สามารถโหลดตารางเวลาจากไฟล์ หรือไฟล์ว่างเปล่า. จะไม่มีการตั้งเวลา TTS อัตโนมัติ.")

        # --- สร้างและเริ่ม Scheduler ---
        try:
            self.scheduler = AsyncIOScheduler(timezone=self.default_timezone)
            # ตั้งค่า Job โดยใช้ข้อมูลที่โหลดมา
            self._schedule_initial_jobs(self.jobs_schedule_data or []) # ส่ง list ว่างถ้าโหลดไม่ได้
            self.scheduler.start()
            log.info(f"APScheduler started with timezone: {self.scheduler.timezone}")
        except Exception as e:
            log.exception("Failed to initialize or start APScheduler!")
            self.scheduler = None # ตั้งเป็น None ถ้า init ไม่สำเร็จ

    def _load_schedule_from_file(self) -> Optional[List[Dict[str, Any]]]:
        """โหลดตารางเวลา Job จากไฟล์ JSON"""
        script_dir = os.path.dirname(__file__)
        file_path = os.path.join(script_dir, SCHEDULE_FILENAME)
        log.info(f"Attempting to load schedule from: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                valid_jobs = []
                for i, job_info in enumerate(data):
                    if not isinstance(job_info, dict):
                        log.warning(f"Schedule item at index {i} is not a dictionary, skipping.")
                        continue
                    job_id = job_info.get("id")
                    message = job_info.get("message")
                    if not job_id or not message:
                        log.warning(f"Schedule item at index {i} (ID: {job_id}) is missing 'id' or 'message', skipping.")
                        continue
                    # Basic validation (can be expanded)
                    if not isinstance(job_id, (str, int)):
                        log.warning(f"Job '{job_id}' has an invalid ID type, skipping.")
                        continue
                    if not isinstance(message, str):
                        log.warning(f"Job '{job_id}' has an invalid message type, skipping.")
                        continue
                    valid_jobs.append(job_info)

                log.info(f"Successfully loaded {len(valid_jobs)} valid jobs from '{file_path}'.")
                return valid_jobs
            else:
                log.error(f"Data in schedule file '{file_path}' is not a JSON list.")
                return None
        except FileNotFoundError:
            log.error(f"Schedule file not found: '{file_path}'. Please create this file.")
            return None
        except json.JSONDecodeError as e:
            log.error(f"Schedule file '{file_path}' contains invalid JSON: {e}")
            return None
        except Exception as e:
            log.exception(f"An unexpected error occurred while loading schedule file '{file_path}': {e}")
            return None

    def _schedule_initial_jobs(self, jobs_data: List[Dict[str, Any]]):
        """ตั้งค่า Jobs เริ่มต้นสำหรับ TTS จากข้อมูลที่โหลดมา"""
        if not self.scheduler:
            log.error("APScheduler is not available, cannot schedule jobs.")
            return
        if not jobs_data:
            log.warning("No valid job data provided to schedule.")
            return

        scheduled_count = 0
        for job_info in jobs_data:
            job_id = str(job_info.get("id")) # Ensure ID is string
            message = job_info.get("message")
            lang = job_info.get("lang", DEFAULT_LANG) # Get language or use default

            try:
                trigger = CronTrigger(
                    hour=job_info.get("hour", '*'),
                    minute=job_info.get("minute", '*'),
                    second=job_info.get("second", 0),
                    day_of_week=job_info.get("days", '*'), # Day of week (mon-sun, 0-6)
                    timezone=self.default_timezone # Use the scheduler's timezone
                )
                # Add job with args: job_id, message, lang
                self.scheduler.add_job(
                    self.run_tts_job,
                    trigger=trigger,
                    id=job_id,
                    name=f"TTS-{job_id}",
                    args=[job_id, message, lang], # Pass lang as arg
                    replace_existing=True,
                    misfire_grace_time=30
                )
                log.info(f"Scheduled job '{job_id}' (Lang: {lang}) with trigger: {trigger}")
                scheduled_count += 1
            except ValueError as ve:
                 log.error(f"Invalid time/day format for job '{job_id}': {ve}. Skipping.")
            except Exception as e:
                log.exception(f"Failed to schedule job '{job_id}': {e}")
        log.info(f"Scheduled a total of {scheduled_count} jobs.")

    def cog_unload(self):
        """Called when the Cog is unloaded."""
        if self.scheduler and self.scheduler.running:
            log.info("Shutting down APScheduler...")
            try:
                self.scheduler.shutdown(wait=False)
                log.info("APScheduler shut down.")
            except Exception as e:
                 log.exception("Error during APScheduler shutdown.")

        # Attempt to disconnect if still connected
        if self.current_voice_client and self.current_voice_client.is_connected():
            log.warning("Cog unloading: Attempting to disconnect lingering voice client.")
            # Use ensure_future as direct await might block unload
            asyncio.ensure_future(self._force_disconnect(), loop=self.bot.loop)

    async def _force_disconnect(self):
         """Force disconnect, usually on unload."""
         # Check reference before accessing attributes
         vc = self.current_voice_client
         if vc and vc.is_connected():
            log.info("Forcing disconnect...")
            try:
                await vc.disconnect(force=True)
                log.info("Force disconnected voice client.")
            except Exception as e:
                log.error(f"Error during force disconnect: {e}")
            finally:
                 # Clear reference even if disconnect failed
                 self.current_voice_client = None
         else:
             log.debug("Force disconnect called but no active/connected client found.")


    async def run_tts_job(self, job_id: str, message_to_speak: str, lang: str):
        """Function called by APScheduler to run a TTS job."""
        log_prefix = f"Job '{job_id}': "
        log.info(f"{log_prefix}Triggered (Lang: {lang}). Attempting to acquire lock...")

        # Use try_lock if we don't want jobs to queue up waiting for the lock
        # acquired_lock = await self.job_lock.acquire(blocking=False)
        # if not acquired_lock:
        #      log.warning(f"{log_prefix}Could not acquire lock (another job/test running). Skipping.")
        #      return

        # Or use async with to wait for the lock (jobs might queue)
        async with self.job_lock:
            log.info(f"{log_prefix}Acquired lock.")
            # Double-check is_playing inside the lock (might have changed while waiting)
            if self.is_playing:
                log.warning(f"{log_prefix}Another TTS job/test started while waiting for lock. Skipping.")
                return # Release lock implicitly

            # Set playing flag
            self.is_playing = True
            log.info(f"{log_prefix}Set is_playing=True.")

            # --- Main execution logic ---
            guild = self.bot.get_guild(self.target_guild_id)
            if not guild:
                log.error(f"{log_prefix}Cannot find target guild {self.target_guild_id}.")
                self.is_playing = False; return # Release lock implicitly

            voice_channel = guild.get_channel(self.target_voice_channel_id)
            if not voice_channel or not isinstance(voice_channel, discord.VoiceChannel):
                 log.error(f"{log_prefix}Cannot find target voice channel {self.target_voice_channel_id}.")
                 self.is_playing = False; return # Release lock implicitly

            vc = guild.voice_client # Get current client
            tts_filename = os.path.join(TEMP_TTS_DIR, f"scheduled_tts_{job_id}.mp3")
            connected_or_moved = False
            play_initiated = False

            try:
                # --- Connect / Move ---
                if vc and vc.is_connected():
                    if vc.channel.id != self.target_voice_channel_id:
                        log.info(f"{log_prefix}Moving voice client from {vc.channel.name} to {voice_channel.name}")
                        await vc.move_to(voice_channel)
                        self.current_voice_client = vc # Ensure ref is up-to-date
                    else:
                         log.info(f"{log_prefix}Already connected to {voice_channel.name}")
                    connected_or_moved = True
                else:
                    log.info(f"{log_prefix}Connecting to {voice_channel.name}")
                    vc = await voice_channel.connect(timeout=20.0, reconnect=True)
                    if vc:
                         connected_or_moved = True
                         self.current_voice_client = vc # Store new client reference
                    else:
                         log.error(f"{log_prefix}Connection attempt returned None.")

                if not connected_or_moved or not self.current_voice_client:
                    log.error(f"{log_prefix}Failed to establish voice connection.")
                    self.is_playing = False; return # Release lock implicitly

                # --- Generate TTS File ---
                log.info(f"{log_prefix}Generating audio (Lang: {lang}): '{message_to_speak}'")
                try:
                    tts = gTTS(text=message_to_speak, lang=lang, slow=False)
                    await self.bot.loop.run_in_executor(None, tts.save, tts_filename)
                    log.info(f"{log_prefix}Saved audio to: {tts_filename}")
                except Exception as e_gtts:
                    log.exception(f"{log_prefix}Failed to generate audio.")
                    self.is_playing = False; return # Release lock implicitly

                # --- Play Audio File ---
                if os.path.exists(tts_filename):
                    log.info(f"{log_prefix}Playing audio in {voice_channel.name}")
                    # Callback defined to run after playback
                    def after_play_callback(error: Optional[Exception]):
                        self.after_play_cleanup_job(error, job_id, tts_filename)

                    # Ensure client is still valid before playing
                    if not self.current_voice_client or not self.current_voice_client.is_connected():
                        log.error(f"{log_prefix}Voice client disconnected before playback could start.")
                        self.is_playing = False; return # Release lock implicitly

                    source = discord.FFmpegPCMAudio(tts_filename, executable=self.ffmpeg_path)
                    self.current_voice_client.play(source, after=after_play_callback)
                    play_initiated = True
                    # is_playing remains True until callback resets it

                else:
                    log.error(f"{log_prefix}TTS file not found after generation: {tts_filename}")
                    self.is_playing = False; return # Release lock implicitly

            except Exception as e:
                log.exception(f"{log_prefix}An unexpected error occurred during connection or playback setup.")
                self.is_playing = False # Ensure flag is reset on error
                # Don't try to disconnect here, might interfere with other states

            finally:
                # If play was never initiated (due to error before vc.play), reset flag
                if not play_initiated:
                    self.is_playing = False
                    log.debug(f"{log_prefix}Resetting is_playing flag due to error before playback initiation.")
                # Lock is released automatically by 'async with'

    def after_play_cleanup_job(self, error: Optional[Exception], job_id: str, audio_filename: str):
        """Callback function executed after scheduled TTS playback finishes or errors."""
        log_prefix = f"Job '{job_id}' Callback: "
        if error:
            log.error(f'{log_prefix}Player error: {error}')
        else:
            log.info(f"{log_prefix}Playback finished successfully.")

        # --- Cleanup TTS file ---
        try:
            if os.path.exists(audio_filename):
                os.remove(audio_filename)
                log.info(f"{log_prefix}Deleted audio file: {audio_filename}")
        except Exception as e_clean:
            log.error(f"{log_prefix}Error deleting audio file {audio_filename}: {e_clean}")

        # --- Reset playing flag (in main loop) ---
        # It's crucial this runs to allow other jobs/tests
        self.bot.loop.call_soon_threadsafe(self._reset_playing_flag, job_id)

    def _reset_playing_flag(self, source_id: str):
         """Resets the playing flag. Intended to be called from threadsafe context."""
         # This runs in the main event loop
         log.info(f"Callback Helper for '{source_id}': Resetting is_playing flag.")
         self.is_playing = False
         # --- Keep client connected ---
         log.info(f"Callback Helper for '{source_id}': Keeping voice client connected (if still connected).")


    # --- TEST COMMAND ---
    @commands.command(name="testtts")
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user) # Add cooldown to prevent spam
    async def test_tts_command(self, ctx: commands.Context, lang: Optional[str] = None, *, text_to_speak: str = None):
        """
        (Testing) Speaks text in your voice channel. Stays connected.
        Usage: !testtts [lang_code] <text>
        Example: !testtts en Hello there
        Example: !testtts สวัสดี
        """
        log_prefix = "TestTTS: "
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("You need to be in a voice channel.")
            return

        # --- Argument Parsing ---
        actual_lang = DEFAULT_LANG
        actual_text = text_to_speak

        # If only one argument is given, assume it's the text with default lang
        if lang and text_to_speak is None:
             actual_text = lang # The first word was actually the text
             # lang remains None, so actual_lang stays default
        # If lang is provided and seems like a lang code (e.g., 2 letters), use it
        elif lang and len(lang) <= 3 and lang.isalpha(): # Basic check for lang code
             actual_lang = lang.lower()
        # If lang is provided but looks like part of the text, combine them
        elif lang:
            actual_text = f"{lang} {text_to_speak if text_to_speak else ''}".strip()
            # actual_lang stays default

        if not actual_text:
            await ctx.send(f"Please provide text to speak. Usage: `{ctx.prefix}testtts [lang_code] <text>`")
            return
        #-------------------------

        voice_channel = ctx.author.voice.channel
        guild = ctx.guild

        log.info(f"{log_prefix}Command invoked by {ctx.author} in {voice_channel.name}. Lang='{actual_lang}', Text='{actual_text}'")

        # --- Acquire Lock ---
        # Use try_lock or wait briefly
        try:
            async with asyncio.timeout(5): # Wait max 5 seconds for lock
                 await self.job_lock.acquire()
        except asyncio.TimeoutError:
            log.warning(f"{log_prefix}Could not acquire lock within timeout (TTS busy).")
            await ctx.send("The TTS system is currently busy. Please try again shortly.")
            return
        #--------------------

        # Lock acquired, proceed but wrap in try/finally to ensure release
        play_initiated = False
        temp_filename = os.path.join(TEMP_TTS_DIR, f"test_tts_{ctx.message.id}.mp3")
        try:
            # --- Double-check playing status inside lock ---
            if self.is_playing:
                log.warning(f"{log_prefix}Another TTS job/test started while waiting for lock. Aborting.")
                await ctx.send("The TTS system became busy while waiting. Please try again.")
                return # Lock will be released by finally

            # --- Set playing flag ---
            self.is_playing = True
            log.info(f"{log_prefix}Acquired lock and set is_playing=True.")
            # -----------------------

            vc = guild.voice_client
            connected_or_moved = False

            # --- Connect / Move ---
            if vc and vc.is_connected():
                if vc.channel.id != voice_channel.id:
                    log.info(f"{log_prefix}Moving voice client to {voice_channel.name}")
                    await vc.move_to(voice_channel)
                    self.current_voice_client = vc
                else:
                     log.info(f"{log_prefix}Already connected to {voice_channel.name}")
                connected_or_moved = True
            else:
                log.info(f"{log_prefix}Connecting to {voice_channel.name}")
                vc = await voice_channel.connect(timeout=15.0)
                if vc:
                     connected_or_moved = True
                     self.current_voice_client = vc
                else:
                     log.error(f"{log_prefix}Connection attempt returned None.")

            if not connected_or_moved or not self.current_voice_client:
                log.error(f"{log_prefix}Failed to establish voice connection.")
                await ctx.send("Failed to connect to your voice channel.")
                return # Lock released by finally

            # --- Generate gTTS ---
            log.info(f"{log_prefix}Generating audio (Lang: {actual_lang}) for: '{actual_text}'")
            try:
                tts = gTTS(text=actual_text, lang=actual_lang, slow=False)
                await self.bot.loop.run_in_executor(None, tts.save, temp_filename)
                log.info(f"{log_prefix}Saved temporary audio file: {temp_filename}")
            except ValueError as e_lang:
                 log.warning(f"{log_prefix}Invalid language code '{actual_lang}': {e_lang}")
                 await ctx.send(f"Sorry, '{actual_lang}' is not a valid language code for TTS.")
                 return # Lock released by finally
            except Exception as e_gtts:
                log.exception(f"{log_prefix}Failed to generate audio.")
                await ctx.send("Sorry, I couldn't generate the speech audio.")
                return # Lock released by finally


            # --- Callback for Test ---
            def after_test_cb(error: Optional[Exception]):
                cb_log_prefix = "TestTTS Callback: "
                if error: log.error(f'{cb_log_prefix}Player error: {error}')
                else: log.info(f"{cb_log_prefix}Playback finished.")
                # Cleanup file
                try:
                    if os.path.exists(temp_filename): os.remove(temp_filename); log.info(f"{cb_log_prefix}Deleted: {temp_filename}")
                except Exception as e_clean: log.error(f"{cb_log_prefix}Error deleting {temp_filename}: {e_clean}")
                # Reset flag ONLY (no disconnect)
                self.bot.loop.call_soon_threadsafe(self._reset_playing_flag, f"test_{ctx.message.id}")

            # --- Play Audio ---
            if os.path.exists(temp_filename):
                 if not self.current_voice_client or not self.current_voice_client.is_connected():
                      log.error(f"{log_prefix}Voice client disconnected before playback could start.")
                      await ctx.send("Voice connection lost before playback.")
                      return # Lock released by finally

                 log.info(f"{log_prefix}Playing in {voice_channel.name}")
                 source = discord.FFmpegPCMAudio(temp_filename, executable=self.ffmpeg_path)
                 self.current_voice_client.play(source, after=after_test_cb)
                 play_initiated = True
                 await ctx.message.add_reaction("🔊") # Feedback that it started
            else:
                 log.error(f"{log_prefix}Test TTS file not found after generation: {temp_filename}")
                 await ctx.send("Error: Could not find the generated audio file.")
                 return # Lock released by finally

        except asyncio.TimeoutError: # Timeout for acquiring lock
             log.warning(f"{log_prefix}Could not acquire lock within timeout (TTS busy).")
             await ctx.send("The TTS system is currently busy. Please try again shortly.")
        except Exception as e:
            log.exception(f"{log_prefix}Error during execution: {e}")
            await ctx.send(f"An error occurred: {e}")
        finally:
            # --- Release Lock and Reset Flag if needed ---
            if not play_initiated: # Reset flag if play never started due to error
                self.is_playing = False
                log.debug(f"{log_prefix}Resetting is_playing flag in finally block because play was not initiated.")
            if self.job_lock.locked():
                self.job_lock.release()
                log.debug(f"{log_prefix}Released lock in finally block.")
            # ---------------------------------------------


# --- ฟังก์ชัน Setup สำหรับ Cog ---
async def setup(bot: commands.Bot):
    """Loads the TextToSpeechSchedulerCog."""
    try:
        await bot.add_cog(TextToSpeechSchedulerCog(bot))
        log.info("TTS Scheduler Cog (APScheduler): Setup complete, Cog added to bot.")
    except Exception as e:
        log.exception("TTS Scheduler Cog (APScheduler): Failed to load Cog.")