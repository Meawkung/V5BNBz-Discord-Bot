# bidding_cog.py
import discord
from discord.ext import commands
from discord.ui import Button, View, Select
import asyncio
import time
import logging
import os # <<< สำหรับอ่านไฟล์
from typing import Dict, List, Optional # เพิ่ม type hinting
import json # <<< ADD THIS IMPORT

# ตั้งค่า logger สำหรับ Cog นี้
log = logging.getLogger(__name__)

# --- ค่าคงที่ ---
# ย้ายรายการรูนมาไว้ตรงนี้
BIDDING_RUNES: List[str] = [
    "Netherforce"
]
MAX_BIDS_PER_ITEM = 3 # <<< จำนวนสูงสุดของการประมูลต่อรูน
# ID ของช่องที่จะส่งข้อความเริ่มต้นและข้อความประมูล (สำคัญ: แก้ไขเป็น ID ช่องของคุณ)
BIDDING_CHANNEL_ID = 1387457247105515621 # <<< ใส่ ID ช่องที่ถูกต้อง
GUIDE_FILENAME = "bidding_guide.txt" # <<< ชื่อไฟล์คู่มือ

# --- โครงสร้างข้อมูลสำหรับเก็บการประมูล ---
# rune_name -> list of bids
# bid = {'user_id': int, 'user_mention': str, 'user_display_name': str, 'quantity': int, 'timestamp': int, 'done': bool}
BiddingDataType = Dict[str, List[Dict[str, any]]]

# --- คลาส UI Components (Buttons, Select, View) ---

class RuneButton(Button):
    def __init__(self, rune_label: str, *, cog_instance, disabled: bool = False):
        safe_label = "".join(c for c in rune_label if c.isalnum())
        super().__init__(label=rune_label, style=discord.ButtonStyle.secondary, custom_id=f"bid_rune_{safe_label[:50]}", disabled=disabled)
        self.rune_label = rune_label
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        if self.cog.is_paused:
            await interaction.response.send_message("Bidding is currently paused. // ระบบประมูลกำลังหยุดชั่วคราว", ephemeral=True)
            return

        # Defer the response so we have time to process
        await interaction.response.defer()
        
        user = interaction.user
        current_timestamp = int(time.time())

        # Call the updated function and check the return value
        success = await self.cog.add_or_update_bid(self.rune_label, user, current_timestamp)

        if success:
            # If the bid was successful, update the main message
            await self.cog.update_bidding_message(interaction=interaction, is_interaction_edit=True)
        else:
            # If the bid failed (limit reached), send a private message to the user
            # We use followup because we already deferred the interaction
            await interaction.followup.send(
                f"You have reached the maximum of {MAX_BIDS_PER_ITEM} bids for this item. // คุณได้ประมูลไอเทมนี้ครบจำนวนสูงสุด {MAX_BIDS_PER_ITEM} ครั้งแล้ว", 
                ephemeral=True
            )


class ClearBidsButton(Button):
    def __init__(self, *, cog_instance, disabled: bool = False):
        super().__init__(label="Clear My Bids", style=discord.ButtonStyle.primary, custom_id="bid_clear_my", disabled=disabled)
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        if self.cog.is_paused:
            await interaction.response.send_message("Bidding is currently paused. // ระบบประมูลกำลังหยุดชั่วคราว", ephemeral=True)
            return

        user = interaction.user

        # First, check if the user has any bids at all.
        has_any_bids = any(
            bid['user_id'] == user.id
            for bids in self.cog.rune_bids.values()
            for bid in bids
        )

        if not has_any_bids:
            await interaction.response.send_message("You have no bids to clear.", ephemeral=True)
            return

        # --- Create a custom View class that accepts the cog instance ---
        class ChoiceView(View):
            def __init__(self, cog_instance):
                super().__init__(timeout=60)
                self.cog = cog_instance # Store the cog instance

            @discord.ui.button(label="Clear ALL My Bids", style=discord.ButtonStyle.danger)
            async def clear_all_button(self, btn_interaction: discord.Interaction, button: Button):
                await btn_interaction.response.defer()
                cleared_count = await self.cog.clear_user_bids(interaction.user) # Use interaction.user
                await btn_interaction.followup.send(f"✅ All {cleared_count} of your bids have been cleared.", ephemeral=True)
                await interaction.edit_original_response(content="Action completed.", view=None)
                await self.cog.update_bidding_message()

            @discord.ui.button(label="Clear ONLY Done Bids", style=discord.ButtonStyle.primary)
            async def clear_done_button(self, btn_interaction: discord.Interaction, button: Button):
                await btn_interaction.response.defer()
                cleared_count = await self.cog.clear_user_done_bids(interaction.user) # Use interaction.user
                if cleared_count > 0:
                    await btn_interaction.followup.send(f"✅ Cleared {cleared_count} of your 'done' bids.", ephemeral=True)
                else:
                    await btn_interaction.followup.send("You had no 'done' bids to clear.", ephemeral=True)
                await interaction.edit_original_response(content="Action completed.", view=None)
                await self.cog.update_bidding_message()

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel_button(self, btn_interaction: discord.Interaction, button: Button):
                await btn_interaction.response.edit_message(content="Action cancelled.", view=None)

        # --- Pass the cog instance when creating the view ---
        # `self.cog` here refers to the cog stored in the ClearBidsButton instance
        choice_view = ChoiceView(cog_instance=self.cog)

        await interaction.response.send_message(
            "What would you like to clear?",
            view=choice_view,
            ephemeral=True
        )


class DoneBiddingButton(Button):
    def __init__(self, *, cog_instance, disabled: bool = False):
        super().__init__(label="Done Bidding", style=discord.ButtonStyle.success, custom_id="bid_done", disabled=disabled)
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        if self.cog.is_paused:
            await interaction.response.send_message("Bidding is currently paused. // ระบบประมูลกำลังหยุดชั่วคราว", ephemeral=True)
            return

        # Store the cog instance from the button itself
        cog = self.cog
        user = interaction.user
        user_active_runes = cog.get_user_active_bid_runes(user)

        if not user_active_runes:
            await interaction.response.send_message("You don't have any active bids to mark as done.", ephemeral=True)
            return

        # --- Step 1: Create the Rune Selection Menu ---
        rune_options = [discord.SelectOption(label=rune, value=rune) for rune in user_active_runes]
        
        rune_select = Select(
            placeholder="Step 1: Select an item to manage",
            options=rune_options,
        )

        # This inner function will be called when the user selects a rune
        async def rune_select_callback(rune_interaction: discord.Interaction):
            await rune_interaction.response.defer(ephemeral=True)
            selected_rune = rune_interaction.data.get('values', [])[0]

            # --- Step 2: Create the Individual Bid Selection Menu ---
            user_bids_for_rune = [
                bid for bid in cog.rune_bids.get(selected_rune, [])
                if bid['user_id'] == user.id and not bid.get('done', False)
            ]
            user_bids_for_rune.sort(key=lambda b: b.get('timestamp', 0))

            if not user_bids_for_rune:
                await rune_interaction.followup.send("You have no active bids left for this item.", ephemeral=True)
                return

            bid_options = [
                discord.SelectOption(
                    label=f"Bid #{idx + 1} (placed <t:{bid.get('timestamp', 0)}:R>)",
                    value=str(bid.get('timestamp', 0))
                ) for idx, bid in enumerate(user_bids_for_rune)
            ]

            bid_select = Select(
                placeholder="Step 2: Select the specific bid(s) to mark as done",
                min_values=1,
                max_values=len(bid_options),
                options=bid_options,
            )

            # This final callback is triggered when the user selects individual bids
            async def bid_select_callback(bid_interaction: discord.Interaction):
                await bid_interaction.response.defer(ephemeral=True)
                selected_timestamps_str = bid_interaction.data.get('values', [])
                timestamps_to_mark = [int(ts) for ts in selected_timestamps_str]

                # Use the 'cog' variable we stored from the parent scope
                await cog.mark_bids_done(user, selected_rune, timestamps_to_mark)

                await bid_interaction.followup.send(f"Marked {len(timestamps_to_mark)} bid(s) for **{selected_rune}** as done.", ephemeral=True)

                # THE CRITICAL FIX: This 'cog' is the REAL cog instance
                await cog.update_bidding_message()

            bid_select.callback = bid_select_callback
            
            bid_view = View(timeout=180)
            bid_view.add_item(bid_select)
            await rune_interaction.followup.send("Now, select the specific bids to mark as done:", view=bid_view, ephemeral=True)

        rune_select.callback = rune_select_callback
        
        rune_view = View(timeout=180)
        rune_view.add_item(rune_select)
        await interaction.response.send_message("First, choose the item whose bids you want to manage:", view=rune_view, ephemeral=True)


class RestartButton(Button):
    def __init__(self, *, cog_instance):
        super().__init__(label="Restart Bidding", style=discord.ButtonStyle.danger, custom_id="bid_restart")
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You do not have permission to restart bidding.", ephemeral=True)
            return

        # Create the confirmation view
        confirmation_view = ConfirmRestartView(cog_instance=self.cog)

        # Send the private confirmation message
        await interaction.response.send_message(
            "**⚠️ Are you sure you want to restart all bidding?**\nThis will permanently delete all current bids for everyone.",
            view=confirmation_view,
            ephemeral=True
        )

        # Wait for the view to stop (either by button click or timeout)
        await confirmation_view.wait()

        # --- AFTER the view is done, check if it was confirmed ---
        if confirmation_view.confirmed:
            log.info(f"Bidding restart CONFIRMED by {interaction.user.name}")
            # Now we perform the actual restart
            await self.cog.restart_bidding()
            
            # Update the main message. We can't use the original interaction to edit it,
            # so we'll do a direct update.
            await self.cog.update_bidding_message(is_restart=True)
        else:
            log.info(f"Bidding restart was cancelled or timed out by {interaction.user.name}")
            # If not confirmed, we do nothing. The user has already been notified
            # by the text in the confirmation view's buttons.


class RefreshButton(Button):
    def __init__(self, *, cog_instance):
        super().__init__(label="🔃", style=discord.ButtonStyle.secondary, custom_id="bid_refresh")
        self.cog = cog_instance

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # <<< [แก้ไข] เอา `view=self.view` ออกจากการเรียกฟังก์ชัน
        await self.cog.update_bidding_message(interaction=interaction, is_interaction_edit=True)


class BiddingView(View):
    # ทำให้ View สามารถถูกสร้างใหม่ได้ง่าย และจัดการปุ่มต่างๆ
    ## <<< [แก้ไข] รับ is_paused เพื่อกำหนดสถานะปุ่ม
    def __init__(self, cog_instance, *, is_paused: bool = False, timeout=None):
        super().__init__(timeout=timeout)
        self.cog = cog_instance

        # ปุ่มที่ทุกคนใช้ได้ แต่จะถูก disable ตอน pause
        is_action_disabled = is_paused

        # เพิ่มปุ่ม Refresh ก่อน (ปุ่มนี้ไม่ควร disable)
        self.add_item(RefreshButton(cog_instance=self.cog))

        # เพิ่มปุ่มรูน
        for rune in BIDDING_RUNES:
             self.add_item(RuneButton(rune, cog_instance=self.cog, disabled=is_action_disabled))

        # เพิ่มปุ่มจัดการ (บางปุ่มจะ disable ตอน pause)
        self.add_item(ClearBidsButton(cog_instance=self.cog, disabled=is_action_disabled))
        self.add_item(DoneBiddingButton(cog_instance=self.cog, disabled=is_action_disabled))
        # ปุ่ม Restart สำหรับ Admin ไม่ต้อง disable
        self.add_item(RestartButton(cog_instance=self.cog))

class ConfirmRestartView(View):
    def __init__(self, cog_instance):
        super().__init__(timeout=30)  # Short timeout for safety
        self.cog = cog_instance
        self.confirmed = False

    @discord.ui.button(label="Confirm Restart", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        # We have confirmed the action
        self.confirmed = True
        
        # Disable buttons to prevent double-clicks
        for item in self.children:
            item.disabled = True
        
        # Acknowledge the confirmation and then stop the view
        await interaction.response.edit_message(content="✅ **Confirmed!** Restarting the bidding system...", view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        # We have not confirmed, so just stop the view
        self.confirmed = False

        # Disable buttons
        for item in self.children:
            item.disabled = True
            
        await interaction.response.edit_message(content="❌ Restart cancelled.", view=self)
        self.stop()

    async def on_timeout(self):
        # If the user waits too long, disable the buttons and inform them
        for item in self.children:
            item.disabled = True
        # We need the original interaction to edit the message on timeout.
        # This is a bit tricky, so for now, we'll just let it time out visually.
        # A more advanced implementation would pass the original interaction's message
        # to the view so it can be edited here.

# --- คลาส Cog หลัก ---
class BiddingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Assign the constant from the top of the file to this instance of the cog
        self.bidding_channel_id: int = BIDDING_CHANNEL_ID
        log.info(f"BiddingCog: Initializing with channel ID: {self.bidding_channel_id}")
        # Default empty values before loading
        self.rune_bids: BiddingDataType = {}
        self.rune_bid_order: List[str] = []
        self.bidding_message_id: Optional[int] = None
        self.is_paused: bool = False
        
        self.persistent_view_added = False
        self.message_lock = asyncio.Lock()
        
        self._load_state() # <<< LOAD THE SAVED STATE HERE

        log.info(f"BiddingCog: โหลดสำเร็จ จัดการประมูลสำหรับช่อง ID: {self.bidding_channel_id}")

    
    def _load_state(self):
        """Loads state from file, or initializes fresh state if file not found."""
        try:
            with open("bidding_state.json", 'r', encoding='utf-8') as f:
                state = json.load(f)
            # If file is found, load data from it
            self.rune_bids = state.get('rune_bids', {rune: [] for rune in BIDDING_RUNES})
            self.rune_bid_order = state.get('rune_bid_order', [])
            self.bidding_message_id = state.get('bidding_message_id')
            self.is_paused = state.get('is_paused', False)
            log.info(f"Successfully loaded state from bidding_state.json. Message ID: {self.bidding_message_id}")

        except FileNotFoundError:
            # If file is NOT found, this is a fresh start. Initialize all data.
            log.warning("bidding_state.json not found. Initializing a fresh state.")
            self.rune_bids = {rune: [] for rune in BIDDING_RUNES}
            self.rune_bid_order = []
            self.bidding_message_id = None
            self.is_paused = False
            
        except (json.JSONDecodeError, IOError) as e:
            log.error(f"Error loading state from bidding_state.json: {e}. Starting with a fresh state.")
            # Also initialize a fresh state on error
            self.rune_bids = {rune: [] for rune in BIDDING_RUNES}
            self.rune_bid_order = []
            self.bidding_message_id = None
            self.is_paused = False

    async def _save_state(self):
        """Saves the current bidding state to a JSON file asynchronously."""
        # Use the lock to prevent race conditions while saving
        async with self.message_lock:
            await self._save_state_nolock()

    async def _save_state_nolock(self):
        """Saves the current bidding state. ASSUMES a lock is already held."""
        try:
            state = {
                'rune_bids': self.rune_bids,
                'rune_bid_order': self.rune_bid_order,
                'bidding_message_id': self.bidding_message_id,
                'is_paused': self.is_paused
            }
            # (If you implemented the async file I/O from the previous review, keep it here)
            def dump_to_file():
                with open("bidding_state.json", 'w', encoding='utf-8') as f:
                    json.dump(state, f, indent=4)
            await self.bot.loop.run_in_executor(None, dump_to_file)
            
            log.debug("State successfully saved to bidding_state.json (nolock)")
        except (IOError, TypeError) as e:
            log.error(f"Failed to save state (nolock): {e}")

    # --- Listener สำหรับ View แบบถาวร ---
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.persistent_view_added:
             log.info("BiddingCog: on_ready - กำลังตรวจสอบ/เพิ่ม Persistent View...")
             ## <<< [แก้ไข] ส่งสถานะ is_paused ปัจจุบัน (ซึ่งคือ False ตอนเริ่ม)
             persistent_view = BiddingView(cog_instance=self, is_paused=self.is_paused, timeout=None)
             self.bot.add_view(persistent_view)
             self.persistent_view_added = True
             log.info("BiddingCog: Persistent View ถูกเพิ่ม/ตรวจสอบแล้ว")
             if self.bidding_message_id:
                  log.info(f"พบ Bidding Message ID ที่บันทึกไว้: {self.bidding_message_id}")
             else:
                  log.warning("ไม่พบ Bidding Message ID ที่บันทึกไว้. อาจต้องใช้ !startbiddingrune เพื่อสร้างใหม่")


    ## <<< [เพิ่ม] คำสั่ง !pause
    @commands.command(name="pause")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def pause_bidding(self, ctx: commands.Context):
        """Pauses the bidding. Disables bidding buttons. (Admin only)"""
        if self.is_paused:
            await ctx.send("Bidding is already paused.", ephemeral=True)
            return

        # Acquire the lock for the entire transaction
        async with self.message_lock:
            self.is_paused = True
            log.info(f"--- Bidding PAUSED by {ctx.author.name} ---")

            # Call the nolock versions since we already hold the lock
            await self.update_bidding_message_nolock()
            await self._save_state_nolock()

        # Send confirmation after the lock is released
        await ctx.send("Bidding has been paused. Buttons will be disabled.", ephemeral=True)


    @commands.command(name="resume")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def resume_bidding(self, ctx: commands.Context):
        """Resumes the bidding. Re-enables bidding buttons. (Admin only)"""
        if not self.is_paused:
            await ctx.send("Bidding is not currently paused.", ephemeral=True)
            return

        # Acquire the lock for the entire transaction
        async with self.message_lock:
            self.is_paused = False
            log.info(f"--- Bidding RESUMED by {ctx.author.name} ---")

            # Call the nolock versions since we already hold the lock
            await self.update_bidding_message_nolock()
            await self._save_state_nolock()

        # Send confirmation after the lock is released
        await ctx.send("Bidding has been resumed. Buttons will be re-enabled.", ephemeral=True)

    @commands.command(name="clearbids", aliases=["cbids", "removebids"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def clear_bids_for_user(self, ctx: commands.Context, user: discord.Member, item_name: Optional[str] = None):
        """
        Manually clears bids for a specified user. (Admin only)
        
        Usage:
        - To clear ALL bids for a user: !clearbids @User
        - To clear bids for a user on a SPECIFIC item: !clearbids @User "Item Name"
        """
        # Acknowledge the command, showing "Bot is thinking..." to the admin only.
        await ctx.defer(ephemeral=True)

        total_cleared_count = 0
        
        if item_name:
            # --- Clear bids for a specific item ---
            clean_item_name = item_name.strip()
            if clean_item_name not in BIDDING_RUNES:
                # --- FIX: Use ctx.send ---
                await ctx.send(
                    f"❌ Invalid item name: `{clean_item_name}`.\n"
                    f"Valid items are: `{'`, `'.join(BIDDING_RUNES)}`",
                    ephemeral=True
                )
                return

            async with self.message_lock:
                bids_for_item = self.rune_bids.get(clean_item_name, [])
                initial_len = len(bids_for_item)
                
                self.rune_bids[clean_item_name] = [bid for bid in bids_for_item if bid['user_id'] != user.id]
                
                total_cleared_count = initial_len - len(self.rune_bids[clean_item_name])
                
                log.info(f"Admin {ctx.author.name} cleared {total_cleared_count} bids for {user.display_name} on item: {clean_item_name}.")
                
                if not self.rune_bids[clean_item_name] and clean_item_name in self.rune_bid_order:
                    try:
                        self.rune_bid_order.remove(clean_item_name)
                    except ValueError:
                        pass
                
                await self._save_state_nolock()
            
            # --- FIX: Use ctx.send ---
            await ctx.send(f"✅ Cleared {total_cleared_count} bid(s) for **{user.display_name}** on **{clean_item_name}**.", ephemeral=True)

        else:
            # --- Clear ALL bids for the user ---
            total_cleared_count = await self.clear_user_bids(user)
            # --- FIX: Use ctx.send ---
            await ctx.send(f"✅ Cleared all {total_cleared_count} bid(s) for **{user.display_name}** across all items.", ephemeral=True)

        # Update the main message to reflect the changes
        if total_cleared_count > 0:
            await self.update_bidding_message()

    @commands.command(name="deletebidmessage", aliases=["delbidmsg"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def delete_bid_message(self, ctx: commands.Context, message_id: int):
        """
        Manually deletes a specific bidding message by its ID. (Admin only)
        
        This is useful for cleaning up old messages if the bot loses track of the ID.
        It will also clear the saved message ID from the bot's state if it matches.
        """
        try:
            # We assume the message is in the same channel as the command is used,
            # or in the globally configured BIDDING_CHANNEL_ID.
            channel = self.bot.get_channel(self.bidding_channel_id) or ctx.channel
            
            msg_to_delete = await channel.fetch_message(message_id)
            await msg_to_delete.delete()
            
            response = f"✅ Successfully deleted message with ID: `{message_id}`"
            log.info(f"Admin {ctx.author} manually deleted message ID {message_id}")

            # Also check if this was the active message ID and clear it from our state
            # to prevent errors.
            if message_id == self.bidding_message_id:
                async with self.message_lock:
                    self.bidding_message_id = None
                    await self._save_state_nolock()
                response += "\nℹ️ This was the active bidding message, and its ID has been cleared from the bot's state."
                log.warning(f"Active bidding message ID {message_id} was cleared by manual deletion.")

            await ctx.send(response, ephemeral=True)

        except discord.NotFound:
            await ctx.send(f"❌ Error: Could not find a message with the ID `{message_id}` in this channel.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send(f"❌ Error: I don't have permission to delete messages in that channel.", ephemeral=True)
        except discord.HTTPException as e:
            log.error(f"Error manually deleting message {message_id}: {e}")
            await ctx.send(f"❌ An HTTP error occurred while trying to delete the message: {e}", ephemeral=True)

    @commands.command(name="manualbid", aliases=["mbid", "manual"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def manual_bid(self, ctx: commands.Context, item_name: str, user: discord.Member, quantity: int, timestamp: Optional[int] = None):
        """
        Manually set a bid for a user. (Admin only)
        
        Usage: !manualbid "<Item Name>" @User <TotalQuantity> [OptionalUnixTimestamp]
        Example: !manualbid "Netherforce" @SomeUser 3
        Example with timestamp: !manualbid "Netherforce" @SomeUser 3 1672531200
        Note: The timestamp must be a number, not the <t:...:R> format.
        """
        # --- Input Validation ---
        if quantity <= 0:
            await ctx.send("❌ Quantity must be a positive number.", ephemeral=True)
            return

        # Sanitize item_name and check if it's a valid bidding item
        clean_item_name = item_name.strip()
        if clean_item_name not in BIDDING_RUNES:
            await ctx.send(
                f"❌ Invalid item name: `{clean_item_name}`.\n"
                f"Valid items are: `{'`, `'.join(BIDDING_RUNES)}`", 
                ephemeral=True
            )
            return

        # Use the provided timestamp or default to the current time
        final_timestamp = timestamp or int(time.time())

        # --- Execution ---
        await self.manual_add_or_update_bid(
            admin=ctx.author,
            target_user=user,
            rune_label=clean_item_name,
            quantity=quantity,
            timestamp=final_timestamp
        )

        # --- Feedback ---
        await ctx.send(f"✅ Manually set bid for **{user.display_name}** on **{clean_item_name}** to **{quantity}**.", ephemeral=True)
        
        # Update the main bidding message to show the change
        await self.update_bidding_message()


    # --- Command สำหรับเริ่ม/สร้างข้อความประมูล ---
    @commands.command(name="startbiddingrune")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def start_bidding(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Creates the initial bidding messages in the specified channel (Admin only)."""
        target_channel = channel or ctx.guild.get_channel(self.bidding_channel_id) or ctx.channel
        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await ctx.send("Could not find a valid text channel to send the bidding message.", ephemeral=True)
            return

        # --- NEW GUIDE HANDLING LOGIC ---
        user_guide_content = self._get_user_guide()
        if "# Error" in user_guide_content:
            await ctx.send(f"Warning: Could not load the user guide.\n{user_guide_content}", ephemeral=True)
            # We can still proceed, but the admin is warned.
        else:
            # Split the guide into parts based on a clear separator
            # This separator is chosen to split the Thai and English versions
            guide_parts = user_guide_content.split('---') 
            
            for part in guide_parts:
                part = part.strip() # Remove leading/trailing whitespace
                if not part: # Skip empty parts
                    continue

                if len(part) > 4096:
                    log.warning(f"A part of the user guide is still over 4096 characters and will be truncated.")
                    part = part[:4090] + "\n... (Section truncated)"

                try:
                    guide_embed = discord.Embed(
                        description=part,
                        color=discord.Color.gold()
                    )
                    await target_channel.send(embed=guide_embed)
                    log.info(f"Sent a part of the user guide to {target_channel.name}.")
                except discord.Forbidden:
                    await ctx.send(f"I don't have permissions to send embeds in {target_channel.mention}.", ephemeral=True)
                    return # Stop if we can't send the guide
                except discord.HTTPException as e:
                    log.error(f"HTTP error sending a guide part: {e}")
                    await ctx.send(f"An error occurred while sending the guide: {e}", ephemeral=True)
                    return

        # --- MAIN BIDDING MESSAGE (Existing Logic) ---
        async with self.message_lock:
            # Delete old message if it exists
            if self.bidding_message_id:
                try:
                    old_msg = await target_channel.fetch_message(self.bidding_message_id)
                    await old_msg.delete()
                    log.info(f"Deleted old bidding message ID: {self.bidding_message_id}")
                except discord.NotFound:
                    log.info("Old bidding message not found, skipping deletion.")
                except discord.Forbidden:
                    log.warning("No permissions to delete the old bidding message.")
                except Exception as e:
                    log.warning(f"Error deleting old message: {e}")
            
            # Reset message ID before creating a new one
            self.bidding_message_id = None 

            # Create new message and save state
            view = BiddingView(cog_instance=self, is_paused=self.is_paused, timeout=None)
            initial_content = "Choose an item to bid on:"
            try:
                msg = await target_channel.send(initial_content, view=view)
                self.bidding_message_id = msg.id
                
                await self._save_state_nolock() # Use nolock since we have the lock
                
                log.info(f"Created new bidding message ID: {self.bidding_message_id} in channel {target_channel.id}")
                await ctx.send(f"Bidding system started in {target_channel.mention} (Message ID: {msg.id})", ephemeral=True)
            
            except discord.Forbidden:
                await ctx.send(f"I don't have permissions to send messages with views in {target_channel.mention}.", ephemeral=True)
            except discord.HTTPException as e:
                log.exception(f"HTTP error sending the main bidding message: {e}")
                await ctx.send(f"An error occurred sending the main bidding message: {e}", ephemeral=True)

        # สร้าง View และส่งข้อความหลัก
        ## <<< [แก้ไข] ส่งสถานะ is_paused ไปยัง View ตอนสร้าง
        view = BiddingView(cog_instance=self, is_paused=self.is_paused, timeout=None)
        initial_content = "Choose an item to bid on:" # The prompt for the main message
        try:
            msg = await target_channel.send(initial_content, view=view)
            if self.bidding_message_id:
                    try:
                        old_msg = await target_channel.fetch_message(self.bidding_message_id)
                        await old_msg.delete()
                        log.info(f"ลบข้อความประมูลเก่า ID: {self.bidding_message_id}")
                    except discord.NotFound:
                        log.info("ไม่พบข้อความประมูลเก่าที่จะลบ")
                    except discord.Forbidden:
                        log.warning("ไม่มีสิทธิ์ลบข้อความประมูลเก่า")
                    except Exception as e:
                        log.warning(f"เกิดข้อผิดพลาดขณะลบข้อความเก่า: {e}")

            # Don't forget to save state if you implemented persistence!
            self.bidding_message_id = msg.id
            await self._save_state() 
            log.info(f"สร้างข้อความประมูลใหม่ ID: {self.bidding_message_id} ในช่อง {target_channel.id}")
            await ctx.send(f"สร้างข้อความประมูลเรียบร้อยใน {target_channel.mention} (ID: {msg.id})", ephemeral=True)
        except discord.Forbidden:
                await ctx.send(f"ไม่มีสิทธิ์ส่งข้อความพร้อม View ในช่อง {target_channel.mention}", ephemeral=True)
        except discord.HTTPException as e:
            log.exception(f"เกิดข้อผิดพลาด HTTP ในการส่งข้อความประมูลหลัก: {e}")
            await ctx.send(f"เกิดข้อผิดพลาดในการส่งข้อความประมูลหลัก: {e}", ephemeral=True)
        except Exception as e:
            log.exception(f"เกิดข้อผิดพลาดที่ไม่คาดคิดในการส่งข้อความประมูลหลัก: {e}")
            await ctx.send(f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}", ephemeral=True)


    def _get_user_guide(self) -> str:
        """อ่านเนื้อหา User Guide จากไฟล์ GUIDE_FILENAME"""
        default_error_message = "# Error\nCould not load the user guide."
        try:
            script_dir = os.path.dirname(__file__)
            file_path = os.path.join(script_dir, GUIDE_FILENAME)

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                 log.warning(f"ไฟล์คู่มือ '{file_path}' ว่างเปล่า")
                 return f"# Warning\nUser guide file '{GUIDE_FILENAME}' is empty."
            log.info(f"โหลด User Guide จาก '{file_path}' สำเร็จ")
            return content
        except FileNotFoundError:
            log.error(f"ไม่พบไฟล์คู่มือ '{file_path}' กรุณาสร้างไฟล์นี้")
            return f"# Error\nCould not load user guide: File '{GUIDE_FILENAME}' not found at expected location '{file_path}'."
        except IOError as e:
            log.error(f"เกิดข้อผิดพลาด IO ขณะอ่านไฟล์คู่มือ '{file_path}': {e}")
            return f"# Error\nCould not read user guide file '{GUIDE_FILENAME}': {e}"
        except Exception as e:
             log.exception(f"เกิดข้อผิดพลาดที่ไม่คาดคิดขณะโหลดไฟล์คู่มือ '{file_path}': {e}")
             return default_error_message


    # --- Methods สำหรับจัดการข้อมูลการประมูล ---
    async def add_or_update_bid(self, rune_label: str, user: discord.User | discord.Member, timestamp: int) -> bool:
        """
        Adds a new bid entry for the user. Each call represents one bid.
        Returns:
            bool: True if the bid was added, False if the user reached their bid limit.
        """
        async with self.message_lock:  # Lock before modifying bid data
            if rune_label not in self.rune_bids:
                log.warning(f"Attempted bid on unknown rune: {rune_label}")
                return False

            bids_for_rune = self.rune_bids[rune_label]
            user_id = user.id
            display_name = user.display_name
            user_global_name = user.global_name or user.name

            # --- [NEW LOGIC] ---
            # Count the number of existing entries for this user on this rune
            user_bid_count = sum(1 for bid in bids_for_rune if bid['user_id'] == user_id)

            # Check if they have reached the maximum
            if user_bid_count >= MAX_BIDS_PER_ITEM:
                log.info(f"Bid attempt rejected for {display_name} on {rune_label}. Limit of {MAX_BIDS_PER_ITEM} reached.")
                return False  # Return False to indicate failure

            # Always add a new bid entry, as each click is a separate bid.
            new_bid = {
                'user_id': user_id,
                'user_mention': user.mention,
                'user_display_name': user_global_name,
                'quantity': 1,  # Quantity is always 1 per entry
                'timestamp': timestamp,
                'done': False
            }
            bids_for_rune.append(new_bid)
            log.info(f"Added new bid for {display_name} ({user_id}) on {rune_label}. They now have {user_bid_count + 1} bids.")
            
            if rune_label not in self.rune_bid_order:
                self.rune_bid_order.append(rune_label)
            
            # Save the state after adding a new bid
            await self._save_state_nolock()  # <<< SAVE THE CHANGES

            return True # Return True to indicate success

    async def clear_user_bids(self, user: discord.User) -> int:
        """
        ลบการประมูลทั้งหมดของผู้ใช้ที่ระบุ
        Returns the number of bids that were cleared.
        """
        async with self.message_lock: # ล็อคก่อนแก้ไขข้อมูล
            user_id = user.id
            total_cleared_count = 0
            runes_to_check = list(self.rune_bids.keys())

            for rune in runes_to_check:
                initial_len = len(self.rune_bids[rune])
                self.rune_bids[rune] = [bid for bid in self.rune_bids[rune] if bid['user_id'] != user_id]
                cleared_in_rune = initial_len - len(self.rune_bids[rune])
                if cleared_in_rune > 0:
                    total_cleared_count += cleared_in_rune
                    log.info(f"ลบ {cleared_in_rune} bid ของ {user.display_name} ({user_id}) ออกจาก {rune}")
                    if not self.rune_bids[rune] and rune in self.rune_bid_order:
                        try:
                            self.rune_bid_order.remove(rune)
                            log.info(f"นำ {rune} ออกจากลำดับการประมูลเนื่องจากไม่มี bid เหลือ")
                        except ValueError: pass

            if total_cleared_count > 0:
                log.info(f"รวมลบการประมูล {total_cleared_count} รายการสำหรับผู้ใช้: {user.display_name} ({user_id})")
            else:
                 log.info(f"ผู้ใช้ {user.display_name} ({user_id}) ไม่มี bid ให้ลบ")
            
            # Save the state after clearing bids
            await self._save_state_nolock() # <<< SAVE THE CHANGES

            return total_cleared_count


    def get_user_active_bid_runes(self, user: discord.User) -> List[str]:
        """คืนค่ารายการรูนที่ผู้ใช้มีการประมูลที่ยังไม่ 'done' """
        user_id = user.id
        return [rune for rune, bids in self.rune_bids.items() if any(bid['user_id'] == user_id and not bid.get('done', False) for bid in bids)]

    async def mark_bids_done(self, user: discord.User, rune: str, timestamps_to_mark: List[int]):
        """
        Marks specific bids, identified by their timestamps, as 'done' for a given user and rune.
        """
        async with self.message_lock: # Lock before modifying data
            user_id = user.id
            marked_count = 0
            display_name = user.display_name
            
            if rune in self.rune_bids:
                for bid in self.rune_bids[rune]:
                    # Check for user ID, that the bid isn't already done, and that its timestamp is in our target list
                    if bid['user_id'] == user_id and not bid.get('done', False) and bid['timestamp'] in timestamps_to_mark:
                        bid['done'] = True
                        marked_count += 1
            
            if marked_count > 0:
                log.info(f"Marked {marked_count} specific bid(s) as 'done' for {display_name} ({user_id}) on rune: {rune}")
            else:
                log.info(f"No active bids found for {display_name} ({user_id}) matching timestamps for rune: {rune}")
            # Save the state after marking bids done
            await self._save_state_nolock() # <<< SAVE THE CHANGES


    async def restart_bidding(self):
        """รีเซ็ตข้อมูลการประมูลทั้งหมด"""
        async with self.message_lock: # ล็อคขณะรีเซ็ต
            self.rune_bids = {rune: [] for rune in BIDDING_RUNES}
            self.rune_bid_order = []
            log.info("--- ระบบการประมูลถูกรีสตาร์ท (ข้อมูลในหน่วยความจำ) ---")
            await self._save_state_nolock()  # <<< SAVE THE CHANGES AFTER RESET


    # --- Method สำหรับอัปเดตข้อความประมูล ---
    ## <<< [แก้ไข] ไม่ต้องรับ view, สร้างใหม่เสมอตามสถานะ is_paused
    async def update_bidding_message(self, interaction: Optional[discord.Interaction] = None, msg_to_edit: Optional[discord.Message] = None, is_restart: bool = False, is_interaction_edit: bool = True):
        """Acquires the lock and updates the bidding message."""
        async with self.message_lock:
            await self.update_bidding_message_nolock(
                interaction=interaction,
                msg_to_edit=msg_to_edit,
                is_restart=is_restart,
                is_interaction_edit=is_interaction_edit
            )

    async def update_bidding_message_nolock(self, interaction: Optional[discord.Interaction] = None, msg_to_edit: Optional[discord.Message] = None, is_restart: bool = False, is_interaction_edit: bool = True):
        """Updates the bidding message content. ASSUMES a lock is already held."""
        log.debug(f"Update message (nolock) triggered by: {'Interaction' if interaction else 'Direct Call'}{' (Restart)' if is_restart else ''}")

        status_prefix = ""
        if self.is_paused:
            status_prefix = "## ⏸️ BIDDING IS CURRENTLY PAUSED ⏸️\n\n"

        if is_restart:
            new_content = status_prefix + "Bidding has been restarted. Choose a rune to bid on:"
        else:
            active_bids_data = {rune: bids for rune, bids in self.rune_bids.items() if bids}
            if not active_bids_data:
                new_content = status_prefix + "No current bids."
            else:
                def sort_key(rune_name):
                    try: order_index = self.rune_bid_order.index(rune_name)
                    except ValueError: order_index = float('inf')
                    return (-len(self.rune_bids.get(rune_name, [])), order_index)

                sorted_runes = sorted(active_bids_data.keys(), key=sort_key)
                lines = []
                for rune in sorted_runes:
                    bids = active_bids_data[rune]
                    sorted_bids = sorted(bids, key=lambda b: b.get('timestamp', 0))
                    bid_lines = [
                        (f"{idx + 1}. {bid.get('user_mention', 'Unknown User')} "
                         f"({bid.get('user_display_name', '?')}) "
                         f"<t:{bid.get('timestamp', 0)}:R> {'✅' if bid.get('done', False) else ''}").strip()
                        for idx, bid in enumerate(sorted_bids)
                    ]
                    lines.append(f"# **{rune}**:\n" + "\n".join(bid_lines))
                bid_content = "\n\n".join(lines)
                new_content = status_prefix + bid_content
                if len(new_content) > 4000:
                     new_content = new_content[:3950] + "\n... (Message too long, truncated)"
                     log.warning("เนื้อหาข้อความประมูลยาวเกินไป ถูกตัดให้สั้นลง")

        current_view = BiddingView(cog_instance=self, is_paused=self.is_paused, timeout=None)

        message_edited = False
        target_message_id = self.bidding_message_id
        edit_target = None

        if interaction and is_interaction_edit:
            edit_target = interaction
        elif msg_to_edit:
             edit_target = msg_to_edit
             target_message_id = msg_to_edit.id
        elif not target_message_id:
             log.warning("Cannot update message (nolock): No interaction, message, or ID.")
             return

        try:
            if isinstance(edit_target, discord.Interaction):
                await edit_target.edit_original_response(content=new_content, view=current_view)
                message_edited = True
            elif isinstance(edit_target, discord.Message):
                await edit_target.edit(content=new_content, view=current_view)
                message_edited = True
            elif target_message_id:
                channel = self.bot.get_channel(self.bidding_channel_id) or await self.bot.fetch_channel(self.bidding_channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    msg = await channel.fetch_message(target_message_id)
                    await msg.edit(content=new_content, view=current_view)
                    message_edited = True
        except discord.NotFound:
            log.error(f"Cannot update message (nolock): Not Found (ID: {target_message_id})")
            if target_message_id and target_message_id == self.bidding_message_id:
                self.bidding_message_id = None
        except discord.HTTPException as e:
            log.error(f"HTTP error updating message (nolock) (ID: {target_message_id}): {e.status} - {e.text}")
        except Exception as e:
            log.exception(f"Unexpected error updating message (nolock) (ID: {target_message_id}): {e}")

        if message_edited:
            log.info(f"Successfully updated bidding message (nolock) (ID: {target_message_id or 'unknown'})")
        else:
            log.warning("Failed to update bidding message (nolock)")

    async def manual_add_or_update_bid(self, admin: discord.User, target_user: discord.Member, rune_label: str, quantity: int, timestamp: int):
        """
        Manually sets a user's total bid count by removing their old bids
        and adding a specific number of new, individual bids.
        """
        async with self.message_lock: # Lock before modifying bid data
            if rune_label not in self.rune_bids:
                log.warning(f"Manual bid by {admin.name} for {target_user.name} failed: Unknown rune {rune_label}")
                return

            user_id = target_user.id
            user_global_name = target_user.global_name or target_user.name

            # --- [NEW LOGIC] ---
            # 1. Remove all existing bids for this user on this specific rune.
            self.rune_bids[rune_label] = [
                bid for bid in self.rune_bids[rune_label] if bid['user_id'] != user_id
            ]
            log.info(f"Manual bid: Cleared previous bids for {target_user.display_name} on {rune_label}.")

            # 2. Add 'quantity' number of new, individual bids.
            for i in range(quantity):
                new_bid = {
                    'user_id': user_id,
                    'user_mention': target_user.mention,
                    'user_display_name': user_global_name,
                    'quantity': 1, # Each entry has a quantity of 1
                    'timestamp': timestamp + i, # Add a tiny offset to maintain order if needed
                    'done': False
                }
                self.rune_bids[rune_label].append(new_bid)

            log.info(f"Manual bid by {admin.name}: Set {target_user.display_name}'s total bids for {rune_label} to {quantity}")
            
            # Ensure the rune is in the display order if it wasn't already
            if quantity > 0 and rune_label not in self.rune_bid_order:
                self.rune_bid_order.append(rune_label)
            # Remove from order if bids are set to 0 and no one else is bidding
            elif quantity == 0 and not self.rune_bids[rune_label]:
                 if rune_label in self.rune_bid_order:
                     self.rune_bid_order.remove(rune_label)
            # Save the state after manual bid update
            await self._save_state_nolock()  # <<< SAVE THE CHANGES

    async def clear_user_done_bids(self, user: discord.User) -> int:
        """
        Removes only the 'done' bids for a specific user.
        Returns the number of bids that were cleared.
        """
        async with self.message_lock: # Lock before modifying data
            user_id = user.id
            total_cleared_count = 0
            runes_to_check = list(self.rune_bids.keys())

            for rune in runes_to_check:
                initial_len = len(self.rune_bids[rune])
                
                # Keep a bid if it either doesn't belong to the user,
                # OR if it belongs to the user but is NOT marked as 'done'.
                self.rune_bids[rune] = [
                    bid for bid in self.rune_bids[rune]
                    if bid['user_id'] != user_id or not bid.get('done', False)
                ]
                
                cleared_in_rune = initial_len - len(self.rune_bids[rune])
                if cleared_in_rune > 0:
                    total_cleared_count += cleared_in_rune
                    log.info(f"Cleared {cleared_in_rune} DONE bids for {user.display_name} from {rune}")
                    
                    # If the rune now has no bids left at all, remove it from the display order
                    if not self.rune_bids[rune] and rune in self.rune_bid_order:
                        try:
                            self.rune_bid_order.remove(rune)
                            log.info(f"Removed {rune} from bid order as it's now empty after clearing done bids.")
                        except ValueError:
                            pass
            
            if total_cleared_count > 0:
                log.info(f"Total cleared DONE bids: {total_cleared_count} for user {user.display_name}")
            else:
                log.info(f"User {user.display_name} had no DONE bids to clear.")
            
            # Save the state after clearing done bids
            await self._save_state_nolock()  # <<< SAVE THE CHANGES
            # Return the total number of cleared bids
            return total_cleared_count

# --- ฟังก์ชัน Setup สำหรับ Cog ---
async def setup(bot: commands.Bot):
    """Loads the BiddingCog."""
    try:
        cog_instance = BiddingCog(bot)
        await bot.add_cog(cog_instance)
        log.info("BiddingCog: Setup complete, Cog added to bot.")
    except Exception as e:
        log.exception("BiddingCog: Failed to load Cog.")