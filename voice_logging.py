import os
import time
from datetime import datetime, timezone, timedelta
import discord

# List of voice channel IDs to monitor
monitored_voice_channel_ids = [1250561983305224222,1135925419753869312,1251996192699711599]  #  #GLMain, #GLSub, Overun
# monitored_voice_channel_ids = [1264556505206882304,1264542777908265052,396983683124559876]  #  #Testing

# List of text channel IDs where notifications will be sent
notification_text_channel_ids = [1264562975851810847]  # Replace with your text channel IDs
# notification_text_channel_ids = [1264542344607436821] # Testing

def get_unix_timestamp():
    """Return current Unix epoch timestamp."""
    return int(time.time())

def get_human_readable_timestamp(unix_timestamp):
    """Convert Unix epoch timestamp to human-readable format adjusted to GMT+7."""
    gmt7 = timezone(timedelta(hours=7))
    dt = datetime.fromtimestamp(unix_timestamp, gmt7)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def get_current_date():
    """Return current date as a string."""
    return datetime.now().strftime('%Y-%m-%d')

def get_log_folder(channel_name):
    """Return the path to the log folder, creating it if it doesn't exist."""
    log_folder = os.path.join('logged', channel_name, get_current_date())
    if not os.path.exists(log_folder):
        os.makedirs(log_folder)
    return log_folder

def get_log_filename(channel_name, log_type):
    """Generate log file name based on the current date and log type."""
    log_folder = get_log_folder(channel_name)
    return os.path.join(log_folder, f'{log_type}_log_{get_current_date()}.txt')

def get_combined_log_filename(channel_name):
    """Generate combined log file name based on the current date."""
    log_folder = get_log_folder(channel_name)
    return os.path.join(log_folder, f'combined_log_{get_current_date()}.txt')

def setup_voice_logging(bot):
    @bot.event
    async def on_voice_state_update(member, before, after):
        unix_timestamp = get_unix_timestamp()
        human_readable_timestamp = get_human_readable_timestamp(unix_timestamp)
        
        # Improved nickname handling
        nickname = member.nick if member.nick else member.name
        display_name = f"{nickname} ({member.name})" if member.nick else member.name

        if before.channel != after.channel:
            if after.channel is not None and after.channel.id in monitored_voice_channel_ids:
                # User joined a monitored voice channel
                if before.channel is None:
                    log_message = f'{human_readable_timestamp} 👋 {display_name} joined {after.channel.name}'
                    title = "Member Joined Voice Channel"
                    description = f"👋 {member.mention} joined **{after.channel.name}**"
                    embed_color = discord.Color.green()
                    footer_text = "Joined"
                else:
                    log_message = f'{human_readable_timestamp} 🛫 {display_name} moved from {before.channel} to channel {after.channel.name}'
                    title = "Member Moved Voice Channels"
                    description = f"🛫 {member.mention} moved from **{before.channel}** to **{after.channel.name}**"
                    embed_color = discord.Color.from_rgb(148, 0, 211)
                    footer_text = "Moved"

                print(log_message)

                # Log to individual files
                join_log_filename = get_log_filename(after.channel.name, 'join')
                with open(join_log_filename, 'a', encoding='utf-8') as f:
                    f.write(log_message + '\n')

                # Log to combined file
                combined_log_filename = get_combined_log_filename(after.channel.name)
                with open(combined_log_filename, 'a', encoding='utf-8') as f:
                    f.write(log_message + '\n')

                # Create enhanced embed
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=embed_color,
                    timestamp=datetime.fromtimestamp(unix_timestamp)
                )
                embed.set_author(
                    name=display_name,
                    icon_url=member.display_avatar.url
                )
                embed.set_footer(text=footer_text)

                # Send message to specified text channels
                for channel_id in notification_text_channel_ids:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)

            if before.channel is not None and before.channel.id in monitored_voice_channel_ids:
                # User left a monitored voice channel
                if after.channel is None:
                    log_message = f'{human_readable_timestamp} 🚪 {display_name} left {before.channel.name}'
                    title = "Member Left Voice Channel"
                    description = f"🚪 {member.mention} left **{before.channel.name}**"
                    embed_color = discord.Color.red()
                    footer_text = "Left"
                else:
                    log_message = f'{human_readable_timestamp} 🛫 {display_name} moved from {before.channel} to channel {after.channel.name}'
                    title = "Member Moved Voice Channels"
                    description = f"🛫 {member.mention} moved from **{before.channel}** to **{after.channel.name}**"
                    embed_color = discord.Color.from_rgb(148, 0, 211)
                    footer_text = "Moved"

                print(log_message)

                # Log to individual files
                leave_log_filename = get_log_filename(before.channel.name, 'leave')
                with open(leave_log_filename, 'a', encoding='utf-8') as f:
                    f.write(log_message + '\n')

                # Log to combined file
                combined_log_filename = get_combined_log_filename(before.channel.name)
                with open(combined_log_filename, 'a', encoding='utf-8') as f:
                    f.write(log_message + '\n')

                # Create embed message
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=embed_color,
                    timestamp=datetime.fromtimestamp(unix_timestamp)
                )
                embed.set_author(
                    name=display_name,
                    icon_url=member.display_avatar.url
                )
                embed.set_footer(text=footer_text)

                # Send message to specified text channels
                for channel_id in notification_text_channel_ids:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)