import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

import mysql.connector 


db = mysql.connector.connect(
    host=os.getenv('AGAME_DB_IP'),
    user=os.getenv('AGAME_DB_USERNAME'),
    password=os.getenv('AGAME_DB_PASSWORD'),
    database=os.getenv('AGAME_DB_DBNAME')
)

cursor = db.cursor(buffered=True)

try: 
    cursor.execute("SELECT * FROM balances")
except: 
    cursor.execute("CREATE TABLE balances (id INT AUTO_INCREMENT PRIMARY KEY, username VARCHAR(255), balance INT)")
    
# client = discord.Client()
bot = commands.Bot(command_prefix='...')

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

@bot.command(name='gimmeacopper')
async def onecopper(ctx):
    cursor.execute(f"SELECT balance FROM balances where username='{ctx.message.author}'")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # user's not in the database yet, so add them in with balance of 1
        cursor.execute(f"INSERT INTO balances (username, balance) VALUES ('{ctx.message.author}', 1)")
        balance = 1
    else:
        cursor.execute(f"UPDATE balances SET balance = balance + 1 WHERE username = '{ctx.message.author}'")
        balance = query_result[0][0] + 1
    db.commit()
    await ctx.send(f"Here ya go! Balance: {balance}")

bot.run(TOKEN)