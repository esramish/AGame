import os
import pickle
import random

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = os.getenv('AGAME_PREFIX')

import mysql.connector 


db = mysql.connector.connect(
    host=os.getenv('AGAME_DB_IP'),
    user=os.getenv('AGAME_DB_USERNAME'),
    password=os.getenv('AGAME_DB_PASSWORD'),
    database=os.getenv('AGAME_DB_DBNAME')
)

cursor = db.cursor(buffered=True)

try: 
    cursor.execute("SELECT * FROM users")
except: 
    cursor.execute("CREATE TABLE users (id BIGINT PRIMARY KEY, username VARCHAR(255), balance INT)")
try:
    cursor.execute("SELECT * FROM guilds")
except: 
    cursor.execute("CREATE TABLE guilds (id BIGINT PRIMARY KEY, guildname VARCHAR(255), currword VARCHAR(10))")
    
# client = discord.Client()
bot = commands.Bot(command_prefix=PREFIX)

# load 5-letter words
with open('5-letter_words.pkl', 'rb') as f:
    FIVE_LETTER_WORDS = pickle.load(f)

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

@bot.command(name='gimmeacopper')
async def onecopper(ctx):
    author = sql_escape_single_quotes(ctx.author.name)
    cursor.execute(f"SELECT balance FROM users where id={ctx.author.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # user's not in the database yet, so add them in with balance of 1
        cursor.execute(f"INSERT INTO users (id, username, balance) VALUES ({ctx.author.id}, '{author}', 1)")
        balance = 1
    else:
        cursor.execute(f"UPDATE users SET balance = balance + 1 WHERE id = {ctx.author.id}")
        balance = query_result[0][0] + 1
    db.commit()
    await ctx.send(f"Here ya go! Balance: {balance}")

@bot.command(name='startguess')
async def startguess(ctx):
    guild_name = sql_escape_single_quotes(ctx.guild.name)
    cursor.execute(f"SELECT currword FROM guilds where id={ctx.guild.id}")
    query_result = cursor.fetchall()
    word = random.choice(FIVE_LETTER_WORDS)
    if len(query_result) == 0: # guild's not in the database yet, so add them in with a new word
        cursor.execute(f"INSERT INTO guilds (id, guildname, currword) VALUES ({ctx.guild.id}, '{guild_name}', '{word}')")
        db.commit()
    else:
        if query_result[0][0] == None: # ideal case, where they just want to start a new game
            cursor.execute(f"UPDATE guilds SET currword = '{word}' where id = {ctx.guild.id}")
            db.commit()
        else: # there's already a game going on, so complain to the user
            await ctx.send(f"There's already a word-guessing game going on. Use `{PREFIX}guess word` to guess a word.")
            return
    
    # here, we started a new game but haven't told the user anything yet
    await ctx.send(f"New word-guessing game started! Use `{PREFIX}guess word` to guess a word.")


@bot.command(name='guess')
async def guess(ctx, guess):
    guild_name = sql_escape_single_quotes(ctx.guild.name)
    cursor.execute(f"SELECT currword FROM guilds where id={ctx.guild.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # guild's not in the database yet, so add them in with a null word, then complain to the user
        cursor.execute(f"INSERT INTO guilds (id, guildname) VALUES ({ctx.guild.id}, '{guild_name}')")
        db.commit()
        await ctx.send(f"There's no word-guessing game happening right now. Use `{PREFIX}startguess` to start one.")
        return
    else:
        if query_result[0][0] == None: # the guild is in the database but doesn't have a current word, so complain to the user
            await ctx.send(f"There's no word-guessing game happening right now. Use `{PREFIX}startguess` to start one.")
            return
    
    # okay, there is indeed a game going on at this point
    # use the word that's currently in the database for this guild
    word = query_result[0][0]
    
    if guess == word:
        cursor.execute(f"UPDATE guilds SET currword = NULL where id = {ctx.guild.id}")
        db.commit()
        await ctx.send(f"<@!{ctx.author.id}> guessed it! The word was **{word}**. Good game! Use `{PREFIX}startguess` to start another.")
    else:
        await evaluate_word_guess(ctx, word, guess)

async def evaluate_word_guess(ctx, word, guess):
    # check for valid guess
    # check for exactly 5 letters
    if len(guess) != 5:
        await ctx.send(f"Invalid guess. **{guess}** doesn't have exactly five letters")
        return
    # check for no duplicates
    chars = set()
    for char in guess:
        chars.add(char)
    if len(chars) != 5:
        await ctx.send(f"Invalid guess. **{guess}** has a duplicate letter")
        return
    # check if it's a recognized word
    if guess not in FIVE_LETTER_WORDS:
        await ctx.send(f"I don't recognize the word **{guess}**")
        return
    
    # okay, it is a valid guess, so respond to the user with how many letters in common
    num_common_letters = 0
    for char in word:
        num_common_letters += char in guess
    s = "" if num_common_letters == 1 else "s"
    ending = ", but that's not it!" if num_common_letters == 5 else "."
    await ctx.send(f"The word **{guess}** shares **{num_common_letters}** letter{s} with my word{ending}")

@guess.error
async def guess_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}guess word` to guess a word.")

def sql_escape_single_quotes(string):
    return string.replace("'", "''")

def sql_unescape_single_quotes(string):
    return string.replace("''", "'")

bot.run(TOKEN)