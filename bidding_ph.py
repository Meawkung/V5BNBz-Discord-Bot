import discord
from discord.ui import Button, View, Select
import asyncio
import time

# Dictionary to store the quantity of bids for each card
card_bids = {
    "Deviling Puppet II": [],
    "Drake Puppet II": [],
    "Eddga Puppet II": [],
    "Phreeoni Puppet II": [],
    "Goblin Leader Puppet II": [],
    "Doppelganger Puppet II": [],
    "Angeling Puppet II": [],
    "Moonlight Flower Puppet II": [],
    "Golden Thief Bug Puppet II": [],
    "Baphomet Puppet II": []
}

# List to track the order of card bids
card_bid_order = []

class CardButton(Button):
    def __init__(self, label):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        formatted_name = f"{user.mention} ({user.name})"
        current_timestamp = int(time.time())  # Get current Unix timestamp
        
        # Check if user already has a bid for this card
        existing_bid = next((bid for bid in card_bids[self.label] if bid.startswith(f"{user.mention}")), None)
        
        if existing_bid:
            # User already bid, increase their quantity
            quantity = int(existing_bid.split(" - ")[1].split(" ")[0]) + 1
            card_bids[self.label].remove(existing_bid)  # Remove old bid
            # Add updated bid with timestamp
            card_bids[self.label].append(f"{formatted_name} - {quantity} <t:{current_timestamp}:f>")
        else:
            # New bid, starting quantity at 1
            card_bids[self.label].append(f"{formatted_name} - 1 <t:{current_timestamp}:f>")
            
        # If it's the first bid for this card, add it to the order list
        if self.label not in card_bid_order:
            card_bid_order.append(self.label)
            
        await self.update_message(interaction)

    async def update_message(self, interaction: discord.Interaction):
        # Prepare a list of cards with active bids, displayed in the order they were bid on
        active_bids = {card: bidders for card, bidders in card_bids.items() if bidders}
        if not active_bids:
            new_content = "No current bids."
        else:
            # Sort cards by number of bids, and for equal bids, by the order they were first bid on
            sorted_cards = sorted(
                card_bid_order, 
                key=lambda card: (-len(card_bids[card]), card_bid_order.index(card))
            )
            new_content = "\n".join(
                f"# **{card}**:\n" + "\n".join(f"{idx + 1}. {bidder}" for idx, bidder in enumerate(card_bids[card]))
                for card in sorted_cards if card_bids[card]  # Ensure only cards with active bids are displayed
            )

        # Update the message with the current bid queue
        await interaction.response.edit_message(content=new_content, view=self.view)

class ClearBidsButton(Button):
    def __init__(self):
        super().__init__(label="Clear My Bids", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user

        # Clear user's bids from all cards
        for card in card_bids.keys():
            card_bids[card] = [bid for bid in card_bids[card] if not bid.startswith(f"{user.mention}")]

        # Update bid order, removing cards with no active bids
        card_bid_order[:] = [card for card in card_bid_order if card_bids[card]]

        # Prepare a list of cards with active bids after clearing
        active_bids = {card: bidders for card, bidders in card_bids.items() if bidders}
        if not active_bids:
            new_content = "No current bids."
        else:
            # Sort cards by number of bids, and for equal bids, by the order they were first bid on
            sorted_cards = sorted(
                card_bid_order, 
                key=lambda card: (-len(card_bids[card]), card_bid_order.index(card))
            )
            new_content = "\n".join(
                f"# **{card}**:\n" + "\n".join(f"{idx + 1}. {bidder}" for idx, bidder in enumerate(card_bids[card]))
                for card in sorted_cards if card_bids[card]  # Ensure only cards with active bids are displayed
            )

        # Update the message to reflect the cleared bids
        await interaction.response.edit_message(content=new_content, view=self.view)

class DoneBiddingButton(Button):
    def __init__(self):
        super().__init__(label="Done Bidding", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        
        # Find the user's active bids
        user_bids = {card: bids for card, bids in card_bids.items() if any(bid.startswith(f"{user.mention}") for bid in bids)}
        
        if not user_bids:
            await interaction.response.send_message("You don't have any active bids.", ephemeral=True)
            return
        
        # Create a selection menu to choose which cards to mark as "Done"
        select = Select(placeholder="Select the card(s) to mark as Done", min_values=1, max_values=len(user_bids))
        
        # Add options for each card the user has bid on
        for card in user_bids:
            select.add_option(label=card, value=card)

        # Callback for when the user selects cards to mark as Done
        async def select_callback(interaction: discord.Interaction):
            selected_cards = select.values

            # Mark selected cards as Done
            for card in selected_cards:
                card_bids[card] = [
                    f"{bid} ✅ (Done)" if bid.startswith(f"{user.mention}") else bid
                    for bid in card_bids[card]
                ]

            # Prepare a list of cards with active bids
            active_bids = {card: bidders for card, bidders in card_bids.items() if bidders}

            if not active_bids:
                new_content = "No current bids."
            else:
                sorted_cards = sorted(
                    card_bid_order, 
                    key=lambda card: (-len(card_bids[card]), card_bid_order.index(card))
                )
                new_content = "\n".join(
                    f"# **{card}**:\n" + "\n".join(f"{idx + 1}. {bidder}" for idx, bidder in enumerate(bidders)) 
                    for card, bidders in active_bids.items()
                )

            # Update the message to reflect the changes
            await interaction.response.edit_message(content=new_content, view=view)

        select.callback = select_callback

        # Create a new view for the select menu
        view = View()
        view.add_item(select)

        # Send the select menu to the user
        await interaction.response.send_message("Choose the cards to mark as Done:", view=view, ephemeral=True)


class RestartButton(Button):
    def __init__(self):
        super().__init__(label="Restart Bidding", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to restart bidding.", ephemeral=True)
            return

        # Clear all bids and reset bid order
        for card in card_bids.keys():
            card_bids[card].clear()

        card_bid_order.clear()  # Reset the order

        # Prepare a message indicating that the bidding has been restarted
        new_content = "Bidding has been restarted. Choose a card to bid on:"
        
        # Recreate the view with the buttons
        view = BiddingView()
        for card in card_bids.keys():
            view.add_item(CardButton(label=card))
        
        # Add Clear Bids Button
        view.add_item(ClearBidsButton())

        # Add Done Bidding Button
        view.add_item(DoneBiddingButton())
        
        # Add Restart Button for Admins
        view.add_item(RestartButton())  # Always enabled for admin

        # Update the message to reflect the cleared bids
        await interaction.response.edit_message(content=new_content, view=view)

class RefreshButton(Button):
    def __init__(self):
        super().__init__(label="🔃", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        # Prepare a list of cards with active bids
        active_bids = {card: bidders for card, bidders in card_bids.items() if bidders}
        
        if not active_bids:
            new_content = "No current bids."
        else:
            # Sort cards by number of bids, and for equal bids, by the order they were first bid on
            sorted_cards = sorted(
                card_bid_order, 
                key=lambda card: (-len(card_bids[card]), card_bid_order.index(card))
            )
            new_content = "\n".join(
                f"# **{card}**:\n" + "\n".join(f"{idx + 1}. {bidder}" for idx, bidder in enumerate(card_bids[card]))
                for card in sorted_cards if card_bids[card]  # Ensure only cards with active bids are displayed
            )

        # Update the message with the current bid queue
        await interaction.response.edit_message(content=new_content, view=self.view)

class BiddingView(View):
    def __init__(self):
        super().__init__(timeout=None)  # Disable timeout for this view
        self.add_item(RefreshButton())  # Add the refresh button

async def setup_bidding_system(bot):
    # Create an initial message with the User Guide
    user_guide = (
        "# 🔶 วิธีใช้บอทประมูลใน Discord แบบง่ายๆ (DEV)\n"
        "สวัสดีครับ! มาทำความรู้จักกับบอทประมูลตัวใหม่ของเรากันดีกว่า ใช้งานง่ายมากๆ เลย:\n"
        "## เริ่มต้นยังไงดี?\n"
        "- แค่เช็คว่าบอทออนไลน์อยู่ในห้องแชทที่กำหนดไว้ก็พอ\n"
        "## อยากประมูลการ์ด ทำไงดี?\n"
        "1. เห็นการ์ดที่ชอบใช่มั้ย? กดปุ่มเลย! (เช่น ปุ่ม Deviling Puppet II)\n"
        "2. อยากเพิ่มจำนวนที่ประมูล? แค่กดปุ่มเดิมซ้ำๆ มันจะเพิ่มให้ทีละ 1 เอง\n"
        "3. อยากรู้ว่าใครประมูลอะไรบ้าง? บอทจะอัพเดตให้เองทุกครั้งที่มีคนประมูล\n"
        "## จัดการประมูลของเรา\n"
        "- เปลี่ยนใจ อยากยกเลิกหมด: กดปุ่ม \"Clear My Bids\" \n"
        "- ประมูลเสร็จแล้ว: กด \"Done Bidding\" ให้เลือกการ์ดที่ได้ทำการประมูลไปแล้ว จากนั้นจะมีเครื่องหมายถูก (✅) มาให้เอง\n"
        "- เห้ ข้อมูลไม่อัพเดทรึปล่าวนะ: กด \"🔃\" เพื่อทำการดึงข้อมูลจากระบบขึ้นมาใหม่\n"
        "## สำหรับแอดมิน\n"
        "- อยากรีเซ็ตการประมูลทั้งหมด: กดปุ่ม \"Restart Bidding\" ได้เลย (แต่ต้องเป็นแอดมินเท่านั้นนะ)\n"
        "## ใครทำอะไรได้บ้าง?\n"
        "- ทุกคนประมูลได้ ยกเลิกได้ กดเสร็จสิ้นได้หมด\n"
        "- แต่การรีเซ็ตทั้งหมดนี่ ขอสงวนสิทธิ์ไว้ให้แอดมินนะ\n"
        "มีข้อสงสัยอะไร ถามได้เลย! 🎉\n"
        "# 🔶 **Discord Bidding Bot User Guide**\n"
        "Welcome to the Bidding Bot! Here’s how to use it:\n"
        "## **Getting Started**\n"
        "- **Check**: Ensure the bot is online in the designated channel.\n"
        "## **Bidding on Cards**\n"
        "1. **Select a Card:** Click the button for the card you want to bid on (e.g., Deviling Puppet II).\n"
        "2. **Auto Quantity:** Bidding on the same card increases your bid quantity by 1.\n"
        "3. **Current Bids:** The bot will update the bids after each action.\n"
        "## **Manage Bids**\n"
        "- **Clear My Bids:** Click to remove all your bids.\n"
        "- **Done Bidding:** Click to select cards that you've bidding now (✅ will be added).\n"
        "- **🔃** Click to refresh the bid list.\n"
        "## **Admin Controls**\n"
        "- **Restart Bidding:** Admins can reset the bidding for everyone by clicking the Restart button.\n"
        "## **Permissions**\n"
        "- Only admins can restart the bidding. All users can bid, clear bids, and mark them done.\n"
        "If you have questions, feel free to ask! 🎉\n\n"
    )

    # Send the user guide to a specific channel
    channel = bot.get_channel(469091654536527872)  # Replace with your channel ID
    if channel:
        await channel.send(user_guide)

    # Create a bidding view with buttons as before
    view = BiddingView()
    
    # Add Card Buttons
    for card in card_bids.keys():
        view.add_item(CardButton(label=card))
    
    # Add Clear Bids Button
    view.add_item(ClearBidsButton())

    # Add Done Bidding Button
    view.add_item(DoneBiddingButton())
    
    # Add Restart Button for Admins
    view.add_item(RestartButton())

    # Send initial message to a specific channel for bidding
    await channel.send("Choose a card to bid on:", view=view)