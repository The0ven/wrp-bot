import discord
from discord import Button, ChannelType, Interaction, Client, TextStyle
from discord.ui import ChannelSelect, Modal, Select, TextInput, View, button, select
import json

# class SubmitButton(ui.Button):
#     def __init__(self, channel: str, dpy: int, *, style: ButtonStyle = ButtonStyle.secondary, label: Optional[str] = None, disabled: bool = False, custom_id: Optional[str] = None, url: Optional[str] = None, emoji: Optional[Union[str, Emoji, PartialEmoji]] = None, row: Optional[int] = None, sku_id: Optional[int] = None):
#         self.days_per_year = dpy
#         super().__init__(style=style, label=label, disabled=disabled, custom_id=custom_id, url=url, emoji=emoji, row=row, sku_id=sku_id)
#
#     async def callback(self, interaction: discord.Interaction[discord.Client]) -> None:
#         await interaction.response.send_message(f'Configured to send messages in {self.channel} every {self.days_per_year / 20} days', ephemeral=True)

class Initialize(View):

    @select(
        cls=ChannelSelect,
        placeholder="The channel for sending public year updates.",
        channel_types=[ChannelType.text, ChannelType.private, ChannelType.public_thread, ChannelType.private_thread]
    )
    async def chose_calendar_channel(self, inter: Interaction[Client], select: ChannelSelect):
        await inter.response.defer()
        self.channel = select.values[0]

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
    async def submit(self, inter: Interaction[Client], button: Button) -> None:
        try:
            with open("config.json", mode="w", encoding="utf-8") as wb:
                json.dump({"channel": self.channel.id, "calendars": []}, wb, separators=(',',':'))
            await inter.response.send_message(f'Configured to send messages in {self.channel}', ephemeral=True)
            await inter.message.delete(delay=2)
        except AttributeError:  
            await inter.response.send_message(f'Error Submitting: Please ensure you selected all options.', ephemeral=True)


class AddCalendar(Modal, title="Create/Update Calendar"):
    name = TextInput(label="Calendar Name", style=TextStyle.short)
    key = TextInput(label="Calendar acronym (EG: Staff Years -> sy)", style=TextStyle.short)
    current_year = TextInput(label="Current Year", style=TextStyle.short)
    hours_per_year = TextInput(label="Hours Per Year", style=TextStyle.short)
    is_staff_years = TextInput(label="Is Staff Years (Y/N)", style=TextStyle.short)

    async def on_submit(self, interaction: Interaction[Client], /) -> None:
        with open("config.json", mode="r", encoding="utf-8") as rb:
            config = json.load(rb)
        # overwrite old version of calendar
        config["calendars"] = [cal for cal in config["calendars"] if cal["name"] != self.name.value]
        # add new entry
        config["calendars"].append({"name": self.name.value, "key": self.key.value, "hours_per_year": float(self.hours_per_year.value), "current_year": int(self.current_year.value), "is_staff_years": True if self.is_staff_years.value.lower() == "Y".lower() else False})
        with open("config.json", mode="w", encoding="utf-8") as wb:
            json.dump(config, wb)
        await interaction.response.send_message(f"Created {self.name.value}, with years every {self.hours_per_year.value} hours. The starting year (right now) is {self.current_year.value}")
        return await super().on_submit(interaction)

