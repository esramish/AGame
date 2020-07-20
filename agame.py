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

# connect to database
db = get_new_db_connection()

def get_cursor():
    global db
    if not db.is_connected():
        db = get_new_db_connection()
        print(f"Reconnected to database at {datetime.utcnow()}")
    return db.cursor(buffered=True)

# make sure certain database tables exist
with get_cursor() as cursor:
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id BIGINT PRIMARY KEY, username VARCHAR(255), balance INT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS guilds (id BIGINT PRIMARY KEY, guildname VARCHAR(255), currword VARCHAR(10), guessquitvotedeadline DATETIME)")

bot = commands.Bot(command_prefix=PREFIX)

# load 5-letter words
with open('5-letter_words.pkl', 'rb') as f:
    FIVE_LETTER_WORDS = pickle.load(f)

GAMES = ['guess']

# guess
WIN_GUESS_REWARD = 100
PLAY_GUESS_REWARD = 40

# codenames
NUM_CODEWORD_REQ_VOTES = 2
CODEWORD_VOTE_EMOJI = '👍'
CODEWORD_REWARD = 10

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

@bot.event
async def on_reaction_add(reaction, user):
    await codeword_reaction_checker(reaction, user)

@bot.event
async def on_reaction_remove(reaction, user):
    await codeword_reaction_checker(reaction, user)

async def codeword_reaction_checker(reaction, user):
    '''Given a reaction and the user who reacted, check if it was a codeword message reaction and process accordingly'''

    # make sure codewords table exists
    cursor = get_cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS codewords (id INT PRIMARY KEY AUTO_INCREMENT, suggestor BIGINT, suggestionmsg BIGINT, word VARCHAR(45), approved BIT)")

    # handle codeword vote reactions
    cursor.execute(f"SELECT id, suggestor, word, approved FROM codewords WHERE suggestionmsg = {int(reaction.message.id)}")
    query_result = cursor.fetchone()
    if query_result != None:

        # unpack query_result
        word_id, suggestor_id, word, approved = query_result
        
        # make sure it's not already approved
        if approved:
            cursor.close()
            return
        
        # count up all the non-AGame, non-suggestor users who have reacted to the message
        reacted_users = await reaction.users().flatten()
        filtered_reacted_users = list(filter(lambda u: not (u == bot.user or u.id == suggestor_id), reacted_users))
        further_reactions_needed = NUM_CODEWORD_REQ_VOTES - len(filtered_reacted_users)
        if further_reactions_needed == 0: # there are exactly (just another measure to help avoid doing this twice) enough votes for the word to pass:
            # mark the word as approved in the database
            cursor.execute(f"UPDATE codewords SET approved = 1 WHERE id = {word_id}")

            # reward the user
            cursor.execute(f"UPDATE users SET balance = balance + {CODEWORD_REWARD} WHERE id = {suggestor_id}")

            # commit
            db.commit()

            # send a message notifying of the approval and reward
            await reaction.message.channel.send(f"Added the word **{word}** to codenames. {CODEWORD_REWARD} copper to {bot.get_user(suggestor_id).display_name} for the suggestion!")
        if further_reactions_needed >= 0: 
            # update the message with the number of further reactions needed
            further_reactions_needed = NUM_CODEWORD_REQ_VOTES - len(filtered_reacted_users)
            await reaction.message.edit(content=f"React {CODEWORD_VOTE_EMOJI} to this message to approve the codenames word **{word}**! {further_reactions_needed} more vote{'s' if further_reactions_needed != 1 else ''} needed")

    cursor.close()

@bot.command(name='gimmeacopper', help='What could this be???')
async def onecopper(ctx):
    cursor = get_cursor()
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
    cursor.close()
    await ctx.send(f"Here ya go! Balance: {balance}")

@bot.command(name='balance', help='Checks how much money you have')
async def balance(ctx, user: discord.Member=None):
    cursor = get_cursor()
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
    cursor.close()
    await ctx.send(f"{user.name}'s balance: {balance}")

@balance.error
async def balance_error(ctx, error):
    if isinstance(error, commands.errors.BadArgument):
        await ctx.send(f"Use the format `{PREFIX}balance` to check your own balance, or use `{PREFIX}balance <user_mention>` (e.g. `{PREFIX}balance `<@!{bot.user.id}>` `) to check someone else's.")
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
    
    cursor = get_cursor()

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
            cursor.close()
            return

    # here, we started a new game but haven't told the user anything yet
    cursor.close()
    await ctx.send(f"New {game} game started! Use `{PREFIX}guess <word>` to guess a word, or `{PREFIX}quit guess` to initiate a vote to quit the game.")

@start_game.error
async def start_game_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}start <game>` (e.g. `{PREFIX}start guess`) to start a game.")
    else: raise error

@bot.command(name='guess', help='Guesses a word in the 5-letter-word guessing game')
async def guess(ctx, guess):
    
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send(f"Using this command in a private chat is not allowed.")
        return
    
    cursor = get_cursor()

    guild_name = sql_escape_single_quotes(ctx.guild.name)
    cursor.execute(f"SELECT currword FROM guilds where id={ctx.guild.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # guild is not in the guilds table yet, so complain to the user. We won't bother adding the guild to the guilds table here
        await ctx.send(f"There's no word-guessing game happening right now. Use `{PREFIX}start guess` to start one.")
        cursor.close()
        return
    else:
        if query_result[0][0] == None: # the guild is in the database but doesn't have a current word, so complain to the user
            await ctx.send(f"There's no word-guessing game happening right now. Use `{PREFIX}start guess` to start one.")
            cursor.closee()
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

        # commit and close
        db.commit()
        cursor.close()
        
        # send message to context
        await ctx.send(f"<@!{ctx.author.id}>, you guessed it! The word was **{word}**. You win {WIN_GUESS_REWARD} copper! {mentions_string}")
        await ctx.send(f"Good game! Use `{PREFIX}start guess` to start another.")
    else: # not a winning guess
        cursor.close()
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

    cursor = get_cursor()

    # get info about the current states of the game/vote countdown in question
    # start by checking if the guild is in the guilds table
    cursor.execute(f"SELECT currword FROM guilds WHERE id={ctx.guild.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # guild's not in the guilds table yet, which means there isn't a game going. We won't bother adding them here
        await ctx.send(f"There's no {game} game going right now.")
        cursor.close()
        return
    
    # okay, the guild is in the guilds table. Figure out if a game is going
    if game == 'guess':
        game_going = query_result[0][0] != None
    # we can add more games with elifs here
    if not game_going:
        await ctx.send(f"There's no {game} game going on right now.")
        cursor.close()
        return
    
    # okay, the game in question is going. Is there already a countdown to stop it?
    cursor.execute(f"SELECT {game}quitvotedeadline FROM guilds WHERE id={ctx.guild.id}")
    deadline = cursor.fetchone()[0]
    if deadline == None: # there is no countdown going
        # if the user voted no for some reason, don't start a countdown or store their vote
        if vote.lower() == 'no':
            await ctx.send(f"{ctx.author.name}, no one has voted to end this game yet anyway")
            cursor.close()
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
        deadline = datetime.strftime(datetime.utcnow() + timedelta(minutes=1), '%Y-%m-%d %H:%M:%S')
        cursor.execute(f"UPDATE guilds SET {game}quitvotedeadline = '{deadline}' where id={ctx.guild.id}")
        
        db.commit()
        cursor.close()

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
    cursor.close()
    
    await ctx.send(f"{ctx.author.name} votes to **{'quit' if wants_to_quit else 'continue'}** the {game} game")

async def quit_timer(ctx, game):
    await asyncio.sleep(60)
    
    cursor = get_cursor()

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
    
    cursor.close()

@quit_game.error
async def quit_game_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}quit <game>` (e.g. `{PREFIX}quit guess`) to quit a game.")
    else: raise error

@bot.command(help='Suggests a word to be added to the list of codenames words')
async def codeword(ctx, word):
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send(f"Using this command in a private chat is not allowed.")
        return
    
    # make sure table exists
    cursor = get_cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS codewords (id INT PRIMARY KEY AUTO_INCREMENT, suggestor BIGINT, suggestionmsg BIGINT, word VARCHAR(45), approved BIT, suggestion_time DATETIME)")
    
    # format word, and escape word for SQL
    word = word.lower()
    unescaped_word = word
    word = sql_escape_single_quotes(word)
    
    # check if word was recently suggested or already approved
    cursor.execute(f"SELECT suggestion_time, approved FROM codewords WHERE word='{word}'")
    query_result = cursor.fetchone()
    if query_result != None:
        suggestion_time, approved = query_result
        if approved:
            await ctx.send(f"Someone already added the word **{unescaped_word}**")
            cursor.close()
            return
        elif datetime.utcnow() - suggestion_time < timedelta(days=1):
            await ctx.send(f"Someone already suggested the word **{unescaped_word}**. If it still isn't approved in 24 hours, try suggesting it again")
            cursor.close()
            return
        else: # there is an entry for this word in the database, but it's old an unapproved, so let's delete it and let the user add a new one
            cursor.execute(f"DELETE FROM codewords WHERE word='{word}'")
            db.commit()

    # send voting message
    message = await ctx.send(f"React {CODEWORD_VOTE_EMOJI} to this message to approve the codenames word **{word}**! {NUM_CODEWORD_REQ_VOTES} more vote{'s' if NUM_CODEWORD_REQ_VOTES != 1 else ''} needed")
    await message.add_reaction(CODEWORD_VOTE_EMOJI)

    # insert word candidate into database
    cursor.execute(f"INSERT INTO codewords (suggestor, suggestionmsg, word, approved, suggestion_time) VALUES ({int(ctx.author.id)}, {int(message.id)}, '{word}', 0, '{datetime.strftime(datetime.utcnow(), '%Y-%m-%d %H:%M:%S')}')")
    db.commit()
    cursor.close()

@codeword.error
async def codeword_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}codeword <word>` (e.g. `{PREFIX}codeword computer`) to suggest a codenames word.")
    else: raise error

def sql_escape_single_quotes(string):
    return string.replace("'", "''")

def sql_unescape_single_quotes(string):
    return string.replace("''", "'")

bot.run(TOKEN)