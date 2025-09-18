# bot/bot.py
import os
import discord
from dotenv import load_dotenv
from src.pipeline import answer

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.content.startswith("!ask "):
        query = message.content[len("!ask "):].strip()
        try:
            resp = answer(query)
        except Exception as e:
            resp = f"Error: {e}"
        await message.channel.send(resp)

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN not set in .env")
    client.run(TOKEN)
