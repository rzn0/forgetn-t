# bot.py (or taskBot.py)
import discord
from discord.ext import commands
from discord.commands import Option, SlashCommandGroup
import os
import logging
from dotenv import load_dotenv

import database as db
from views import (
    OpenTaskView, InProgressTaskView,
    create_task_embed, create_completed_task_embed
)

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord')

# --- Environment Variables ---
load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if not BOT_TOKEN:
    logger.critical("FATAL ERROR: DISCORD_TOKEN not found in .env file.")
    exit()

# --- Bot Intents ---
intents = discord.Intents.default()
intents.guilds = True
intents.messages = True # For potential on_message_delete or future features
intents.members = True  # For resolving user mentions

bot = discord.Bot(intents=intents)

# --- Event Handlers ---

@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info('Initializing database...')
    db.initialize_database()
    logger.info("Bot is ready and database initialized.")

    # Register persistent views
    bot.add_view(OpenTaskView(task_id=-1)) # task_id is a placeholder
    bot.add_view(InProgressTaskView(task_id=-1))
    logger.info("Persistent views registered.")
    print(f"{bot.user.name} is online!")

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Called when the bot joins a new server."""
    logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
    channel_to_send = guild.system_channel
    if not channel_to_send:
         for channel in guild.text_channels:
              if channel.permissions_for(guild.me).send_messages:
                  channel_to_send = channel
                  break
    if channel_to_send:
        try:
            await channel_to_send.send(
                f"Hello! I'm the Task Bot. An administrator needs to set me up:\n"
                f"➡️ Use `/setup open_channel` for new tasks.\n"
                f"➡️ Use `/setup inprogress_channel` for claimed tasks.\n"
                f"➡️ Use `/setup completed_channel` (optional) for logging completed tasks.\n"
                f"➡️ If you have tasks from an older version, use `/resync_tasks` once after setup."
            )
        except Exception as e:
            logger.error(f"Error sending welcome message in {guild.name}: {e}")

# --- Slash Commands ---

setup_group = SlashCommandGroup("setup", "Commands for setting up the task channels.")

@setup_group.command(name="open_channel", description="Set the channel for open tasks.")
@commands.has_permissions(manage_channels=True)
async def set_open_channel_cmd(ctx: discord.ApplicationContext, channel: Option(discord.TextChannel, "Channel for open tasks", required=True)):
    if db.set_channel(ctx.guild.id, 'open', channel.id):
        await ctx.respond(f"✅ Open tasks channel set to {channel.mention}.", ephemeral=True)
    else:
        await ctx.respond("❌ Error setting open tasks channel.", ephemeral=True)

@setup_group.command(name="inprogress_channel", description="Set the channel for in-progress tasks.")
@commands.has_permissions(manage_channels=True)
async def set_inprogress_channel_cmd(ctx: discord.ApplicationContext, channel: Option(discord.TextChannel, "Channel for in-progress tasks", required=True)):
    if db.set_channel(ctx.guild.id, 'inprogress', channel.id):
        await ctx.respond(f"✅ In-progress tasks channel set to {channel.mention}.", ephemeral=True)
    else:
        await ctx.respond("❌ Error setting in-progress tasks channel.", ephemeral=True)

@setup_group.command(name="completed_channel", description="Set the channel for completed task logs (optional).")
@commands.has_permissions(manage_channels=True)
async def set_completed_channel_cmd(ctx: discord.ApplicationContext, channel: Option(discord.TextChannel, "Channel for completed logs", required=True)):
    if db.set_channel(ctx.guild.id, 'completed', channel.id):
        await ctx.respond(f"✅ Completed tasks will be logged in {channel.mention}.", ephemeral=True)
    else:
        await ctx.respond("❌ Error setting completed tasks channel.", ephemeral=True)

bot.add_application_command(setup_group)

@bot.slash_command(name="addtask", description="Add a new task.")
async def add_task_cmd(ctx: discord.ApplicationContext, description: Option(str, "Describe the task", required=True)):
    """Adds a new task to the open tasks list."""
    channel_ids = db.get_channel_ids(ctx.guild.id)
    if not channel_ids or not channel_ids.get('open') or not channel_ids.get('inprogress'):
        await ctx.respond("❌ Open and In-Progress channels must be set up first.", ephemeral=True)
        return

    task_id = db.add_task(ctx.guild.id, description, ctx.author.id)
    if not task_id:
        await ctx.respond("❌ Error saving task to database.", ephemeral=True)
        return

    open_channel = bot.get_channel(channel_ids['open'])
    if not open_channel or not isinstance(open_channel, discord.TextChannel):
        await ctx.respond(f"❌ Configured open tasks channel not found/invalid. Task DB ID: {task_id}", ephemeral=True)
        return

    task_data = db.get_task_by_id(task_id)
    if not task_data:
        await ctx.respond("❌ Task added to DB, but couldn't retrieve its data.", ephemeral=True)
        return

    embed = create_task_embed(task_data, 'open', bot.user)
    view = OpenTaskView(task_id=task_id)
    new_task_message = None
    try:
        new_task_message = await open_channel.send(embed=embed, view=view)
        if not db.update_task_message_id(task_id, 'open', new_task_message.id):
             if new_task_message: await new_task_message.delete()
             await ctx.respond("❌ Error linking task message. Task removed. Try again.", ephemeral=True)
             # db.remove_task_by_id(task_id) could be an option if defined
             return
        await ctx.respond(f"✅ Task **#{task_id}** added to {open_channel.mention}!", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"❌ Error sending task message: {e}. Task not created.", ephemeral=True)
        if task_id and new_task_message: db.remove_task_by_message_id(new_task_message.id)
        elif task_id: logger.warning(f"Task {task_id} created in DB but message send failed without message ID.")

@bot.slash_command(name="resync_tasks", description="Reposts existing tasks to ensure buttons work (Admin Only).")
@commands.has_permissions(manage_guild=True)
async def resync_tasks_cmd(ctx: discord.ApplicationContext):
    """Refreshes tasks by re-posting them and updating message IDs."""
    await ctx.defer(ephemeral=True)
    guild_id = ctx.guild.id
    channel_ids = db.get_channel_ids(guild_id)

    if not channel_ids or not channel_ids.get('open') or not channel_ids.get('inprogress'):
        await ctx.followup.send("❌ Open and In-Progress channels must be set up first.", ephemeral=True)
        return

    open_channel = bot.get_channel(channel_ids['open']) if channel_ids.get('open') else None
    inprogress_channel = bot.get_channel(channel_ids['inprogress']) if channel_ids.get('inprogress') else None

    if not open_channel or not isinstance(open_channel, discord.TextChannel):
        await ctx.followup.send("❌ Open tasks channel not found/invalid.", ephemeral=True)
        return
    if not inprogress_channel or not isinstance(inprogress_channel, discord.TextChannel):
        await ctx.followup.send("❌ In-progress tasks channel not found/invalid.", ephemeral=True)
        return

    resynced_open, resynced_inprogress, errors = 0, 0, []

    for status, target_channel, TaskViewClass in [('open', open_channel, OpenTaskView), ('in_progress', inprogress_channel, InProgressTaskView)]:
        logger.info(f"Resyncing '{status}' tasks in guild {guild_id}")
        tasks_to_resync = db.get_tasks_by_status(guild_id, status)
        for task_data in tasks_to_resync:
            task_id = task_data['task_id']
            old_msg_id_col = f"{status}_message_id"
            if task_data[old_msg_id_col]:
                try:
                    old_msg = await target_channel.fetch_message(task_data[old_msg_id_col])
                    await old_msg.delete()
                except (discord.NotFound, discord.Forbidden): pass # Ignore if old message is gone/unreachable

            try:
                embed = create_task_embed(task_data, status, bot.user)
                view = TaskViewClass(task_id=task_id)
                new_message = await target_channel.send(embed=embed, view=view)
                if db.update_task_message_id(task_id, status, new_message.id):
                    # Clear the other status message ID if it exists to prevent confusion
                    other_status = 'inprogress' if status == 'open' else 'open'
                    db.update_task_message_id(task_id, other_status, None)
                    if status == 'open': resynced_open += 1
                    else: resynced_inprogress += 1
                else:
                    errors.append(f"DB update fail for {status} task {task_id}")
                    await new_message.delete()
            except Exception as e:
                errors.append(f"Error resyncing {status} task {task_id}: {str(e)[:100]}")

    summary = f"✅ Resync Complete!\n📬 Open: {resynced_open}\n⏳ In-Progress: {resynced_inprogress}\n"
    if errors: summary += "⚠️ Errors (see logs):\n" + "\n".join([f"- {e}" for e in errors[:5]])
    summary += "\nℹ️ *Old messages (if any) were attempted to be deleted. Manual cleanup may be needed.*"
    await ctx.followup.send(summary, ephemeral=True)

# --- Error Handling for Commands ---
@bot.event
async def on_application_command_error(ctx: discord.ApplicationContext, error: discord.DiscordException):
    """Global error handler for slash commands."""
    original_error = getattr(error, 'original', error)
    if isinstance(original_error, commands.MissingPermissions):
        msg = "❌ You lack permissions for this command."
    elif isinstance(original_error, commands.BotMissingPermissions):
        msg = f"❌ I lack permissions: `{'`, `'.join(original_error.missing_perms)}`"
    else:
        logger.error(f"Unhandled error for cmd '{ctx.command.qualified_name}':", exc_info=original_error)
        msg = "❌ An unexpected error occurred. Check bot logs."

    try:
        if ctx.interaction.response.is_done(): await ctx.followup.send(msg, ephemeral=True)
        else: await ctx.respond(msg, ephemeral=True)
    except discord.HTTPException:
        logger.error("Failed to send error message to user after command error.")

# --- Run the Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN: print("CRITICAL: DISCORD_TOKEN is not set.")
    else: bot.run(BOT_TOKEN)