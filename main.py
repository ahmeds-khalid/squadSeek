import nextcord
from nextcord.ext import commands
import mysql.connector
from nextcord import Interaction, SlashOption
import os
from dotenv import load_dotenv
import random

load_dotenv()

# Bot setup
intents = nextcord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Database connection
db = mysql.connector.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT', 3306)),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    database=os.getenv('DB_NAME')
)
cursor = db.cursor()

# Create tables if not exists and add new columns
cursor.execute("""
CREATE TABLE IF NOT EXISTS players (
    id INT AUTO_INCREMENT PRIMARY KEY,
    discord_id VARCHAR(255),
    name VARCHAR(255),
    contact VARCHAR(255),
    game VARCHAR(255),
    note TEXT,
    avatar_url VARCHAR(255),
    discord_name VARCHAR(255)
)
""")

# Check if columns exist, if not, add them
def add_column_if_not_exists(table, column, definition):
    cursor.execute(f"SHOW COLUMNS FROM {table} LIKE '{column}'")
    if not cursor.fetchone():
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"Added column {column} to {table}")

add_column_if_not_exists('players', 'avatar_url', 'VARCHAR(255)')
add_column_if_not_exists('players', 'discord_name', 'VARCHAR(255)')

db.commit()

# Game list
GAMES = [
    "Minecraft", "Fortnite", "Among Us", "PUBG", "Mobile Legends", 
    "Rocket League", "Call of Duty: Warzone", "Apex Legends", "Valorant", 
    "Overwatch 2", "League of Legends", "Fall Guys", "Genshin Impact",
    "Roblox"
]


class SignUpModal(nextcord.ui.Modal):
    def __init__(self):
        super().__init__(
            "Sign Up as Player",
            timeout=5 * 60,  # 5 minutes timeout
        )

        self.name = nextcord.ui.TextInput(label="Your Name", placeholder="Enter your name", required=True)
        self.add_item(self.name)

        self.contact = nextcord.ui.TextInput(label="Contact Info", placeholder="Enter your ID or contact method", required=True)
        self.add_item(self.contact)

        self.game = nextcord.ui.TextInput(
            label="Game",
            placeholder=f"Enter a game from the list (check /games for full list)",
            required=True
        )
        self.add_item(self.game)

        self.note = nextcord.ui.TextInput(label="Note", placeholder="Any additional information?", required=False, style=nextcord.TextInputStyle.paragraph)
        self.add_item(self.note)

    async def callback(self, interaction: nextcord.Interaction):
        # Normalize the game input to lowercase for comparison
        selected_game = self.game.value.strip().lower()

        # Check if the entered game is valid (case insensitive)
        if selected_game not in [game.lower() for game in GAMES]:
            await interaction.response.send_message(f"{self.game.value} is not a valid game.", ephemeral=True)
            return

        # Get user's avatar URL and Discord name
        avatar_url = str(interaction.user.avatar.url) if interaction.user.avatar else None
        discord_name = interaction.user.name

        # Save player info to database
        cursor.execute("""
        INSERT INTO players (discord_id, name, contact, game, note, avatar_url, discord_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (str(interaction.user.id), self.name.value, self.contact.value, selected_game.title(), self.note.value, avatar_url, discord_name))
        db.commit()

        await interaction.response.send_message(f"Thanks for signing up, {self.name.value}!", ephemeral=True)

class PlayerFinderView(nextcord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @nextcord.ui.button(label="Sign Up as Player", emoji="📝", style=nextcord.ButtonStyle.primary)
    async def sign_up(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_modal(SignUpModal())

    @nextcord.ui.button(label="Find Players", emoji="🔍", style=nextcord.ButtonStyle.success)
    async def find_players(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_message("Select a game to find players:", view=GameSelectorView(), ephemeral=True)

    @nextcord.ui.button(label="Delete My Data", emoji="🗑️", style=nextcord.ButtonStyle.danger)
    async def delete_data(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_message("Are you sure you want to delete your data?", view=ConfirmDeletionView(), ephemeral=True)

class ConfirmDeletionView(nextcord.ui.View):
    def __init__(self):
        super().__init__()

    @nextcord.ui.button(label="Confirm Deletion", style=nextcord.ButtonStyle.danger)
    async def confirm_deletion(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        cursor.execute("DELETE FROM players WHERE discord_id = %s", (str(interaction.user.id),))
        db.commit()
        deleted_count = cursor.rowcount
        if deleted_count > 0:
            await interaction.response.send_message("Your data has been successfully deleted.", ephemeral=True)
        else:
            await interaction.response.send_message("No data found to delete.", ephemeral=True)

    @nextcord.ui.button(label="Cancel", style=nextcord.ButtonStyle.secondary)
    async def cancel_deletion(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.send_message("Deletion cancelled.", ephemeral=True)

class GameSelectorView(nextcord.ui.View):
    def __init__(self):
        super().__init__()
        self.selected_game = None
        self.players = []
        self.current_index = -1
        self.message = None

        options = []
        for game in GAMES:
            cursor.execute("SELECT COUNT(*) FROM players WHERE game = %s", (game,))
            player_count = cursor.fetchone()[0]
            options.append(
                nextcord.SelectOption(
                    label=game,
                    description=f"{player_count} player(s) found"
                )
            )

        self.game_select = nextcord.ui.StringSelect(
            placeholder="Select a game",
            options=options,
            custom_id="game_selector"
        )
        self.game_select.callback = self.select_game
        self.add_item(self.game_select)

    async def select_game(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.selected_game = self.game_select.values[0]
        cursor.execute("SELECT name, contact, note, avatar_url, discord_name FROM players WHERE game = %s", (self.selected_game,))
        self.players = cursor.fetchall()
        random.shuffle(self.players)
        self.current_index = 0

        if not self.players:
            await interaction.followup.send(f"No players found for {self.selected_game}.", ephemeral=True)
        else:
            await self.update_player_message(interaction)

    async def update_player_message(self, interaction: nextcord.Interaction):
        if 0 <= self.current_index < len(self.players):
            player = self.players[self.current_index]
            embed = nextcord.Embed(title=f"Player for {self.selected_game}", color=nextcord.Color.green())
            embed.add_field(name="Name:", value=player[0], inline=False)
            embed.add_field(name="ID:", value=player[1], inline=False)
            embed.add_field(name="Note:", value=player[2], inline=False)
            embed.set_author(name=player[4], icon_url=player[3])
            if player[3]:
                embed.set_thumbnail(url=player[3])
            
            view = nextcord.ui.View()
            
            prev_button = nextcord.ui.Button(label="Previous", emoji="◀", style=nextcord.ButtonStyle.secondary, disabled=(self.current_index == 0))
            prev_button.callback = self.prev_player_callback
            view.add_item(prev_button)
            
            next_button = nextcord.ui.Button(label="Next", emoji="▶", style=nextcord.ButtonStyle.primary, disabled=(self.current_index == len(self.players) - 1))
            next_button.callback = self.next_player_callback
            view.add_item(next_button)
            
            if self.message:
                await self.message.edit(embed=embed, view=view)
            else:
                self.message = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            if self.message:
                await self.message.edit(content=f"No more players found for {self.selected_game}.", embed=None, view=None)
            else:
                await interaction.followup.send(f"No more players found for {self.selected_game}.", ephemeral=True)

    async def next_player_callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        if self.current_index < len(self.players) - 1:
            self.current_index += 1
            await self.update_player_message(interaction)

    async def prev_player_callback(self, interaction: nextcord.Interaction):
        await interaction.response.defer()
        if self.current_index > 0:
            self.current_index -= 1
            await self.update_player_message(interaction)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')

@bot.slash_command(name="delete_my_data", description="Delete your data from the player database")
async def delete_my_data(interaction: nextcord.Interaction):
    await interaction.response.send_message("Are you sure you want to delete your data? This action will remove your data from all games.", view=ConfirmDeletionView(), ephemeral=True)

@bot.slash_command(name="games", description="List all available games")
async def list_games(interaction: nextcord.Interaction):
    games_list = "\n".join(GAMES)
    embed = nextcord.Embed(title="Available Games", description=games_list, color=nextcord.Color.blue())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.slash_command(name="setup", description="Set up the SquadSeek embed")
async def setup(interaction: nextcord.Interaction):
    embed = nextcord.Embed(title="SquadSeek", description="Connect with players, find teammates, and discover your next gaming buddy with ease.", color=nextcord.Color.blue())
    embed.set_thumbnail(url=str(bot.user.avatar.url))
    embed.add_field(name="Sign Up as Player", value="Register as a player for a game.")
    embed.add_field(name="Find Players", value="Search for players for a specific game.")
    embed.set_image(url="https://i.postimg.cc/5t45MXS2/banner.png")
    await interaction.channel.send(embed=embed, view=PlayerFinderView())
    await interaction.response.send_message("SquadSeek embed has been set up!", ephemeral=True)

bot.run(os.getenv('DISCORD_TOKEN'))