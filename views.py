import discord
from discord import Button, ChannelType, ComponentType, InputTextStyle
from discord.ui import Modal, View, button, select, channel_select, InputText
import json
import uuid
from datetime import datetime
from approval_views import ApprovalView, create_approval_embed
import logging
from file_locks import CONFIG_LOCK, PENDING_LOCK

logger = logging.getLogger(__name__)

# class SubmitButton(ui.Button):
#     def __init__(self, channel: str, dpy: int, *, style: ButtonStyle = ButtonStyle.secondary, label: Optional[str] = None, disabled: bool = False, custom_id: Optional[str] = None, url: Optional[str] = None, emoji: Optional[Union[str, Emoji, PartialEmoji]] = None, row: Optional[int] = None, sku_id: Optional[int] = None):
#         self.days_per_year = dpy
#         super().__init__(style=style, label=label, disabled=disabled, custom_id=custom_id, url=url, emoji=emoji, row=row, sku_id=sku_id)
#
#     async def callback(self, interaction: discord.Interaction[discord.Client]) -> None:
#         await interaction.response.send_message(f'Configured to send messages in {self.channel} every {self.days_per_year / 20} days', ephemeral=True)

class Initialize(View):

    @channel_select(
        placeholder="The channel for sending public year updates.",
        channel_types=[ChannelType.text, ChannelType.private, ChannelType.public_thread, ChannelType.private_thread]
    )
    async def chose_calendar_channel(self, inter: discord.Interaction, select):
        await inter.response.defer()
        self.channel = select.values[0]
        logger.info(
            "Initialize channel selected user_id=%s channel_id=%s",
            inter.user.id,
            self.channel.id,
        )

    # @select(
    #     cls=ChannelSelect,
    #     placeholder="The channel for storing year logs."
    # )
    # async def chose_log_channel(self, inter: Interaction[Client], select: ChannelSelect):
    #     await inter.response.defer()
    #     self.log_channel = select.values[0]

    # @select(options=[
    #     discord.SelectOption(label="1", value="1"),
    #     discord.SelectOption(label="2.4", value="2.4"),
    #     discord.SelectOption(label="6", value="6"),
    #     discord.SelectOption(label="12", value="12"),
    #     discord.SelectOption(label="24", value="24"),
    #     discord.SelectOption(label="48", value="48"),
    #     discord.SelectOption(label="72", value="72"),
    # ], placeholder="How many hours pass between each standard/staf year?")
    # async def choose_period(self, inter: Interaction[Client], select: Select):
    #     await inter.response.defer()
    #     self.hours_per_year = int(select.values[0])

    @button(style=discord.ButtonStyle.primary, label="Submit")
    async def submit(self, button: Button, inter: discord.Interaction) -> None:
        try:
            logger.info("Initialize submit started user_id=%s", inter.user.id)
            async with CONFIG_LOCK:
                config = {}
                with open("config.json", mode="r", encoding="utf-8") as rb:
                    config = json.load(rb)
                if self.channel:
                    config["channel"] = self.channel.id
                with open("config.json", mode="w", encoding="utf-8") as wb:
                    json.dump(config, wb, separators=(',',':'))
            logger.info(
                "Initialize submit saved config user_id=%s configured_channel=%s",
                inter.user.id,
                config.get("channel"),
            )
            await inter.response.send_message(f'Configured to send messages in {config["channel"]}', ephemeral=True)
            await inter.message.delete(delay=2)
        except AttributeError:  
            logger.warning("Initialize submit missing required selections user_id=%s", inter.user.id)
            await inter.response.send_message(f'Error Submitting: Please ensure you selected all options.', ephemeral=True)


class AddCalendar(Modal):
    title="Create/Update Calendar"
    children = [
        InputText(label="Calendar Name", style=InputTextStyle.short),
        InputText(label="Calendar acronym (EG: Staff Years -> sy)", style=InputTextStyle.short),
        InputText(label="Current Year", style=InputTextStyle.short),
        InputText(label="Staff Years Per Year", style=InputTextStyle.short),
        InputText(label="Is Staff Years (Y/N)", style=InputTextStyle.short)
    ]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            logger.info("Calendar submission started user_id=%s", interaction.user.id)
            # Validate input
            if not self.name.value.strip():
                logger.warning("Calendar submission rejected empty name user_id=%s", interaction.user.id)
                await interaction.response.send_message("Calendar name cannot be empty.", ephemeral=True)
                return
            
            if not self.key.value.strip():
                logger.warning("Calendar submission rejected empty key user_id=%s", interaction.user.id)
                await interaction.response.send_message("Calendar key cannot be empty.", ephemeral=True)
                return
            
            # Check for duplicate calendar names in existing config.
            async with CONFIG_LOCK:
                with open("config.json", mode="r", encoding="utf-8") as rb:
                    config = json.load(rb)
            
            existing_names = [cal["name"] for cal in config["calendars"]]
            if self.name.value in existing_names:
                logger.warning(
                    "Calendar submission rejected duplicate name user_id=%s calendar_name=%s",
                    interaction.user.id,
                    self.name.value,
                )
                await interaction.response.send_message(f"A calendar with the name '{self.name.value}' already exists.", ephemeral=True)
                return
            
            # Check for duplicate calendar keys
            existing_keys = [cal["key"] for cal in config["calendars"]]
            if self.key.value in existing_keys:
                logger.warning(
                    "Calendar submission rejected duplicate key user_id=%s calendar_key=%s",
                    interaction.user.id,
                    self.key.value,
                )
                await interaction.response.send_message(f"A calendar with the key '{self.key.value}' already exists.", ephemeral=True)
                return
            
            # Validate numeric inputs
            try:
                staff_years_per_year = float(self.staff_years_per_year.value)
                if staff_years_per_year <= 0:
                    logger.warning(
                        "Calendar submission rejected non-positive staff years rate user_id=%s value=%s",
                        interaction.user.id,
                        self.staff_years_per_year.value,
                    )
                    await interaction.response.send_message("Staff years per year must be a positive number.", ephemeral=True)
                    return
            except ValueError:
                logger.warning(
                    "Calendar submission rejected invalid staff years rate user_id=%s value=%s",
                    interaction.user.id,
                    self.staff_years_per_year.value,
                )
                await interaction.response.send_message("Staff years per year must be a valid number.", ephemeral=True)
                return
            
            try:
                current_year = int(self.current_year.value)
                if current_year < 0:
                    logger.warning(
                        "Calendar submission rejected negative year user_id=%s value=%s",
                        interaction.user.id,
                        self.current_year.value,
                    )
                    await interaction.response.send_message("Current year must be a non-negative number.", ephemeral=True)
                    return
            except ValueError:
                logger.warning(
                    "Calendar submission rejected invalid year user_id=%s value=%s",
                    interaction.user.id,
                    self.current_year.value,
                )
                await interaction.response.send_message("Current year must be a valid integer.", ephemeral=True)
                return
            
            # Validate is_staff_years input
            is_staff_years_input = self.is_staff_years.value.lower().strip()
            if is_staff_years_input not in ['y', 'n', 'yes', 'no']:
                logger.warning(
                    "Calendar submission rejected invalid staff flag user_id=%s value=%s",
                    interaction.user.id,
                    self.is_staff_years.value,
                )
                await interaction.response.send_message("Is Staff Years must be Y/N, Yes/No.", ephemeral=True)
                return
            
            is_staff_years = is_staff_years_input in ['y', 'yes']
            
            # Create calendar data
            calendar_data = {
                "name": self.name.value.strip(),
                "key": self.key.value.strip(),
                "staff_years_per_year": 1.0 if is_staff_years else staff_years_per_year,
                "current_year": current_year,
                "is_staff_years": is_staff_years
            }
            
            # Generate unique submission ID
            submission_id = str(uuid.uuid4())
            
            submission = {
                "submission_id": submission_id,
                "submitter_id": interaction.user.id,
                "submitter_name": interaction.user.display_name,
                "submission_timestamp": datetime.now().isoformat(),
                "calendar_data": calendar_data
            }
            
            # Lock pending read-modify-write to avoid dropped submissions under concurrency.
            async with PENDING_LOCK:
                try:
                    with open("pending_calendars.json", mode="r", encoding="utf-8") as rb:
                        pending_data = json.load(rb)
                except FileNotFoundError:
                    pending_data = {"pending_submissions": []}

                pending_data["pending_submissions"].append(submission)
                
                with open("pending_calendars.json", mode="w", encoding="utf-8") as wb:
                    json.dump(pending_data, wb, indent=2)
            logger.info(
                "Calendar submission saved pending user_id=%s submission_id=%s calendar_name=%s pending_count=%s",
                interaction.user.id,
                submission_id,
                calendar_data["name"],
                len(pending_data["pending_submissions"]),
            )
            
            # Send approval request to the designated user (322487124102479873)
            try:
                approval_user = await interaction.client.fetch_user(322487124102479873)
                if approval_user:
                    embed = create_approval_embed(calendar_data, interaction.user.id, submission_id)
                    approval_view = ApprovalView(submission_id, calendar_data, interaction.user.id)
                    await approval_user.send(embed=embed, view=approval_view)
                    logger.info(
                        "Approval request sent via DM user_id=%s submission_id=%s approval_user_id=%s",
                        interaction.user.id,
                        submission_id,
                        approval_user.id,
                    )
                else:
                    # Fallback: send to the channel where the command was used
                    embed = create_approval_embed(calendar_data, interaction.user.id, submission_id)
                    approval_view = ApprovalView(submission_id, calendar_data, interaction.user.id)
                    await interaction.channel.send(embed=embed, view=approval_view)
                    logger.warning(
                        "Approval user missing; request sent to channel user_id=%s submission_id=%s channel_id=%s",
                        interaction.user.id,
                        submission_id,
                        interaction.channel.id if interaction.channel else None,
                    )
            except Exception as e:
                logger.exception(
                    "Approval DM failed; sending fallback channel message user_id=%s submission_id=%s",
                    interaction.user.id,
                    submission_id,
                )
                # Fallback: send to the channel where the command was used
                embed = create_approval_embed(calendar_data, interaction.user.id, submission_id)
                approval_view = ApprovalView(submission_id, calendar_data, interaction.user.id)
                await interaction.channel.send(embed=embed, view=approval_view)
            
            # Send success message to submitter
            await interaction.response.send_message(
                f"✅ Calendar submission **{self.name.value}** has been submitted for approval!\n\n"
                f"**Details:**\n"
                f"• Name: {self.name.value}\n"
                f"• Key: {self.key.value}\n"
                f"• Current Year: {current_year}\n"
                f"• Staff Years Per Year: {1.0 if is_staff_years else staff_years_per_year}\n"
                f"• Is Staff Years: {'Yes' if is_staff_years else 'No'}\n\n"
                f"You will be notified when your submission is reviewed.",
                ephemeral=True
            )
            logger.info(
                "Calendar submission success response sent user_id=%s submission_id=%s",
                interaction.user.id,
                submission_id,
            )
            
        except Exception as e:
            logger.exception("Calendar submission failed user_id=%s", interaction.user.id)
            await interaction.response.send_message(f"Error submitting calendar: {str(e)}", ephemeral=True)
        
        return await super().on_submit(interaction)

