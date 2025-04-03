# tts_scheduler_cog.py
import discord
from discord.ext import commands, tasks
import datetime
import asyncio
import os
import logging
from gtts import gTTS # For Text-to-Speech generation
from typing import Optional, List, Dict
from zoneinfo import ZoneInfo # For timezone handling (Python 3.9+)
# If using Python < 3.9, install pytz: pip install pytz
# and uncomment the following line, then comment out the zoneinfo import
# from pytz import timezone

# Setup basic logging
log = logging.getLogger(__name__)

# --- Configuration ---
# Time for the bot to speak (in your local time)
SCHEDULED_HOUR = 20 # Example: 13 hours (1 PM)
SCHEDULED_MINUTE = 27 # Example: 59 minutes past the hour
# Your local timezone name (e.g., 'Asia/Bangkok', 'Europe/London', 'America/New_York')
# Ensure you have the 'tzdata' package installed (`pip install -U tzdata`)
LOCAL_TIMEZONE = 'Asia/Bangkok'

# Target Voice Channel ID where the bot should speak
TARGET_VOICE_CHANNEL_ID = 1357336799462166598 # <<< IMPORTANT: Replace with your target voice channel ID

# Message the bot should speak
MESSAGE_TO_SPEAK = "Guild league is starting in 1 minutes." # <<< IMPORTANT: Replace with your message
# Language for TTS (e.g., 'th' for Thai, 'en' for English, 'ja' for Japanese)
TTS_LANG = 'en'
# Temporary filename for the generated audio
TEMP_AUDIO_FILENAME = "tts_schedule_output.mp3"
# Path to FFmpeg executable (usually just 'ffmpeg' if it's in PATH, otherwise specify the full path)
FFMPEG_EXECUTABLE_PATH = "C:/Users/ayato/ffmpeg-7.1.1-full_build/bin/ffmpeg.exe" # Example for Windows: "C:/ffmpeg/bin/ffmpeg.exe"

# --- Pre-calculate Timezone and Target Time Object ---
try:
    # Use ZoneInfo (Python 3.9+)
    _tzinfo = ZoneInfo(LOCAL_TIMEZONE)
    # If using pytz (Python < 3.9)
    # _tzinfo = timezone(LOCAL_TIMEZONE)
except Exception as e:
    log.error(f"Could not find Timezone '{LOCAL_TIMEZONE}'. Please check spelling and ensure 'tzdata' package is installed (`pip install -U tzdata`). Falling back to UTC. Error: {e}")
    _tzinfo = datetime.timezone.utc # Fallback to UTC

# Create the datetime.time object required by tasks.loop
_scheduled_time_obj = datetime.time(hour=SCHEDULED_HOUR, minute=SCHEDULED_MINUTE, tzinfo=_tzinfo)
log.info(f"TTS Scheduler: Task loop scheduled time set to {_scheduled_time_obj.strftime('%H:%M:%S %Z')}")
# -----------------------------------------

class TextToSpeechSchedulerCog(commands.Cog):
    """
    A Cog that connects to a specified voice channel at a scheduled time
    and plays a text-to-speech message.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.target_channel_id = TARGET_VOICE_CHANNEL_ID
        self.message = MESSAGE_TO_SPEAK
        self.lang = TTS_LANG
        self.temp_filename = TEMP_AUDIO_FILENAME
        self.ffmpeg_path = FFMPEG_EXECUTABLE_PATH
        self.current_voice_client: Optional[discord.VoiceClient] = None # Stores the current voice connection

        log.info(f"TTS Scheduler Cog Initialized. Target Channel ID: {self.target_channel_id}, Language: {self.lang}")

        # Start the background task loop
        self.speak_message_task.start()
        log.info("TTS Scheduler: Background task loop started.")

    def cog_unload(self):
        """Called when the Cog is unloaded."""
        self.speak_message_task.cancel()
        log.info("TTS Scheduler: Background task loop cancelled.")
        # Attempt to clean up voice connection if the cog is unloaded while connected
        if self.current_voice_client and self.current_voice_client.is_connected():
             log.warning("TTS Scheduler: Cog unloading while connected, attempting cleanup (may not be reliable).")
             # Disconnecting directly here can cause issues. Rely on bot shutdown or manual disconnect.
             # asyncio.create_task(self.current_voice_client.disconnect(force=True))

    @tasks.loop(time=_scheduled_time_obj)
    async def speak_message_task(self):
        """The main task that runs at the scheduled time."""
        current_time_str = datetime.datetime.now(_tzinfo).strftime('%Y-%m-%d %H:%M:%S %Z')
        log.info(f"TTS Scheduler: Task triggered at {current_time_str}")

        # 1. Find the target voice channel
        voice_channel = self.bot.get_channel(self.target_channel_id)
        if not voice_channel:
            log.error(f"TTS Scheduler: Target Voice Channel ID {self.target_channel_id} not found.")
            return
        if not isinstance(voice_channel, discord.VoiceChannel):
            log.error(f"TTS Scheduler: Target ID {self.target_channel_id} is not a Voice Channel (Type: {type(voice_channel)}).")
            return

        log.info(f"TTS Scheduler: Found target voice channel: '{voice_channel.name}' in guild '{voice_channel.guild.name}'")

        # --- 2. Generate TTS Audio File ---
        try:
            log.info(f"TTS Scheduler: Generating TTS audio for text: '{self.message}' (Lang: {self.lang})")
            tts = gTTS(text=self.message, lang=self.lang, slow=False)
            tts.save(self.temp_filename)
            log.info(f"TTS Scheduler: Successfully saved TTS audio to '{self.temp_filename}'")
        except Exception as e:
            log.exception(f"TTS Scheduler: Failed to generate TTS audio file: {e}")
            # Clean up potentially corrupted file
            if os.path.exists(self.temp_filename):
                try: os.remove(self.temp_filename)
                except OSError: pass
            return # Stop task if audio generation fails

        # --- 3. Connect to Voice Channel and Play Audio ---
        audio_source = None # Initialize to ensure cleanup happens
        try:
            # Check if already connected
            if self.current_voice_client and self.current_voice_client.is_connected():
                if self.current_voice_client.channel.id != voice_channel.id:
                    # Move to the target channel if connected elsewhere
                    log.info(f"TTS Scheduler: Moving from '{self.current_voice_client.channel.name}' to '{voice_channel.name}'...")
                    await self.current_voice_client.move_to(voice_channel)
                    log.info(f"TTS Scheduler: Successfully moved to '{voice_channel.name}'.")
                else:
                    log.info(f"TTS Scheduler: Already connected to the target channel '{voice_channel.name}'.")
            else:
                # Connect to the target channel
                log.info(f"TTS Scheduler: Connecting to voice channel '{voice_channel.name}'...")
                # Set a timeout for connection attempt
                self.current_voice_client = await voice_channel.connect(timeout=30.0, reconnect=True)
                log.info(f"TTS Scheduler: Successfully connected. Voice Client: {self.current_voice_client}")

            # Verify connection status again after connect/move
            if not self.current_voice_client or not self.current_voice_client.is_connected():
                 log.error("TTS Scheduler: Connection failed or lost before playing audio.")
                 await self.cleanup_after_error() # Attempt cleanup
                 return

            # Stop any currently playing audio (optional, prevents overlap)
            if self.current_voice_client.is_playing():
                log.warning("TTS Scheduler: Bot is already playing audio. Stopping previous audio.")
                self.current_voice_client.stop()
                await asyncio.sleep(0.5) # Short pause after stopping

            log.info(f"TTS Scheduler: Preparing to play audio file '{self.temp_filename}'...")

            # Create the audio source using FFmpeg
            # Ensure the executable path is correct
            audio_source = discord.FFmpegPCMAudio(self.temp_filename, executable=self.ffmpeg_path)

            # Play the audio, scheduling cleanup for afterwards
            self.current_voice_client.play(audio_source, after=lambda e: self.after_play_cleanup(e))

            log.info("TTS Scheduler: Audio playback started. Waiting for completion...")
            # The task will now wait implicitly until the 'after' callback is triggered

        except discord.ClientException as e:
            log.error(f"TTS Scheduler: Discord ClientException during connection/playback: {e}")
            await self.cleanup_after_error()
        except asyncio.TimeoutError:
            log.error("TTS Scheduler: Timeout occurred while trying to connect to the voice channel.")
            await self.cleanup_after_error()
        except Exception as e:
            # Catch any other unexpected errors during connection or playback setup
            log.exception(f"TTS Scheduler: An unexpected error occurred during voice connection or playback setup: {e}")
            await self.cleanup_after_error()


    def after_play_cleanup(self, error: Optional[Exception]):
        """Callback function executed after audio playback finishes or errors."""
        log.info("TTS Scheduler: 'after_play_cleanup' callback executing...")
        if error:
            log.error(f"TTS Scheduler: Error during audio playback: {error}")

        # Schedule the asynchronous cleanup task safely from the potentially different thread context of the callback
        coro = self.disconnect_and_delete_file()
        # Use bot.loop to ensure it runs on the main event loop
        future = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

        try:
            # Optionally wait for the cleanup coroutine to finish with a timeout
            future.result(timeout=15.0)
            log.info("TTS Scheduler: Cleanup coroutine completed successfully.")
        except TimeoutError:
            log.error("TTS Scheduler: Timeout waiting for cleanup coroutine to finish.")
        except Exception as e:
            # Log errors happening within the cleanup coroutine itself
            log.exception(f"TTS Scheduler: Error occurred within the cleanup coroutine future: {e}")

    async def disconnect_and_delete_file(self):
        """Asynchronous task to disconnect from voice and delete the temp file."""
        log.info("TTS Scheduler: Starting disconnect_and_delete_file...")

        # Disconnect from the voice channel if connected
        if self.current_voice_client and self.current_voice_client.is_connected():
            vc_name = self.current_voice_client.channel.name
            log.info(f"TTS Scheduler: Attempting to disconnect from voice channel '{vc_name}'...")
            try:
                await self.current_voice_client.disconnect(force=False) # Try graceful disconnect first
                log.info(f"TTS Scheduler: Successfully disconnected from '{vc_name}'.")
            except Exception as e:
                log.exception(f"TTS Scheduler: Error during disconnecting from '{vc_name}': {e}")
            finally:
                 # Always clear the reference, even if disconnect fails
                 self.current_voice_client = None
                 log.debug("TTS Scheduler: Cleared current_voice_client reference.")

        # Delete the temporary audio file
        if os.path.exists(self.temp_filename):
            log.info(f"TTS Scheduler: Attempting to delete temporary file '{self.temp_filename}'...")
            try:
                os.remove(self.temp_filename)
                log.info(f"TTS Scheduler: Successfully deleted '{self.temp_filename}'.")
            except OSError as e:
                log.error(f"TTS Scheduler: Failed to delete temporary file '{self.temp_filename}': {e}")
        else:
             log.warning(f"TTS Scheduler: Temporary file '{self.temp_filename}' not found for deletion.")

    async def cleanup_after_error(self):
         """Force cleanup if an error occurs *before* playback starts."""
         log.warning("TTS Scheduler: Running cleanup_after_error due to pre-playback failure...")
         if self.current_voice_client and self.current_voice_client.is_connected():
              log.info("TTS Scheduler: Force disconnecting voice client after error.")
              try:
                  await self.current_voice_client.disconnect(force=True)
              except Exception: pass # Ignore errors during forced disconnect
              finally: self.current_voice_client = None
         # Ensure temp file is deleted even if playback didn't start
         if os.path.exists(self.temp_filename):
             log.info(f"TTS Scheduler: Deleting temporary file '{self.temp_filename}' after error.")
             try: os.remove(self.temp_filename)
             except OSError: pass

    @speak_message_task.before_loop
    async def before_speak_message_task(self):
        """Executed once before the task loop starts."""
        log.info("TTS Scheduler: Waiting for bot to be ready before starting task loop...")
        await self.bot.wait_until_ready()
        log.info("TTS Scheduler: Bot is ready. Task loop will now wait for the scheduled time.")

# --- Setup Function for Cog Loading ---
async def setup(bot: commands.Bot):
    """Loads the TextToSpeechSchedulerCog."""
    # --- FFmpeg Check ---
    ffmpeg_path = FFMPEG_EXECUTABLE_PATH
    log.info(f"TTS Scheduler Setup: Checking for FFmpeg using command: '{ffmpeg_path} -version'")
    try:
        # Use quotes around the path in case it contains spaces
        process = await asyncio.create_subprocess_shell(
            f'"{ffmpeg_path}" -version',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            log.info("TTS Scheduler Setup: FFmpeg check successful.")
            # Optionally log the version found
            # version_line = stdout.decode(errors='ignore').split('\n', 1)[0]
            # log.info(f"FFmpeg version found: {version_line}")
        else:
            # Log failure details to help diagnose
            stdout_str = stdout.decode(errors='ignore').strip()
            stderr_str = stderr.decode(errors='ignore').strip()
            log.error(f"TTS Scheduler Setup: FFmpeg check failed! (Return Code: {process.returncode})")
            log.error(f"Please ensure FFmpeg is installed correctly and the path '{ffmpeg_path}' is valid and accessible in the system's PATH environment variable.")
            if stdout_str: log.error(f"FFmpeg stdout: {stdout_str}")
            if stderr_str: log.error(f"FFmpeg stderr: {stderr_str}")
            # Consider raising an error to prevent loading if FFmpeg is crucial and not found
            # raise RuntimeError("FFmpeg check failed. TTS functionality will not work.")
    except FileNotFoundError:
        log.error(f"TTS Scheduler Setup: FFmpeg command '{ffmpeg_path}' not found.")
        log.error("Please ensure FFmpeg is installed and its location is added to the system's PATH environment variable, or specify the full path in FFMPEG_EXECUTABLE_PATH.")
        # raise RuntimeError("FFmpeg command not found.")
    except Exception as e:
         # Catch other potential errors during the check
         log.exception(f"TTS Scheduler Setup: An unexpected error occurred while checking for FFmpeg: {e}")
         # raise e # Optionally re-raise

    # --- Load the Cog ---
    try:
        await bot.add_cog(TextToSpeechSchedulerCog(bot))
        log.info("TextToSpeechSchedulerCog: Setup complete, Cog added successfully.")
    except Exception as e:
        # Log any errors during Cog initialization or adding
        log.exception("TextToSpeechSchedulerCog: Failed to load Cog.")
        raise e # Re-raise the exception so the main bot knows loading failed