import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import json
import logging

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

class WRPBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        self._commands_synced = False
        
        super().__init__(
            command_prefix="C!",  # Works with both prefix and slash commands
            intents=intents
        )
        
        # Initialize pending_calendars.json if it doesn't exist
        if not os.path.exists('pending_calendars.json'):
            with open('pending_calendars.json', 'w') as f:
                json.dump({"pending_submissions": []}, f, indent=2)
        
    async def on_ready(self):
        if not self._commands_synced:
            await self.sync_commands()
            self._commands_synced = True
        logger.info("Bot setup complete")
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        logger.info("------")
        # Ensure calendar loop is started (Pycord: cog on_ready runs after this)
        calendar_cog = self.get_cog("CalendarCog")
        if calendar_cog and hasattr(calendar_cog, "new_year_loop") and not calendar_cog.new_year_loop.is_running():
            calendar_cog.new_year_loop.start()
            logger.info("Started calendar new_year_loop from main on_ready")
    

def main():
    bot = WRPBot()
    logger.info("Setting up bot")
    # Pycord: load_extension is sync; load before run() so cogs are ready for on_ready
    for ext in ("cogs.calendar_cog", "cogs.admin_cog", "cogs.query_cog", "cogs.registration_cog"):
        bot.load_extension(ext)
        logger.info("Loaded extension: %s", ext)
    bot.run(os.getenv('TOKEN'))

if __name__ == "__main__":
    main() 
