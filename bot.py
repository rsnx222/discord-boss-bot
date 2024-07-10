import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
import json
import pytz
import time

# Load configuration from JSON file
with open('config.json', encoding='utf-8') as f:
    config = json.load(f)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

class MyBot(commands.Bot):
    def __init__(self, guild_id):
        super().__init__(command_prefix="!", intents=intents)
        self.guild_id = guild_id

    async def setup_hook(self):
        guild = discord.Object(id=self.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)  # Sync commands to the specified guild for faster testing

    async def on_ready(self):
        print(f'Bot is ready. Logged in as {self.user}')

guild_id = 1242722293700886591  # Your Guild ID
bot = MyBot(guild_id)

# Pre-populate date options for the next 2 weeks
date_options = [(datetime.now() + timedelta(days=i)).strftime('%A, %d %B') for i in range(14)]
date_values = [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(14)]

# Generate time options every hour from 00:00 to 23:00
time_options = [
    {
        "name": (datetime.strptime("00:00", "%H:%M") + timedelta(hours=i)).strftime('%H:%M'),
        "value": (datetime.strptime("00:00", "%H:%M") + timedelta(hours=i)).strftime('%H:%M')
    } for i in range(24)
]

class RoleSelectView(discord.ui.View):
    def __init__(self, event):
        super().__init__()
        self.event = event
        self.signups = {role['name']: [] for role in event['roles']}  # Initialize with empty lists for each role
        self.date_time = ""
        self.message = None
        self.host_id = None
        self.max_attendees = event.get('max_attendees', None)
        self.multiple_roles_allowed = event.get('multiple_roles', False)
        self.exclusive_roles = {role['name']: role.get('exclusive_with', []) for role in event['roles']}
        for role in event['roles']:
            self.add_item(RoleButton(role, self))
        self.add_item(CloseSignupsButton(self))
        self.add_item(PingSignupsButton(self))

    def update_embed(self):
        embed = discord.Embed(title=f"{self.event['name']}", description=f"{self.date_time}\n\n")

        role_lines = []
        for role in self.event['roles']:
            num_signed_up = len(self.signups[role['name']])
            max_count = role['max']
            users = "\n".join([f" - <@{user_id}>" for user_id in self.signups[role['name']]])
            role_line = f"**{role['emoji']} {role['name']} ({num_signed_up}/{max_count})**\n"
            role_line += users if users else " - No sign-ups yet"
            role_lines.append(role_line)

        # Split role lines into two columns
        half = (len(role_lines) + 1) // 2
        column1 = "\n\n".join(role_lines[:half])
        column2 = "\n\n".join(role_lines[half:])

        # Add fields to embed
        embed.add_field(name="\u200b", value=column1, inline=True)
        embed.add_field(name="\u200b", value=column2, inline=True)

        return embed

class RoleButton(discord.ui.Button):
    def __init__(self, role, view):
        super().__init__(label=role['name'], style=discord.ButtonStyle.primary, emoji=role.get('emoji', '⚔️'))
        self.role = role
        self.parent_view = view  # Use another attribute instead of 'view'

    async def callback(self, interaction: discord.Interaction):
        role_name = self.role['name']
        current_signups = self.parent_view.signups[role_name]

        # Check maximum attendees
        if self.parent_view.max_attendees is not None:
            total_signups = sum(len(users) for users in self.parent_view.signups.values())
            if total_signups >= self.parent_view.max_attendees and interaction.user.id not in current_signups:
                await interaction.response.send_message("The event is already full.", ephemeral=True)
                return

        # Toggle sign-up status
        if interaction.user.id in current_signups:
            current_signups.remove(interaction.user.id)
        else:
            # Check multiple roles
            if not self.parent_view.multiple_roles_allowed and any(interaction.user.id in users for users in self.parent_view.signups.values()):
                await interaction.response.send_message("You can only sign up for one role in this event.", ephemeral=True)
                return

            # Check exclusivity
            for ex_role in self.role.get('exclusive_with', []):
                if interaction.user.id in self.parent_view.signups.get(ex_role, []):
                    await interaction.response.send_message(f"You cannot sign up for {role_name} due to role exclusivity restrictions.", ephemeral=True)
                    return

            current_signups.append(interaction.user.id)

        self.parent_view.signups[role_name] = current_signups
        embed = self.parent_view.update_embed()
        await self.parent_view.message.edit(embed=embed)
        await interaction.response.send_message(f"You have {'removed from' if interaction.user.id not in current_signups else 'signed up for'} the role: {role_name}.", ephemeral=True)





class CloseSignupsButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Close Sign-ups", style=discord.ButtonStyle.danger)
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.host_id:
            await interaction.response.send_message("You are not the host.", ephemeral=True)
            return

        for child in self.parent_view.children:
            if isinstance(child, RoleButton) or isinstance(child, CloseSignupsButton):
                child.disabled = True
            else:
                child.disabled = False
        self.parent_view.clear_items()
        self.parent_view.add_item(PingSignupsButton(self.parent_view))
        self.parent_view.add_item(CancelEventButton(self.parent_view))
        await self.parent_view.message.edit(view=self.parent_view)
        await interaction.response.send_message("Sign-ups are now closed!", ephemeral=True)

class PingMessageModal(discord.ui.Modal, title="Enter Ping Message"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.message = discord.ui.TextInput(label="Message", style=discord.TextStyle.long, placeholder="Enter your custom message here...")
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        mentions = []
        for users in self.view.signups.values():
            mentions.extend([f"<@{user_id}>" for user_id in users])

        if mentions:
            ping_message = self.message.value + " " + " ".join(mentions)
            await interaction.channel.send(ping_message)
            await interaction.response.send_message("Team members have been pinged.", ephemeral=True)
        else:
            await interaction.response.send_message("No users to ping.", ephemeral=True)

class PingSignupsButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Ping Team", style=discord.ButtonStyle.secondary)
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.host_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You are not authorized to ping the team.", ephemeral=True)
            return

        modal = PingMessageModal(self.parent_view)
        await interaction.response.send_modal(modal)



class CancelEventModal(discord.ui.Modal, title="Cancel Event"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.long, placeholder="Enter the reason for cancellation...")
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        mentions = []
        for users in self.view.signups.values():
            mentions.extend([f"<@{user_id}>" for user_id in users])

        apology_message = f"The event has been cancelled. Reason: {self.reason.value}. We apologize for the inconvenience. " + " ".join(mentions)
        await interaction.channel.send(apology_message)
        await self.view.message.delete()
        await interaction.response.send_message("The event has been cancelled.", ephemeral=True)

class CancelEventButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Cancel Event", style=discord.ButtonStyle.danger)
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.host_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You are not authorized to cancel the event.", ephemeral=True)
            return

        modal = CancelEventModal(self.parent_view)
        await interaction.response.send_modal(modal)

class AdminOptionsView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__()
        self.add_item(CancelEventButton(parent_view))
        self.add_item(PingSignupsButton(parent_view))


@bot.tree.command(name="host", description="Host a new event")
@app_commands.describe(
    event="The event you want to host",
    date="The date of the event (YYYY-MM-DD or select from options)",
    time="The time of the event (HH:MM in 24-hour format or select from options)",
    role="Optional role to tag for the event"
)
@app_commands.choices(event=[
    app_commands.Choice(name=event['name'], value=event['name']) for event in config['events']
])
@app_commands.choices(date=[
    app_commands.Choice(name=date, value=value) for date, value in zip(date_options, date_values)
])
@app_commands.choices(time=[
    app_commands.Choice(name=time['name'], value=time['value']) for time in time_options
])
async def host(interaction: discord.Interaction, event: str, date: str, time: str, role: discord.Role = None):
    # Validate custom date and time inputs
    try:
        event_utc_time = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M')
        event_utc_time = pytz.utc.localize(event_utc_time)  # Localize to UTC
        unix_timestamp = int(event_utc_time.timestamp())
        date_time_str = f"**When?** <t:{unix_timestamp}:F> (**<t:{unix_timestamp}:R>**)"  # Full date and time with relative time in bold
    except ValueError:
        await interaction.response.send_message("Invalid date or time format. Please use YYYY-MM-DD for date and HH:MM for time (24-hour format).", ephemeral=True)
        return
    except pytz.UnknownTimeZoneError:
        await interaction.response.send_message("Unknown time zone. Please provide a valid time zone.", ephemeral=True)
        return

    # Find the selected event
    selected_event = next((e for e in config['events'] if e['name'] == event), None)
    if not selected_event:
        await interaction.response.send_message("Event not found. Please select a valid event.", ephemeral=True)
        return

    # Create and send the embed
    view = RoleSelectView(selected_event)
    view.date_time = date_time_str
    view.host_id = interaction.user.id
    embed = view.update_embed()
    message = await interaction.channel.send(embed=embed, view=view)
    view.message = message

    # Notify the tagged role if provided
    if role:
        await interaction.channel.send(f"{role.mention}")

    await interaction.response.send_message(f"Event {selected_event['name']} scheduled for {date_time_str}.", ephemeral=True)





@bot.tree.command(name="clear", description="Clear all messages in this channel")
async def clear(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You do not have permission to clear messages.", ephemeral=True)
        return

    await interaction.response.defer()
    try:
        deleted = await interaction.channel.purge()
        await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)
    except discord.NotFound:
        await interaction.followup.send("Some messages could not be found or have already been deleted.", ephemeral=True)


bot.run('BOT-KEY')