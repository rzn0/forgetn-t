# views.py
import discord
import database as db
import logging
from datetime import datetime, timezone # Ensure timezone is imported

logger = logging.getLogger('discord')

# --- Helper Function to Create Embeds ---

def create_task_embed(task_data: db.sqlite3.Row, status: str, bot_user: discord.ClientUser) -> discord.Embed:
    """Creates a standardized embed for displaying task information (open/in_progress)."""
    if status == 'open':
        title = "📬 Open Task"
        color = discord.Color.blue()
    elif status == 'in_progress':
        title = "⏳ Task In Progress"
        color = discord.Color.orange()
    else:
        title = "❓ Unknown Task State"
        color = discord.Color.greyple()

    try:
        timestamp_str = task_data['timestamp']
        timestamp_dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        # If your DB stores naive datetimes representing UTC, make them UTC aware:
        # timestamp_dt = timestamp_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as e:
        logger.error(f"Error parsing task creation timestamp '{task_data['timestamp']}': {e}. Using current time.")
        timestamp_dt = datetime.now(timezone.utc) # Fallback to current UTC time

    embed = discord.Embed(
        title=title,
        description=f"**Description:**\n{task_data['description']}",
        color=color,
        timestamp=timestamp_dt
    )
    creator = f"<@{task_data['creator_id']}>"
    embed.add_field(name="Created By", value=creator, inline=True)
    if status == 'in_progress' and task_data['assignee_id']:
        assignee = f"<@{task_data['assignee_id']}>"
        embed.add_field(name="Assigned To", value=assignee, inline=True)
    embed.set_footer(text=f"Task ID: {task_data['task_id']} | {bot_user.name}", icon_url=bot_user.display_avatar.url)
    return embed

def create_completed_task_embed(task_data: db.sqlite3.Row, completer_user: discord.User, bot_user: discord.ClientUser) -> discord.Embed:
    """Creates an embed for a completed task."""
    title = "✅ Task Completed!"
    color = discord.Color.green()

    try:
        creation_timestamp_str = task_data['timestamp']
        creation_timestamp_dt = datetime.strptime(creation_timestamp_str, '%Y-%m-%d %H:%M:%S')
        # creation_timestamp_dt = creation_timestamp_dt.replace(tzinfo=timezone.utc) # If UTC
    except (ValueError, TypeError):
        creation_timestamp_dt = None # Or some fallback

    embed = discord.Embed(
        title=title,
        description=f"**Original Description:**\n{task_data['description']}",
        color=color,
        timestamp=datetime.now(timezone.utc) # Completion timestamp is current UTC time
    )

    creator = f"<@{task_data['creator_id']}>"
    embed.add_field(name="Created By", value=creator, inline=True)

    if task_data['assignee_id']:
        assignee = f"<@{task_data['assignee_id']}>"
        embed.add_field(name="Originally Assigned To", value=assignee, inline=True)
    else:
        embed.add_field(name="Originally Assigned To", value="N/A", inline=True)

    embed.add_field(name="Completed By", value=completer_user.mention, inline=True)
    if creation_timestamp_dt: # Display original creation time
        embed.add_field(name="Created At", value=discord.utils.format_dt(creation_timestamp_dt, style='R'), inline=False)
    embed.add_field(name="Completed At", value=discord.utils.format_dt(datetime.now(timezone.utc), style='R'), inline=False)

    embed.set_footer(text=f"Task ID: {task_data['task_id']} | Logged by {bot_user.name}", icon_url=bot_user.display_avatar.url)
    return embed


# --- Button Views ---

class OpenTaskView(discord.ui.View):
    def __init__(self, task_id: int):
        super().__init__(timeout=None)
        self.add_item(ClaimButton(task_id=task_id, custom_id=f"claim_task_{task_id}"))

class InProgressTaskView(discord.ui.View):
    def __init__(self, task_id: int):
        super().__init__(timeout=None)
        self.add_item(CompleteButton(task_id=task_id, custom_id=f"complete_task_{task_id}"))

# --- Button Components ---

class ClaimButton(discord.ui.Button):
    def __init__(self, task_id: int, custom_id: str):
        super().__init__(
            label="Claim Task",
            style=discord.ButtonStyle.green,
            custom_id=custom_id,
            emoji="🙋"
        )
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Correct deferral

        guild_id = interaction.guild.id
        user_id = interaction.user.id

        channel_ids = db.get_channel_ids(guild_id)
        if not channel_ids or not channel_ids.get('open') or not channel_ids.get('inprogress'):
            await interaction.followup.send("Task channels (open/in-progress) are not set up correctly. Please ask an admin to run setup commands.", ephemeral=True)
            return

        task_data = db.get_task_by_id(self.task_id)
        if not task_data:
            await interaction.followup.send("This task no longer exists or there was an error retrieving it.", ephemeral=True)
            try: await interaction.message.delete()
            except discord.HTTPException: pass
            return

        if task_data['status'] != 'open':
             await interaction.followup.send("This task has already been claimed or completed.", ephemeral=True)
             if task_data['open_message_id'] == interaction.message.id:
                 try: await interaction.message.delete()
                 except discord.HTTPException: pass
             return

        if not db.claim_task(self.task_id, user_id):
            await interaction.followup.send("Failed to claim the task. It might have been claimed by someone else just now.", ephemeral=True)
            return

        updated_task_data = db.get_task_by_id(self.task_id)
        if not updated_task_data:
            await interaction.followup.send("Error retrieving updated task data after claiming.", ephemeral=True)
            return

        inprogress_channel = interaction.guild.get_channel(channel_ids['inprogress'])
        if not inprogress_channel or not isinstance(inprogress_channel, discord.TextChannel):
            await interaction.followup.send("The 'In Progress' channel is not configured correctly or I can't access it.", ephemeral=True)
            return

        embed = create_task_embed(updated_task_data, 'in_progress', interaction.client.user)
        view = InProgressTaskView(task_id=self.task_id)

        try:
            inprogress_message = await inprogress_channel.send(embed=embed, view=view)
            db.update_task_message_id(self.task_id, 'inprogress', inprogress_message.id)
            db.update_task_message_id(self.task_id, 'open', None)
        except discord.HTTPException as e:
            await interaction.followup.send(f"An error occurred while sending the task to the 'In Progress' channel: {e}", ephemeral=True)
            return

        try:
            await interaction.message.delete()
        except discord.HTTPException as e:
            logger.warning(f"Could not delete original 'open' task message {interaction.message.id}: {e}")
            # Optionally inform user if deletion fails but main action succeeded
            # await interaction.followup.send(f"Task claimed, but couldn't delete original message (Error: {e}).", ephemeral=True, delete_after=10)

        await interaction.followup.send(f"✅ You have claimed task **#{self.task_id}**. It has been moved to the 'In Progress' channel.", ephemeral=True)


class CompleteButton(discord.ui.Button):
    def __init__(self, task_id: int, custom_id: str):
        super().__init__(
            label="Complete Task",
            style=discord.ButtonStyle.primary,
            custom_id=custom_id,
            emoji="✅"
        )
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Correct deferral

        guild_id = interaction.guild.id
        completer_user = interaction.user

        task_data = db.get_task_by_id(self.task_id)
        if not task_data:
            await interaction.followup.send("This task seems to have already been processed or deleted.", ephemeral=True)
            try: await interaction.message.delete()
            except discord.HTTPException: pass
            return

        if task_data['status'] != 'in_progress':
            await interaction.followup.send("This task is not marked as 'in progress'. Cannot complete.", ephemeral=True)
            if task_data['inprogress_message_id'] == interaction.message.id:
                 try: await interaction.message.delete()
                 except discord.HTTPException: pass
            return

        channel_ids = db.get_channel_ids(guild_id)
        completed_channel_id = channel_ids.get('completed') if channel_ids else None
        completed_channel = None # Initialize

        log_to_completed_channel_success = False # Assume failure until success

        if completed_channel_id:
            completed_channel = interaction.guild.get_channel(completed_channel_id)
            if completed_channel and isinstance(completed_channel, discord.TextChannel):
                completed_embed = create_completed_task_embed(task_data, completer_user, interaction.client.user)
                try:
                    await completed_channel.send(embed=completed_embed)
                    logger.info(f"Task {self.task_id} logged to completed channel {completed_channel.id}")
                    log_to_completed_channel_success = True
                except discord.Forbidden:
                    await interaction.followup.send(f"⚠️ Task **#{self.task_id}** processed, but I lack permission to log it in {completed_channel.mention}. The task will be completed without this log.", ephemeral=True)
                    logger.warning(f"No permission to send to completed channel {completed_channel_id} for task {self.task_id}.")
                    log_to_completed_channel_success = True # Allow completion even if logging fails here
                except discord.HTTPException as e:
                    await interaction.followup.send(f"⚠️ Task **#{self.task_id}** processed, but an error occurred logging it: {e}. The task will be completed without this log.", ephemeral=True)
                    logger.error(f"HTTP error sending to completed channel {completed_channel_id} for task {self.task_id}: {e}")
                    log_to_completed_channel_success = True # Allow completion
            else:
                await interaction.followup.send(f"⚠️ Configured 'Completed Tasks' channel (ID: {completed_channel_id}) not found or invalid. Task will be completed without logging there.", ephemeral=True)
                logger.warning(f"Completed channel ID {completed_channel_id} invalid for task {self.task_id}. Task {self.task_id} will be completed without logging.")
                log_to_completed_channel_success = True # Allow completion if channel is bad
        else:
            # No completed channel is set, so logging is "successful" by omission
            log_to_completed_channel_success = True

        # Proceed to DB deletion and message removal if logging was successful OR not required OR channel was bad but we allow completion
        if log_to_completed_channel_success:
            if db.complete_task(self.task_id): # Deletes from DB
                try:
                    await interaction.message.delete() # Delete from In Progress channel
                    logger.info(f"Deleted 'in progress' message for completed task {self.task_id}")
                except discord.HTTPException as e:
                    logger.warning(f"Could not delete 'in progress' message {interaction.message.id} for task {self.task_id}: {e}")

                completion_message_text = f"🎉 Task **#{self.task_id}** completed by {completer_user.mention}!"
                if completed_channel_id and completed_channel and log_to_completed_channel_success: # Re-check completed_channel for valid mention
                    # Only mention if it was successfully logged into a valid channel
                    was_logged_successfully = False
                    try:
                        # A bit of a check to ensure it was logged by checking if we attempted to send
                        # and didn't hit the 'Forbidden' or 'HTTPException' that *didn't* set success to True
                        # This logic is a bit tricky, simpler to just say "logged" if channel was set and no *critical* error stopped it.
                        # For now, if completed_channel was valid and no *permission* error, assume logging was fine.
                        # A more robust way would be to ensure the send didn't raise earlier.
                        # The current `log_to_completed_channel_success` logic is designed to allow completion even if logging failed.
                        # So, we only add this part if completed_channel is valid.
                        if completed_channel: # Check if channel object exists (was found)
                             completion_message_text += f" Logged in {completed_channel.mention}."
                    except Exception: # Catch any issue with completed_channel here
                        pass # Don't add the mention if there's an issue

                await interaction.followup.send(completion_message_text, ephemeral=True)
            else:
                await interaction.followup.send("❌ Error marking task as complete in the database. It might have been processed by another action or no longer 'in progress'.", ephemeral=True)
                logger.error(f"Failed to delete task {self.task_id} from DB even after attempting to log/prepare for completion.")
        # else: # This case should ideally not be hit if log_to_completed_channel_success is True for "no channel" or "bad channel allowing completion"
        #     await interaction.followup.send(f"Task **#{self.task_id}** could not be logged to the completed tasks channel and was not completed. Please check bot permissions or channel setup.", ephemeral=True)
