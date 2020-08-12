import discord
from discord.ext import commands
import sys

# sys.path.append(sys.path[0][:sys.path[0].index('/cogs')]) # adds the parent directory to the list of paths from which packages can be imported. I don't think it's necessary if running agame.py from that parent directory
from agame import PREFIX

class Money(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='gimmeacopper', help='What could this be???')
    async def onecopper(self, ctx):
        
        self.bot.get_cog("General").confirm_user_in_db_users(ctx.author)
        
        author_id = int(ctx.author.id)
        cursor = self.bot.get_cog("General").get_cursor("buffered")
        cursor.execute(f"UPDATE users SET balance = balance + 1 WHERE id = {author_id}")
        cursor.execute(f"SELECT balance FROM users where id={author_id}")
        query_result = cursor.fetchone()
        balance = query_result[0]
        cursor.close()
        await ctx.send(f"Here ya go! Balance: {balance}")

    @commands.command(name='balance', help='Checks how much money you have')
    async def balance(self, ctx, user: discord.Member=None):

        if user==None: 
            user = ctx.author

        self.bot.get_cog("General").confirm_user_in_db_users(user)
        
        user_id = int(user.id)
        cursor = self.bot.get_cog("General").get_cursor("buffered")
        cursor.execute(f"SELECT balance FROM users where id={user_id}")
        query_result = cursor.fetchone()
        balance = query_result[0]
        cursor.close()
        await ctx.send(f"{user.name}'s balance: {balance}")

    @balance.error
    async def balance_error(self, ctx, error):
        if isinstance(error, commands.errors.BadArgument):
            await ctx.send(f"Use the format `{PREFIX}balance` to check your own balance, or use `{PREFIX}balance <user_mention>` (e.g. `{PREFIX}balance `<@!{self.bot.user.id}>` `) to check someone else's.")
        else: raise error


def setup(bot):
    bot.add_cog(Money(bot))
