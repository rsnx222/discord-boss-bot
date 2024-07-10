import discord
from discord.ext import commands
from discord import app_commands
import json
from datetime import datetime, timedelta

# Load the configuration from the JSON file
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

@bot.tree.command(name="host", description="Host a new event")
@app_commands.describe(
    event="The event you want to host",
    date="The date of the event",
    time="The time of the event (HH:MM in 24-hour format)"
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
async def host(interaction: discord.Interaction, event: str, date: str, time: str):
    # Check if time is a custom input
    is_custom_time = all(char.isdigit() or char == ':' for char in time)
    
    if not is_custom_time:
        await interaction.response.send_message("Invalid time format. Please use HH:MM in 24-hour format or select from the provided options.", ephemeral=True)
        return
    
    # Validate date and time
    try:
        event_date_time = datetime.strptime(f"{date} {time}", '%Y-%m-%d %H:%M')
        date_time_str = event_date_time.strftime('%Y-%m-%d %H:%M')
    except ValueError:
        await interaction.response.send_message("Invalid date or time format. Please use YYYY-MM-DD for date and HH:MM for time (24-hour format).", ephemeral=True)
        return

    # Find the selected event
    selected_event = next((e for e in config['events'] if e['name'] == event), None)
    if not selected_event:
        await interaction.response.send_message("Event not found. Please select a valid event.", ephemeral=True)
        return

    embed = discord.Embed(title=f"Sign-up Sheet for {selected_event['name']}", description=f"Event Date and Time: {date_time_str}\n\nSelect roles below:")
    view = RoleSelectView(selected_event)
    view.date_time = date_time_str
    view.host_id = interaction.user.id
    message = await interaction.channel.send(embed=embed, view=view)
    view.message = message
    await interaction.response.send_message(f"Event {selected_event['name']} scheduled for {date_time_str}.", ephemeral=True)

class RoleSelectView(discord.ui.View):
    def __init__(self, event):
        super().__init__()
        self.event = event
        self.signups = {}  # Role name -> list of user ids
        self.date_time = ""
        self.message = None
        self.host_id = None
        self.max_attendees = event.get('max_attendees', None)
        self.multiple_roles_allowed = event.get('multiple_roles', False)
        for role in event['roles']:
            self.add_item(RoleButton(role, self))
        self.add_item(CloseSignupsButton(self))
        self.add_item(PingSignupsButton(self))

    def update_embed(self):
        description = f"Event Date and Time: {self.date_time}\n\n"
        for role in self.event['roles']:
            num_signed_up = len(self.signups.get(role['name'], []))
            max_count = role['max']
            users = ", ".join([f"<@{user_id}>" for user_id in self.signups.get(role['name'], [])])
            description += f"{role['emoji']} {role['name']}: {num_signed_up}/{max_count} signed up\n"
            if users:
                description += f" - {users}\n"
        return discord.Embed(title=f"Sign-up Sheet for {self.event['name']}", description=description)

class RoleButton(discord.ui.Button):
    def __init__(self, role, view):
        super().__init__(label=role['name'], style=discord.ButtonStyle.primary, emoji=role.get('emoji', '⚔️'))
        self.role = role
        self.parent_view = view  # Use another attribute instead of 'view'

    async def callback(self, interaction: discord.Interaction):
        role_name = self.role['name']
        current_signups = self.parent_view.signups.get(role_name, [])

        # Check maximum attendees
        if self.parent_view.max_attendees is not None:
            total_signups = sum(len(users) for users in self.parent_view.signups.values())
            if total_signups >= self.parent_view.max_attendees and interaction.user.id not in current_signups:
                await interaction.response.send_message("The event is already full.", ephemeral=True)
                return

        # Check exclusivity
        if interaction.user.id in current_signups:
            current_signups.remove(interaction.user.id)
        else:
            # Check multiple roles
            if not self.parent_view.multiple_roles_allowed and any(interaction.user.id in users for users in self.parent_view.signups.values()):
                await interaction.response.send_message("You can only sign up for one role in this event.", ephemeral=True)
                return

            # Check exclusivity
            for ex_role in self.role.get('exclusive_with', []):
                if ex_role in self.parent_view.signups and interaction.user.id in self.parent_view.signups[ex_role]:
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

class PingSignupsButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Ping Team", style=discord.ButtonStyle.secondary)
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.host_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You are not authorized to ping the team.", ephemeral=True)
            return

        mentions = []
        for users in self.parent_view.signups.values():
            mentions.extend([f"<@{user_id}>" for user_id in users])

        if mentions:
            await interaction.channel.send(" ".join(mentions))
            await interaction.response.send_message("Team members have been pinged.", ephemeral=True)
        else:
            await interaction.response.send_message("No users to ping.", ephemeral=True)

class CancelEventButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Cancel Event", style=discord.ButtonStyle.danger)
        self.parent_view = view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.host_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You are not authorized to cancel the event.", ephemeral=True)
            return

        await self.parent_view.message.delete()
        await interaction.response.send_message("The event has been cancelled.", ephemeral=True)

class AdminOptionsView(discord.ui.View):
    def __init__(self, parent_view):
        super().__init__()
        self.add_item(CancelEventButton(parent_view))
        self.add_item(PingSignupsButton(parent_view))

@bot.tree.command(name="clear", description="Clear all messages in this channel")
async def clear(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You do not have permission to clear messages.", ephemeral=True)
        return

    await interaction.response.defer()
    deleted = await interaction.channel.purge()
    await interaction.followup.send(f"Deleted {len(deleted)} messages.", ephemeral=True)

bot.run('BOT-TOKEN')