import discord
from discord.ext import commands
from discord.ui import View, Select, Button, Modal, InputText
import json
import asyncio

# Load the configuration from the JSON file
with open('config.json') as f:
    config = json.load(f)

intents = discord.Intents.default()
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

class EventSelect(Select):
    def __init__(self, events):
        options = [
            discord.SelectOption(label=event['name'], description=event['description']) 
            for event in events
        ]
        super().__init__(placeholder='Select an event to host...', options=options)

    async def callback(self, interaction: discord.Interaction):
        event_name = self.values[0]
        event = next(event for event in config['events'] if event['name'] == event_name)
        modal = EventSetupModal(event)
        await interaction.response.send_modal(modal)

class EventSetupModal(Modal):
    def __init__(self, event):
        super().__init__(title=f"Setup {event['name']}")
        self.event = event
        self.add_item(InputText(label="Event Date and Time (YYYY-MM-DD HH:MM)", placeholder="2023-08-01 18:30"))
    
    async def callback(self, interaction: discord.Interaction):
        date_time = self.children[0].value
        event_name = self.event['name']
        embed = discord.Embed(title=f"Sign-up Sheet for {event_name}")
        embed.add_field(name="Date and Time", value=date_time, inline=False)
        for role in self.event['roles']:
            embed.add_field(name=role['name'], value=f"0/{role['max']} signed up", inline=False)

        view = RoleSelectView(self.event, interaction.user.id)
        await interaction.channel.send(embed=embed, view=view)

class EventHostView(View):
    def __init__(self):
        super().__init__()
        self.add_item(EventSelect(config['events']))

class RoleButton(Button):
    def __init__(self, role, event):
        self.role = role
        self.event = event
        super().__init__(label=role['name'], custom_id=f"role_{role['name']}", emoji=role.get('emoji', '🛡️'))

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        event_name = self.event['name']
        role_name = self.role['name']
        multiple_roles = self.event.get('multiple_roles', False)
        exclusive_roles = self.role.get('exclusive_with', [])

        if user_id in self.view.signups:
            if multiple_roles:
                if role_name in self.view.signups[user_id]:
                    self.view.signups[user_id].remove(role_name)
                    if not self.view.signups[user_id]:  # Remove user if no roles left
                        del self.view.signups[user_id]
                    await interaction.response.send_message(f"You have unsubscribed from {role_name}", ephemeral=True)
                else:
                    for existing_role in self.view.signups[user_id]:
                        if existing_role in exclusive_roles:
                            await interaction.response.send_message(f"You cannot sign up for {role_name} along with {existing_role}.", ephemeral=True)
                            return
                    self.view.signups[user_id].append(role_name)
                    await interaction.response.send_message(f"You have signed up for {role_name}", ephemeral=True)
            else:
                if self.view.signups[user_id] == [role_name]:
                    del self.view.signups[user_id]
                    await interaction.response.send_message(f"You have unsubscribed from {role_name}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"You cannot sign up for multiple roles in this event.", ephemeral=True)
                    return
        else:
            role_signups = [r for roles in self.view.signups.values() for r in roles if r == role_name]
            if len(role_signups) >= self.role['max']:
                await interaction.response.send_message(f"The role {role_name} is already full.", ephemeral=True)
                return
            if self.event['max_attendees'] and sum(len(roles) for roles in self.view.signups.values()) >= self.event['max_attendees']:
                await interaction.response.send_message(f"The event {event_name} is already full.", ephemeral=True)
                return

            self.view.signups[user_id] = [role_name]
            await interaction.response.send_message(f"You have signed up for {role_name}", ephemeral=True)

        embed = interaction.message.embeds[0]
        for field in embed.fields:
            if field.name == role_name:
                role_signups = [r for roles in self.view.signups.values() for r in roles if r == role_name]
                field.value = f"{len(role_signups)}/{self.role['max']} signed up"
        await interaction.message.edit(embed=embed, view=self.view)

class RoleSelectView(View):
    def __init__(self, event, host_id):
        super().__init__()
        self.event = event
        self.signups = {}
        self.host_id = host_id
        for role in event['roles']:
            self.add_item(RoleButton(role, event))
        self.add_item(CompleteButton())
        self.add_item(AddMemberButton())
        self.add_item(NotifyButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.host_id:
            await interaction.response.send_message("Only the host can perform this action.", ephemeral=True)
            return False
        return True

class CompleteButton(Button):
    def __init__(self):
        super().__init__(label="Complete & Close Sign-ups", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        for child in self.view.children:
            if isinstance(child, RoleButton):
                child.disabled = True
        await interaction.response.edit_message(view=self.view)
        await interaction.channel.send("Sign-ups are now closed!")

class AddMemberButton(Button):
    def __init__(self):
        super().__init__(label="Add Member", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        modal = AddMemberModal(self.view.event)
        await interaction.response.send_modal(modal)

class AddMemberModal(Modal):
    def __init__(self, event):
        super().__init__(title="Add Member")
        self.event = event
        self.add_item(InputText(label="Member Name"))
        self.add_item(InputText(label="Role"))

    async def callback(self, interaction: discord.Interaction):
        member_name = self.children[0].value
        role_name = self.children[1].value
        member = discord.utils.get(interaction.guild.members, name=member_name)

        if not member:
            await interaction.response.send_message(f"Member {member_name} not found.", ephemeral=True)
            return

        role = next((r for r in self.event['roles'] if r['name'] == role_name), None)
        if not role:
            await interaction.response.send_message(f"Role {role_name} not found.", ephemeral=True)
            return

        role_signups = [r for roles in self.view.signups.values() for r in roles if r == role_name]
        if len(role_signups) >= role['max']:
            await interaction.response.send_message(f"The role {role_name} is already full.", ephemeral=True)
            return

        self.view.signups[member.id] = [role_name]
        await interaction.response.send_message(f"Added {member_name} to {role_name}", ephemeral=True)

        embed = interaction.message.embeds[0]
        for field in embed.fields:
            if field.name == role_name:
                role_signups = [r for roles in self.view.signups.values() for r in roles if r == role_name]
                field.value = f"{len(role_signups)}/{role['max']} signed up"
        await interaction.message.edit(embed=embed, view=self.view)

class NotifyButton(Button):
    def __init__(self):
        super().__init__(label="Notify Team", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        modal = NotifyModal(self.view.signups)
        await interaction.response.send_modal(modal)

class NotifyModal(Modal):
    def __init__(self, signups):
        super().__init__(title="Notify Team")
        self.signups = signups
        self.add_item(InputText(label="Custom Message"))

    async def callback(self, interaction: discord.Interaction):
        message = self.children[0].value
        mentions = [f"<@{user_id}>" for user_id in self.signups.keys()]
        await interaction.channel.send(" ".join(mentions) + "\n" + message)

@bot.event
async def on_ready():
    print(f'Bot is ready. Logged in as {bot.user}')

@bot.command()
async def host(ctx):
    await ctx.author.send("Please select an event to host:", view=EventHostView())

bot.run('DISCORD_BOT_TOKEN')