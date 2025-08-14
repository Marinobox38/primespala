import os
import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands

ROLE_MOD_ID = 1402780875694801007
ADMIN_CHANNEL_ID = 1405590755698937856
PUBLIC_CHANNEL_ID = 1405590431231905833
KILL_TICKET_CATEGORY_ID = 1405589530287014049
LEADERBOARD_CHANNEL_ID = 1405590875941376042

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

primes = {}
prime_counter = 1
leaderboard = {}
leaderboard_message_id = None

def is_mod(member: discord.Member) -> bool:
    return any(r.id == ROLE_MOD_ID for r in member.roles)

def fmt_user(guild: discord.Guild, user_id: int) -> str:
    u = guild.get_member(user_id)
    return u.mention if u else f"<@{user_id}>"

class PrimeModal(discord.ui.Modal, title="Déposer une prime"):
    pseudo = discord.ui.TextInput(label="Pseudo cible", placeholder="Pseudo Minecraft / Paladium", max_length=32)
    montant = discord.ui.TextInput(label="Montant (en $)", placeholder="Ex: 5000", max_length=10)
    preuve  = discord.ui.TextInput(label="Preuve de paiement (lien/description)", style=discord.TextStyle.paragraph, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        global prime_counter
        try:
            montant_val = int(str(self.montant.value).strip())
        except ValueError:
            await interaction.response.send_message("Le montant doit être un nombre entier.", ephemeral=True)
            return
        if montant_val < 1000:
            await interaction.response.send_message("Le montant doit être au moins 1000$.", ephemeral=True)
            return

        prime_id = prime_counter
        prime_counter += 1
        primes[prime_id] = {
            "id": prime_id,
            "pseudo": self.pseudo.value.strip(),
            "montant": montant_val,
            "preuve": self.preuve.value.strip(),
            "auteur_id": interaction.user.id,
            "statut": "En attente"
        }

        guild = interaction.guild
        admin_channel = guild.get_channel(ADMIN_CHANNEL_ID)
        if admin_channel is None:
            await interaction.response.send_message("Salon admin introuvable. Contacte un administrateur.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Nouvelle Prime #{prime_id} - En attente",
            description=(
                f"**Cible :** {primes[prime_id]['pseudo']}\\n"
                f"**Montant :** {primes[prime_id]['montant']}$\\n"
                f"**Preuve :** {primes[prime_id]['preuve']}\\n"
                f"**Déposée par :** {interaction.user.mention}\\n\\n"
                f"Statut : **{primes[prime_id]['statut']}**"
            ),
            color=discord.Color.orange(),
        )
        await admin_channel.send(embed=embed, view=PrimeAdminView(prime_id))

        await interaction.response.send_message(f"✅ Prime #{prime_id} déposée ! Elle sera vérifiée par le staff.", ephemeral=True)

class PrimeAdminView(discord.ui.View):
    def __init__(self, prime_id: int):
        super().__init__(timeout=None)
        self.prime_id = prime_id

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._decide(interaction, accepted=True)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger, emoji="❌")
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._decide(interaction, accepted=False)

    async def _decide(self, interaction: discord.Interaction, accepted: bool):
        if not is_mod(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission pour cette action.", ephemeral=True)
            return

        prime = primes.get(self.prime_id)
        if not prime:
            await interaction.response.send_message("Prime introuvable.", ephemeral=True)
            return
        if prime["statut"] != "En attente":
            await interaction.response.send_message(f"Cette prime est déjà {prime['statut']}.", ephemeral=True)
            return

        prime["statut"] = "Acceptée" if accepted else "Refusée"

        embed = discord.Embed(
            title=f"Prime #{prime['id']} - Statut mis à jour",
            description=(
                f"**Cible :** {prime['pseudo']}\\n"
                f"**Montant :** {prime['montant']}$\\n"
                f"**Preuve :** {prime['preuve']}\\n"
                f"**Déposée par :** <@{prime['auteur_id']}>\\n\\n"
                f"Statut : **{prime['statut']}**"
            ),
            color=discord.Color.green() if accepted else discord.Color.red()
        )
        await interaction.message.edit(embed=embed, view=None)

        try:
            author = interaction.guild.get_member(prime["auteur_id"])
            if author:
                await author.send(f"Ta prime #{prime['id']} sur **{prime['pseudo']}** a été **{prime['statut']}**.")
        except Exception:
            pass

        await interaction.response.send_message(f"OK, prime #{prime['id']} marquée **{prime['statut']}**.", ephemeral=True)

        if accepted:
            public = interaction.guild.get_channel(PUBLIC_CHANNEL_ID)
            if public:
                pub_embed = discord.Embed(
                    title="🎯 Prime acceptée !",
                    description=(
                        f"**Cible :** {prime['pseudo']}\\n"
                        f"**Récompense :** **{prime['montant']}$**\\n"
                        f"**Infos paiement :** {prime['preuve']}\\n\\n"
                        f"Tu as abattu la cible ? Clique ci-dessous pour soumettre ta preuve au staff."
                    ),
                    color=discord.Color.gold()
                )
                await public.send(embed=pub_embed, view=KillClaimView(prime_id=prime["id"], target=prime["pseudo"]))

class KillClaimView(discord.ui.View):
    def __init__(self, prime_id: int, target: str):
        super().__init__(timeout=None)
        self.prime_id = prime_id
        self.target = target

    @discord.ui.button(label="J'ai tué la cible", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        category = guild.get_channel(KILL_TICKET_CATEGORY_ID)
        if category is None:
            await interaction.response.send_message("Catégorie tickets introuvable, contacte un admin.", ephemeral=True)
            return

        ticket_name = f"kill-{self.prime_id}-{interaction.user.name}".replace(" ", "-").lower()
        for ch in category.channels:
            if ch.name == ticket_name:
                await interaction.response.send_message(f"Tu as déjà un ticket ouvert : {ch.mention}", ephemeral=True)
                return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.get_role(ROLE_MOD_ID): discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
        }
        channel = await guild.create_text_channel(ticket_name, category=category, overwrites=overwrites)

        await channel.send(
            f"{interaction.user.mention} merci d'envoyer **une preuve de kill** (vidéo/screen) pour la cible **{self.target}**.\\n"
            f"Un modérateur passera valider ou refuser. Utilisez les boutons ci-dessous.",
            view=KillValidationView(prime_id=self.prime_id, hunter_id=interaction.user.id, target=self.target)
        )

        await interaction.response.send_message(f"Ticket créé : {channel.mention}", ephemeral=True)

class KillValidationView(discord.ui.View):
    def __init__(self, prime_id: int, hunter_id: int, target: str):
        super().__init__(timeout=None)
        self.prime_id = prime_id
        self.hunter_id = hunter_id
        self.target = target

    @discord.ui.button(label="Valider le kill", style=discord.ButtonStyle.success, emoji="✅")
    async def validate(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_mod(interaction.user):
            await interaction.response.send_message("Action réservée au staff.", ephemeral=True)
            return

        leaderboard[self.hunter_id] = leaderboard.get(self.hunter_id, 0) + 1

        await interaction.response.send_message(f"Kill validé pour {fmt_user(interaction.guild, self.hunter_id)} 🎉", ephemeral=True)
        try:
            await interaction.message.channel.send(f"✅ Kill validé par {interaction.user.mention} pour la prime #{self.prime_id}.")
        except Exception:
            pass

    @discord.ui.button(label="Refuser le kill", style=discord.ButtonStyle.danger, emoji="❌")
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_mod(interaction.user):
            await interaction.response.send_message("Action réservée au staff.", ephemeral=True)
            return

        await interaction.response.send_message("Kill refusé.", ephemeral=True)
        try:
            await interaction.message.channel.send(f"❌ Kill refusé par {interaction.user.mention} pour la prime #{self.prime_id}.")
        except Exception:
            pass

@bot.tree.command(name="prime", description="Ouvrir le formulaire pour déposer une prime")
async def prime_cmd(interaction: discord.Interaction):
    await interaction.response.send_modal(PrimeModal())

@bot.tree.command(name="afficher", description="Afficher l'embed d'information avec bouton pour déposer une prime")
async def afficher_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🧭 Les Primes de Paladium",
        description=(
            "Place une prime sur un joueur (PVP fair-play uniquement).\\n\\n"
            "• Spécifie le pseudo, le montant, et ajoute une preuve de paiement.\\n"
            "• Le staff valide/retire la prime côté admin.\\n"
            "• Une fois acceptée, elle apparaît publiquement avec un bouton pour déclarer un kill.\\n\\n"
            "Une **taxe de 1000$** est appliquée sur chaque dépôt.\\n"
            "Preuve de paiement à envoyer (screen/vidéo) vers l'adresse communiquée par le staff."
        ),
        color=discord.Color.blurple()
    )
    view = discord.ui.View()
    btn = discord.ui.Button(label="Déposer une prime", style=discord.ButtonStyle.primary, emoji="🎯")
    async def cb(i: discord.Interaction):
        await i.response.send_modal(PrimeModal())
    btn.callback = cb
    view.add_item(btn)
    await interaction.response.send_message(embed=embed, view=view)

def build_leaderboard_embed(guild: discord.Guild) -> discord.Embed:
    items = sorted(leaderboard.items(), key=lambda kv: kv[1], reverse=True)
    desc = "Aucun kill validé pour le moment." if not items else ""
    embed = discord.Embed(title="🏆 Classement des chasseurs de primes", color=discord.Color.gold())
    if items:
        lines = []
        for rank, (uid, score) in enumerate(items[:20], start=1):
            lines.append(f"**{rank}.** {fmt_user(guild, uid)} — **{score}** kill(s) validé(s)")
        desc = "\\n".join(lines)
    embed.description = desc
    return embed

@tasks.loop(seconds=180)
async def update_leaderboard_loop():
    await bot.wait_until_ready()
    for guild in bot.guilds:
        channel = guild.get_channel(LEADERBOARD_CHANNEL_ID)
        if not channel:
            continue
        global leaderboard_message_id
        try:
            if leaderboard_message_id:
                try:
                    msg = await channel.fetch_message(leaderboard_message_id)
                    await msg.edit(embed=build_leaderboard_embed(guild))
                    continue
                except Exception:
                    leaderboard_message_id = None
            msg = await channel.send(embed=build_leaderboard_embed(guild))
            leaderboard_message_id = msg.id
        except Exception:
            pass

@bot.event
async def on_ready():
    print(f"Connecté comme {bot.user} (ID: {bot.user.id})")
    try:
        await bot.tree.sync()
        print("Slash commands synchronisées.")
    except Exception as e:
        print("Erreur sync:", e)
    update_leaderboard_loop.start()

def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN manquant (variable d'environnement).")
    bot.run(token)

if __name__ == "__main__":
    main()
