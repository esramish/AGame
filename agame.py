##### IMPORTS AND SETUP #####

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
        database=os.getenv('AGAME_DB_DBNAME'),
        autocommit=True
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
    cursor.execute("CREATE TABLE IF NOT EXISTS guilds (id BIGINT PRIMARY KEY, guildname VARCHAR(255), currword VARCHAR(10), guessquitvotedeadline DATETIME, codenamesstartmsg BIGINT, codenamesquitvotedeadline DATETIME)")
    cursor.execute("CREATE TABLE IF NOT EXISTS members (id INT PRIMARY KEY AUTO_INCREMENT, user BIGINT NOT NULL, guild BIGINT NOT NULL, votetoquitguess BIT, playingguess BIT, votetoquitcodenames BIT, codenamesroleandcolor VARCHAR(25))")
    cursor.execute("CREATE TABLE IF NOT EXISTS codewords (id INT PRIMARY KEY AUTO_INCREMENT, suggestor BIGINT, suggestionmsg BIGINT, word VARCHAR(45), approved BIT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS activeCodewords (id INT PRIMARY KEY AUTO_INCREMENT, guild BIGINT, word VARCHAR(45), color varchar(10), revealed BIT, position FLOAT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS codenamesGames (id INT PRIMARY KEY AUTO_INCREMENT, guild BIGINT, opsChannel BIGINT, turn VARCHAR(25), numClued INT, numGuessed INT)")

bot = commands.Bot(command_prefix=PREFIX)

# load 5-letter words
with open('5-letter_words.pkl', 'rb') as f:
    FIVE_LETTER_WORDS = pickle.load(f)

GAMES = ['guess', 'codenames']
CANCELABLE_GAMES = ['codenames']

# guess
WIN_GUESS_REWARD = 100
PLAY_GUESS_REWARD = 40

# codenames
NUM_CODEWORD_REQ_VOTES = 2
CODEWORD_VOTE_EMOJI = '👍'
CODEWORD_REWARD = 10
BLUE_SPY_EMOJI = '🖌'
RED_SPY_EMOJI = '📕'
BLUE_OP_EMOJI = '💙'
RED_OP_EMOJI = '🔴'
CODENAMES_EMOJIS = [BLUE_SPY_EMOJI, RED_SPY_EMOJI, BLUE_OP_EMOJI, RED_OP_EMOJI]
WIN_CODENAMES_REWARD = 100
PLAY_CODENAMES_REWARD = 40
DOUBLE_AGENT_REWARD = (WIN_CODENAMES_REWARD + PLAY_CODENAMES_REWARD) // 2

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

##### REACTIONS #####

@bot.event
async def on_reaction_add(reaction, user):
    await codeword_reaction_checker(reaction, user)

@bot.event
async def on_reaction_remove(reaction, user):
    await codeword_reaction_checker(reaction, user)

async def codeword_reaction_checker(reaction, user):
    '''Given a reaction and the user who reacted, check if it was a codeword message reaction and process accordingly'''

    # check if the reaction in question is the codeword vote emoji
    if reaction.emoji != CODEWORD_VOTE_EMOJI: return

    cursor = get_cursor()

    # see if it was a reaction to a codeword suggestion message
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

##### BALANCE AND COPPER COMMANDS #####

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

##### LISTGAMES #####

@bot.command(name='listgames', help="Lists all the games the bot currently provides")
async def list_games(ctx):
    await ctx.send(', '.join(GAMES))

##### START #####

@bot.command(name='start', help='Starts a new game')
async def start_game(ctx, game):
    
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send("Using this command in a private chat is not allowed.")
        return
    
    # check if valid command
    if game not in GAMES:
        await ctx.send(f"**{game}** is not a game that can be started")
        return

    if game=='guess':
        await start_guess(ctx)
    elif game=='codenames':
        await start_codenames(ctx)

async def start_guess(ctx):
    cursor = get_cursor()
    
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
            await ctx.send(f"There's already a guess game going on. Use `{PREFIX}guess <word>` to guess a word.")
            cursor.close()
            return

    # here, we started a new game but haven't told the user anything yet
    cursor.close()
    await ctx.send(f"New guess game started! Use `{PREFIX}guess <word>` to guess a word, or `{PREFIX}quit guess` to initiate a vote to quit the game.")

async def start_codenames(ctx):
    cursor = get_cursor()
    guild_id = int(ctx.guild.id)
    guild_name = sql_escape_single_quotes(ctx.guild.name)

    # make sure there's not already a game going
    cursor.execute(f"SELECT * FROM activeCodewords WHERE guild = {guild_id}")
    query_result = cursor.fetchone()
    if query_result != None:
        await ctx.send("There's already a codenames game in progress on this server--sorry!")
        cursor.close()
        return

    cursor.execute(f"SELECT codenamesstartmsg FROM guilds WHERE id = {guild_id}")
    query_result = cursor.fetchone()
    
    if query_result == None: # make sure the guild is in the guilds table
        cursor.execute(f"INSERT INTO guilds (id, guildname) VALUES ({ctx.guild.id}, '{guild_name}')")
        db.commit()
    elif query_result[0] != None: # make sure there's not already a start-game going
        await ctx.send(f"It seems someone else is already trying to start codenames on this server. If this is not the case, use `{PREFIX}cancel codenames` before giving this command again")
        cursor.close()
        return

    # send a message indicating the allowed role combiniations and seeking reactions to assign roles
    embed = discord.Embed(title="Welcome to Codenames!", description=f"Following the instructions in the `Role Reactions` section, everyone who wants to play must assign themselves a role. No more than one spymaster of either color. If only one spymaster is selected, you'll play a cooperative game; if both are selected, you'll play a competitive game. Use `{PREFIX}begin codenames` to begin the game once everyone is ready.", color=16711935) # magenta
    embed.add_field(name="Role Reactions", value=f"React with the role you want to have in this game: \n\n{BLUE_SPY_EMOJI} - blue spymaster \n{RED_SPY_EMOJI} - red spymaster \n{BLUE_OP_EMOJI} - blue operatives \n{RED_OP_EMOJI} - red operatives \n\nIf there is only one spymaster, it doesn't matter which of the two operative reactions everyone else selects. Two spymasters and only one operative means the operative guesses for both teams.", inline=False)
    embed.set_footer(text=f"Use \"{PREFIX}cancel codenames\" to cancel game start")
    message = await ctx.send(embed=embed)

    # get the id of this message and store it in the guilds table
    cursor.execute(f"UPDATE guilds SET codenamesstartmsg = {int(message.id)} WHERE id = {guild_id}")
    db.commit()

    # set up the reactions
    await message.add_reaction(BLUE_SPY_EMOJI)
    await message.add_reaction(RED_SPY_EMOJI)
    await message.add_reaction(BLUE_OP_EMOJI)
    await message.add_reaction(RED_OP_EMOJI)

    cursor.close()

@start_game.error
async def start_game_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}start <game>` (e.g. `{PREFIX}start guess`) to start a game.")
    else: raise error

##### BEGIN #####

@bot.command(name='begin', help='Begins a game that has been set up')
async def begin_game(ctx, game):
    
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send("Using this command in a private chat is not allowed.")
        return

    # check if valid command
    if game not in CANCELABLE_GAMES:
        await ctx.send(f"**{game}** is not a game that can be \"begun.\" If you're simply trying to start a game, use `{PREFIX}start {game}`")
        return

    cursor = get_cursor()

    # get info about the current state of the game
    # start by checking if the guild is in the guilds table
    cursor.execute(f"SELECT codenamesstartmsg FROM guilds WHERE id={ctx.guild.id}")
    query_result = cursor.fetchone()
    if query_result == None: # guild's not in the guilds table yet, which means there isn't a game in the process of starting. We won't bother adding them here
        await ctx.send(f"There's no {game} game in the process of starting right now.")
        cursor.close()
        return
    
    cursor.close()

    # okay, if there's a game starting, cancel it and send an informative message
    game_begun = False
    if game=='codenames':
        if query_result[0] != None:
            game_begun = True
            await begin_codenames(ctx, query_result[0])
    # can add more games with elifs here

    if not game_begun:
        await ctx.send(f"There is no {game} game in the process of starting right now. If you're trying to start that process, use `{PREFIX}start {game}`")

async def begin_codenames(ctx, start_msg_id):
    
    guild_id = int(ctx.guild.id)

    # get lists of users who have given each reaction
    message = await ctx.fetch_message(start_msg_id)
    players = set()
    num_role_reactions = 0
    role_lists = {}
    for reaction in message.reactions:
        users = await reaction.users().flatten()
        filtered_users = list(filter(lambda u: u != bot.user, users))
        if reaction.emoji in CODENAMES_EMOJIS:
            role_lists[reaction.emoji] = filtered_users
            players.update(filtered_users)
            num_role_reactions += len(filtered_users)

    # make sure no one's chosen more than one role
    if len(players) != num_role_reactions:
        await ctx.send(f"Someone chose more than one role! Please review your reactions, then use `{PREFIX}begin codenames` again once everyone has selected only one role.")
        return

    # make sure there is at least 1 spymaster and 1 operative
    if len(role_lists[BLUE_SPY_EMOJI]) == 0 and len(role_lists[RED_SPY_EMOJI]) == 0:
        await ctx.send(f"There needs to be at least one spymaster. Use `{PREFIX}begin codenames` again once someone has selected a spymaster role.")
        return
    if len(role_lists[BLUE_OP_EMOJI]) == 0 and len(role_lists[RED_OP_EMOJI]) == 0:
        await ctx.send(f"There needs to be at least one operative. Use `{PREFIX}begin codenames` again once someone has selected an operative role.")
        return

    # make sure there is no more than one spymaster of either color
    if len(role_lists[BLUE_SPY_EMOJI]) > 1 or len(role_lists[RED_SPY_EMOJI]) > 1:
        await ctx.send(f"There can be no more than one spymaster of either color. Use `{PREFIX}begin codenames` again once this condition is satisfied.")
        return

    # if there are two spymasters and multiple operatives, make sure there's at least one operative of both colors
    if len(role_lists[BLUE_SPY_EMOJI]) + len(role_lists[RED_SPY_EMOJI]) > 1 and len(role_lists[BLUE_OP_EMOJI]) + len(role_lists[RED_OP_EMOJI]) > 1:
        if len(role_lists[BLUE_OP_EMOJI]) == 0 or len(role_lists[RED_OP_EMOJI]) == 0:
            await ctx.send(f"A game with two spymasters and multiple operatives must have at least one blue and one red operative. Use `{PREFIX}begin codenames` again once this condition is satisfied.")
            return

    # make sure no user is already in a codenames game on another server
    cursor = get_cursor()
    comma_separated_player_ids = comma_separated_ids_from_user_list(players)
    cursor.execute(f"SELECT user FROM members WHERE user IN ({comma_separated_player_ids}) AND codenamesroleandcolor IS NOT NULL")
    query_result = cursor.fetchall()
    if len(query_result) > 0:
        already_playing_ids = list(map(lambda player_tuple: str(player_tuple[0]), query_result)) # convert from list of 1-tuples to list of strings
        await ctx.send(f"{mention_string_from_ids(already_playing_ids)}: you are already in a codenames game. Playing multiple codenames games at once, even on different servers, is not currently supported.")
        await ctx.send(f"Use `{PREFIX}begin codenames` again once everyone attempting to play is free.")
        cursor.close()
        return

    # make sure all players are in the members table for this guild, and the users table
    for user in players:
        user_id = int(user.id)
        cursor.execute(f"SELECT * FROM members WHERE user = {user_id} AND guild = {guild_id}")
        query_result = cursor.fetchone()
        if query_result == None:
            cursor.execute(f"INSERT INTO members (user, guild) VALUES ({user_id}, {guild_id})")

        username = sql_escape_single_quotes(user.name)
        cursor.execute(f"SELECT * FROM users where id={user_id}")
        query_result = cursor.fetchone()
        if query_result == None: # user's not in the users table yet, so add them in with balance of 0
            cursor.execute(f"INSERT INTO users (id, username, balance) VALUES ({user_id}, '{username}', 0)")
    db.commit()

    # assign users their new roles in the members table (making them all operatives of the spymaster's color in a cooperative game, and making the operative both colors in a competitive 3-player game)
    # spymasters
    if len(role_lists[BLUE_SPY_EMOJI]) == 1:
        cursor.execute(f"UPDATE members SET codenamesroleandcolor = 'blue spymaster' WHERE guild = {guild_id} AND user = {int(role_lists[BLUE_SPY_EMOJI][0].id)}")
    if len(role_lists[RED_SPY_EMOJI]) == 1:
        cursor.execute(f"UPDATE members SET codenamesroleandcolor = 'red spymaster' WHERE guild = {guild_id} AND user = {int(role_lists[RED_SPY_EMOJI][0].id)}")
    
    # operatives
    all_operatives = role_lists[BLUE_OP_EMOJI] + role_lists[RED_OP_EMOJI]
    if len(role_lists[BLUE_SPY_EMOJI]) + len(role_lists[RED_SPY_EMOJI]) == 2 and len(all_operatives) == 1: # competitive 3-player game
        cooperative = False
        user_id = int(all_operatives[0].id)
        cursor.execute(f"UPDATE members SET codenamesroleandcolor = 'blue and red operative' WHERE guild = {guild_id} AND user = {user_id}")
    elif len(role_lists[BLUE_SPY_EMOJI]) == 0: # cooperative; all operatives will be on the red team
        cooperative = True
        cursor.execute(f"UPDATE members SET codenamesroleandcolor = 'red operative' WHERE guild = {guild_id} AND user IN ({comma_separated_ids_from_user_list(all_operatives)})")
    elif len(role_lists[RED_SPY_EMOJI]) == 0: # cooperative; all operatives will be on the blue team
        cooperative = True
        cursor.execute(f"UPDATE members SET codenamesroleandcolor = 'blue operative' WHERE guild = {guild_id} AND user IN ({comma_separated_ids_from_user_list(all_operatives)})")
    else: # normal competitive game with multiple operatives
        cooperative = False
        cursor.execute(f"UPDATE members SET codenamesroleandcolor = 'blue operative' WHERE guild = {guild_id} AND user IN ({comma_separated_ids_from_user_list(role_lists[BLUE_OP_EMOJI])})")
        cursor.execute(f"UPDATE members SET codenamesroleandcolor = 'red operative' WHERE guild = {guild_id} AND user IN ({comma_separated_ids_from_user_list(role_lists[RED_OP_EMOJI])})")

    # remove the game start message id from the guilds table
    cursor.execute(f"UPDATE guilds SET codenamesstartmsg = NULL WHERE id = {guild_id}")

    # set up words
    cursor.execute(f"SELECT word FROM codewords ORDER BY RAND() LIMIT 25")
    query_result = cursor.fetchall()
    words = list(map(lambda word_tuple: word_tuple[0], query_result)) # convert from list of 1-tuples to list of strings
    if cooperative:
        blue_goes_first = len(role_lists[BLUE_SPY_EMOJI])
    else:
        blue_goes_first = random.randint(0,1)
    red_start_index = 8 + blue_goes_first
    blue_words = words[:red_start_index]
    red_words = words[red_start_index:17]
    neutral_words = words[17:24]
    assassin_words = words[24:]
    cursor.execute(active_codewords_insert_sql(guild_id, blue_words, "blue"))
    cursor.execute(active_codewords_insert_sql(guild_id, red_words, "red"))
    cursor.execute(active_codewords_insert_sql(guild_id, neutral_words, "neutral"))
    cursor.execute(active_codewords_insert_sql(guild_id, assassin_words, "assassin"))
    
    # insert an entry for the game into the codenamesGames table (but don't worry about initializing the entire row yet)
    cursor.execute(f"INSERT INTO codenamesGames (guild, opsChannel) VALUES ({guild_id}, {int(ctx.channel.id)})")

    # commit, get the shuffled words, and close the cursor
    db.commit()
    cursor.execute(f"SELECT word FROM activeCodewords WHERE guild = {guild_id} ORDER BY position")
    shuffled_word_tuples = cursor.fetchall()
    shuffled_words = list(map(lambda word_tuple: word_tuple[0], shuffled_word_tuples))
    cursor.close()

    # assign red and blue spymaster variables, and variables regarding who goes first and second
    if cooperative: # in cooperative games, the non-computer team will always go first
        if blue_goes_first:
            blue_spymaster = role_lists[BLUE_SPY_EMOJI][0]
            starting_spymaster = role_lists[BLUE_SPY_EMOJI][0]
            red_spymaster = None
            second_spymaster = None
            starting_color = 'blue'
            second_color = 'red'
            starting_words = blue_words
            second_words = red_words
        else:
            red_spymaster = role_lists[RED_SPY_EMOJI][0]
            starting_spymaster = role_lists[RED_SPY_EMOJI][0]
            blue_spymaster = None
            second_spymaster = None
            starting_color = 'red'
            second_color = 'blue'
            starting_words = red_words
            second_words = blue_words
    else:
        blue_spymaster = role_lists[BLUE_SPY_EMOJI][0]
        red_spymaster = role_lists[RED_SPY_EMOJI][0]
    
        # assign variables regarding who goes first and second
        if blue_goes_first:
            starting_spymaster = blue_spymaster
            second_spymaster = red_spymaster
            starting_color = 'blue'
            second_color = 'red'
            starting_words = blue_words
            second_words = red_words
        else:
            starting_spymaster = red_spymaster
            second_spymaster = blue_spymaster
            starting_color = 'red'
            second_color = 'blue'
            starting_words = red_words
            second_words = blue_words

    # start first turn
    await cn_start_spymaster_turn(starting_spymaster, ctx, starting_color, blue_words, [], red_words, [], neutral_words, [], assassin_words[0], shuffled_words)
    
    # send message to second spymaster
    if second_spymaster != None: # second_spymaster == None in a cooperative game
        await cn_send_spymaster_update(second_spymaster, second_color, second_words, [], starting_words, [], neutral_words, [], assassin_words[0])
        dm_channel = await get_dm_channel(second_spymaster)
        await dm_channel.send("You'll go second this game—-I'll send you another message when it's your turn")

def active_codewords_insert_sql(guild_id, word_list, color):
    '''Build a MySQL INSERT string where the VALUES section includes series of (guild, word, color, revealed) groupings separated by commas, to be used when starting codenames.'''
    values_groupings_list = list(map(lambda word: f"({int(guild_id)}, '{word}', '{color}', 0, RAND())", word_list))
    values_section = ", ".join(values_groupings_list)
    return f"INSERT INTO activeCodewords (guild, word, color, revealed, position) VALUES {values_section}"

@begin_game.error
async def begin_game_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}begin <game>` (e.g. `{PREFIX}begin codenames`) to begin a game that's ready.")
    else: raise error

##### GUESS #####

@bot.command(name='guess', help='Guesses a word in the 5-letter-word guessing game')
async def guess(ctx, guess):
    
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send("Using this command in a private chat is not allowed.")
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
            cursor.close()
            return
    
    # okay, there is indeed a game going on at this point
    # use the word that's currently in the database for this guild
    word = query_result[0][0]

    # make sure the user gets credit for participating in this game
    cursor.execute(f"SELECT * FROM members WHERE user = {ctx.author.id} AND guild = {ctx.guild.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0:
        cursor.execute(f"INSERT INTO members (user, guild, playingguess) VALUES ({ctx.author.id}, {ctx.guild.id}, 1)")
    else:
        cursor.execute(f"UPDATE members SET playingguess = 1 WHERE user = {ctx.author.id} AND guild = {ctx.guild.id}")
    
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
        cursor.execute(f"SELECT user FROM members WHERE (NOT user = {ctx.author.id}) AND guild = {ctx.guild.id} AND playingguess = 1")
        other_players_query = cursor.fetchall()
        if len(other_players_query) > 0:
            other_players = list(map(lambda player_tuple: str(player_tuple[0]), other_players_query)) # convert from list of 1-tuples to list of strings
            mentions_string = mention_string_from_id_strings(other_players) + f": you win {PLAY_GUESS_REWARD} copper! "
        else:
            mentions_string = ""

        # reward other participants
        cursor.execute(f"UPDATE users SET balance = balance + {PLAY_GUESS_REWARD} WHERE (NOT id = {ctx.author.id}) AND id IN (SELECT user FROM members WHERE guild = {ctx.guild.id} AND playingguess = 1)")
        
        # reset the list of who is playing the guess game
        cursor.execute(f"UPDATE members SET playingguess = NULL WHERE guild = {ctx.guild.id}")

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

##### CODENAMES #####

async def cn_send_spymaster_update(user: discord.User, color, their_words_unrevealed, their_words_revealed, other_words_unrevealed, other_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word):
    
    # Format each sub-list of words
    display_color = color[0].upper() + color[1:]
    their_words_formatted = '\n'.join(their_words_unrevealed) + (('\n~~' + '\n'.join(their_words_revealed) + '~~\n') if len(their_words_revealed) else '\n')
    other_words_formatted = '\n'.join(other_words_unrevealed) + (('\n~~' + '\n'.join(other_words_revealed) + '~~\n') if len(other_words_revealed) else '\n')
    neutral_words_formatted = '\n'.join(neutral_words_unrevealed) + (('\n~~' + '\n'.join(neutral_words_revealed) + '~~\n') if len(neutral_words_revealed) else '\n')
    
    # Build the embed description
    embed_descr = f"**Your Words**\n" + their_words_formatted
    embed_descr += f"\n**Opponent's Words**\n" + other_words_formatted
    embed_descr += "\n**Neutral Words**\n" + neutral_words_formatted
    embed_descr += "\n**Assassin Word**\n" + assassin_word
    
    # Build and send embed
    embed = discord.Embed(title=f"Codenames: {display_color} Spymaster", description=embed_descr, color=0x0000ff if color=='blue' else 0xff0000)
    dm_channel = await get_dm_channel(user)
    await dm_channel.send(embed=embed)

async def cn_send_public_update(ctx, next_turn_color, blue_words_revealed, red_words_revealed, neutral_words_revealed, unrevealed_words):
    embed = discord.Embed(title=f"Codenames Board", color=16711935) # magenta
    
    unrevealed_words_formatted = '\n'.join(unrevealed_words)
    embed.add_field(name=f"Unrevealed Words", value=unrevealed_words_formatted, inline=False)
    if len(blue_words_revealed):
        blue_words_formatted = '\n'.join(blue_words_revealed)
        embed.add_field(name=f"Blue Words", value=blue_words_formatted, inline=False)
    if len(red_words_revealed):
        red_words_formatted = '\n'.join(red_words_revealed)
        embed.add_field(name=f"Red Words", value=red_words_formatted, inline=False)
    if len(red_words_revealed):
        neutral_words_formatted = '\n'.join(neutral_words_revealed)
        embed.add_field(name=f"Neutral Words", value=neutral_words_formatted, inline=False)
    
    await ctx.send(embed=embed)
    await ctx.send(f"Awaiting a clue from the {next_turn_color} spymaster...")

async def cn_send_declassified_board(ctx):
    
    blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word = cn_get_word_lists(int(ctx.guild.id))

    # Format each sub-list of words
    blue_words_formatted = '\n'.join(blue_words_unrevealed) + (('\n~~' + '\n'.join(blue_words_revealed) + '~~\n') if len(blue_words_revealed) else '\n')
    red_words_formatted = '\n'.join(red_words_unrevealed) + (('\n~~' + '\n'.join(red_words_revealed) + '~~\n') if len(red_words_revealed) else '\n')
    neutral_words_formatted = '\n'.join(neutral_words_unrevealed) + (('\n~~' + '\n'.join(neutral_words_revealed) + '~~\n') if len(neutral_words_revealed) else '\n')
    
    # Build the embed description
    embed_descr = f"**Blue Words**\n" + blue_words_formatted
    embed_descr += f"\n**Red Words**\n" + red_words_formatted
    embed_descr += "\n**Neutral Words**\n" + neutral_words_formatted
    embed_descr += "\n**Assassin Word**\n" + assassin_word
    
    # Build and send embed
    embed = discord.Embed(title=f"Codenames Board Declassified", description=embed_descr, color=16711935) # magenta
    await ctx.send(embed=embed)

async def cn_start_spymaster_turn(spymaster: discord.User, guild_ctx, color, blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word, shuffled_unrevealed_words):
    
    # message spymaster
    if spymaster != None: # spymaster == None on the computer side in a cooperative game
        if color=='blue':
            their_words_unrevealed = blue_words_unrevealed
            their_words_revealed = blue_words_revealed
            other_words_unrevealed = red_words_unrevealed
            other_words_revealed = red_words_revealed
        else:
            their_words_unrevealed = red_words_unrevealed
            their_words_revealed = red_words_revealed
            other_words_unrevealed = blue_words_unrevealed
            other_words_revealed = blue_words_revealed
        await cn_send_spymaster_update(spymaster, color, their_words_unrevealed, their_words_revealed, other_words_unrevealed, other_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word)
        dm_channel = await get_dm_channel(spymaster)
        await dm_channel.send(f"Your turn! Use `{PREFIX}cnclue <word> <number>` (e.g. `{PREFIX}cnclue bush 2`) to give your clue.")
    
    # message public channel
    await cn_send_public_update(guild_ctx, color, blue_words_revealed, red_words_revealed, neutral_words_revealed, shuffled_unrevealed_words)

    # update database
    cursor = get_cursor()
    cursor.execute(f"UPDATE codenamesGames SET turn = '{color} spymaster', numClued = NULL, numGuessed = NULL WHERE guild = {int(guild_ctx.guild.id)}")
    db.commit()
    cursor.close()

@bot.command(help='Gives a clue, as a codenames spymaster')
async def cnclue(ctx, word, num):
    
    # make sure user is a spymaster (which also checks that a game is going) and it's their turn
    validation_results = await cn_validate_spymaster(ctx)
    if validation_results == None: return
    
    # finish making sure the clue is valid
    word = sql_escape_single_quotes(word)
    try: 
        num = int(num)
    except ValueError: 
        if num.lower() in ['infinity', 'inf']:
            num = 25
        else:
            await ctx.send(f"**{num}** is not a valid number of words. Please try again")
            return
    if num < 0:
        await ctx.send(f"**{num}** is not a valid number of words. Please try again")
        return
    
    # let user know their clue was valid
    await ctx.send("Your clue has been submitted!")

    # message public channel
    guild_id, operatives_channel, turn = validation_results
    color = turn.split()[0]
    cursor = get_cursor()
    cursor.execute(f"SELECT user FROM members WHERE guild = {guild_id} AND codenamesroleandcolor LIKE '%{color}%operative'")
    query_result = cursor.fetchall()
    these_operative_id_strings = list(map(lambda id_tuple: str(id_tuple[0]), query_result))
    cursor.execute(f"SELECT COUNT(word) FROM activeCodewords WHERE guild = {guild_id} AND color = '{color}' AND NOT revealed")
    count_their_unrevealed = cursor.fetchone()[0]
    if num <= count_their_unrevealed:
        num_str = str(num)
    else:
        num_str = "infinity"
        num = -1
    cursor.execute(f"SELECT word FROM activeCodewords WHERE guild = {guild_id} AND NOT revealed ORDER BY position LIMIT 1")
    unrevealed_word_example = cursor.fetchone()[0]
    await bot.get_channel(operatives_channel).send(f"{mention_string_from_id_strings(these_operative_id_strings)} ({color} operatives): your turn! Your clue is **{word} {num_str}**. Use `{PREFIX}cnguess <word>` (e.g. `{PREFIX}cnguess {unrevealed_word_example}`) to guess a word that you think is the {color} team's.")

    # update database
    cursor.execute(f"UPDATE codenamesGames SET turn = '{color} operative', numClued = {num}, numGuessed = 0 WHERE guild = {guild_id}")
    db.commit()
    cursor.close()

@cnclue.error
async def cnclue_error(ctx, error):
    
    # see if user is not a spymaster, or if it's not their turn even if they are a spymaster
    validation_results = await cn_validate_spymaster(ctx)
    if validation_results == None: return
    
    # okay, just respond to the malformatted command
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}cnclue <word> <number>` (e.g. `{PREFIX}cnclue bush 2`) to give your clue.")
    else: raise error

@bot.command(help='Guesses a word, as a codenames operative')
async def cnguess(ctx, guess):
    
    guess = sql_escape_single_quotes(guess)

    # make sure it's not in a private channel
    if ctx.guild == None:
        await ctx.send("Using this command in a private chat is not allowed.")
        return

    # make sure user is an operative (which also checks that a game is going) and it's their turn
    validation_results = await cn_validate_operative(ctx)
    if validation_results == None: return
    
    # make sure the word is a guessable word
    guild_id, turn_color, _ = validation_results
    cursor = get_cursor()
    cursor.execute(f"SELECT color FROM activeCodewords WHERE guild = {guild_id} AND word = '{guess}' AND NOT revealed")
    query_result = cursor.fetchone()
    if query_result == None: 
        await ctx.send(f"**{sql_unescape_single_quotes(guess)}** is not one of the unrevealed words on the board. Please guess one of those")
        cursor.close()
        return

    # mark word as revealed
    cursor.execute(f"UPDATE activeCodewords SET revealed = 1 WHERE guild = {guild_id} AND word = '{guess}'")
    db.commit()
    
    # evaluate guess
    guess_color = query_result[0]
    if guess_color == turn_color: # correct guess
        await ctx.send(f"Nice! **{guess}** is a **{turn_color}** word.")
        
        # see if they won
        cursor.execute(f"SELECT COUNT(*) FROM activeCodewords WHERE guild = {guild_id} AND color = '{turn_color}' AND NOT revealed")
        count_their_unrevealed = cursor.fetchone()[0]
        if count_their_unrevealed == 0: # they won
            await cn_end_game(ctx, turn_color)
        else: # they didn't win
            cursor.execute(f"SELECT numClued, numGuessed FROM codenamesGames WHERE guild = {guild_id}")
            num_clued, num_guessed = cursor.fetchone()
            if num_clued < 1 or num_guessed < num_clued: # they're still allowed more guesses (since if num_clued >= 1, they're allowed num_clued + 1 guesses, and we haven't updated num_guessed with this guess yet)
                cursor.execute(f"UPDATE codenamesGames SET numGuessed = numGuessed + 1 WHERE guild = {guild_id}")
                db.commit()
                await ctx.send(f"Use `{PREFIX}cnguess <word>` to guess another word, or use `{PREFIX}cnpass` to end your team's turn.")
            else:
                await cn_end_turn(ctx)
    elif guess_color == 'assassin':
        await ctx.send(f"OH NOOOO!!! **{guess}** is the **ASSASSIN** word!")
        await cn_end_game(ctx, cn_opposite_color(turn_color))
    else: # they guessed one of the other team's words or a neutral word
        await ctx.send(f"Whoops: **{guess}** is a **{guess_color}** word.")
        
        # see if they lost
        cursor.execute(f"SELECT COUNT(*) FROM activeCodewords WHERE guild = {guild_id} AND color = '{cn_opposite_color(turn_color)}' AND NOT revealed")
        count_other_unrevealed = cursor.fetchone()[0]
        if count_other_unrevealed == 0: # they lost
            await cn_end_game(ctx, cn_opposite_color(turn_color))
        else: # they didn't lose
            await cn_end_turn(ctx)

    cursor.close()

@cnguess.error
async def cnguess_error(ctx, error):
    
    # see if user is not an operative, or if it's not their turn even if they are an operative
    validation_results = await cn_validate_operative(ctx)
    if validation_results == None: return
    
    # okay, just respond to the malformatted comman
    guild_id = validation_results[0]
    cursor = get_cursor()
    cursor.execute(f"SELECT word FROM activeCodewords WHERE guild = {guild_id} AND NOT revealed ORDER BY position LIMIT 1")
    unrevealed_word_example = cursor.fetchone()[0]
    cursor.close()
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use `{PREFIX}cnguess <word>` (e.g. `{PREFIX}cnguess {unrevealed_word_example}`) to guess a word.")
    else: raise error

@bot.command(help='Ends your team\'s turn, as a codenames operative')
async def cnpass(ctx):
    
    # make sure it's not in a private channel
    if ctx.guild == None:
        await ctx.send("Using this command in a private chat is not allowed.")
        return

    # make sure user is an operative (which also checks that a game is going) and it's their turn
    validation_results = await cn_validate_operative(ctx)
    if validation_results == None: return

    # make sure the team has guessed at least 
    numGuessed = validation_results[2]
    if numGuessed == 0:
        await ctx.send("Your team must guess at least one word before you can pass your turn.")
        return

    # end their turn
    await cn_end_turn(ctx)

async def cn_validate_spymaster(ctx):
    
    # are they a spymasteer
    author_id = int(ctx.author.id)
    cursor = get_cursor()
    cursor.execute(f"SELECT guild, codenamesroleandcolor FROM members WHERE user = {author_id} AND codenamesroleandcolor LIKE '%spymaster'")
    query_result = cursor.fetchone()
    if query_result == None: 
        await ctx.send("Only someone who is currently playing as a spymaster in a codenames game may use this command.")
        cursor.close()
        return
    
    # is it their turn
    guild_id, role_and_color = query_result
    cursor.execute(f"SELECT opsChannel, turn FROM codenamesGames WHERE guild = {guild_id}")
    operatives_channel, turn = cursor.fetchone()
    if turn != role_and_color:
        await ctx.send(f"It is not your turn.")
        cursor.close()
        return
    
    # valid, so return necessary info
    cursor.close()
    return guild_id, operatives_channel, turn

async def cn_validate_operative(ctx):
    
    # are they an operative 
    author_id = int(ctx.author.id)
    cursor = get_cursor()
    cursor.execute(f"SELECT guild, codenamesroleandcolor FROM members WHERE user = {author_id} AND codenamesroleandcolor LIKE '%operative'")
    query_result = cursor.fetchone()
    if query_result == None: 
        await ctx.send("Only someone who is currently playing as an operative in a codenames game may use this command.")
        cursor.close()
        return
    
    # is it their turn
    guild_id, role_and_color = query_result
    cursor.execute(f"SELECT turn, numGuessed FROM codenamesGames WHERE guild = {guild_id}")
    turn, numGuessed = cursor.fetchone()
    color = turn.split()[0]
    if 'operative' not in turn or color not in role_and_color:
        await ctx.send(f"It is not your turn.")
        cursor.close()
        return
    
    # valid, so return necessary info
    cursor.close()
    return guild_id, color, numGuessed

def cn_opposite_color(color):
    if color=='blue': return 'red'
    if color=='red': return 'blue'
    raise ValueError()

def cn_get_word_lists(guild_id):
    '''Query the database for and return the unrevealed and revealed words of each color, plus the assassin word'''
    
    # get stuff from database
    cursor = get_cursor()
    cursor.execute(f"SELECT word, color, revealed FROM activeCodewords WHERE guild = {guild_id}")
    words = cursor.fetchall()
    cursor.close()

    # filter stuff from database into individual lists/variables
    blue_words_unrevealed = list(map(lambda row: row[0], filter(lambda row: row[1] == 'blue' and not row[2], words)))
    blue_words_revealed = list(map(lambda row: row[0], filter(lambda row: row[1] == 'blue' and row[2], words)))
    red_words_unrevealed = list(map(lambda row: row[0], filter(lambda row: row[1] == 'red' and not row[2], words)))
    red_words_revealed = list(map(lambda row: row[0], filter(lambda row: row[1] == 'red' and row[2], words)))
    neutral_words_unrevealed = list(map(lambda row: row[0], filter(lambda row: row[1] == 'neutral' and not row[2], words)))
    neutral_words_revealed = list(map(lambda row: row[0], filter(lambda row: row[1] == 'neutral' and row[2], words)))
    assassin_word = list(filter(lambda row: row[1] == 'assassin', words))[0][0]

    return blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word

async def cn_end_turn(ctx):

    # get some basic info
    guild_id = int(ctx.guild.id)
    cursor = get_cursor()
    cursor.execute(f"SELECT turn FROM codenamesGames WHERE guild = {guild_id}")
    prev_turn_color = cursor.fetchone()[0].split()[0]
    next_turn_color = cn_opposite_color(prev_turn_color)

    # check if cooperative or competitive
    cursor.execute(f"SELECT COUNT(*) FROM members WHERE guild = {guild_id} AND codenamesroleandcolor LIKE '%spymaster'")
    num_spymasters = cursor.fetchone()[0]
    if num_spymasters == 1: # cooperative game

        # reveal a random word for the computer team
        cursor.execute(f"SELECT id, word FROM activeCodewords WHERE guild = {guild_id} AND color = '{next_turn_color}' AND NOT revealed ORDER BY RAND()")
        cpu_unrevealed_words = cursor.fetchall()
        rev_word_id, rev_word = cpu_unrevealed_words[0]
        cursor.execute(f"UPDATE activeCodewords SET revealed = 1 WHERE id = {rev_word_id}")
        db.commit()
        await ctx.send(f"The computer correctly guesses that **{rev_word}** is **{next_turn_color}**.")
        
        if len(cpu_unrevealed_words) == 1: # the players lost
            await cn_end_game(ctx, next_turn_color)
    
    else: # competitive game
        
        # update database
        cursor.execute(f"UPDATE codenamesGames SET turn = '{next_turn_color} spymaster', numClued = NULL, numGuessed = NULL WHERE guild = {guild_id}")
        db.commit()
        
        # send message updates
        blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word = cn_get_word_lists(guild_id)
        cursor.execute(f"SELECT user FROM members WHERE guild = {guild_id} AND codenamesroleandcolor = '{next_turn_color} spymaster'")
        spymaster_id = cursor.fetchone()[0]
        spymaster = bot.get_user(spymaster_id)
        cursor.execute(f"SELECT word FROM activeCodewords WHERE guild = {guild_id} AND NOT revealed ORDER BY position")
        shuffled_unrevealed_word_tuples = cursor.fetchall()
        shuffled_unrevealed_words = list(map(lambda word_tuple: word_tuple[0], shuffled_word_tuples))
        await cn_start_spymaster_turn(spymaster, ctx, next_turn_color, blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word, shuffled_unrevealed_words)

    cursor.close()

async def cn_end_game(ctx, winning_color):

    # give rewards
    guild_id = int(ctx.guild.id)
    cursor = get_cursor()
    cursor.execute(f"UPDATE users SET balance = balance + {WIN_CODENAMES_REWARD} WHERE id IN (SELECT user FROM members WHERE guild = {guild_id} AND (codenamesroleandcolor = '{winning_color} spymaster' OR codenamesroleandcolor = '{winning_color} operative'))")
    cursor.execute(f"UPDATE users SET balance = balance + {PLAY_CODENAMES_REWARD} WHERE id IN (SELECT user FROM members WHERE guild = {guild_id} AND (codenamesroleandcolor = '{cn_opposite_color(winning_color)} spymaster' OR codenamesroleandcolor = '{cn_opposite_color(winning_color)} operative'))")
    cursor.execute(f"UPDATE users SET balance = balance + {DOUBLE_AGENT_REWARD} WHERE id IN (SELECT user FROM members WHERE guild = {guild_id} AND codenamesroleandcolor = 'blue and red operative')")

    # get python list of winning team user ids as strings
    cursor.execute(f"SELECT user FROM members WHERE guild = {guild_id} AND (codenamesroleandcolor = '{winning_color} spymaster' OR codenamesroleandcolor = '{winning_color} operative')")
    query_result = cursor.fetchall()
    winning_user_ids = list(map(lambda player_tuple: str(player_tuple[0]), query_result))

    # get python list of losing team user ids as strings
    cursor.execute(f"SELECT user FROM members WHERE guild = {guild_id} AND (codenamesroleandcolor = '{cn_opposite_color(winning_color)} spymaster' OR codenamesroleandcolor = '{cn_opposite_color(winning_color)} operative')")
    query_result = cursor.fetchall()
    losing_user_ids = list(map(lambda player_tuple: str(player_tuple[0]), query_result))

    # get python list of double agent user ids as strings
    cursor.execute(f"SELECT user FROM members WHERE guild = {guild_id} AND codenamesroleandcolor = 'blue and red operative'")
    query_result = cursor.fetchall()
    double_agent_user_ids = list(map(lambda player_tuple: str(player_tuple[0]), query_result))

    # send victory message and reward info (both will read differently depending on cooperative vs competitive)
    cursor.execute(f"SELECT COUNT(*) FROM members WHERE guild = {guild_id} AND codenamesroleandcolor = 'blue spymaster'")
    num_blue_spymasters = cursor.fetchone()[0]
    cursor.execute(f"SELECT COUNT(*) FROM members WHERE guild = {guild_id} AND codenamesroleandcolor = 'red spymaster'")
    num_red_spymasters = cursor.fetchone()[0]
    if num_blue_spymasters and num_red_spymasters: # competitive game
        double_agent_substring = f"{mention_string_from_id_strings(double_agent_user_ids)}: you get {DOUBLE_AGENT_REWARD} coppers. " if len(double_agent_user_ids) else ""
        await ctx.send(f"Game over! The **{winning_color}** team won. {mention_string_from_id_strings(winning_user_ids)}: you get {WIN_CODENAMES_REWARD} coppers. {mention_string_from_id_strings(losing_user_ids)}: you get {PLAY_CODENAMES_REWARD} coppers. {double_agent_substring}")
    else: # cooperative game
        human_color = 'blue' if num_blue_spymasters else 'red'
        winning_team = 'human' if human_color == winning_color else 'computer'
        exclamation = 'congratulations!' if winning_team == 'human' else 'better luck next time!'
        human_user_ids = winning_user_ids if winning_team == 'human' else losing_user_ids
        reward = WIN_CODENAMES_REWARD if winning_team == 'human' else PLAY_CODENAMES_REWARD
        action = 'winning' if winning_team == 'human' else 'playing'
        await ctx.send(f"Game over! The **{winning_color}** team (the **{winning_team}** team) won--{exclamation} {mention_string_from_id_strings(human_user_ids)}: you get {reward} coppers for {action}.")
    await ctx.send(f"Good game! Use `{PREFIX}start codenames` to start another.")

    # send the declassified game board
    await cn_send_declassified_board(ctx)
    
    # reset database stuff
    cursor.execute(f"UPDATE members SET codenamesroleandcolor = NULL WHERE guild = {guild_id}")
    cursor.execute(f"DELETE FROM activeCodewords WHERE guild={guild_id}")
    cursor.execute(f"DELETE FROM codenamesGames WHERE guild={guild_id}")
    db.commit()
    cursor.close()

##### CODEWORD #####

@bot.command(help='Suggests a word to be added to the list of codenames words')
async def codeword(ctx, word):
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send("Using this command in a private chat is not allowed.")
        return
    
    cursor = get_cursor()
    
    # make sure the user is in the users table, so they can be rewarded if their suggestion is approved
    author = sql_escape_single_quotes(ctx.author.name)
    cursor.execute(f"SELECT balance FROM users where id={int(ctx.author.id)}")
    query_result = cursor.fetchall()
    if len(query_result) == 0: # user's not in the users table yet, so add them in with balance of 0
        cursor.execute(f"INSERT INTO users (id, username, balance) VALUES ({int(ctx.author.id)}, '{author}', 0)")
    db.commit()

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

##### QUIT #####

@bot.command(name='quit', help='Initiates a vote to quit a current game')
async def quit_game(ctx, game, vote='yes'):
    
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send("Using this command in a private chat is not allowed.")
        return

    # check if valid command
    if game not in GAMES:
        await ctx.send(f"**{game}** is not a game that can be quit")
        return

    cursor = get_cursor()

    # get info about the current states of the game/vote countdown in question
    # start by checking if the guild is in the guilds table
    cursor.execute(f"SELECT currword FROM guilds WHERE id={ctx.guild.id}")
    query_result = cursor.fetchone()
    if query_result == None: # guild's not in the guilds table yet, which means there isn't a game going. We won't bother adding them here
        await ctx.send(f"There's no {game} game going right now.")
        cursor.close()
        return
    
    # okay, the guild is in the guilds table. Figure out if a game is going
    if game == 'guess':
        game_going = query_result[0] != None
    elif game == 'codenames':
        cursor.execute(f"SELECT * FROM activeCodewords WHERE guild = {ctx.guild.id}")
        query_result = cursor.fetchone()
        game_going = query_result != None
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
        cursor.execute(f"UPDATE members SET votetoquit{game} = NULL WHERE guild = {ctx.guild.id}")
        db.commit()
        cursor.execute(f"SELECT * from members WHERE user = {ctx.author.id} AND guild = {ctx.guild.id}")
        query_result = cursor.fetchall()
        if len(query_result) == 0:
            cursor.execute(f"INSERT INTO members (user, guild, votetoquit{game}) VALUES ({ctx.author.id}, {ctx.guild.id}, 1)")
        else:
            cursor.execute(f"UPDATE members SET votetoquit{game} = 1 WHERE user = {ctx.author.id} AND guild = {ctx.guild.id}")
        
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
    cursor.execute(f"SELECT * from members WHERE user = {ctx.author.id} AND guild = {ctx.guild.id}")
    query_result = cursor.fetchall()
    if len(query_result) == 0:
        cursor.execute(f"INSERT INTO members (user, guild, votetoquit{game}) VALUES ({ctx.author.id}, {ctx.guild.id}, {wants_to_quit})")
    else:
        cursor.execute(f"UPDATE members SET votetoquit{game} = {wants_to_quit} WHERE user = {ctx.author.id} AND guild = {ctx.guild.id}")
    
    db.commit()
    cursor.close()
    
    await ctx.send(f"{ctx.author.name} votes to **{'end' if wants_to_quit else 'continue'}** the {game} game")

async def quit_timer(ctx, game):
    await asyncio.sleep(60)
    
    cursor = get_cursor()
    guild_id = int(ctx.guild.id)

    # clear deadline in database
    cursor.execute(f"UPDATE guilds SET {game}quitvotedeadline = NULL WHERE id={guild_id}")
    db.commit()
    
    # address the results
    cursor.execute(f"SELECT votetoquit{game} FROM members WHERE guild = {guild_id}")
    results = cursor.fetchall()
    yeas = list(filter(lambda query_row: query_row[0] == 1, results))
    neas = list(filter(lambda query_row: query_row[0] == 0, results))
    if len(yeas) > len(neas):   
        await ctx.send(f"Time's up! The people have spoken: they've voted {len(yeas)}-{len(neas)} to **end** the {game} game. Use `{PREFIX}start {game}` to start a new one")
        if game=='guess':
            # reset the list of who is playing the guess game
            cursor.execute(f"UPDATE members SET playingguess = NULL WHERE guild = {guild_id}")
            
            # send the secret word in a message, then clear the word
            cursor.execute(f"SELECT currword FROM guilds WHERE id={guild_id}")
            await ctx.send(f"My word was **{cursor.fetchone()[0]}**")
            cursor.execute(f"UPDATE guilds SET currword = NULL where id={guild_id}")
            db.commit()
        elif game=='codenames':
            # send the declassified game board
            await cn_send_declassified_board(ctx)
            
            # reset database stuff
            cursor.execute(f"UPDATE members SET codenamesroleandcolor = NULL WHERE guild = {guild_id}")
            cursor.execute(f"DELETE FROM activeCodewords WHERE guild={guild_id}")
            cursor.execute(f"DELETE FROM codenamesGames WHERE guild={guild_id}")
            db.commit()
        # can add more games here with elifs
    else: 
        await ctx.send(f"Time's up! The people have spoken: they've voted {len(neas)}-{len(yeas)} to **continue** the {game} game.")
    
    cursor.close()

@quit_game.error
async def quit_game_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}quit <game>` (e.g. `{PREFIX}quit guess`) to quit a game.")
    else: raise error

##### CANCEL #####

@bot.command(name='cancel', help='Cancels the start process for a game')
async def cancel_game(ctx, game):
    # make sure command is being given in a guild context
    if ctx.guild == None:
        await ctx.send("Using this command in a private chat is not allowed.")
        return

    # check if valid command
    if game not in CANCELABLE_GAMES:
        await ctx.send(f"**{game}** is not a game that can be cancelled. If you're trying to quit an in-progress game, use `{PREFIX}quit {game}`")
        return

    cursor = get_cursor()

    # get info about the current state of the game
    # start by checking if the guild is in the guilds table
    cursor.execute(f"SELECT codenamesstartmsg FROM guilds WHERE id={ctx.guild.id}")
    query_result = cursor.fetchone()
    if query_result == None: # guild's not in the guilds table yet, which means there isn't a game in the process of starting. We won't bother adding them here
        await ctx.send(f"There's no {game} game in the process of starting right now.")
        cursor.close()
        return
    
    # okay, if there's a game starting, cancel it and send an informative message
    game_cancelled = False
    if game=='codenames':
        if query_result[0] != None:
            cursor.execute(f"UPDATE guilds SET codenamesstartmsg = NULL WHERE id={ctx.guild.id}")
            db.commit()
            game_cancelled = True
    # can add more games with elifs here

    if game_cancelled:
        await ctx.send(f"{game} game cancelled. Use `{PREFIX}start {game}` to restart")
    else:
        await ctx.send(f"There is no {game} game in the process of starting right now. If you're trying to quit an in-progress game, use `{PREFIX}quit {game}`")
    cursor.close()

@cancel_game.error
async def cancel_game_error(ctx, error):
    if isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send(f"Use the format `{PREFIX}cancel <game>` (e.g. `{PREFIX}cancel codenames`) to cancel a game start.")
    else: raise error

##### GENERAL HELPER FUNCTIONS #####

def sql_escape_single_quotes(string):
    return string.replace("'", "''")

def sql_unescape_single_quotes(string):
    return string.replace("''", "'")

def mention_string_from_id_strings(user_ids):
    return "<@!" + ">, <@!".join(user_ids) + ">"

def comma_separated_ids_from_user_list(user_list):
    '''Get a string of comma-separated ids from a list of Discord.py User objects.'''
    user_ids = list(map(lambda p: str(int(p.id)), user_list)) # str(int(p.id)) to use int for safety but because it needs to be a string for the next line
    return ", ".join(user_ids)

async def get_dm_channel(user):
    return user.dm_channel if user.dm_channel != None else await user.create_dm()

##########

if __name__ == "__main__":
    bot.run(TOKEN)
