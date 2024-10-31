import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from bidding_ph import setup_bidding_system
from voice_logging import setup_voice_logging

# Load environment variables from .env file
load_dotenv()

# Get the bot token from the environment variables
BOT_TOKEN = os.getenv('DISCORD_TESTBOT_TOKEN')

# Set up the bot intents
intents = discord.Intents.default()
intents.messages = True
intents.voice_states = True  # Enable the voice state intent

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Bot is ready. Logged in as {bot.user}')
    
    # Call function to set up bidding system
    await setup_bidding_system(bot)
    
    # Call function to set up voice logging
    setup_voice_logging(bot)

bot.run(BOT_TOKEN)