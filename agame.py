import os, sys
from datetime import datetime, timedelta
import traceback

import discord
from discord.ext import commands
from dotenv import load_dotenv

import mysql.connector 

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = os.getenv('AGAME_PREFIX')

##### GENERAL HELPER FUNCTIONS #####

def get_new_db_connection():
    '''Connect to the database using the values specified in the environment. Implemented as a function so that it can be called easily in other places when it's discovered that the connection was lost/ended.'''
    return mysql.connector.connect(
        host=os.getenv('AGAME_DB_IP'),
        user=os.getenv('AGAME_DB_USERNAME'),
        password=os.getenv('AGAME_DB_PASSWORD'),
        database=os.getenv('AGAME_DB_DBNAME'),
        autocommit=True
    )

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

#####

class General(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot
        self.db = get_new_db_connection()

    def get_cursor(self, cursor_type):
        if not self.db.is_connected():
            self.db = get_new_db_connection()
            print(f"Reconnected to database at {datetime.utcnow()}")
        if cursor_type == "normal": # avoid using this with SELECT statements--requires programmer to fetch all the rows before executing another statement on the same connection
            return self.db.cursor()
        elif cursor_type == "buffered": # fine for use with statements where injection isn't a concern
            return self.db.cursor(buffered=True)
        elif cursor_type == "prepared": # use this, together with parameterized queries, when injection is a concern
            return self.db.cursor(prepared=True)
        else:
            raise ValueError()

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'{bot.user.name} has connected to Discord!')

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        await bot.get_cog('Codenames').codeword_reaction_checker(reaction, user)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        await bot.get_cog('Codenames').codeword_reaction_checker(reaction, user)

    def cog_unload(self):
        self.db.close()
        return super().cog_unload()

#####

if __name__ == "__main__":

    bot = commands.Bot(command_prefix=PREFIX)

    # load general cog
    bot.add_cog(General(bot))
    
    # load extensions
    initial_extensions = ['cogs.guess', 'cogs.codenames', 'cogs.game_controls', 'cogs.money']
    for extension in initial_extensions:
        try:
            bot.load_extension(extension)
        except Exception as e:
            print(f'Failed to load extension {extension}.', file=sys.stderr)
            traceback.print_exc()
    
    # make sure certain database tables exist
    with bot.get_cog("General").get_cursor("normal") as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS users (id BIGINT PRIMARY KEY, username VARCHAR(255), balance INT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS guilds (id BIGINT PRIMARY KEY, guildname VARCHAR(255), currword VARCHAR(10), guessquitvotedeadline DATETIME, codenamesstartmsg BIGINT, codenamesquitvotedeadline DATETIME)")
        cursor.execute("CREATE TABLE IF NOT EXISTS members (id INT PRIMARY KEY AUTO_INCREMENT, user BIGINT NOT NULL, guild BIGINT NOT NULL, votetoquitguess BIT, playingguess BIT, votetoquitcodenames BIT, codenamesroleandcolor VARCHAR(25))")
        cursor.execute("CREATE TABLE IF NOT EXISTS codewords (id INT PRIMARY KEY AUTO_INCREMENT, suggestor BIGINT, suggestionmsg BIGINT, word VARCHAR(45), approved BIT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS activeCodewords (id INT PRIMARY KEY AUTO_INCREMENT, guild BIGINT, word VARCHAR(45), color varchar(10), revealed BIT, position FLOAT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS codenamesGames (id INT PRIMARY KEY AUTO_INCREMENT, guild BIGINT, opsChannel BIGINT, turn VARCHAR(25), numClued INT, numGuessed INT)")

    bot.run(TOKEN)
