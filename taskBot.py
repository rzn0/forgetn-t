# bot.py
import discord
from discord.ext import commands # For has_permissions
from discord.commands import Option, SlashCommandGroup
import os
import logging
from dotenv import load_dotenv

import database as db
from views import (
    OpenTaskView, InProgressTaskView,
    create_task_embed, create_completed_task_embed # Ensure all needed functions/classes are imported
)

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger('discord') # Main logger for discord.py related logs
# logging.getLogger('database').setLevel(logging.DEBUG) # Example for more verbose DB logs

# --- Environment Variables ---
load_dotenv()
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
if not BOT_TOKEN:
    logger.critical("FATAL ERROR: DISCORD_TOKEN not found in .env file.")
    exit()

# --- Bot Intents ---
intents = discord.Intents.default()
intents.guilds = True        # For guild events and info
intents.messages = True      # For on_message_delete or future message-based commands (if any)
intents.members = True       # For resolving user mentions and guild member info

bot = discord.Bot(intents=intents, command_prefix="!") # Prefix is fallback, not used for slash

# --- Event Handlers ---

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info('Initializing database...')
    db.initialize_database() # This will also handle ALTER TABLE if needed
    logger.info("Bot is ready and database initialized.")

    # Register persistent views (important for buttons to work after bot restart)
    # The task_id=-1 is a placeholder; actual task_id is set when view is sent.
    # The custom_id format (e.g., "claim_task_{task_id}") links buttons to tasks.
    bot.add_view(OpenTaskView(task_id=-1))
    bot.add_view(InProgressTaskView(task_id=-1))
    logger.info("Persistent views registered.")
    print("------")
    print(f"{bot.user.name} is online!")
    print("------")


@bot.event
async def on_guild_join(guild: discord.Guild):
    logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
    channel_to_send = guild.system_channel
    if not channel_to_send: # Fallback if no system channel
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
                f"➡️ If you have tasks from an older version of me, use `/resync_tasks` once after setup."
            )
            logger.info(f"Sent welcome message to {channel_to_send.name} in {guild.name}")
        except discord.Forbidden:
             logger.warning(f"Could not send welcome message in {guild.name} due to permissions.")
        except Exception as e:
            logger.error(f"Error sending welcome message in {guild.name}: {e}")

# Optional: Clean up DB if a task message is manually deleted
# @bot.event
# async def on_message_delete(message: discord.Message):
#     if message.author == bot.user and message.embeds: # Likely one of our task messages
#         removed_from_db = db.remove_task_by_message_id(message.id)
#         if removed_from_db:
#             logger.info(f"Task associated with manually deleted message {message.id} removed from DB.")

# --- Slash Commands ---

setup_group = SlashCommandGroup("setup", "Commands for setting up the task channels.")

@setup_group.command(name="open_channel", description="Set the channel where new tasks will appear.")
@commands.has_permissions(manage_channels=True)
async def set_open_channel_cmd(ctx: discord.ApplicationContext, channel: Option(discord.TextChannel, "The channel for open tasks", required=True)):
    guild_id = ctx.guild.id
    if db.set_channel(guild_id, 'open', channel.id):
        await ctx.respond(f"✅ Open tasks channel set to {channel.mention}.", ephemeral=True)
    else:
        await ctx.respond("❌ Error setting open tasks channel.", ephemeral=True)

@setup_group.command(name="inprogress_channel", description="Set the channel where claimed tasks will appear.")
@commands.has_permissions(manage_channels=True)
async def set_inprogress_channel_cmd(ctx: discord.ApplicationContext, channel: Option(discord.TextChannel, "The channel for in-progress tasks", required=True)):
    guild_id = ctx.guild.id
    if db.set_channel(guild_id, 'inprogress', channel.id):
        await ctx.respond(f"✅ In-progress tasks channel set to {channel.mention}.", ephemeral=True)
    else:
        await ctx.respond("❌ Error setting in-progress tasks channel.", ephemeral=True)

@setup_group.command(name="completed_channel", description="Set the channel where completed tasks will be logged (optional).")
@commands.has_permissions(manage_channels=True)
async def set_completed_channel_cmd(ctx: discord.ApplicationContext, channel: Option(discord.TextChannel, "The channel for completed task logs", required=True)):
    guild_id = ctx.guild.id
    if db.set_channel(guild_id, 'completed', channel.id):
        await ctx.respond(f"✅ Completed tasks will now be logged in {channel.mention}.", ephemeral=True)
    else:
        await ctx.respond("❌ An error occurred while setting the completed tasks channel.", ephemeral=True)

bot.add_application_command(setup_group)


@bot.slash_command(name="addtask", description="Add a new task to the open tasks list.")
async def add_task_cmd(ctx: discord.ApplicationContext, description: Option(str, "Describe the task", required=True)):
    guild_id = ctx.guild.id
    creator_id = ctx.author.id

    channel_ids = db.get_channel_ids(guild_id)
    if not channel_ids or not channel_ids.get('open') or not channel_ids.get('inprogress'):
        await ctx.respond("❌ Open and In-Progress task channels must be set up first. Use `/setup open_channel` and `/setup inprogress_channel`.", ephemeral=True)
        return

    task_id = db.add_task(guild_id, description, creator_id)
    if not task_id:
        await ctx.respond("❌ Error saving task to database.", ephemeral=True)
        return

    open_channel_id = channel_ids.get('open') # Should exist due to check above
    open_channel = bot.get_channel(open_channel_id)

    if not open_channel or not isinstance(open_channel, discord.TextChannel):
        await ctx.respond(f"❌ Configured open tasks channel (ID: {open_channel_id}) not found or invalid. Task created in DB (ID: {task_id}) but not posted.", ephemeral=True)
        logger.error(f"Open channel {open_channel_id} not found/invalid for guild {guild_id} when adding task {task_id}")
        # Consider auto-deleting task from DB if channel is bad: db.complete_task_in_db(task_id) - but this function expects 'in_progress' status
        return

    task_data = db.get_task_by_id(task_id)
    if not task_data: # Should not happen if add_task succeeded
        await ctx.respond("❌ Task added to DB, but couldn't retrieve its data immediately. Cannot post message.", ephemeral=True)
        logger.error(f"Failed to retrieve task {task_id} immediately after adding for guild {guild_id}")
        return

    embed = create_task_embed(task_data, 'open', bot.user)
    view = OpenTaskView(task_id=task_id)

    new_task_message = None
    try:
        new_task_message = await open_channel.send(embed=embed, view=view)
        logger.info(f"Posted new task {task_id} to channel {open_channel.id} in guild {guild_id}")

        if not db.update_task_message_id(task_id, 'open', new_task_message.id):
             logger.error(f"Failed to update open_message_id for task {task_id} after sending message {new_task_message.id}")
             if new_task_message: await new_task_message.delete() # Clean up message if DB link fails
             await ctx.respond("❌ An error occurred updating the task's message link. Task message removed. Please try again.", ephemeral=True)
             # db.remove_task_by_id(task_id) or similar to remove the DB entry
             return

        await ctx.respond(f"✅ Task **#{task_id}** added to {open_channel.mention}!", ephemeral=True)

    except discord.Forbidden:
        await ctx.respond(f"❌ I don't have permission to send messages in the open tasks channel ({open_channel.mention}). Task not created.", ephemeral=True)
        if task_id: db.remove_task_by_message_id(new_task_message.id if new_task_message else 0) # Clean up DB if task was added but message failed
        logger.warning(f"Permission error sending to open channel {open_channel_id}. Task {task_id} (if created) removed from DB.")
    except discord.HTTPException as e:
        await ctx.respond(f"❌ An error occurred while sending the task message: {e}. Task not created.", ephemeral=True)
        if task_id: db.remove_task_by_message_id(new_task_message.id if new_task_message else 0)
        logger.error(f"HTTP error sending task {task_id} to open channel {open_channel_id}: {e}. Task (if created) removed from DB.")
    except Exception as e:
        await ctx.respond(f"❌ An unexpected error occurred: {e}. Task not created.", ephemeral=True)
        if task_id: db.remove_task_by_message_id(new_task_message.id if new_task_message else 0)
        logger.exception(f"Unexpected error adding task {task_id} for guild {guild_id}: {e}")


@bot.slash_command(name="resync_tasks", description="Reposts existing tasks to ensure buttons work (Admin Only).")
@commands.has_permissions(manage_guild=True)
async def resync_tasks_cmd(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)

    guild_id = ctx.guild.id
    channel_ids = db.get_channel_ids(guild_id)

    if not channel_ids or not channel_ids.get('open') or not channel_ids.get('inprogress'):
        await ctx.followup.send("❌ Open and In-Progress task channels must be set up first. Cannot resync.", ephemeral=True)
        return

    open_channel = bot.get_channel(channel_ids['open']) if channel_ids.get('open') else None
    inprogress_channel = bot.get_channel(channel_ids['inprogress']) if channel_ids.get('inprogress') else None

    if not open_channel or not isinstance(open_channel, discord.TextChannel):
        await ctx.followup.send(f"❌ Configured open tasks channel not found or invalid. Cannot resync open tasks.", ephemeral=True)
        return
    if not inprogress_channel or not isinstance(inprogress_channel, discord.TextChannel):
        await ctx.followup.send(f"❌ Configured in-progress tasks channel not found or invalid. Cannot resync in-progress tasks.", ephemeral=True)
        return

    resynced_open_count = 0
    resynced_inprogress_count = 0
    errors = []

    # Resync OPEN tasks
    logger.info(f"Starting resync for 'open' tasks in guild {guild_id}")
    open_tasks_to_resync = db.get_tasks_by_status(guild_id, 'open')
    for task_data in open_tasks_to_resync:
        task_id = task_data['task_id']
        # Attempt to delete old message if its ID is stored
        if task_data['open_message_id']:
            try:
                old_msg = await open_channel.fetch_message(task_data['open_message_id'])
                await old_msg.delete()
                logger.info(f"Resync: Deleted old open message {task_data['open_message_id']} for task {task_id}")
            except (discord.NotFound, discord.Forbidden):
                logger.warning(f"Resync: Old open message {task_data['open_message_id']} for task {task_id} not found or no permission to delete.")

        try:
            embed = create_task_embed(task_data, 'open', bot.user)
            view = OpenTaskView(task_id=task_id)
            new_message = await open_channel.send(embed=embed, view=view)
            if db.update_task_message_id(task_id, 'open', new_message.id):
                db.update_task_message_id(task_id, 'inprogress', None) # Ensure inprogress message ID is cleared
                resynced_open_count += 1
            else:
                errors.append(f"DB update failed for open task {task_id}")
                await new_message.delete() # Clean up
        except Exception as e:
            errors.append(f"Error resyncing open task {task_id}: {str(e)[:100]}")
            logger.exception(f"Resync error for open task {task_id}")

    # Resync IN-PROGRESS tasks
    logger.info(f"Starting resync for 'in_progress' tasks in guild {guild_id}")
    inprogress_tasks_to_resync = db.get_tasks_by_status(guild_id, 'in_progress')
    for task_data in inprogress_tasks_to_resync:
        task_id = task_data['task_id']
        if task_data['inprogress_message_id']:
            try:
                old_msg = await inprogress_channel.fetch_message(task_data['inprogress_message_id'])
                await old_msg.delete()
                logger.info(f"Resync: Deleted old in-progress message {task_data['inprogress_message_id']} for task {task_id}")
            except (discord.NotFound, discord.Forbidden):
                 logger.warning(f"Resync: Old in-progress message {task_data['inprogress_message_id']} for task {task_id} not found or no permission to delete.")

        try:
            embed = create_task_embed(task_data, 'in_progress', bot.user)
            view = InProgressTaskView(task_id=task_id)
            new_message = await inprogress_channel.send(embed=embed, view=view)
            if db.update_task_message_id(task_id, 'inprogress', new_message.id):
                db.update_task_message_id(task_id, 'open', None) # Ensure open message ID is cleared
                resynced_inprogress_count += 1
            else:
                errors.append(f"DB update failed for in-progress task {task_id}")
                await new_message.delete()
        except Exception as e:
            errors.append(f"Error resyncing in-progress task {task_id}: {str(e)[:100]}")
            logger.exception(f"Resync error for in-progress task {task_id}")

    summary = f"✅ Resync Complete!\n" \
              f"📬 Open Tasks Resynced: {resynced_open_count}\n" \
              f"⏳ In-Progress Tasks Resynced: {resynced_inprogress_count}\n"
    if errors:
        summary += "\n⚠️ Errors Encountered (see bot logs for full details):\n" + "\n".join([f"- {e}" for e in errors[:5]])
    summary += "\n\nℹ️ *If any old task messages still appear, you may need to delete them manually.*"
    await ctx.followup.send(summary, ephemeral=True)


# --- Error Handling for Commands ---
@bot.event
async def on_application_command_error(ctx: discord.ApplicationContext, error: discord.DiscordException):
    """Handles errors for slash commands."""
    original_error = getattr(error, 'original', error) # Get original error if wrapped

    if isinstance(original_error, commands.MissingPermissions):
        await ctx.respond("❌ You don't have the required permissions to run this command.", ephemeral=True)
    elif isinstance(original_error, commands.BotMissingPermissions):
        await ctx.respond(f"❌ I lack the necessary permissions: `{'`, `'.join(original_error.missing_perms)}`", ephemeral=True)
    else:
        logger.error(f"Unhandled application command error in guild {ctx.guild_id} for command {ctx.command.qualified_name}:", exc_info=original_error)
        try:
            if ctx.interaction.response.is_done():
                await ctx.followup.send("❌ An unexpected error occurred while processing your command. Please check the bot logs.", ephemeral=True)
            else:
                await ctx.respond("❌ An unexpected error occurred while processing your command. Please check the bot logs.", ephemeral=True)
        except discord.HTTPException: # If responding itself fails
            logger.error("Failed to send error message to user after command error.")


# --- Run the Bot ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("CRITICAL: DISCORD_TOKEN is not set. Exiting.")
    else:
        bot.run(BOT_TOKEN)
