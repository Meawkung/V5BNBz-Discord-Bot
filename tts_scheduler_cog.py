# tts_scheduler_cog.py
import discord
from discord.ext import commands
import asyncio
import datetime
from gtts import gTTS
import os
import logging
import json
from typing import Optional, List, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

# --- ค่าคงที่ ---
TEMP_TTS_DIR = "temp_tts" # โฟลเดอร์เก็บไฟล์ TTS (ตอนนี้ไม่ชั่วคราวแล้วสำหรับ schedule)
SCHEDULE_FILENAME = "tts_schedule.json"
DEFAULT_LANG = 'en'

# สร้าง directory ถ้ายังไม่มี
if not os.path.exists(TEMP_TTS_DIR):
    try:
        os.makedirs(TEMP_TTS_DIR)
        log.info(f"สร้าง directory สำหรับเก็บไฟล์ TTS: {TEMP_TTS_DIR}")
    except OSError as e:
        log.error(f"ไม่สามารถสร้าง directory {TEMP_TTS_DIR}: {e}")
        TEMP_TTS_DIR = "." # Fallback

class TextToSpeechSchedulerCog(commands.Cog):
    """
    A Cog that schedules Text-to-Speech announcements in a specific voice channel
    based on a schedule loaded from a JSON file, using APScheduler.
    Scheduled TTS audio files are now cached based on job ID and language.
    Also provides a command to test TTS manually (test files are still temporary).
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        try:
            self.default_timezone = datetime.timezone(datetime.timedelta(hours=7), name="GMT+7")
            log.info(f"Using timezone: {self.default_timezone.tzname(None)}")
        except Exception:
            log.exception("Failed to create timezone object. Using system default.")
            self.default_timezone = None

        self.target_guild_id = 1097740536527470717
        self.target_voice_channel_id = 1250561983305224222
        self.ffmpeg_path = os.getenv("FFMPEG_PATH")

        self.is_playing = False
        self.current_voice_client: Optional[discord.VoiceClient] = None
        self.job_lock = asyncio.Lock()

        self.jobs_schedule_data = self._load_schedule_from_file()
        if not self.jobs_schedule_data:
            log.warning("ไม่สามารถโหลดตารางเวลาจากไฟล์ หรือไฟล์ว่างเปล่า. จะไม่มีการตั้งเวลา TTS อัตโนมัติ.")

        try:
            self.scheduler = AsyncIOScheduler(timezone=self.default_timezone)
            self._schedule_initial_jobs(self.jobs_schedule_data or [])
            self.scheduler.start()
            log.info(f"APScheduler started with timezone: {self.scheduler.timezone}")
        except Exception as e:
            log.exception("Failed to initialize or start APScheduler!")
            self.scheduler = None

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
                seen_ids = set() # Track IDs to prevent duplicates
                for i, job_info in enumerate(data):
                    if not isinstance(job_info, dict):
                        log.warning(f"Schedule item at index {i} is not a dictionary, skipping.")
                        continue
                    job_id = job_info.get("id")
                    message = job_info.get("message")
                    if not job_id or not message:
                        log.warning(f"Schedule item at index {i} (ID: {job_id}) is missing 'id' or 'message', skipping.")
                        continue
                    if not isinstance(job_id, (str, int)):
                        log.warning(f"Job '{job_id}' has an invalid ID type, skipping.")
                        continue
                    if not isinstance(message, str):
                        log.warning(f"Job '{job_id}' has an invalid message type, skipping.")
                        continue

                    # Ensure ID uniqueness for scheduling
                    if str(job_id) in seen_ids:
                        log.warning(f"Duplicate job ID '{job_id}' found in schedule file. Skipping subsequent occurrences.")
                        continue
                    seen_ids.add(str(job_id))

                    valid_jobs.append(job_info)

                log.info(f"Successfully loaded {len(valid_jobs)} valid and unique jobs from '{file_path}'.")
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
            lang = job_info.get("lang", DEFAULT_LANG).lower() # Use lower case for consistency

            try:
                trigger = CronTrigger(
                    hour=job_info.get("hour", '*'),
                    minute=job_info.get("minute", '*'),
                    second=job_info.get("second", 0),
                    day_of_week=job_info.get("days", '*'),
                    timezone=self.default_timezone
                )
                self.scheduler.add_job(
                    self.run_tts_job,
                    trigger=trigger,
                    id=job_id,
                    name=f"TTS-{job_id}-{lang}", # Include lang in job name for clarity
                    args=[job_id, message, lang], # Pass lang as arg
                    replace_existing=True,
                    misfire_grace_time=30 # Allow job to run up to 30s late
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
                # Give pending callbacks a chance to finish slightly
                self.scheduler.shutdown(wait=True) # Wait for running jobs
                log.info("APScheduler shut down.")
            except Exception as e:
                 log.exception("Error during APScheduler shutdown.")

        if self.current_voice_client and self.current_voice_client.is_connected():
            log.warning("Cog unloading: Attempting to disconnect lingering voice client.")
            asyncio.ensure_future(self._force_disconnect(), loop=self.bot.loop)

    async def _force_disconnect(self):
         """Force disconnect, usually on unload."""
         vc = self.current_voice_client
         if vc and vc.is_connected():
            log.info("Forcing disconnect...")
            try:
                await vc.disconnect(force=True)
                log.info("Force disconnected voice client.")
            except Exception as e:
                log.error(f"Error during force disconnect: {e}")
            finally:
                 self.current_voice_client = None
         else:
             log.debug("Force disconnect called but no active/connected client found.")


    async def run_tts_job(self, job_id: str, message_to_speak: str, lang: str):
        """Function called by APScheduler to run a TTS job. Reuses existing audio files."""
        log_prefix = f"Job '{job_id}' (Lang: {lang}): "
        log.info(f"{log_prefix}Triggered. Attempting to acquire lock...")

        async with self.job_lock:
            log.info(f"{log_prefix}Acquired lock.")
            if self.is_playing:
                log.warning(f"{log_prefix}Another TTS job/test started while waiting for lock. Skipping.")
                return # Release lock implicitly

            self.is_playing = True
            log.info(f"{log_prefix}Set is_playing=True.")

            guild = self.bot.get_guild(self.target_guild_id)
            if not guild:
                log.error(f"{log_prefix}Cannot find target guild {self.target_guild_id}.")
                self.is_playing = False; return

            voice_channel = guild.get_channel(self.target_voice_channel_id)
            if not voice_channel or not isinstance(voice_channel, discord.VoiceChannel):
                 log.error(f"{log_prefix}Cannot find target voice channel {self.target_voice_channel_id}.")
                 self.is_playing = False; return

            vc = guild.voice_client
            # --- MODIFICATION: Consistent filename including language ---
            tts_filename = os.path.join(TEMP_TTS_DIR, f"scheduled_tts_{job_id}_{lang}.mp3")
            log.debug(f"{log_prefix}Expected audio file: {tts_filename}")
            # --- END MODIFICATION ---

            connected_or_moved = False
            play_initiated = False

            try:
                # --- Connect / Move ---
                if vc and vc.is_connected():
                    if vc.channel.id != self.target_voice_channel_id:
                        log.info(f"{log_prefix}Moving voice client from {vc.channel.name} to {voice_channel.name}")
                        await vc.move_to(voice_channel)
                        self.current_voice_client = vc
                    else:
                         log.info(f"{log_prefix}Already connected to {voice_channel.name}")
                    connected_or_moved = True
                else:
                    log.info(f"{log_prefix}Connecting to {voice_channel.name}")
                    vc = await voice_channel.connect(timeout=20.0, reconnect=True)
                    if vc:
                         connected_or_moved = True
                         self.current_voice_client = vc
                    else:
                         log.error(f"{log_prefix}Connection attempt returned None.")

                if not connected_or_moved or not self.current_voice_client:
                    log.error(f"{log_prefix}Failed to establish voice connection.")
                    self.is_playing = False; return

                # --- Generate TTS File (Only if it doesn't exist) ---
                # --- MODIFICATION: Check for existing file ---
                if not os.path.exists(tts_filename):
                    log.info(f"{log_prefix}Audio file not found. Generating audio: '{message_to_speak}'")
                    try:
                        tts = gTTS(text=message_to_speak, lang=lang, slow=False)
                        # Ensure directory exists before saving
                        os.makedirs(os.path.dirname(tts_filename), exist_ok=True)
                        await self.bot.loop.run_in_executor(None, tts.save, tts_filename)
                        log.info(f"{log_prefix}Saved new audio to: {tts_filename}")
                    except ValueError as e_lang:
                        log.warning(f"{log_prefix}Invalid language code '{lang}': {e_lang}")
                        self.is_playing = False; return
                    except Exception as e_gtts:
                        log.exception(f"{log_prefix}Failed to generate audio.")
                        self.is_playing = False; return
                else:
                    log.info(f"{log_prefix}Reusing existing audio file: {tts_filename}")
                # --- END MODIFICATION ---

                # --- Play Audio File ---
                if os.path.exists(tts_filename): # Double check before playing
                    log.info(f"{log_prefix}Playing audio in {voice_channel.name}")
                    def after_play_callback(error: Optional[Exception]):
                        # Pass filename for logging, though we won't delete it
                        self.after_play_cleanup_job(error, job_id, lang, tts_filename)

                    if not self.current_voice_client or not self.current_voice_client.is_connected():
                        log.error(f"{log_prefix}Voice client disconnected before playback could start.")
                        self.is_playing = False; return

                    try:
                        source = discord.FFmpegPCMAudio(tts_filename, executable=self.ffmpeg_path)
                        self.current_voice_client.play(source, after=after_play_callback)
                        play_initiated = True
                        log.debug(f"{log_prefix}Playback initiated.")
                    except Exception as e_play:
                         log.exception(f"{log_prefix}Error initiating playback with FFmpegPCMAudio for {tts_filename}.")
                         self.is_playing = False; return

                else:
                    # This should ideally not happen if generation succeeded or file existed
                    log.error(f"{log_prefix}Audio file unexpectedly not found before playback: {tts_filename}")
                    self.is_playing = False; return

            except discord.errors.ClientException as e_voice:
                 log.error(f"{log_prefix}Voice client error (e.g., already connected elsewhere?): {e_voice}")
                 self.is_playing = False; # Reset flag
                 # Don't try to disconnect here, might cause issues
            except Exception as e:
                log.exception(f"{log_prefix}An unexpected error occurred during connection or playback setup.")
                self.is_playing = False # Ensure flag is reset on error

            finally:
                if not play_initiated:
                    # If play never started, ensure flag is reset and lock is released
                    self.is_playing = False
                    log.debug(f"{log_prefix}Resetting is_playing flag in finally block (play not initiated).")
                # Lock is released automatically by 'async with'

    # --- MODIFICATION: Changed signature slightly for logging ---
    def after_play_cleanup_job(self, error: Optional[Exception], job_id: str, lang: str, audio_filename: str):
        """Callback function executed after scheduled TTS playback finishes or errors. Does NOT delete the audio file."""
        log_prefix = f"Job '{job_id}' (Lang: {lang}) Callback: "
        # --- END MODIFICATION ---
        if error:
            log.error(f'{log_prefix}Player error: {error}')
        else:
            log.info(f"{log_prefix}Playback finished successfully.")

        # --- MODIFICATION: Keep the audio file ---
        log.info(f"{log_prefix}Keeping audio file for potential reuse: {audio_filename}")
        # --- END MODIFICATION ---

        # Reset playing flag (critical)
        # Needs job_id and lang for unique identifier in logging if needed
        reset_id = f"{job_id}-{lang}"
        self.bot.loop.call_soon_threadsafe(self._reset_playing_flag, reset_id)

    def _reset_playing_flag(self, source_id: str):
         """Resets the playing flag. Intended to be called from threadsafe context."""
         log.info(f"Callback Helper for '{source_id}': Resetting is_playing flag.")
         self.is_playing = False
         log.info(f"Callback Helper for '{source_id}': Keeping voice client connected (if still connected).")

    # --- TEST COMMAND (Keeps its temporary file deletion logic) ---
    @commands.command(name="testtts")
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def test_tts_command(self, ctx: commands.Context, lang: Optional[str] = None, *, text_to_speak: str = None):
        """
        (Testing) Speaks text in your voice channel. Stays connected. Deletes test audio file afterwards.
        Usage: !testtts [lang_code] <text>
        Example: !testtts en Hello there
        Example: !testtts th สวัสดี
        """
        log_prefix = "TestTTS: "
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            await ctx.send("You need to be in a voice channel.")
            return

        # --- Argument Parsing ---
        actual_lang = DEFAULT_LANG
        actual_text = text_to_speak
        if lang and text_to_speak is None: actual_text = lang
        elif lang and len(lang) <= 3 and lang.isalpha(): actual_lang = lang.lower()
        elif lang: actual_text = f"{lang} {text_to_speak if text_to_speak else ''}".strip()

        if not actual_text:
            await ctx.send(f"Please provide text to speak. Usage: `{ctx.prefix}testtts [lang_code] <text>`")
            return
        #-------------------------

        voice_channel = ctx.author.voice.channel
        guild = ctx.guild
        actual_lang = actual_lang.lower() # Ensure consistency
        log.info(f"{log_prefix}Invoked by {ctx.author} in {voice_channel.name}. Lang='{actual_lang}', Text='{actual_text}'")

        # --- Acquire Lock ---
        try:
            async with asyncio.timeout(5):
                 await self.job_lock.acquire()
        except asyncio.TimeoutError:
            log.warning(f"{log_prefix}Could not acquire lock (TTS busy).")
            await ctx.send("The TTS system is currently busy. Please try again shortly.")
            return
        #--------------------

        play_initiated = False
        # --- Test files remain temporary ---
        temp_filename = os.path.join(TEMP_TTS_DIR, f"test_tts_{ctx.message.id}_{actual_lang}.mp3")
        log.debug(f"{log_prefix}Temporary audio file: {temp_filename}")
        # ---------------------------------
        try:
            if self.is_playing:
                log.warning(f"{log_prefix}Another TTS job/test started while waiting. Aborting.")
                await ctx.send("The TTS system became busy while waiting. Please try again.")
                return

            self.is_playing = True
            log.info(f"{log_prefix}Acquired lock and set is_playing=True.")

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
                return

            # --- Generate gTTS ---
            log.info(f"{log_prefix}Generating audio (Lang: {actual_lang}) for: '{actual_text}'")
            try:
                tts = gTTS(text=actual_text, lang=actual_lang, slow=False)
                # Ensure directory exists
                os.makedirs(os.path.dirname(temp_filename), exist_ok=True)
                await self.bot.loop.run_in_executor(None, tts.save, temp_filename)
                log.info(f"{log_prefix}Saved temporary audio file: {temp_filename}")
            except ValueError as e_lang:
                 log.warning(f"{log_prefix}Invalid language code '{actual_lang}': {e_lang}")
                 await ctx.send(f"Sorry, '{actual_lang}' is not a valid language code for TTS.")
                 return
            except Exception as e_gtts:
                log.exception(f"{log_prefix}Failed to generate audio.")
                await ctx.send("Sorry, I couldn't generate the speech audio.")
                return

            # --- Callback for Test (still deletes the test file) ---
            def after_test_cb(error: Optional[Exception]):
                cb_log_prefix = f"TestTTS Callback ({ctx.message.id}): "
                if error: log.error(f'{cb_log_prefix}Player error: {error}')
                else: log.info(f"{cb_log_prefix}Playback finished.")
                # Cleanup TEST file
                try:
                    if os.path.exists(temp_filename):
                         os.remove(temp_filename);
                         log.info(f"{cb_log_prefix}Deleted test file: {temp_filename}")
                except Exception as e_clean: log.error(f"{cb_log_prefix}Error deleting test file {temp_filename}: {e_clean}")
                # Reset flag ONLY
                self.bot.loop.call_soon_threadsafe(self._reset_playing_flag, f"test_{ctx.message.id}")

            # --- Play Audio ---
            if os.path.exists(temp_filename):
                 if not self.current_voice_client or not self.current_voice_client.is_connected():
                      log.error(f"{log_prefix}Voice client disconnected before playback could start.")
                      await ctx.send("Voice connection lost before playback.")
                      return

                 log.info(f"{log_prefix}Playing in {voice_channel.name}")
                 try:
                     source = discord.FFmpegPCMAudio(temp_filename, executable=self.ffmpeg_path)
                     self.current_voice_client.play(source, after=after_test_cb)
                     play_initiated = True
                     await ctx.message.add_reaction("🔊")
                 except Exception as e_play:
                     log.exception(f"{log_prefix}Error initiating playback with FFmpegPCMAudio for test file {temp_filename}.")
                     await ctx.send("Error playing the generated audio.")
                     # Ensure cleanup happens if play fails
                     try:
                         if os.path.exists(temp_filename): os.remove(temp_filename)
                     except: pass
                     return
            else:
                 log.error(f"{log_prefix}Test TTS file not found after generation: {temp_filename}")
                 await ctx.send("Error: Could not find the generated audio file.")
                 return

        except asyncio.TimeoutError:
             log.warning(f"{log_prefix}Could not acquire lock (TTS busy).")
             await ctx.send("The TTS system is currently busy. Please try again shortly.")
        except discord.errors.ClientException as e_voice:
             log.error(f"{log_prefix}Voice client error: {e_voice}")
             await ctx.send(f"Voice connection error: {e_voice}")
        except Exception as e:
            log.exception(f"{log_prefix}Error during execution: {e}")
            await ctx.send(f"An error occurred: {e}")
        finally:
            # Release Lock and Reset Flag if play didn't start
            if not play_initiated:
                self.is_playing = False
                log.debug(f"{log_prefix}Resetting is_playing flag in finally (play not initiated).")
                # Clean up test file if it exists and play never started
                try:
                    if os.path.exists(temp_filename): os.remove(temp_filename); log.info(f"{log_prefix}Cleaned up test file {temp_filename} as play failed.")
                except Exception as e_final_clean: log.error(f"{log_prefix}Error during final cleanup of {temp_filename}: {e_final_clean}")

            if self.job_lock.locked():
                self.job_lock.release()
                log.debug(f"{log_prefix}Released lock in finally block.")


# --- ฟังก์ชัน Setup สำหรับ Cog ---
async def setup(bot: commands.Bot):
    """Loads the TextToSpeechSchedulerCog."""
    try:
        await bot.add_cog(TextToSpeechSchedulerCog(bot))
        log.info("TTS Scheduler Cog (APScheduler, Reuses Files): Setup complete, Cog added to bot.")
    except Exception as e:
        log.exception("TTS Scheduler Cog (APScheduler): Failed to load Cog.")