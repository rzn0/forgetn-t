# views.py
import discord
import database as db
import logging
from datetime import datetime, timezone

logger = logging.getLogger('discord')

# --- Helper Function to Create Embeds ---

def _parse_timestamp(timestamp_str: Optional[str]) -> datetime:
    """Safely parses a timestamp string from DB to a datetime object, defaulting to UTC."""
    if timestamp_str:
        try:
            dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            return dt.replace(tzinfo=timezone.utc) # Assume DB stores naive datetime as UTC
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing timestamp '{timestamp_str}': {e}. Using current UTC time as fallback.")
    return datetime.now(timezone.utc)

def create_task_embed(task_data: db.sqlite3.Row, status: str, bot_user: discord.ClientUser) -> discord.Embed:
    """Creates a standardized embed for displaying task information (open/in_progress)."""
    title = "❓ Unknown Task State"
    color = discord.Color.greyple()
    if status == 'open':
        title = "📬 Open Task"
        color = discord.Color.blue()
    elif status == 'in_progress':
        title = "⏳ Task In Progress"
        color = discord.Color.orange()

    timestamp_dt = _parse_timestamp(task_data['timestamp'])

    embed = discord.Embed(
        title=title,
        description=f"**Description:**\n{task_data['description']}",
        color=color,
        timestamp=timestamp_dt # Embed timestamp is original creation time
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
    creation_timestamp_dt = _parse_timestamp(task_data['timestamp'])
    completion_timestamp_dt = datetime.now(timezone.utc)

    embed = discord.Embed(
        title="✅ Task Completed!",
        description=f"**Original Description:**\n{task_data['description']}",
        color=discord.Color.green(),
        timestamp=completion_timestamp_dt # Embed timestamp is completion time
    )
    creator = f"<@{task_data['creator_id']}>"
    embed.add_field(name="Created By", value=creator, inline=True)
    if task_data['assignee_id']:
        assignee = f"<@{task_data['assignee_id']}>"
        embed.add_field(name="Originally Assigned To", value=assignee, inline=True)
    else:
        embed.add_field(name="Originally Assigned To", value="N/A", inline=True)
    embed.add_field(name="Completed By", value=completer_user.mention, inline=True)
    embed.add_field(name="Created At", value=discord.utils.format_dt(creation_timestamp_dt, style='R'), inline=False)
    embed.add_field(name="Completed At", value=discord.utils.format_dt(completion_timestamp_dt, style='R'), inline=False)
    embed.set_footer(text=f"Task ID: {task_data['task_id']} | Logged by {bot_user.name}", icon_url=bot_user.display_avatar.url)
    return embed

# --- Button Views ---

class OpenTaskView(discord.ui.View):
    """View for an open task, containing a 'Claim Task' button."""
    def __init__(self, task_id: int):
        super().__init__(timeout=None)
        self.add_item(ClaimButton(task_id=task_id, custom_id=f"claim_task_{task_id}"))

class InProgressTaskView(discord.ui.View):
    """View for an in-progress task, containing a 'Complete Task' button."""
    def __init__(self, task_id: int):
        super().__init__(timeout=None)
        self.add_item(CompleteButton(task_id=task_id, custom_id=f"complete_task_{task_id}"))

# --- Button Components ---

class ClaimButton(discord.ui.Button):
    """Button to claim an open task."""
    def __init__(self, task_id: int, custom_id: str):
        super().__init__(label="Claim Task", style=discord.ButtonStyle.green, custom_id=custom_id, emoji="🙋")
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        """Handles the 'Claim Task' button press."""
        await interaction.response.defer(ephemeral=True) # Acknowledge ephemerally

        guild_id = interaction.guild.id
        user_id = interaction.user.id

        channel_ids = db.get_channel_ids(guild_id)
        if not channel_ids or not channel_ids.get('open') or not channel_ids.get('inprogress'):
            await interaction.followup.send("Task channels (open/in-progress) are not set up correctly.", ephemeral=True)
            return

        task_data = db.get_task_by_id(self.task_id)
        if not task_data:
            await interaction.followup.send("This task no longer exists.", ephemeral=True)
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
            await interaction.followup.send("Failed to claim the task (it might have just been claimed).", ephemeral=True)
            return

        updated_task_data = db.get_task_by_id(self.task_id)
        if not updated_task_data:
            await interaction.followup.send("Error retrieving updated task data after claiming.", ephemeral=True)
            return

        inprogress_channel = interaction.guild.get_channel(channel_ids['inprogress'])
        if not inprogress_channel or not isinstance(inprogress_channel, discord.TextChannel):
            await interaction.followup.send("The 'In Progress' channel is not configured correctly.", ephemeral=True)
            return

        embed = create_task_embed(updated_task_data, 'in_progress', interaction.client.user)
        view = InProgressTaskView(task_id=self.task_id)
        new_inprogress_message = None
        try:
            new_inprogress_message = await inprogress_channel.send(embed=embed, view=view)
            db.update_task_message_id(self.task_id, 'inprogress', new_inprogress_message.id)
            db.update_task_message_id(self.task_id, 'open', None)
        except discord.HTTPException as e:
            await interaction.followup.send(f"Error sending task to 'In Progress' channel: {e}", ephemeral=True)
            if new_inprogress_message: await new_inprogress_message.delete() # Clean up if message sent but DB update failed
            return

        try:
            await interaction.message.delete()
        except discord.HTTPException as e:
            logger.warning(f"Could not delete original 'open' task message {interaction.message.id}: {e}")

        await interaction.followup.send(f"✅ You claimed task **#{self.task_id}**. Moved to 'In Progress'.", ephemeral=True)

class CompleteButton(discord.ui.Button):
    """Button to complete an in-progress task."""
    def __init__(self, task_id: int, custom_id: str):
        super().__init__(label="Complete Task", style=discord.ButtonStyle.primary, custom_id=custom_id, emoji="✅")
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        """Handles the 'Complete Task' button press."""
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        completer_user = interaction.user

        task_data = db.get_task_by_id(self.task_id)
        if not task_data:
            await interaction.followup.send("This task seems to have already been processed or deleted.", ephemeral=True)
            try: await interaction.message.delete()
            except discord.HTTPException: pass
            return

        if task_data['status'] != 'in_progress':
            await interaction.followup.send("This task is not 'in progress'.", ephemeral=True)
            if task_data['inprogress_message_id'] == interaction.message.id:
                 try: await interaction.message.delete()
                 except discord.HTTPException: pass
            return

        channel_ids = db.get_channel_ids(guild_id)
        completed_channel_id = channel_ids.get('completed') if channel_ids else None
        completed_channel = None
        logged_successfully_to_channel = False

        if completed_channel_id:
            completed_channel = interaction.guild.get_channel(completed_channel_id)
            if completed_channel and isinstance(completed_channel, discord.TextChannel):
                completed_embed = create_completed_task_embed(task_data, completer_user, interaction.client.user)
                try:
                    await completed_channel.send(embed=completed_embed)
                    logged_successfully_to_channel = True
                except discord.Forbidden:
                    await interaction.followup.send(f"⚠️ Task processed, but I lack permission to log it in {completed_channel.mention}. It will be completed without this log.", ephemeral=True)
                except discord.HTTPException as e:
                    await interaction.followup.send(f"⚠️ Task processed, but an error occurred logging it: {e}. It will be completed without this log.", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ Configured 'Completed Tasks' channel not found or invalid. Task will be completed without logging there.", ephemeral=True)

        if db.complete_task_in_db(self.task_id):
            try:
                await interaction.message.delete()
            except discord.HTTPException as e:
                logger.warning(f"Could not delete 'in progress' message {interaction.message.id}: {e}")

            completion_message_text = f"🎉 Task **#{self.task_id}** completed by {completer_user.mention}!"
            if logged_successfully_to_channel and completed_channel:
                 completion_message_text += f" Logged in {completed_channel.mention}."
            await interaction.followup.send(completion_message_text, ephemeral=True)
        else:
            await interaction.followup.send("❌ Error marking task as complete in the database (it may have already been processed).", ephemeral=True)