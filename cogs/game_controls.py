from discord.ext import commands
import sys
from datetime import datetime, timedelta
import asyncio

# sys.path.append(sys.path[0][:sys.path[0].index('/cogs')]) # adds the parent directory to the list of paths from which packages can be imported. I don't think it's necessary if running agame.py from that parent directory
from agame import PREFIX

GAMES = ['guess', 'codenames']
CANCELABLE_GAMES = ['codenames']

class GameControls(commands.Cog, name="Game Controls"):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='listgames', help="Lists all the games the bot currently provides")
    async def list_games(self, ctx):
        await ctx.send(', '.join(GAMES))
    
    @commands.command(name='start', help='Starts a new game')
    async def start_game(self, ctx, game):
        
        # make sure command is being given in a guild context
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return
        
        # check if valid command
        if game not in GAMES:
            await ctx.send(f"**{game}** is not a game that can be started")
            return

        if game=='guess':
            await self.bot.get_cog('Guess').start_guess(ctx)
        elif game=='codenames':
            await self.bot.get_cog('Codenames').start_codenames(ctx)

    @start_game.error
    async def start_game_error(self, ctx, error):
        if isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f"Use the format `{PREFIX}start <game>` (e.g. `{PREFIX}start guess`) to start a game.")
        else: raise error

    @commands.command(name='begin', help='Begins a game that has been set up')
    async def begin_game(self, ctx, game):
        
        # make sure command is being given in a guild context
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return

        # check if valid command
        if game not in CANCELABLE_GAMES:
            await ctx.send(f"**{game}** is not a game that can be \"begun.\" If you're simply trying to start a game, use `{PREFIX}start {game}`")
            return

        cursor = self.bot.get_cog("General").get_cursor()

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
                await self.bot.get_cog('Codenames').begin_codenames(ctx, query_result[0])
        # can add more games with elifs here

        if not game_begun:
            await ctx.send(f"There is no {game} game in the process of starting right now. If you're trying to start that process, use `{PREFIX}start {game}`")

    @begin_game.error
    async def begin_game_error(self, ctx, error):
        if isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f"Use the format `{PREFIX}begin <game>` (e.g. `{PREFIX}begin codenames`) to begin a game that's ready.")
        else: raise error

    @commands.command(name='quit', help='Initiates a vote to quit a current game')
    async def quit_game(self, ctx, game, vote='yes'):
        
        # make sure command is being given in a guild context
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return

        # check if valid command
        if game not in GAMES:
            await ctx.send(f"**{game}** is not a game that can be quit")
            return

        cursor = self.bot.get_cog("General").get_cursor()

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
            self.bot.get_cog("General").db.commit()
            cursor.execute(f"SELECT * from members WHERE user = {ctx.author.id} AND guild = {ctx.guild.id}")
            query_result = cursor.fetchall()
            if len(query_result) == 0:
                cursor.execute(f"INSERT INTO members (user, guild, votetoquit{game}) VALUES ({ctx.author.id}, {ctx.guild.id}, 1)")
            else:
                cursor.execute(f"UPDATE members SET votetoquit{game} = 1 WHERE user = {ctx.author.id} AND guild = {ctx.guild.id}")
            
            # enter the voting deadline
            deadline = datetime.strftime(datetime.utcnow() + timedelta(minutes=1), '%Y-%m-%d %H:%M:%S')
            cursor.execute(f"UPDATE guilds SET {game}quitvotedeadline = '{deadline}' where id={ctx.guild.id}")
            
            self.bot.get_cog("General").db.commit()
            cursor.close()

            # send a message to the context
            await ctx.send(f"**{ctx.author.name} votes to end the {game} game.** Use `{PREFIX}quit {game} <yes/no>` to vote for or against quitting the game. Votes will be tallied in 1 minute")

            # start the timer
            await self.quit_timer(ctx, game)

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
        
        self.bot.get_cog("General").db.commit()
        cursor.close()
        
        await ctx.send(f"{ctx.author.name} votes to **{'end' if wants_to_quit else 'continue'}** the {game} game")

    async def quit_timer(self, ctx, game):
        await asyncio.sleep(60)
        
        cursor = self.bot.get_cog("General").get_cursor()
        guild_id = int(ctx.guild.id)

        # clear deadline in database
        cursor.execute(f"UPDATE guilds SET {game}quitvotedeadline = NULL WHERE id={guild_id}")
        self.bot.get_cog("General").db.commit()
        
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
                self.bot.get_cog("General").db.commit()
            elif game=='codenames':
                # send the declassified game board
                await self.bot.get_cog('Codenames').cn_send_declassified_board(ctx)
                
                # reset database stuff
                cursor.execute(f"UPDATE members SET codenamesroleandcolor = NULL WHERE guild = {guild_id}")
                cursor.execute(f"DELETE FROM activeCodewords WHERE guild={guild_id}")
                cursor.execute(f"DELETE FROM codenamesGames WHERE guild={guild_id}")
                self.bot.get_cog("General").db.commit()
            # can add more games here with elifs
        else: 
            await ctx.send(f"Time's up! The people have spoken: they've voted {len(neas)}-{len(yeas)} to **continue** the {game} game.")
        
        cursor.close()

    @quit_game.error
    async def quit_game_error(self, ctx, error):
        if isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f"Use the format `{PREFIX}quit <game>` (e.g. `{PREFIX}quit guess`) to quit a game.")
        else: raise error

    @commands.command(name='cancel', help='Cancels the start process for a game')
    async def cancel_game(self, ctx, game):
        # make sure command is being given in a guild context
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return

        # check if valid command
        if game not in CANCELABLE_GAMES:
            await ctx.send(f"**{game}** is not a game that can be cancelled. If you're trying to quit an in-progress game, use `{PREFIX}quit {game}`")
            return

        cursor = self.bot.get_cog("General").get_cursor()

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
                self.bot.get_cog("General").db.commit()
                game_cancelled = True
        # can add more games with elifs here

        if game_cancelled:
            await ctx.send(f"{game} game cancelled. Use `{PREFIX}start {game}` to restart")
        else:
            await ctx.send(f"There is no {game} game in the process of starting right now. If you're trying to quit an in-progress game, use `{PREFIX}quit {game}`")
        cursor.close()

    @cancel_game.error
    async def cancel_game_error(self, ctx, error):
        if isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f"Use the format `{PREFIX}cancel <game>` (e.g. `{PREFIX}cancel codenames`) to cancel a game start.")
        else: raise error


def setup(bot):
    bot.add_cog(GameControls(bot))
