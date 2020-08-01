import discord
from discord.ext import commands
import sys

# sys.path.append(sys.path[0][:sys.path[0].index('/cogs')]) # adds the parent directory to the list of paths from which packages can be imported. I don't think it's necessary if running agame.py from that parent directory
from agame import PREFIX, sql_escape_single_quotes

class Money(commands.Cog):
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='gimmeacopper', help='What could this be???')
    async def onecopper(self, ctx):
        cursor = self.bot.get_cog("General").get_cursor()
        author = sql_escape_single_quotes(ctx.author.name)
        cursor.execute(f"SELECT balance FROM users where id={ctx.author.id}")
        query_result = cursor.fetchall()
        if len(query_result) == 0: # user's not in the database yet, so add them in with balance of 1
            cursor.execute(f"INSERT INTO users (id, username, balance) VALUES ({ctx.author.id}, '{author}', 1)")
            balance = 1
        else:
            cursor.execute(f"UPDATE users SET balance = balance + 1 WHERE id = {ctx.author.id}")
            balance = query_result[0][0] + 1
        self.bot.get_cog("General").db.commit()
        cursor.close()
        await ctx.send(f"Here ya go! Balance: {balance}")

    @commands.command(name='balance', help='Checks how much money you have')
    async def balance(self, ctx, user: discord.Member=None):
        cursor = self.bot.get_cog("General").get_cursor()
        if user==None: 
            user = ctx.author
        username = sql_escape_single_quotes(user.name)
        cursor.execute(f"SELECT balance FROM users where id={user.id}")
        query_result = cursor.fetchall()
        if len(query_result) == 0: # user's not in the database yet, so add them in with balance of 0
            cursor.execute(f"INSERT INTO users (id, username, balance) VALUES ({user.id}, '{username}', 0)")
            self.bot.get_cog("General").db.commit()
            balance = 0
        else:
            balance = query_result[0][0]
        cursor.close()
        await ctx.send(f"{user.name}'s balance: {balance}")

    @balance.error
    async def balance_error(self, ctx, error):
        if isinstance(error, commands.errors.BadArgument):
            await ctx.send(f"Use the format `{PREFIX}balance` to check your own balance, or use `{PREFIX}balance <user_mention>` (e.g. `{PREFIX}balance `<@!{self.bot.user.id}>` `) to check someone else's.")
        else: raise error


def setup(bot):
    bot.add_cog(Money(bot))
