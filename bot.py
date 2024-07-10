import discord
from discord.ext import commands
from discord import app_commands
import json
import pytz
from datetime import datetime, timedelta

# Load the configuration with explicit encoding
with open('config.json', encoding='utf-8') as f:
    config = json.load(f)

# Define date and time options
date_options = [(datetime.now() + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(14)]
time_options = [f"{str(h).zfill(2)}:00" for h in range(24)]

# Define the bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
bot = commands.Bot(command_prefix='!', intents=intents)

# Helper function to get the event configuration
def get_event_config(event_name):
    return next((event for event in config['events'] if event['name'] == event_name), None)

# Role selection view
class RoleSelectView(discord.ui.View):
    def __init__(self, event):
        super().__init__()
        self.event = event
        self.signups = {role['name']: [] for role in event['roles']}
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
            max_count = role.get('max', '∞')
            users = "\n".join([f" - <@{user_id}>" for user_id in self.signups[role['name']]])
            role_line = f"**{role['emoji']} {role['name']} ({num_signed_up}/{max_count})**\n"
            role_line += users if users else " - No sign-ups yet"
            role_lines.append(role_line)
        half = (len(role_lines) + 1) // 2
        column1 = "\n\n".join(role_lines[:half])
        column2 = "\n\n".join(role_lines[half:])
        embed.add_field(name="\u200b", value=column1, inline=True)
        embed.add_field(name="\u200b", value=column2, inline=True)
        return embed

    async def close_signups(self, interaction):
        missing_roles = []
        for role in self.event['roles']:
            min_count = role.get('min', 0)
            if len(self.signups[role['name']]) < min_count:
                missing_roles.append(role['name'])
        if missing_roles:
            await interaction.response.send_message(f"The following roles do not meet the minimum requirements: {', '.join(missing_roles)}", ephemeral=True)
        else:
            await self.message.edit(content="Sign-ups are now closed.", embed=None, view=None)
            await interaction.response.send_message("Sign-ups closed successfully.", ephemeral=True)

# Role button
class RoleButton(discord.ui.Button):
    def __init__(self, role, view):
        super().__init__(label=role['name'], style=discord.ButtonStyle.primary, emoji=role.get('emoji', '⚔️'))
        self.role = role
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        role_name = self.role['name']
        current_signups = self.parent_view.signups[role_name]
        if interaction.user.id in current_signups:
            current_signups.remove(interaction.user.id)
        else:
            if not self.parent_view.multiple_roles_allowed and any(interaction.user.id in users for users in self.parent_view.signups.values()):
                await interaction.response.send_message("You can only sign up for one role in this event.", ephemeral=True)
                return
            for ex_role in self.role.get('exclusive_with', []):
                if interaction.user.id in self.parent_view.signups.get(ex_role, []):
                    await interaction.response.send_message(f"You cannot sign up for {role_name} due to role exclusivity restrictions.", ephemeral=True)
                    return
            max_count = self.role.get('max', None)
            if max_count and len(current_signups) >= max_count:
                await interaction.response.send_message(f"The role {role_name} is already full.", ephemeral=True)
                return
            current_signups.append(interaction.user.id)
        self.parent_view.signups[role_name] = current_signups
        embed = self.parent_view.update_embed()
        await self.parent_view.message.edit(embed=embed)
        await interaction.response.send_message(f"You have {'removed from' if interaction.user.id not in current_signups else 'signed up for'} the role: {role_name}.", ephemeral=True)

# Close signups button
class CloseSignupsButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Close Sign-ups", style=discord.ButtonStyle.danger)
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.host_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You are not authorized to close the sign-ups.", ephemeral=True)
            return
        await self.parent_view.close_signups(interaction)

# Ping signups button
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

# Ping message modal
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

# Define the bot commands
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
    app_commands.Choice(name=date, value=date) for date in date_options
])
@app_commands.choices(time=[
    app_commands.Choice(name=time, value=time) for time in time_options
])
async def host(interaction: discord.Interaction, event: str, date: str, time: str, role: discord.Role = None):
    try:
        event_utc_time = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M')
        event_utc_time = pytz.utc.localize(event_utc_time)
        unix_timestamp = int(event_utc_time.timestamp())
        date_time_str = f"**When?** <t:{unix_timestamp}:F> (**<t:{unix_timestamp}:R>**)"
    except ValueError:
        await interaction.response.send_message("Invalid date or time format. Please use YYYY-MM-DD for date and HH:MM for time (24-hour format).", ephemeral=True)
        return
    except pytz.UnknownTimeZoneError:
        await interaction.response.send_message("Unknown time zone. Please provide a valid time zone.", ephemeral=True)
        return

    selected_event = get_event_config(event)
    if not selected_event:
        await interaction.response.send_message("Event not found. Please select a valid event.", ephemeral=True)
        return

    view = RoleSelectView(selected_event)
    view.date_time = date_time_str
    view.host_id = interaction.user.id
    embed = view.update_embed()
    message = await interaction.channel.send(embed=embed, view=view)
    view.message = message

    if role:
        await interaction.channel.send(f"{role.mention}")

    await interaction.response.send_message(f"Event {selected_event['name']} scheduled for {date_time_str}.", ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f'Logged in as {bot.user}!')

