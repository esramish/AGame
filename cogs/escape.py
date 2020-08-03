import discord
from discord.ext import commands
import re
import random
import os

from agame import PREFIX
ROOT_FILES_DIR = "escape_files"
NO_MATCHED_ACTION_RESPS = [
    "Funny you should try that! Nothing happens",
    "What a fascinating idea!",
    "Perhaps try something else",
    "Mmm nothing there",
    "Not quite helpful",
    "That doesn't feel right to me",
    "I'm not gonna express my opinion about that",
    "Must I comment on that?",
    "Nothing happens. Nice try",
    "More ideas!",
    "More actions!",
    "Perhaps...not",
    "Well you could...",
    "Hey, do I sound robotic to you?",
    "BEEP BEEP BOOP (sorry, those are just random bot sounds)",
    "*crunch crunch*",
    "*sleeps*",
    "*ignores that*",
    "Ew!",
    "A spider lands on your head. Her name is Charlotte's Web. Yes. I know it's weird. It's also not related to anything.",
    "According to all known laws of aviation, you can't do that!",
    "<random response #923, hehehehehehehehe (that rhymes-ish)>",
    "albafjhcvsajnkdfsn;jafds",
    "This does not help your cause.",
    "Democracy!",
    f"ooh, now THAT would be a good codenames word. I'm talking `{PREFIX}codeword that`",
    "*says nothing*",
    "oooooooooooh! oooooooooooh! oooh. Never mind.",
    "Did someone sneeze?",
    "Lemme go check on that! Or don't! Probably won't make a difference",
    "Here is a punctuation mark for you in response to your clever idea: ,",
    "ACHOOOOOO!!!"
]

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
            await ctx.send(f"Welcome to my room!...in which you are TRAPPED! (mwa. ha. ha.) To try to escape, send commands (starting now!) formatted like `{PREFIX}escape touch the black ball` or `{PREFIX}escape enter 32 16 23 on combo lock #3` or `{PREFIX}escape inspect the north wall`")
            return
        else:
            stage = query_result[0]
        
        cursor.close()

        # if the user didn't include any arguments in their command, send a little help
        if len(words) == 0:
            await ctx.send(f"To play the escape room, send a command formatted like `{PREFIX}escape touch the black ball` or `{PREFIX}escape enter 32 16 23 on combo lock #3` or `{PREFIX}escape inspect the north wall`")
            return

        # handle cases where the user wants to view an image
        if words[0].lower() == 'view' and len(words) >= 3:
            try: 
                await self.send_image(ctx, words[1], words[2].lower())
                return
            except FileNotFoundError:
                pass

        # process the user's action
        try: 
            await self.stage_methods[stage](ctx, " ".join(words))
        except IndexError: # the guild has completed all stages implemented so far
            await ctx.send("The room is black—pitch black. You can hear, smell, and feel nothing. You wait for your senses to adjust (or perhaps for the developer to build a puzzle or two) before taking any more actions.")
        
    async def send_image(self, ctx, stage, image_code):
        with open(os.path.join(ROOT_FILES_DIR, str(stage), str(stage) + "-" + image_code + ".png"), "rb") as f:
            await ctx.send(file=discord.File(f, filename=f"{stage}-{image_code}.png"))

    def check_if_action(self, user_str, *action_expr_lists, req_ordered=False, ignore_case=True):
        '''Return a boolean representing whether or not all of the regular expressions of any one of action_expr_lists match (in order, if req_ordered) user_str'''
        for action_exprs in action_expr_lists:
            if self.check_if_action_helper(user_str, action_exprs, req_ordered, ignore_case):
                return True
        return False
    
    def check_if_action_helper(self, user_str_raw, action_exprs, req_ordered, ignore_case):
        '''Return a boolean representing whether or not all of the regular expressions of action_exprs match (in order, if req_ordered) user_str_raw.
        Probably call check_if_action rather than calling this method directly.'''
        user_str = user_str_raw.lower() if ignore_case else user_str_raw
        for expr in action_exprs:
            if ignore_case: expr = expr.lower() # note that this prevents use of regex classes involving capital letters
            match = re.search(expr, user_str)
            if not match:
                return False
            if req_ordered:
                user_str = user_str[match.end():]
        return True

    async def stage_0(self, ctx, action_str):
        '''Initial room'''
        guild_id = int(ctx.guild.id)

        # looking around
        if self.check_if_action(action_str, [r'look|check|see|inspect|examine|describe', r'around|room|surroundings']): 
            await ctx.send("You are in a normal room. Without giving particular attention to any of the six directions, you notice a bed and dresser to the east and a bookshelf to the north.")
        # floor
        elif self.check_if_action(action_str, [r'look|check|see|inspect|examine|describe', r'down|floor|ground']): 
            await ctx.send("There's a plain grey rug in the center of the room. The rest of the floor is wooden paneled.")
        # ceiling
        elif self.check_if_action(action_str, [r'look|check|see|inspect|examine|describe', r'up|roof|ceiling']): 
            await ctx.send("OMG, what a work of art there is on the ceiling! It looks like this:")
            await self.send_image(ctx, 0, '2b8ac9')
            await ctx.send(f"You can use `{PREFIX}escape view 0 2b8ac9` to view this image again")
        elif False:
            # advance them to stage 1
            cursor = self.bot.get_cog("General").get_cursor()
            cursor.execute(f"UPDATE escapeGames SET stage = 1 WHERE guild = {guild_id}")
            cursor.close()
        else:
            await ctx.send(random.choice(NO_MATCHED_ACTION_RESPS))


def setup(bot):
    bot.add_cog(Escape(bot))
