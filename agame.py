import os
import pickle
import random
from datetime import datetime, timedelta
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = os.getenv('AGAME_PREFIX')

import mysql.connector 

def get_new_db_connection():
    '''Connect to the database using the values specified in the environment. Implemented as a function so that it can be called easily in other places when it's discovered that the connection was lost/ended.'''
    return mysql.connector.connect(
        host=os.getenv('AGAME_DB_IP'),
        user=os.getenv('AGAME_DB_USERNAME'),
        password=os.getenv('AGAME_DB_PASSWORD'),
        database=os.getenv('AGAME_DB_DBNAME')
    )

db = get_new_db_connection()

cursor = db.cursor(buffered=True)


cursor.execute("CREATE TABLE IF NOT EXISTS users (id BIGINT PRIMARY KEY, username VARCHAR(255), balance INT)")
cursor.execute("CREATE TABLE IF NOT EXISTS guilds (id BIGINT PRIMARY KEY, guildname VARCHAR(255), currword VARCHAR(10), guessquitvotedeadline DATETIME)")

bot = commands.Bot(command_prefix=PREFIX)

# load 5-letter words
with open('5-letter_words.pkl', 'rb') as f:
    FIVE_LETTER_WORDS = pickle.load(f)

GAMES = ['guess']

WIN_GUESS_REWARD = 100
PLAY_GUESS_REWARD = 40

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

@bot.command(name='gimmeacopper', help='What could this be???')
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

@bot.command(name='balance', help='Checks how much money you have')
async def balance(ctx, user: discord.Member=None):
    if user==None: 
        user = ctx.author
    username = sql_escape_single_quotes(user.name)
    cursor.execute(f"SELECT balance FROM users where id={user.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # user's not in the database yet, so add them in with balance of 0
        cursor.execute(f"INSERT INTO users (id, username, balance) VALUES ({user.id}, '{username}', 0)")
        db.commit()
        balance = 0
    else:
        balance = query_result[0][0]
    await ctx.send(f"{user.name}'s balance: {balance}")

@balance.error
async def balance_error(ctx, error):
    if isinstance(error, commands.errors.BadArgument):
        await ctx.send(f"Use the format `{PREFIX}balance` to check your own balance, or use `{PREFIX}balance <user_mention>` (e.g. `{PREFIX}balance `<@!{bot.user.id}>` `) to check someone else's.")
    elif not db.is_connected():
        db = get_new_db_connection()
        if db.is_connected():
            print(f"Reconnected to database at {datetime.now()}")
            ctx.send("Sorry, I was snoozing! Could you give your command again, please?")
        else:
            print(f"Failed to reconnect to database at {datetime.now()}")
            ctx.send("Sorry, there's been an internal error")
    else: raise error

@bot.command(name='listgames', help="Lists all the games the bot currently provides")
async def list_games(ctx):
    await ctx.send(', '.join(GAMES))

@bot.command(name='start', help='Starts a new game')
async def start_game(ctx, game):
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send(f"Using this command in a private chat is not allowed.")
        return
    
    # check if valid command
    if game not in GAMES:
        await ctx.send(f"**{game}** is not a game that can be started")
        return
    
    # make sure the guild users table exists for this guild
    cursor.execute(f"CREATE TABLE IF NOT EXISTS guild{ctx.guild.id}users (id BIGINT PRIMARY KEY, username VARCHAR(255), playingguess BIT, votetoquitguess BIT)")

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
            await ctx.send(f"There's already a {game} game going on.")
            if game=='guess':
                await ctx.send(f"Use `{PREFIX}guess <word>` to guess a word.")
            return
    
    # here, we started a new game but haven't told the user anything yet
    await ctx.send(f"New {game} game started! Use `{PREFIX}guess <word>` to guess a word, or `{PREFIX}quit guess` to initiate a vote to quit the game.")

@start_game.error
async def start_game_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}start <game>` (e.g. `{PREFIX}start guess`) to start a game.")
    elif not db.is_connected():
        db = get_new_db_connection()
        if db.is_connected():
            print(f"Reconnected to database at {datetime.now()}")
            ctx.send("Sorry, I was snoozing! Could you give your command again, please?")
        else:
            print(f"Failed to reconnect to database at {datetime.now()}")
            ctx.send("Sorry, there's been an internal error")
    else: raise error

@bot.command(name='guess', help='Guesses a word in the 5-letter-word guessing game')
async def guess(ctx, guess):
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send(f"Using this command in a private chat is not allowed.")
        return
    
    guild_name = sql_escape_single_quotes(ctx.guild.name)
    cursor.execute(f"SELECT currword FROM guilds where id={ctx.guild.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # guild is not in the guilds table yet, so complain to the user. We won't bother adding the guild to the guilds table here
        await ctx.send(f"There's no word-guessing game happening right now. Use `{PREFIX}start guess` to start one.")
        return
    else:
        if query_result[0][0] == None: # the guild is in the database but doesn't have a current word, so complain to the user
            await ctx.send(f"There's no word-guessing game happening right now. Use `{PREFIX}start guess` to start one.")
            return
    
    # okay, there is indeed a game going on at this point
    # use the word that's currently in the database for this guild
    word = query_result[0][0]

    # make sure the user gets credit for participating in this game
    cursor.execute(f"SELECT * FROM guild{ctx.guild.id}users WHERE id = {ctx.author.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0:
        cursor.execute(f"INSERT INTO guild{ctx.guild.id}users (id, username, playingguess) VALUES ({ctx.author.id}, '{sql_escape_single_quotes(ctx.author.name)}', 1)")
    else:
        cursor.execute(f"UPDATE guild{ctx.guild.id}users SET playingguess = 1 WHERE id = {ctx.author.id}")
    
    # and make sure the user is in the users table, so they can be rewarded at game end
    author = sql_escape_single_quotes(ctx.author.name)
    cursor.execute(f"SELECT balance FROM users where id={ctx.author.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # user's not in the users table yet, so add them in with balance of 0
        cursor.execute(f"INSERT INTO users (id, username, balance) VALUES ({ctx.author.id}, '{author}', 0)")
    db.commit()

    # evaluate the guess
    if guess == word: # winning guess!
        cursor.execute(f"UPDATE guilds SET currword = NULL WHERE id = {ctx.guild.id}")
        
        # reward winner 
        cursor.execute(f"UPDATE users SET balance = balance + {WIN_GUESS_REWARD} WHERE id = {ctx.author.id}")

        # record other participants, for the sake of the message that'll be sent
        cursor.execute(f"SELECT id FROM guild{ctx.guild.id}users WHERE (NOT id = {ctx.author.id}) AND playingguess = 1")
        other_players_query = cursor.fetchall()
        if len(other_players_query) > 0:
            other_players = list(map(lambda player_tuple: str(player_tuple[0]), other_players_query)) # convert from list of 1-tuples to list of strings
            mentions_string = "<@!" + ">, <@!".join(other_players) + f">: you win {PLAY_GUESS_REWARD} copper! "
        else:
            mentions_string = ""

        # reward other participants
        cursor.execute(f"UPDATE users SET balance = balance + {PLAY_GUESS_REWARD} WHERE (NOT id = {ctx.author.id}) AND id IN (SELECT id FROM guild{ctx.guild.id}users WHERE playingguess = 1)")
        
        # reset the list of who is playing the guess game
        cursor.execute(f"UPDATE guild{ctx.guild.id}users SET playingguess = NULL")

        # commit
        db.commit()
        
        # send message to context
        await ctx.send(f"<@!{ctx.author.id}>, you guessed it! The word was **{word}**. You win {WIN_GUESS_REWARD} copper! {mentions_string}")
        await ctx.send(f"Good game! Use `{PREFIX}start guess` to start another.")
    else: # not a winning guess
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
        await ctx.send(f"Use the format `{PREFIX}guess <word>` to guess a word.")
    elif not db.is_connected():
        db = get_new_db_connection()
        if db.is_connected():
            print(f"Reconnected to database at {datetime.now()}")
            ctx.send("Sorry, I was snoozing! Could you give your command again, please?")
        else:
            print(f"Failed to reconnect to database at {datetime.now()}")
            ctx.send("Sorry, there's been an internal error")
    else: raise error

@bot.command(name='quit', help='Initiates a vote to quit a current game')
async def quit_game(ctx, game, vote='yes'):
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send(f"Using this command in a private chat is not allowed.")
        return

    # check if valid command
    if game not in GAMES:
        await ctx.send(f"**{game}** is not a game that can be quit")
        return

    # get info about the current states of the game/vote countdown in question
    # start by checking if the guild is in the guilds table
    cursor.execute(f"SELECT currword FROM guilds WHERE id={ctx.guild.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # guild's not in the guilds table yet, which means there isn't a game going. We won't bother adding them here
        await ctx.send(f"There's no {game} game going right now.")
        return
    
    # okay, the guild is in the guilds table. Figure out if a game is going
    if game == 'guess':
        game_going = query_result[0][0] != None
    # we can add more games with elifs here
    if not game_going:
        await ctx.send(f"There's no {game} game going on right now.")
        return
    
    # okay, the game in question is going. Is there already a countdown to stop it?
    cursor.execute(f"SELECT {game}quitvotedeadline FROM guilds WHERE id={ctx.guild.id}")
    deadline = cursor.fetchone()[0]
    if deadline == None: # there is no countdown going
        # if the user voted no for some reason, don't start a countdown or store their vote
        if vote.lower() == 'no':
            await ctx.send(f"{ctx.author.name}, no one has voted to end this game yet anyway")
            return
        
        # set all votes to null, except the person who gave the command
        cursor.execute(f"UPDATE guild{ctx.guild.id}users SET votetoquit{game} = NULL")
        db.commit()
        cursor.execute(f"SELECT * from guild{ctx.guild.id}users WHERE id = {ctx.author.id}")
        query_result = cursor.fetchall()
        if len(query_result) == 0:
            cursor.execute(f"INSERT INTO guild{ctx.guild.id}users (id, username, votetoquit{game}) VALUES ({ctx.author.id}, '{sql_escape_single_quotes(ctx.author.name)}', 1)")
        else:
            cursor.execute(f"UPDATE guild{ctx.guild.id}users SET votetoquit{game} = 1 WHERE id = {ctx.author.id}")
        
        # enter the voting deadline
        deadline = datetime.strftime(datetime.now() + timedelta(minutes=1), '%Y-%m-%d %H:%M:%S')
        cursor.execute(f"UPDATE guilds SET {game}quitvotedeadline = '{deadline}' where id={ctx.guild.id}")
        
        db.commit()

        # send a message to the context
        await ctx.send(f"**{ctx.author.name} votes to end the {game} game.** Use `{PREFIX}quit {game} <yes/no>` to vote for or against quitting the game. Votes will be tallied in 1 minute")

        # start the timer
        await quit_timer(ctx, game)

        # return, so the rest of the function doesn't run once the vote is done
        return
    
    # there was already a countdown going, so just record the author's vote
    if vote.lower() == 'yes': 
        wants_to_quit = 1
    elif vote.lower() == 'no':
        wants_to_quit = 0
    else:
        await ctx.send(f"{ctx.author.name}, I don't understand your vote. Please use the format `{PREFIX}quit {game} <yes/no>`")
        return
    # record vote
    cursor.execute(f"SELECT * from guild{ctx.guild.id}users WHERE id = {ctx.author.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0:
        cursor.execute(f"INSERT INTO guild{ctx.guild.id}users (id, username, votetoquit{game}) VALUES ({ctx.author.id}, '{sql_escape_single_quotes(ctx.author.name)}', {wants_to_quit})")
    else:
        cursor.execute(f"UPDATE guild{ctx.guild.id}users SET votetoquit{game} = {wants_to_quit} WHERE id = {ctx.author.id}")
    db.commit()
    await ctx.send(f"{ctx.author.name} votes to **{'quit' if wants_to_quit else 'continue'}** the {game} game")

async def quit_timer(ctx, game):
    await asyncio.sleep(60)
    
    # clear deadline in database
    cursor.execute(f"UPDATE guilds SET {game}quitvotedeadline = NULL where id={ctx.guild.id}")
    db.commit()
    
    # address the results
    cursor.execute(f"SELECT votetoquit{game} FROM guild{ctx.guild.id}users")
    results = cursor.fetchall()
    yeas = list(filter(lambda query_row: query_row[0] == 1, results))
    neas = list(filter(lambda query_row: query_row[0] == 0, results))
    if len(yeas) > len(neas):   
        await ctx.send(f"Time's up! The people have spoken: they've voted {len(yeas)}-{len(neas)} to **quit** the {game} game. Use `{PREFIX}start {game}` to start a new one")
        if game=='guess':
            # reset the list of who is playing the guess game
            cursor.execute(f"UPDATE guild{ctx.guild.id}users SET playingguess = NULL")
            
            # send the secret word in a message, then clear the word
            cursor.execute(f"SELECT currword FROM guilds WHERE id={ctx.guild.id}")
            await ctx.send(f"My word was **{cursor.fetchone()[0]}**")
            cursor.execute(f"UPDATE guilds SET currword = NULL where id={ctx.guild.id}")
            db.commit()
    else: 
        await ctx.send(f"Time's up! The people have spoken: they've voted {len(neas)}-{len(yeas)} to **continue** the {game} game.")

@quit_game.error
async def quit_game_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}quit <game>` (e.g. `{PREFIX}quit guess`) to quit a game.")
    elif not db.is_connected():
        db = get_new_db_connection()
        if db.is_connected():
            print(f"Reconnected to database at {datetime.now()}")
            ctx.send("Sorry, I was snoozing! Could you give your command again, please?")
        else:
            print(f"Failed to reconnect to database at {datetime.now()}")
            ctx.send("Sorry, there's been an internal error")
    else: raise error

def sql_escape_single_quotes(string):
    return string.replace("'", "''")

def sql_unescape_single_quotes(string):
    return string.replace("''", "'")

bot.run(TOKEN)