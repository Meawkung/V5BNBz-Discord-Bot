import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, Select, SelectOption, 

class MyModal(Modal):
    def __init__(self):
        super().__init__(title="Example Form")

        # Add text inputs
        self.add_item(TextInput(label="Name"))
        self.add_item(TextInput(label="Email", style=discord.ui.TextInputStyle.long))
        
        # Add dropdown (select menu)
        self.add_item(
            Select(
                placeholder="Select an option...",
                options=[
                    discord.SelectOption(label="Option 1", value="option_1"),
                    discord.SelectOption(label="Option 2", value="option_2"),
                    discord.SelectOption(label="Option 3", value="option_3"),
                ]
            )
        )

    async def callback(self, interaction: discord.Interaction):
        name = self.children[0].value
        email = self.children[1].value
        selected_option = self.children[2].values[0]  # Get the selected option

        await interaction.response.send_message(
            f"Name: {name}\nEmail: {email}\nSelected Option: {selected_option}", 
            ephemeral=True
        )
