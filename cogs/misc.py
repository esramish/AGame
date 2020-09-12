import discord
from discord.ext import commands
import random
import asyncio

from agame import PREFIX

PARROT_NOISES = [
    "SQUAAAAAAAAAAAK!",
    "Polly want a cracker!",
    "Polly want a board game!",
    "uggh I was parrot-napping",
    "Who are you calling a parrot???"
]

class Miscellaneous(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(brief="Gets the bot to respond like a parrot", help=f'''Gets the bot to respond like a parrot. Examples:

        `{PREFIX}parrot word` will cause the bot to reply with `word`...usually ;)
        Use quotes (`{PREFIX}parrot "some message"`) for messages with more than one word
        `{PREFIX}parrot "some message" #some-channel` to have the bot reply to #some-channel
        `{PREFIX}parrot "some message" #some-channel 4.5` to have the bot reply to #some-channel after 4.5 seconds
        `{PREFIX}parrot` if ya just wanna have fun'''
    )
    async def parrot(self, ctx, message=None, channel:discord.TextChannel=None, after_seconds:float=0):
        # set the correct destination for the message
        destination = channel if channel != None else ctx
        
        # prepare the specified message or select a parrot noise
        if message == None or random.randint(0,9) == 9:
            message = random.choice(PARROT_NOISES)
        else: 
            message_to_send = message

        # sleep, if so specified
        if after_seconds > 0.001:
            await asyncio.sleep(after_seconds)
        
        # send message
        await destination.send(message)
    
    @parrot.error
    async def parrot_error(self, ctx, error):
        if isinstance(error, commands.errors.BadArgument):
            await ctx.send(
                "Your command isn't formatted correctly. Here are some correct examples:\n\n" +
                f"`{PREFIX}parrot word` will cause the bot to reply with `word`...usually ;)\n" +
                f"Use quotes (`{PREFIX}parrot \"some message\"`) for messages with more than one word\n" +
                f"`{PREFIX}parrot \"some message\" #some-channel` to have the bot reply to `#some-channel`\n" +
                f"`{PREFIX}parrot \"some message\" #some-channel 4.5` to have the bot reply to `#some-channel` after 4.5 seconds\n" +
                f"`{PREFIX}parrot` if ya just wanna have fun"
            )
        else: raise error

def setup(bot):
    bot.add_cog(Miscellaneous(bot))
