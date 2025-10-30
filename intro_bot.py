import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timedelta

# Bot configuration
INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.guilds = True

bot = commands.Bot(command_prefix='!', intents=INTENTS)

# Configuration - adjust these values
INTRO_CHANNEL_ID = 0  # Replace with your introductions channel ID
GRACE_PERIOD_HOURS = 72  # Time users have to post before being kicked
CHECK_INTERVAL_MINUTES = 60  # How often to check for non-introduced members

# Store pending members {user_id: {'join_time': timestamp, 'reminded_24': bool, 'reminded_48': bool}}
PENDING_FILE = 'pending_members.json'
# Store user IDs who have posted introductions (persistent cache)
INTRODUCED_FILE = 'introduced_members.json'

def load_pending_members():
    """Load pending members from file"""
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r') as f:
            data = json.load(f)
            # Migrate old format to new format if needed
            for user_id, value in data.items():
                if isinstance(value, str):
                    data[user_id] = {
                        'join_time': value,
                        'reminded_24': False,
                        'reminded_48': False
                    }
            return data
    return {}

def save_pending_members(pending_members):
    """Save pending members to file"""
    with open(PENDING_FILE, 'w') as f:
        json.dump(pending_members, f, indent=2)

def load_introduced_members():
    """Load set of user IDs who have introduced themselves"""
    if os.path.exists(INTRODUCED_FILE):
        with open(INTRODUCED_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_introduced_members(introduced_members):
    """Save set of user IDs who have introduced themselves"""
    with open(INTRODUCED_FILE, 'w') as f:
        json.dump(list(introduced_members), f, indent=2)

pending_members = load_pending_members()
introduced_members = load_introduced_members()

async def scan_intro_channel_history():
    """Scan intro channel history on startup to build/update the introduced members cache"""
    if INTRO_CHANNEL_ID == 0:
        print("Intro channel not set, skipping initial scan")
        return

    intro_channel = bot.get_channel(INTRO_CHANNEL_ID)
    if not intro_channel:
        print(f"Could not find intro channel {INTRO_CHANNEL_ID}")
        return

    print("Scanning intro channel history to build cache...")

    try:
        message_count = 0
        new_members = 0

        async for message in intro_channel.history(limit=10000):
            message_count += 1
            if not message.author.bot and message.author.id not in introduced_members:
                introduced_members.add(message.author.id)
                new_members += 1

        save_introduced_members(introduced_members)
        print(f"Scanned {message_count} messages, found {new_members} new introduced members")
        print(f"Total introduced members in cache: {len(introduced_members)}")

    except discord.Forbidden:
        print("Missing permissions to read intro channel history")
    except Exception as e:
        print(f"Error scanning intro channel: {e}")

@bot.event
async def on_ready():
    """Called when bot is ready"""
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guild(s)')

    # Scan intro channel history on startup
    await scan_intro_channel_history()

    # Start the background task to check for non-introduced members
    if not check_introductions.is_running():
        check_introductions.start()

@bot.event
async def on_member_join(member):
    """Track when a new member joins"""
    if member.bot:
        return  # Ignore bots

    print(f'{member.name} joined the server')

    # Add to pending members with current timestamp
    pending_members[str(member.id)] = {
        'join_time': datetime.utcnow().isoformat(),
        'reminded_24': False,
        'reminded_48': False
    }
    save_pending_members(pending_members)

    # Send initial welcome DM
    try:
        intro_channel = bot.get_channel(INTRO_CHANNEL_ID)
        await member.send(
            f"Welcome to the server! Please introduce yourself in {intro_channel.mention} "
            f"within {GRACE_PERIOD_HOURS} hours to avoid being removed."
        )
    except discord.Forbidden:
        print(f"Could not send DM to {member.name}")

@bot.event
async def on_message(message):
    """Check if message is in intro channel"""
    if message.author.bot:
        return

    # If message is in intro channel, add to introduced cache and remove from pending
    if message.channel.id == INTRO_CHANNEL_ID:
        user_id = str(message.author.id)

        # Add to introduced members cache
        if message.author.id not in introduced_members:
            introduced_members.add(message.author.id)
            save_introduced_members(introduced_members)

        # Remove from pending if they were being tracked
        if user_id in pending_members:
            print(f'{message.author.name} posted introduction')
            del pending_members[user_id]
            save_pending_members(pending_members)

            # React to their intro
            await message.add_reaction('✅')

    # Process commands
    await bot.process_commands(message)

@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_introductions():
    """Periodically check for members who haven't introduced themselves"""
    print("Checking for members who haven't introduced themselves...")

    current_time = datetime.utcnow()
    to_remove = []
    save_needed = False

    for user_id, user_data in pending_members.items():
        join_time = datetime.fromisoformat(user_data['join_time'])
        time_elapsed = current_time - join_time
        hours_elapsed = time_elapsed.total_seconds() / 3600

        # Find the member
        member = None
        for guild in bot.guilds:
            member = guild.get_member(int(user_id))
            if member:
                break

        if not member:
            continue

        intro_channel = bot.get_channel(INTRO_CHANNEL_ID)

        # Send 24-hour reminder
        if hours_elapsed >= 24 and not user_data['reminded_24']:
            hours_left = GRACE_PERIOD_HOURS - hours_elapsed
            try:
                await member.send(
                    f"**Reminder:** You have **{hours_left:.0f} hours** remaining to introduce yourself in {intro_channel.mention}. "
                    f"Please post your introduction to avoid being removed from the server."
                )
                print(f"Sent 24-hour reminder to {member.name}")
                user_data['reminded_24'] = True
                save_needed = True
            except discord.Forbidden:
                print(f"Could not send 24-hour reminder to {member.name}")

        # Send 48-hour reminder
        if hours_elapsed >= 48 and not user_data['reminded_48']:
            hours_left = GRACE_PERIOD_HOURS - hours_elapsed
            try:
                await member.send(
                    f"**Final Reminder:** You have **{hours_left:.0f} hours** remaining to introduce yourself in {intro_channel.mention}. "
                    f"This is your last warning before being removed from the server!"
                )
                print(f"Sent 48-hour reminder to {member.name}")
                user_data['reminded_48'] = True
                save_needed = True
            except discord.Forbidden:
                print(f"Could not send 48-hour reminder to {member.name}")

        # If grace period has passed (72 hours), kick the member
        if hours_elapsed >= GRACE_PERIOD_HOURS:
            to_remove.append(user_id)

            try:
                # Send final DM before kicking
                try:
                    await member.send(
                        f"You have been removed from the server for not posting an introduction "
                        f"in {intro_channel.mention} within {GRACE_PERIOD_HOURS} hours."
                    )
                except:
                    pass

                await member.kick(reason=f"Did not post introduction within {GRACE_PERIOD_HOURS} hours")
                print(f"Kicked {member.name} for not introducing themselves")

            except discord.Forbidden:
                print(f"Missing permissions to kick {member.name}")
            except Exception as e:
                print(f"Error kicking {member.name}: {e}")

    # Remove kicked members from pending list
    for user_id in to_remove:
        del pending_members[user_id]

    if to_remove or save_needed:
        save_pending_members(pending_members)

@check_introductions.before_loop
async def before_check():
    """Wait until bot is ready before starting checks"""
    await bot.wait_until_ready()

# Admin commands
@bot.command(name='checkpending')
@commands.has_permissions(administrator=True)
async def check_pending(ctx):
    """Check how many members are pending introduction"""
    if not pending_members:
        await ctx.send("No members are pending introduction.")
        return

    embed = discord.Embed(title="Pending Introductions", color=discord.Color.orange())

    for user_id, user_data in pending_members.items():
        member = ctx.guild.get_member(int(user_id))
        if member:
            join_time = datetime.fromisoformat(user_data['join_time'])
            time_left = timedelta(hours=GRACE_PERIOD_HOURS) - (datetime.utcnow() - join_time)
            hours_left = max(0, time_left.total_seconds() / 3600)

            # Show reminder status
            status = []
            if user_data['reminded_24']:
                status.append("24hr ✓")
            if user_data['reminded_48']:
                status.append("48hr ✓")
            status_str = f" ({', '.join(status)})" if status else ""

            embed.add_field(
                name=member.name,
                value=f"{hours_left:.1f} hours remaining{status_str}",
                inline=False
            )

    await ctx.send(embed=embed)

@bot.command(name='setintrochannel')
@commands.has_permissions(administrator=True)
async def set_intro_channel(ctx, channel: discord.TextChannel):
    """Set the introductions channel"""
    global INTRO_CHANNEL_ID
    INTRO_CHANNEL_ID = channel.id
    await ctx.send(f"Introductions channel set to {channel.mention}")

@bot.command(name='scanexisting')
@commands.has_permissions(administrator=True)
async def scan_existing(ctx):
    """Scan existing members to find who hasn't posted in introductions"""
    if INTRO_CHANNEL_ID == 0:
        await ctx.send("Please set the introductions channel first using !setintrochannel")
        return

    await ctx.send("Scanning all members using cached data...")

    intro_channel = bot.get_channel(INTRO_CHANNEL_ID)
    if not intro_channel:
        await ctx.send("Could not find the introductions channel.")
        return

    # Use cached introduced_members (already loaded from persistent storage)
    # Find members who haven't introduced themselves
    unintroduced = []
    for member in ctx.guild.members:
        if member.bot:
            continue
        if member.id not in introduced_members and str(member.id) not in pending_members:
            unintroduced.append(member)

    if not unintroduced:
        await ctx.send("All existing members have posted introductions!")
        return

    # Create embed showing results
    embed = discord.Embed(
        title="Unintroduced Existing Members",
        description=f"Found {len(unintroduced)} members who haven't posted in {intro_channel.mention}",
        color=discord.Color.red()
    )

    # Show up to 25 members in the embed (Discord limit)
    member_list = "\n".join([f"• {member.mention} ({member.name})" for member in unintroduced[:25]])
    embed.add_field(name="Members", value=member_list or "None", inline=False)

    if len(unintroduced) > 25:
        embed.set_footer(text=f"Showing 25 of {len(unintroduced)} members")

    embed.add_field(
        name="Next Steps",
        value=f"Use `!trackexisting <hours>` to start tracking these members\nExample: `!trackexisting 72` gives them 72 hours to introduce",
        inline=False
    )

    await ctx.send(embed=embed)

@bot.command(name='trackexisting')
@commands.has_permissions(administrator=True)
async def track_existing(ctx, grace_hours: int = None):
    """Start tracking existing members who haven't introduced themselves"""
    if INTRO_CHANNEL_ID == 0:
        await ctx.send("Please set the introductions channel first using !setintrochannel")
        return

    if grace_hours is None:
        await ctx.send(f"Please specify how many hours to give them.\nExample: `!trackexisting 72`")
        return

    if grace_hours < 1 or grace_hours > 168:
        await ctx.send("Grace period must be between 1 and 168 hours (1 week).")
        return

    await ctx.send("Adding unintroduced members to tracking list...")

    intro_channel = bot.get_channel(INTRO_CHANNEL_ID)
    if not intro_channel:
        await ctx.send("Could not find the introductions channel.")
        return

    # Use cached introduced_members (already loaded from persistent storage)
    # Add unintroduced members to tracking
    added_count = 0
    current_time = datetime.utcnow()
    backdated_time = current_time - timedelta(hours=GRACE_PERIOD_HOURS - grace_hours)

    for member in ctx.guild.members:
        if member.bot:
            continue
        if member.id not in introduced_members and str(member.id) not in pending_members:
            pending_members[str(member.id)] = {
                'join_time': backdated_time.isoformat(),
                'reminded_24': False,
                'reminded_48': False
            }
            added_count += 1

            # Send them a DM notification
            try:
                await member.send(
                    f"Hello! Our server now requires all members to post an introduction in {intro_channel.mention}. "
                    f"You have **{grace_hours} hours** to introduce yourself or you will be removed from the server. "
                    f"Thank you for understanding!"
                )
            except discord.Forbidden:
                print(f"Could not send DM to {member.name}")

    save_pending_members(pending_members)

    await ctx.send(
        f"Added {added_count} existing members to the tracking list. "
        f"They have {grace_hours} hours to introduce themselves."
    )

# Run the bot
if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')

    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set")
        print("Please set it with: export DISCORD_BOT_TOKEN='your_token_here'")
    else:
        if INTRO_CHANNEL_ID == 0:
            print("Warning: INTRO_CHANNEL_ID is not set. Use !setintrochannel command after starting.")
        bot.run(TOKEN)
