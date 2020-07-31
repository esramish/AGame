from discord.ext import commands
import sys
import random
import pickle

# sys.path.append(sys.path[0][:sys.path[0].index('/cogs')]) # adds the parent directory to the list of paths from which packages can be imported. I don't think it's necessary if running agame.py from that parent directory
from agame import PREFIX, db, get_cursor, sql_escape_single_quotes, mention_string_from_id_strings

# load 5-letter words
with open('5-letter_words.pkl', 'rb') as f:
    FIVE_LETTER_WORDS = pickle.load(f)

WIN_GUESS_REWARD = 100
PLAY_GUESS_REWARD = 40

class Guess(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot
    
    async def start_guess(self, ctx):
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

    @commands.command(name='guess', help='Guesses a word in the 5-letter-word guessing game')
    async def guess(self, ctx, guess):
        
        # make sure command is being given in a guild context
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return
        
        cursor = get_cursor()

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
            await self.evaluate_word_guess(ctx, word, guess)

    async def evaluate_word_guess(self, ctx, word, guess):
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
    async def guess_error(self, ctx, error):
        if isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f"Use the format `{PREFIX}guess <word>` to guess a word.")
        else: raise error


def setup(bot):
    bot.add_cog(Guess(bot))
