from discord.ext import commands
import re

from agame import PREFIX

class Escape(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.stage_methods = [
            self.stage_0
        ]

    @commands.command(help=f"Takes an action in the escape room. The bot will attempt to infer the action you want to take from whatever words and/or numbers you type following `{PREFIX}escape`")
    async def escape(self, ctx, *words):
        
        # make sure command is being given in a guild context
        if ctx.guild == None:
            await ctx.send("Using this command in a private chat is not allowed.")
            return
        
        # figure out guild's current stage in the escape game
        guild_id = int(ctx.guild.id)
        cursor = self.bot.get_cog("General").get_cursor()
        cursor.execute(f"SELECT stage FROM escapeGames WHERE guild = {guild_id}")
        query_result = cursor.fetchone()
        if query_result == None:
            # This is the first time someone has used the escape command in this guild
            cursor.execute(f"INSERT INTO escapeGames (guild, stage) VALUES ({guild_id}, 0)")
            cursor.close()
            await ctx.send(f"Welcome to my room!...in which you are TRAPPED! (mwa. ha. ha.) To try to escape, send commands (starting now!) formatted like `{PREFIX}escape touch the black ball` or `{PREFIX}escape enter 32 16 23 on combo lock #3` or `{PREFIX}escape inspect the left wall`")
            return
        else:
            stage = query_result[0]
        
        cursor.close()

        # if the user didn't include any arguments in their command, send a little help
        if len(words) == 0:
            await ctx.send(f"To play the escape room, send a command formatted like `{PREFIX}escape touch the black ball` or `{PREFIX}escape enter 32 16 23 on combo lock #3` or `{PREFIX}escape inspect the left wall`")
            return

        # process the user's action
        try: 
            await self.stage_methods[stage](ctx, " ".join(words))
        except IndexError: # the guild has completed all stages implemented so far
            await ctx.send("The room is black—pitch black. You can hear, smell, and feel nothing. You wait for your senses to adjust (or perhaps for the developer to build a puzzle or two) before taking any more actions.")

    def check_if_action(self, user_str, *action_expr_lists, req_ordered=False, ignore_case=True):
        '''Return a boolean representing whether or not user_str matches all of the regular expressions of any one of action_expr_lists (in order, if req_ordered)'''
        for action_exprs in action_expr_lists:
            if self.check_if_action_helper(user_str, action_exprs, req_ordered, ignore_case):
                return True
        return False
    
    def check_if_action_helper(self, user_str_raw, action_exprs, req_ordered, ignore_case):
        '''Return a boolean representing whether or not user_str_raw matches all of the regular expressions of action_exprs (in order, if req_ordered).
        Probably call check_if_action rather than calling this method directly.'''
        user_str = user_str_raw.lower() if ignore_case else user_str_raw
        for expr in action_exprs:
            if ignore_case: expr = expr.lower()
            match = re.search(expr, user_str)
            if not match:
                return False
            if req_ordered:
                user_str = user_str[match.end():]
        return True

    async def stage_0(self, ctx, action_str):
        '''Initial room'''
        guild_id = int(ctx.guild.id)

        if self.check_if_action(action_str, [r'look|gaze|glance|check|see', r'up|roof|ceiling|above|top']): 
            await ctx.send("ooo")

        if False:
            # advance them to stage 1
            cursor = self.bot.get_cog("General").get_cursor()
            cursor.execute(f"UPDATE escapeGames SET stage = 1 WHERE guild = {guild_id}")
            cursor.close()





def setup(bot):
    bot.add_cog(Escape(bot))
