import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import json
from datetime import datetime
from cogs.calendar_cog import CalendarCog
from cogs.admin_cog import AdminCog
from cogs.query_cog import QueryCog

load_dotenv()

class WRPBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(
            command_prefix="C!",  # Works with both prefix and slash commands
            intents=intents
        )
        
        # Initialize pending_calendars.json if it doesn't exist
        if not os.path.exists('pending_calendars.json'):
            with open('pending_calendars.json', 'w') as f:
                json.dump({"pending_submissions": []}, f, indent=2)
        
    async def on_ready(self):
        await self.sync_commands()
        calendar_cog = CalendarCog(self)
        calendar_cog.new_year_loop.start()
        print("Bot setup complete!")
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')
    

def main():
    bot = WRPBot()
    print("Setting up bot...")
    
    bot.load_extensions('cogs.calendar_cog', 'cogs.admin_cog', 'cogs.query_cog')
    
    bot.run(os.getenv('TOKEN'))

if __name__ == "__main__":
    main() 