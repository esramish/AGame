import discord
from discord.ext import commands
import sys
import random
from datetime import datetime, timedelta

# sys.path.append(sys.path[0][:sys.path[0].index('/cogs')]) # adds the parent directory to the list of paths from which packages can be imported. I don't think it's necessary if running agame.py from that parent directory
from agame import PREFIX, sql_escape_single_quotes, sql_unescape_single_quotes, mention_string_from_id_strings, comma_separated_ids_from_user_list, get_dm_channel

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

class Codenames(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot

    @commands.command(help='Suggests a word to be added to the list of codenames words')
    async def codeword(self, ctx, word):
        # make sure command is being given in a guild context
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return
        
        cursor = self.bot.get_cog("General").get_cursor()
        
        # make sure the user is in the users table, so they can be rewarded if their suggestion is approved
        author = sql_escape_single_quotes(ctx.author.name)
        cursor.execute(f"SELECT balance FROM users where id={int(ctx.author.id)}")
        query_result = cursor.fetchall()
        if len(query_result) == 0: # user's not in the users table yet, so add them in with balance of 0
            cursor.execute(f"INSERT INTO users (id, username, balance) VALUES ({int(ctx.author.id)}, '{author}', 0)")
        self.bot.get_cog("General").db.commit()

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
                self.bot.get_cog("General").db.commit()

        # send voting message
        message = await ctx.send(f"React {CODEWORD_VOTE_EMOJI} to this message to approve the codenames word **{word}**! {NUM_CODEWORD_REQ_VOTES} more vote{'s' if NUM_CODEWORD_REQ_VOTES != 1 else ''} needed")
        await message.add_reaction(CODEWORD_VOTE_EMOJI)

        # insert word candidate into database
        cursor.execute(f"INSERT INTO codewords (suggestor, suggestionmsg, word, approved, suggestion_time) VALUES ({int(ctx.author.id)}, {int(message.id)}, '{word}', 0, '{datetime.strftime(datetime.utcnow(), '%Y-%m-%d %H:%M:%S')}')")
        self.bot.get_cog("General").db.commit()
        cursor.close()

    @codeword.error
    async def codeword_error(self, ctx, error):
        if isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f"Use the format `{PREFIX}codeword <word>` (e.g. `{PREFIX}codeword computer`) to suggest a codenames word.")
        else: raise error

    async def codeword_reaction_checker(self, reaction, user):
        '''Given a reaction and the user who reacted, check if it was a codeword message reaction and process accordingly'''

        # check if the reaction in question is the codeword vote emoji
        if reaction.emoji != CODEWORD_VOTE_EMOJI: return

        cursor = self.bot.get_cog("General").get_cursor()

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
            filtered_reacted_users = list(filter(lambda u: not (u == self.bot.user or u.id == suggestor_id), reacted_users))
            further_reactions_needed = NUM_CODEWORD_REQ_VOTES - len(filtered_reacted_users)
            if further_reactions_needed == 0: # there are exactly (just another measure to help avoid doing this twice) enough votes for the word to pass:
                # mark the word as approved in the database
                cursor.execute(f"UPDATE codewords SET approved = 1 WHERE id = {word_id}")

                # reward the user
                cursor.execute(f"UPDATE users SET balance = balance + {CODEWORD_REWARD} WHERE id = {suggestor_id}")

                # commit
                self.bot.get_cog("General").db.commit()

                # send a message notifying of the approval and reward
                await reaction.message.channel.send(f"Added the word **{word}** to codenames. {CODEWORD_REWARD} copper to {self.bot.get_user(suggestor_id).display_name} for the suggestion!")
            if further_reactions_needed >= 0: 
                # update the message with the number of further reactions needed
                further_reactions_needed = NUM_CODEWORD_REQ_VOTES - len(filtered_reacted_users)
                await reaction.message.edit(content=f"React {CODEWORD_VOTE_EMOJI} to this message to approve the codenames word **{word}**! {further_reactions_needed} more vote{'s' if further_reactions_needed != 1 else ''} needed")

        cursor.close()

    async def start_codenames(self, ctx):
        cursor = self.bot.get_cog("General").get_cursor()
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
            self.bot.get_cog("General").db.commit()
        elif query_result[0] != None: # make sure there's not already a start-game going
            await ctx.send(f"It seems someone is already trying to start codenames on this server. If this is not the case, use `{PREFIX}cancel codenames` before giving this command again")
            cursor.close()
            return

        # send a message indicating the allowed role combiniations and seeking reactions to assign roles
        embed = discord.Embed(title="Welcome to Codenames!", description=f"Following the instructions in the `Role Reactions` section, everyone who wants to play must assign themselves a role. No more than one spymaster of either color. If only one spymaster is selected, you'll play a cooperative game; if both are selected, you'll play a competitive game. Use `{PREFIX}begin codenames` to begin the game once everyone is ready.", color=16711935) # magenta
        embed.add_field(name="Role Reactions", value=f"React with the role you want to have in this game: \n\n{BLUE_SPY_EMOJI} - blue spymaster \n{RED_SPY_EMOJI} - red spymaster \n{BLUE_OP_EMOJI} - blue operatives \n{RED_OP_EMOJI} - red operatives \n\nIf there is only one spymaster, it doesn't matter which of the two operative reactions everyone else selects. Two spymasters and only one operative means the operative guesses for both teams.", inline=False)
        embed.set_footer(text=f"Use \"{PREFIX}cancel codenames\" to cancel game start")
        message = await ctx.send(embed=embed)

        # get the id of this message and store it in the guilds table
        cursor.execute(f"UPDATE guilds SET codenamesstartmsg = {int(message.id)} WHERE id = {guild_id}")
        self.bot.get_cog("General").db.commit()

        # set up the reactions
        await message.add_reaction(BLUE_SPY_EMOJI)
        await message.add_reaction(RED_SPY_EMOJI)
        await message.add_reaction(BLUE_OP_EMOJI)
        await message.add_reaction(RED_OP_EMOJI)

        cursor.close()

    async def begin_codenames(self, ctx, start_msg_id):
        
        guild_id = int(ctx.guild.id)

        # get lists of users who have given each reaction
        message = await ctx.fetch_message(start_msg_id)
        players = set()
        num_role_reactions = 0
        role_lists = {}
        for reaction in message.reactions:
            users = await reaction.users().flatten()
            filtered_users = list(filter(lambda u: u != self.bot.user, users))
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
        cursor = self.bot.get_cog("General").get_cursor()
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
        self.bot.get_cog("General").db.commit()

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
        cursor.execute(f"SELECT word FROM codewords WHERE approved ORDER BY RAND() LIMIT 25")
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
        cursor.execute(self.active_codewords_insert_sql(guild_id, blue_words, "blue"))
        cursor.execute(self.active_codewords_insert_sql(guild_id, red_words, "red"))
        cursor.execute(self.active_codewords_insert_sql(guild_id, neutral_words, "neutral"))
        cursor.execute(self.active_codewords_insert_sql(guild_id, assassin_words, "assassin"))
        
        # insert an entry for the game into the codenamesGames table (but don't worry about initializing the entire row yet)
        cursor.execute(f"INSERT INTO codenamesGames (guild, opsChannel) VALUES ({guild_id}, {int(ctx.channel.id)})")

        # commit, get the shuffled words, and close the cursor
        self.bot.get_cog("General").db.commit()
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
        await self.cn_start_spymaster_turn(starting_spymaster, ctx, starting_color, blue_words, [], red_words, [], neutral_words, [], assassin_words[0], shuffled_words)
        
        # send message to second spymaster
        if second_spymaster != None: # second_spymaster == None in a cooperative game
            await self.cn_send_spymaster_update(second_spymaster, second_color, second_words, [], starting_words, [], neutral_words, [], assassin_words[0])
            dm_channel = await get_dm_channel(second_spymaster)
            await dm_channel.send("You'll go second this game—I'll send you another message when it's your turn")

    def active_codewords_insert_sql(self, guild_id, word_list, color):
        '''Build a MySQL INSERT string where the VALUES section includes series of (guild, word, color, revealed) groupings separated by commas, to be used when starting codenames.'''
        values_groupings_list = list(map(lambda word: f"({int(guild_id)}, '{word}', '{color}', 0, RAND())", word_list))
        values_section = ", ".join(values_groupings_list)
        return f"INSERT INTO activeCodewords (guild, word, color, revealed, position) VALUES {values_section}"

    async def cn_send_spymaster_update(self, user: discord.User, color, their_words_unrevealed, their_words_revealed, other_words_unrevealed, other_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word):
        
        # Format each sub-list of words
        display_color = color[0].upper() + color[1:]
        their_words_formatted = '\n'.join(their_words_unrevealed) + (('\n~~' + '\n'.join(their_words_revealed) + '~~\n') if len(their_words_revealed) else '\n')
        other_words_formatted = '\n'.join(other_words_unrevealed) + (('\n~~' + '\n'.join(other_words_revealed) + '~~\n') if len(other_words_revealed) else '\n')
        neutral_words_formatted = '\n'.join(neutral_words_unrevealed) + (('\n~~' + '\n'.join(neutral_words_revealed) + '~~\n') if len(neutral_words_revealed) else '\n')
        
        # Build the embed description
        embed_descr = f"**Your Words**\n" + their_words_formatted
        embed_descr += f"\n**Opponent's Words**\n" + other_words_formatted
        embed_descr += "\n**Neutral Words**" + ("\n" if len(neutral_words_unrevealed) else "") + neutral_words_formatted
        embed_descr += "\n**Assassin Word**\n" + assassin_word
        
        # Build and send embed
        embed = discord.Embed(title=f"Codenames: {display_color} Spymaster", description=embed_descr, color=0x0000ff if color=='blue' else 0xff0000)
        dm_channel = await get_dm_channel(user)
        await dm_channel.send(embed=embed)

    async def cn_send_public_update(self, ctx, next_turn_color, blue_words_revealed, red_words_revealed, neutral_words_revealed, unrevealed_words):
        embed = discord.Embed(title=f"Codenames Board", color=16711935) # magenta
        
        unrevealed_words_formatted = '\n'.join(unrevealed_words) + '\n'
        embed.add_field(name=f"Unrevealed Words", value=unrevealed_words_formatted, inline=False)
        if len(blue_words_revealed):
            blue_words_formatted = '\n'.join(blue_words_revealed) + '\n'
            embed.add_field(name=f"Blue Words", value=blue_words_formatted, inline=False)
        if len(red_words_revealed):
            red_words_formatted = '\n'.join(red_words_revealed) + '\n'
            embed.add_field(name=f"Red Words", value=red_words_formatted, inline=False)
        if len(neutral_words_revealed):
            neutral_words_formatted = '\n'.join(neutral_words_revealed) + '\n'
            embed.add_field(name=f"Neutral Words", value=neutral_words_formatted, inline=False)
        
        await ctx.send(embed=embed)
        await ctx.send(f"Awaiting a clue from the {next_turn_color} spymaster...")

    async def cn_send_declassified_board(self, ctx):
        
        blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word, assassin_is_revealed = self.cn_get_word_lists(int(ctx.guild.id))

        # Format each sub-list of words
        blue_words_formatted = '\n'.join(blue_words_unrevealed) + (('\n~~' + '\n'.join(blue_words_revealed) + '~~\n') if len(blue_words_revealed) else '\n')
        red_words_formatted = '\n'.join(red_words_unrevealed) + (('\n~~' + '\n'.join(red_words_revealed) + '~~\n') if len(red_words_revealed) else '\n')
        neutral_words_formatted = '\n'.join(neutral_words_unrevealed) + (('\n~~' + '\n'.join(neutral_words_revealed) + '~~\n') if len(neutral_words_revealed) else '\n')
        assassin_word_formatted = ("~~" + assassin_word + "~~") if assassin_is_revealed else assassin_word
        
        # Build the embed description
        embed_descr = f"**Blue Words**" + ("\n" if len(blue_words_unrevealed) else "") + blue_words_formatted
        embed_descr += f"\n**Red Words**" + ("\n" if len(red_words_unrevealed) else "") + red_words_formatted
        embed_descr += "\n**Neutral Words**" + ("\n" if len(neutral_words_unrevealed) else "") + neutral_words_formatted
        embed_descr += "\n**Assassin Word**\n" + assassin_word_formatted
        
        # Build and send embed
        embed = discord.Embed(title=f"Codenames Board Declassified", description=embed_descr, color=16711935) # magenta
        await ctx.send(embed=embed)

    async def cn_start_spymaster_turn(self, spymaster: discord.User, guild_ctx, color, blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word, shuffled_unrevealed_words):
        
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
            await self.cn_send_spymaster_update(spymaster, color, their_words_unrevealed, their_words_revealed, other_words_unrevealed, other_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word)
            dm_channel = await get_dm_channel(spymaster)
            await dm_channel.send(f"Your turn! Use `{PREFIX}cnclue <word> <number>` (e.g. `{PREFIX}cnclue bush 2`) to give your clue.")
        
        # message public channel
        await self.cn_send_public_update(guild_ctx, color, blue_words_revealed, red_words_revealed, neutral_words_revealed, shuffled_unrevealed_words)

        # update database
        cursor = self.bot.get_cog("General").get_cursor()
        cursor.execute(f"UPDATE codenamesGames SET turn = '{color} spymaster', numClued = NULL, numGuessed = NULL WHERE guild = {int(guild_ctx.guild.id)}")
        self.bot.get_cog("General").db.commit()
        cursor.close()

    @commands.command(help='Gives a clue, as a codenames spymaster')
    async def cnclue(self, ctx, word, num):
        
        # make sure user is a spymaster (which also checks that a game is going) and it's their turn
        validation_results = await self.cn_validate_spymaster(ctx)
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
        
        guild_id, operatives_channel, turn = validation_results
        cursor = self.bot.get_cog("General").get_cursor()
        cursor.execute(f"SELECT COUNT(*) FROM activeCodewords WHERE guild = {guild_id} AND word = '{word}' AND NOT revealed")
        query_result = cursor.fetchone()[0]
        if query_result > 0:
            await ctx.send(f"You may not use one of the unrevealed words as your clue.")
            cursor.close()
            return

        # let user know their clue was valid
        await ctx.send("Your clue has been submitted!")

        # message public channel
        color = turn.split()[0]
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
        await self.bot.get_channel(operatives_channel).send(f"{mention_string_from_id_strings(these_operative_id_strings)} ({color} operatives): your turn! Your clue is **{word} {num_str}**. Use `{PREFIX}cnguess <word>` (e.g. `{PREFIX}cnguess {unrevealed_word_example}`) to guess a word that you think is the {color} team's.")

        # update database
        cursor.execute(f"UPDATE codenamesGames SET turn = '{color} operative', numClued = {num}, numGuessed = 0 WHERE guild = {guild_id}")
        self.bot.get_cog("General").db.commit()
        cursor.close()

    @cnclue.error
    async def cnclue_error(self, ctx, error):
        
        # see if user is not a spymaster, or if it's not their turn even if they are a spymaster
        validation_results = await self.cn_validate_spymaster(ctx)
        if validation_results == None: return
        
        # okay, just respond to the malformatted command
        if isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f"Use the format `{PREFIX}cnclue <word> <number>` (e.g. `{PREFIX}cnclue bush 2`) to give your clue.")
        else: raise error

    @commands.command(help='Guesses a word, as a codenames operative')
    async def cnguess(self, ctx, guess):
        
        guess = sql_escape_single_quotes(guess)

        # make sure it's not in a private channel
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return

        # make sure user is an operative (which also checks that a game is going) and it's their turn
        validation_results = await self.cn_validate_operative(ctx)
        if validation_results == None: return
        
        # make sure the word is a guessable word
        guild_id, turn_color, _ = validation_results
        cursor = self.bot.get_cog("General").get_cursor()
        cursor.execute(f"SELECT color FROM activeCodewords WHERE guild = {guild_id} AND word = '{guess}' AND NOT revealed")
        query_result = cursor.fetchone()
        if query_result == None: 
            await ctx.send(f"**{sql_unescape_single_quotes(guess)}** is not one of the unrevealed words on the board. Please guess one of those words.")
            cursor.close()
            return

        # mark word as revealed
        cursor.execute(f"UPDATE activeCodewords SET revealed = 1 WHERE guild = {guild_id} AND word = '{guess}'")
        self.bot.get_cog("General").db.commit()
        
        # evaluate guess
        guess_color = query_result[0]
        if guess_color == turn_color: # correct guess
            await ctx.send(f"Nice! **{guess}** is a **{turn_color}** word.")
            
            # see if they won
            cursor.execute(f"SELECT COUNT(*) FROM activeCodewords WHERE guild = {guild_id} AND color = '{turn_color}' AND NOT revealed")
            count_their_unrevealed = cursor.fetchone()[0]
            if count_their_unrevealed == 0: # they won
                await self.cn_end_game(ctx, turn_color)
            else: # they didn't win
                cursor.execute(f"SELECT numClued, numGuessed FROM codenamesGames WHERE guild = {guild_id}")
                num_clued, num_guessed = cursor.fetchone()
                if num_clued < 1 or num_guessed < num_clued: # they're still allowed more guesses (since if num_clued >= 1, they're allowed num_clued + 1 guesses, and we haven't updated num_guessed with this guess yet)
                    cursor.execute(f"UPDATE codenamesGames SET numGuessed = numGuessed + 1 WHERE guild = {guild_id}")
                    self.bot.get_cog("General").db.commit()
                    await ctx.send(f"Use `{PREFIX}cnguess <word>` to guess another word, or use `{PREFIX}cnpass` to end your team's turn.")
                else:
                    await ctx.send("You are now out of guesses, so your turn is over.")
                    await self.cn_end_turn(ctx)
        elif guess_color == 'assassin':
            await ctx.send(f"OH NOOOO!!! **{guess}** is the **ASSASSIN** word!")
            await self.cn_end_game(ctx, self.cn_opposite_color(turn_color))
        else: # they guessed one of the other team's words or a neutral word
            await ctx.send(f"Whoops: **{guess}** is a **{guess_color}** word. Your turn is over")
            
            # see if they lost
            cursor.execute(f"SELECT COUNT(*) FROM activeCodewords WHERE guild = {guild_id} AND color = '{self.cn_opposite_color(turn_color)}' AND NOT revealed")
            count_other_unrevealed = cursor.fetchone()[0]
            if count_other_unrevealed == 0: # they lost
                await self.cn_end_game(ctx, self.cn_opposite_color(turn_color))
            else: # they didn't lose
                await self.cn_end_turn(ctx)

        cursor.close()

    @cnguess.error
    async def cnguess_error(self, ctx, error):
        
        # see if user is not an operative, or if it's not their turn even if they are an operative
        validation_results = await self.cn_validate_operative(ctx)
        if validation_results == None: return
        
        # okay, just respond to the malformatted comman
        guild_id = validation_results[0]
        cursor = self.bot.get_cog("General").get_cursor()
        cursor.execute(f"SELECT word FROM activeCodewords WHERE guild = {guild_id} AND NOT revealed ORDER BY position LIMIT 1")
        unrevealed_word_example = cursor.fetchone()[0]
        cursor.close()
        if isinstance(error, commands.errors.MissingRequiredArgument):
            await ctx.send(f"Use `{PREFIX}cnguess <word>` (e.g. `{PREFIX}cnguess {unrevealed_word_example}`) to guess a word.")
        else: raise error

    @commands.command(help='Ends your team\'s turn, as a codenames operative')
    async def cnpass(self, ctx):
        
        # make sure it's not in a private channel
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return

        # make sure user is an operative (which also checks that a game is going) and it's their turn
        validation_results = await self.cn_validate_operative(ctx)
        if validation_results == None: return

        # make sure the team has guessed at least 
        numGuessed = validation_results[2]
        if numGuessed == 0:
            await ctx.send("Your team must guess at least one word before you can pass your turn.")
            return

        # end their turn
        await self.cn_end_turn(ctx)

    async def cn_validate_spymaster(self, ctx):
        
        # are they a spymasteer
        author_id = int(ctx.author.id)
        cursor = self.bot.get_cog("General").get_cursor()
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

    async def cn_validate_operative(self, ctx):
        
        # are they an operative 
        author_id = int(ctx.author.id)
        cursor = self.bot.get_cog("General").get_cursor()
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

    def cn_opposite_color(self, color):
        if color=='blue': return 'red'
        if color=='red': return 'blue'
        raise ValueError()

    def cn_get_word_lists(self, guild_id):
        '''Query the database for and return the unrevealed and revealed words of each color, plus the assassin word'''
        
        # get stuff from database
        cursor = self.bot.get_cog("General").get_cursor()
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
        assassin_row = list(filter(lambda row: row[1] == 'assassin', words))[0]
        assassin_word = assassin_row[0]
        assassin_is_revealed = assassin_row[2]

        return blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word, assassin_is_revealed

    async def cn_end_turn(self, ctx):

        # get some basic info
        guild_id = int(ctx.guild.id)
        cursor = self.bot.get_cog("General").get_cursor()
        cursor.execute(f"SELECT turn FROM codenamesGames WHERE guild = {guild_id}")
        prev_turn_color = cursor.fetchone()[0].split()[0]
        next_turn_color = self.cn_opposite_color(prev_turn_color)

        # handle extra steps for a cooperative game
        cursor.execute(f"SELECT COUNT(*) FROM members WHERE guild = {guild_id} AND codenamesroleandcolor LIKE '%spymaster'")
        num_spymasters = cursor.fetchone()[0]
        if num_spymasters == 1: # cooperative game

            # reveal a random word for the computer team
            cursor.execute(f"SELECT id, word FROM activeCodewords WHERE guild = {guild_id} AND color = '{next_turn_color}' AND NOT revealed ORDER BY RAND()")
            cpu_unrevealed_words = cursor.fetchall()
            rev_word_id, rev_word = cpu_unrevealed_words[0]
            cursor.execute(f"UPDATE activeCodewords SET revealed = 1 WHERE id = {rev_word_id}")
            self.bot.get_cog("General").db.commit()
            await ctx.send(f"The computer correctly guesses that **{rev_word}** is **{next_turn_color}**.")
            
            # check if the human players lost
            if len(cpu_unrevealed_words) == 1:
                await self.cn_end_game(ctx, next_turn_color)
                cursor.close()
                return
            
            # switch next_turrn_color back to the human players'
            next_turn_color = prev_turn_color
            
        # update game state in database
        cursor.execute(f"UPDATE codenamesGames SET turn = '{next_turn_color} spymaster', numClued = NULL, numGuessed = NULL WHERE guild = {guild_id}")
        self.bot.get_cog("General").db.commit()
            
        # send message updates
        blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word, _ = self.cn_get_word_lists(guild_id)
        cursor.execute(f"SELECT user FROM members WHERE guild = {guild_id} AND codenamesroleandcolor = '{next_turn_color} spymaster'")
        spymaster_id = cursor.fetchone()[0]
        spymaster = self.bot.get_user(spymaster_id)
        cursor.execute(f"SELECT word FROM activeCodewords WHERE guild = {guild_id} AND NOT revealed ORDER BY position")
        shuffled_unrevealed_word_tuples = cursor.fetchall()
        shuffled_unrevealed_words = list(map(lambda word_tuple: word_tuple[0], shuffled_unrevealed_word_tuples))
        await self.cn_start_spymaster_turn(spymaster, ctx, next_turn_color, blue_words_unrevealed, blue_words_revealed, red_words_unrevealed, red_words_revealed, neutral_words_unrevealed, neutral_words_revealed, assassin_word, shuffled_unrevealed_words)
        
        cursor.close()

    async def cn_end_game(self, ctx, winning_color):

        # give rewards
        guild_id = int(ctx.guild.id)
        cursor = self.bot.get_cog("General").get_cursor()
        cursor.execute(f"UPDATE users SET balance = balance + {WIN_CODENAMES_REWARD} WHERE id IN (SELECT user FROM members WHERE guild = {guild_id} AND (codenamesroleandcolor = '{winning_color} spymaster' OR codenamesroleandcolor = '{winning_color} operative'))")
        cursor.execute(f"UPDATE users SET balance = balance + {PLAY_CODENAMES_REWARD} WHERE id IN (SELECT user FROM members WHERE guild = {guild_id} AND (codenamesroleandcolor = '{self.cn_opposite_color(winning_color)} spymaster' OR codenamesroleandcolor = '{self.cn_opposite_color(winning_color)} operative'))")
        cursor.execute(f"UPDATE users SET balance = balance + {DOUBLE_AGENT_REWARD} WHERE id IN (SELECT user FROM members WHERE guild = {guild_id} AND codenamesroleandcolor = 'blue and red operative')")

        # get python list of winning team user ids as strings
        cursor.execute(f"SELECT user FROM members WHERE guild = {guild_id} AND (codenamesroleandcolor = '{winning_color} spymaster' OR codenamesroleandcolor = '{winning_color} operative')")
        query_result = cursor.fetchall()
        winning_user_ids = list(map(lambda player_tuple: str(player_tuple[0]), query_result))

        # get python list of losing team user ids as strings
        cursor.execute(f"SELECT user FROM members WHERE guild = {guild_id} AND (codenamesroleandcolor = '{self.cn_opposite_color(winning_color)} spymaster' OR codenamesroleandcolor = '{self.cn_opposite_color(winning_color)} operative')")
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
        await self.cn_send_declassified_board(ctx)
        
        # reset database stuff
        cursor.execute(f"UPDATE members SET codenamesroleandcolor = NULL WHERE guild = {guild_id}")
        cursor.execute(f"DELETE FROM activeCodewords WHERE guild={guild_id}")
        cursor.execute(f"DELETE FROM codenamesGames WHERE guild={guild_id}")
        self.bot.get_cog("General").db.commit()
        cursor.close()


def setup(bot):
    bot.add_cog(Codenames(bot))
