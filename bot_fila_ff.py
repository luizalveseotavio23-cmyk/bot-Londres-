# bot_fila_ff.py
# Requisitos:
# pip install -U discord.py python-dotenv

import os
import re
import asyncio
from dataclasses import dataclass, field
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv("/storage/emulated/0/.env")

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("Defina DISCORD_TOKEN no arquivo .env")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True  # necessário para ver cargos/usuários com mais consistência


def mention_user_id(user_id: Optional[int]) -> str:
    return f"<@{user_id}>" if user_id else "Não definido"


def mention_role_id(role_id: Optional[int]) -> str:
    return f"<@&{role_id}>" if role_id else "Não definido"


def mention_channel_id(channel_id: Optional[int]) -> str:
    return f"<#${channel_id}>" if channel_id else "Não definido"


def channel_mention(channel_id: Optional[int]) -> str:
    return f"<#{channel_id}>" if channel_id else "Não definido"


@dataclass
class GuildQueueConfig:
    mode_size: int = 1
    opponent_id: Optional[int] = None
    required_role_id: Optional[int] = None
    thread_channel_id: Optional[int] = None
    queue_title: str = "Aguardando"

    thread_id: Optional[int] = None
    panel_message_id: Optional[int] = None
    team2: list[int] = field(default_factory=list)


guild_configs: dict[int, GuildQueueConfig] = {}


def get_config(guild_id: int) -> GuildQueueConfig:
    if guild_id not in guild_configs:
        guild_configs[guild_id] = GuildQueueConfig()
    return guild_configs[guild_id]


def build_setup_embed(guild: discord.Guild, cfg: GuildQueueConfig) -> discord.Embed:
    e = discord.Embed(
        title="Configuração da fila",
        description="Use os controles abaixo para montar a sala e depois criar o tópico **Aguardando**.",
        color=discord.Color.blurple(),
    )
    e.add_field(name="Modo da sala", value=f"{cfg.mode_size}x{cfg.mode_size}", inline=True)
    e.add_field(name="Oponente fixo", value=mention_user_id(cfg.opponent_id), inline=True)
    e.add_field(name="Cargo permitido no Time 1", value=mention_role_id(cfg.required_role_id), inline=True)
    e.add_field(name="Canal do tópico", value=channel_mention(cfg.thread_channel_id), inline=True)
    e.add_field(name="Título do tópico", value=cfg.queue_title, inline=True)

    if cfg.team2:
        team2_txt = "\n".join(f"- <@{uid}>" for uid in cfg.team2[:20])
    else:
        team2_txt = "Ninguém na fila ainda."
    e.add_field(name="Fila do Time 2", value=team2_txt, inline=False)

    e.set_footer(text="O tópico será criado com o nome: Aguardando")
    return e


def build_queue_embed(guild: discord.Guild, cfg: GuildQueueConfig) -> discord.Embed:
    e = discord.Embed(
        title="Fila de desafio",
        description=f"Tópico: **{cfg.queue_title}**",
        color=discord.Color.green(),
    )
    e.add_field(name="Modo", value=f"{cfg.mode_size}x{cfg.mode_size}", inline=True)
    e.add_field(name="Time 1 fixo", value=mention_user_id(cfg.opponent_id), inline=True)
    e.add_field(name="Cargo exigido no Time 1", value=mention_role_id(cfg.required_role_id), inline=True)

    team1_status = "Oponente configurado" if cfg.opponent_id else "Ainda não configurado"
    e.add_field(name="Status do Time 1", value=team1_status, inline=True)

    if cfg.team2:
        team2_txt = "\n".join(f"{i+1}. <@{uid}>" for i, uid in enumerate(cfg.team2[:25]))
    else:
        team2_txt = "Fila vazia."
    e.add_field(name="Fila do Time 2", value=team2_txt, inline=False)

    e.set_footer(text="Use os botões abaixo para entrar ou sair da fila.")
    return e


class ModeSelect(discord.ui.Select):
    def __init__(self, view: "SetupView"):
        self.setup_view = view
        options = [
            discord.SelectOption(label="1x1", value="1", description="Uma pessoa por time"),
            discord.SelectOption(label="2x2", value="2", description="Dois por time"),
            discord.SelectOption(label="3x3", value="3", description="Três por time"),
            discord.SelectOption(label="4x4", value="4", description="Quatro por time"),
        ]
        super().__init__(
            placeholder="Escolha o modo da sala",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = self.setup_view.cfg
        cfg.mode_size = int(self.values[0])
        await self.setup_view.refresh(interaction, "Modo atualizado.")


class OpponentSelect(discord.ui.UserSelect):
    def __init__(self, view: "SetupView"):
        self.setup_view = view
        super().__init__(
            placeholder="Selecione o jogador fixo do Time 1",
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = self.setup_view.cfg
        cfg.opponent_id = self.values[0].id
        await self.setup_view.refresh(interaction, "Oponente definido.")


class RoleSelectMenu(discord.ui.RoleSelect):
    def __init__(self, view: "SetupView"):
        self.setup_view = view
        super().__init__(
            placeholder="Selecione o cargo que pode entrar no Time 1",
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = self.setup_view.cfg
        cfg.required_role_id = self.values[0].id
        await self.setup_view.refresh(interaction, "Cargo definido.")


class ChannelSelectMenu(discord.ui.ChannelSelect):
    def __init__(self, view: "SetupView"):
        self.setup_view = view
        super().__init__(
            placeholder="Selecione o canal onde o tópico será criado",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        cfg = self.setup_view.cfg
        cfg.thread_channel_id = self.values[0].id
        await self.setup_view.refresh(interaction, "Canal definido.")


class TitleModal(discord.ui.Modal, title="Definir título do tópico"):
    queue_title = discord.ui.TextInput(
        label="Título",
        placeholder="Aguardando",
        default="Aguardando",
        max_length=100,
        required=True,
    )

    def __init__(self, setup_view: "SetupView"):
        super().__init__()
        self.setup_view = setup_view

    async def on_submit(self, interaction: discord.Interaction):
        cfg = self.setup_view.cfg
        cfg.queue_title = str(self.queue_title.value).strip() or "Aguardando"
        await self.setup_view.refresh(interaction, "Título atualizado.")


class SetupView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, cfg: GuildQueueConfig):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild = guild
        self.cfg = cfg

        self.add_item(ModeSelect(self))
        self.add_item(OpponentSelect(self))
        self.add_item(RoleSelectMenu(self))
        self.add_item(ChannelSelectMenu(self))

    async def refresh(self, interaction: discord.Interaction, notice: str):
        embed = build_setup_embed(self.guild, self.cfg)
        await interaction.response.edit_message(content=notice, embed=embed, view=self)

    @discord.ui.button(label="Editar título", style=discord.ButtonStyle.secondary, row=4)
    async def edit_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TitleModal(self))

    @discord.ui.button(label="Criar/atualizar tópico", style=discord.ButtonStyle.success, row=4)
    async def create_topic(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Use isso em um servidor.", ephemeral=True)

        cfg = self.cfg

        if not cfg.thread_channel_id:
            return await interaction.response.send_message("Selecione o canal do tópico primeiro.", ephemeral=True)

        if not cfg.opponent_id:
            return await interaction.response.send_message("Selecione o oponente fixo do Time 1.", ephemeral=True)

        if cfg.required_role_id:
            member = interaction.guild.get_member(cfg.opponent_id)
            role = interaction.guild.get_role(cfg.required_role_id)
            if member and role and role not in member.roles:
                return await interaction.response.send_message(
                    "O oponente fixo não possui o cargo exigido para o Time 1.",
                    ephemeral=True,
                )

        channel = interaction.guild.get_channel(cfg.thread_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("O canal selecionado precisa ser um canal de texto.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Reaproveita o tópico se ele já existir.
        thread: Optional[discord.Thread] = None
        if cfg.thread_id:
            t = interaction.guild.get_thread(cfg.thread_id)
            if t:
                thread = t

        if thread is None:
            starter = await channel.send(
                embed=discord.Embed(
                    title="Criando tópico...",
                    description="A fila está sendo preparada.",
                    color=discord.Color.dark_grey(),
                )
            )
            thread = await starter.create_thread(name="Aguardando", auto_archive_duration=1440)

        cfg.thread_id = thread.id

        panel_embed = build_queue_embed(interaction.guild, cfg)
        queue_view = QueueView(self.bot, interaction.guild.id)

        # Tenta achar/editar o painel anterior, se existir.
        if cfg.panel_message_id:
            try:
                old_msg = await thread.fetch_message(cfg.panel_message_id)
                await old_msg.edit(embed=panel_embed, view=queue_view)
                await interaction.followup.send("Tópico atualizado com sucesso.", ephemeral=True)
                return
            except Exception:
                pass

        msg = await thread.send(embed=panel_embed, view=queue_view)
        cfg.panel_message_id = msg.id
        await interaction.followup.send("Tópico criado com sucesso.", ephemeral=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.danger, row=4)
    async def close_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Painel fechado.", view=None)


class QueueView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id

    def cfg(self) -> GuildQueueConfig:
        return get_config(self.guild_id)

    async def update_message(self, interaction: discord.Interaction, notice: str = "Fila atualizada."):
        cfg = self.cfg()
        if interaction.message:
            await interaction.message.edit(embed=build_queue_embed(interaction.guild, cfg), view=self)
        await interaction.response.send_message(notice, ephemeral=True)

    @discord.ui.button(label="Entrar no Time 2", style=discord.ButtonStyle.success, row=0)
    async def join_team2(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Use isso em um servidor.", ephemeral=True)

        cfg = self.cfg()
        user_id = interaction.user.id

        if cfg.opponent_id and user_id == cfg.opponent_id:
            return await interaction.response.send_message("O oponente fixo já pertence ao Time 1.", ephemeral=True)

        if user_id in cfg.team2:
            return await interaction.response.send_message("Você já está na fila do Time 2.", ephemeral=True)

        cfg.team2.append(user_id)
        await interaction.message.edit(embed=build_queue_embed(interaction.guild, cfg), view=self)
        await interaction.response.send_message("Você entrou na fila do Time 2.", ephemeral=True)

    @discord.ui.button(label="Sair da fila", style=discord.ButtonStyle.secondary, row=0)
    async def leave_team2(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = self.cfg()
        user_id = interaction.user.id

        if user_id not in cfg.team2:
            return await interaction.response.send_message("Você não está na fila do Time 2.", ephemeral=True)

        cfg.team2.remove(user_id)
        await interaction.message.edit(embed=build_queue_embed(interaction.guild, cfg), view=self)
        await interaction.response.send_message("Você saiu da fila.", ephemeral=True)

    @discord.ui.button(label="Atualizar painel", style=discord.ButtonStyle.primary, row=0)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = self.cfg()
        await interaction.message.edit(embed=build_queue_embed(interaction.guild, cfg), view=self)
        await interaction.response.send_message("Painel atualizado.", ephemeral=True)


class FFQueueBot(commands.Bot):
    async def setup_hook(self):
        # Sincroniza os comandos de aplicativo
        await self.tree.sync()

        # Mantém a view da fila disponível em mensagens existentes na mesma execução
        # (não persiste após reiniciar, que é o comportamento padrão deste arquivo único).

bot = FFQueueBot(command_prefix="!", intents=intents)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(name="manu", description="Abrir o painel de configuração da fila")
async def manu(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)

    cfg = get_config(interaction.guild.id)
    embed = build_setup_embed(interaction.guild, cfg)
    view = SetupView(bot, interaction.guild, cfg)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(name="fila_streamer", description="Criar ou atualizar a fila de desafio")
async def fila_streamer(interaction: discord.Interaction):
    if not interaction.guild:
        return await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)

    cfg = get_config(interaction.guild.id)

    if not cfg.thread_channel_id:
        return await interaction.response.send_message("Use /manu para selecionar o canal do tópico primeiro.", ephemeral=True)

    if not cfg.opponent_id:
        return await interaction.response.send_message("Use /manu para definir o oponente fixo primeiro.", ephemeral=True)

    channel = interaction.guild.get_channel(cfg.thread_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message("O canal configurado não é um canal de texto.", ephemeral=True)

    # Reusa o tópico existente, se houver
    if cfg.thread_id:
        thread = interaction.guild.get_thread(cfg.thread_id)
    else:
        thread = None

    await interaction.response.defer(ephemeral=True, thinking=True)

    if thread is None:
        starter = await channel.send(
            embed=discord.Embed(
                title="Criando fila...",
                description="Preparando o tópico Aguardando.",
                color=discord.Color.dark_grey(),
            )
        )
        thread = await starter.create_thread(name="Aguardando", auto_archive_duration=1440)
        cfg.thread_id = thread.id

    panel_embed = build_queue_embed(interaction.guild, cfg)
    queue_view = QueueView(bot, interaction.guild.id)

    if cfg.panel_message_id:
        try:
            msg = await thread.fetch_message(cfg.panel_message_id)
            await msg.edit(embed=panel_embed, view=queue_view)
            return await interaction.followup.send("Fila atualizada.", ephemeral=True)
        except Exception:
            pass

    msg = await thread.send(embed=panel_embed, view=queue_view)
    cfg.panel_message_id = msg.id
    await interaction.followup.send("Fila criada com sucesso.", ephemeral=True)


@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.command(name="confi_aparencia", description="Mudar o apelido do bot no servidor")
@app_commands.describe(nick="Novo apelido do bot neste servidor")
async def confi_aparencia(interaction: discord.Interaction, nick: str):
    if not interaction.guild:
        return await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)

    me = interaction.guild.me or interaction.guild.get_member(bot.user.id)  # type: ignore[arg-type]
    if me is None:
        return await interaction.response.send_message("Não consegui localizar o bot no servidor.", ephemeral=True)

    try:
        await me.edit(nick=nick[:32])
        await interaction.response.send_message(f"Apelido alterado para **{nick[:32]}**.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "Não tenho permissão para alterar apelidos. Dê ao bot a permissão **Gerenciar Apelidos**.",
            ephemeral=True,
        )
    except discord.HTTPException:
        await interaction.response.send_message("Falha ao alterar o apelido.", ephemeral=True)


@manu.error
@fila_streamer.error
@confi_aparencia.error
async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "Você precisa da permissão **Gerenciar Servidor** para usar este comando."
    else:
        msg = f"Ocorreu um erro: `{type(error).__name__}`"

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


bot.tree.add_command(manu)
bot.tree.add_command(fila_streamer)
bot.tree.add_command(confi_aparencia)


@bot.event
async def on_ready():
    print(f"Logado como {bot.user} (ID: {bot.user.id})")


bot.run(TOKEN)