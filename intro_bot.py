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
REMINDER_TIMES = [24, 48]  # Hours after join to send reminders
EXEMPT_ROLE_IDS = []  # Role IDs that are exempt from intro requirement
WELCOME_ROLE_ID = 0  # Role to assign when someone introduces themselves (0 = disabled)
MOD_LOG_CHANNEL_ID = 0  # Channel to log kicks and warnings (0 = disabled)
MIN_INTRO_LENGTH = 0  # Minimum intro message length (0 = disabled)
REQUIRE_KEYWORDS = []  # Keywords required in intro (empty = disabled)
BOOSTER_GRACE_HOURS = 0  # Extra hours for server boosters (0 = same as normal)

# Safety settings
ENABLE_KICKING = False  # MUST be True to actually kick members (safety switch)
DRY_RUN_MODE = False  # If True, logs what would happen but doesn't kick
STARTUP_GRACE_PERIOD_HOURS = 24  # Extra hours added to existing members on first startup

# Store pending members {user_id: {'join_time': timestamp, 'reminded_24': bool, 'reminded_48': bool}}
PENDING_FILE = 'pending_members.json'
# Store user IDs who have posted introductions (persistent cache)
INTRODUCED_FILE = 'introduced_members.json'
# Store bot configuration
CONFIG_FILE = 'bot_config.json'

def load_config():
    """Load bot configuration from file"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config():
    """Save bot configuration to file"""
    config = {
        'intro_channel_id': INTRO_CHANNEL_ID,
        'mod_log_channel_id': MOD_LOG_CHANNEL_ID,
        'welcome_role_id': WELCOME_ROLE_ID
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

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

# Load saved config on startup
saved_config = load_config()
if 'intro_channel_id' in saved_config:
    INTRO_CHANNEL_ID = saved_config['intro_channel_id']
if 'mod_log_channel_id' in saved_config:
    MOD_LOG_CHANNEL_ID = saved_config['mod_log_channel_id']
if 'welcome_role_id' in saved_config:
    WELCOME_ROLE_ID = saved_config['welcome_role_id']

def is_member_exempt(member):
    """Check if a member is exempt from intro requirements"""
    if not EXEMPT_ROLE_IDS:
        return False
    member_role_ids = [role.id for role in member.roles]
    return any(role_id in EXEMPT_ROLE_IDS for role_id in member_role_ids)

def get_member_grace_period(member):
    """Get grace period for a member (accounts for booster status)"""
    if BOOSTER_GRACE_HOURS > 0 and member.premium_since:
        return GRACE_PERIOD_HOURS + BOOSTER_GRACE_HOURS
    return GRACE_PERIOD_HOURS

async def log_to_mod_channel(message, color=discord.Color.orange()):
    """Log a message to the mod log channel if configured"""
    if MOD_LOG_CHANNEL_ID == 0:
        return

    mod_channel = bot.get_channel(MOD_LOG_CHANNEL_ID)
    if mod_channel:
        try:
            embed = discord.Embed(description=message, color=color, timestamp=datetime.utcnow())
            await mod_channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to log to mod channel: {e}")

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

    # Check if member is exempt
    if is_member_exempt(member):
        print(f'{member.name} joined the server (exempt from intro requirement)')
        return

    print(f'{member.name} joined the server')

    # Get grace period for this member
    grace_hours = get_member_grace_period(member)

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
        booster_msg = f" (Server boosters get {grace_hours} hours!)" if member.premium_since and BOOSTER_GRACE_HOURS > 0 else ""
        await member.send(
            f"Welcome to the server! Please introduce yourself in {intro_channel.mention} "
            f"within {grace_hours} hours to avoid being removed.{booster_msg}"
        )
    except discord.Forbidden:
        print(f"Could not send DM to {member.name}")

    # Log to mod channel
    await log_to_mod_channel(f"👋 **{member.mention}** joined - tracking for introduction ({grace_hours}h grace period)", discord.Color.blue())

@bot.event
async def on_message(message):
    """Check if message is in intro channel"""
    if message.author.bot:
        return

    # If message is in intro channel, validate and process introduction
    if message.channel.id == INTRO_CHANNEL_ID:
        user_id = str(message.author.id)

        # Validate minimum length
        if MIN_INTRO_LENGTH > 0 and len(message.content) < MIN_INTRO_LENGTH:
            await message.delete()
            try:
                await message.author.send(
                    f"Your introduction was too short. Please write at least {MIN_INTRO_LENGTH} characters. "
                    f"Tell us about yourself!"
                )
            except discord.Forbidden:
                pass
            return

        # Validate required keywords
        if REQUIRE_KEYWORDS:
            content_lower = message.content.lower()
            missing_keywords = [kw for kw in REQUIRE_KEYWORDS if kw.lower() not in content_lower]
            if missing_keywords:
                await message.delete()
                try:
                    await message.author.send(
                        f"Your introduction is missing required information. "
                        f"Please include: {', '.join(missing_keywords)}"
                    )
                except discord.Forbidden:
                    pass
                return

        # Valid introduction - add to introduced members cache
        if message.author.id not in introduced_members:
            introduced_members.add(message.author.id)
            save_introduced_members(introduced_members)

        # Remove from pending if they were being tracked
        was_pending = user_id in pending_members
        if was_pending:
            print(f'{message.author.name} posted introduction')
            del pending_members[user_id]
            save_pending_members(pending_members)

        # Assign welcome role if configured
        if WELCOME_ROLE_ID != 0:
            try:
                role = message.guild.get_role(WELCOME_ROLE_ID)
                if role and role not in message.author.roles:
                    await message.author.add_roles(role, reason="Posted introduction")
                    print(f"Assigned welcome role to {message.author.name}")
            except discord.Forbidden:
                print(f"Missing permissions to assign welcome role to {message.author.name}")

        # React to their intro
        await message.add_reaction('✅')

        # Log to mod channel
        if was_pending:
            await log_to_mod_channel(
                f"✅ **{message.author.mention}** posted their introduction - no longer tracking",
                discord.Color.green()
            )

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

        # Get grace period for this member (might be different for boosters)
        member_grace_hours = get_member_grace_period(member)

        intro_channel = bot.get_channel(INTRO_CHANNEL_ID)

        # Send reminders based on REMINDER_TIMES config
        for i, reminder_hour in enumerate(REMINDER_TIMES):
            reminder_key = f'reminded_{reminder_hour}'

            # Initialize reminder key if it doesn't exist (for backwards compatibility)
            if reminder_key not in user_data:
                user_data[reminder_key] = False

            if hours_elapsed >= reminder_hour and not user_data[reminder_key]:
                hours_left = member_grace_hours - hours_elapsed

                # Determine if this is the final reminder
                is_final = i == len(REMINDER_TIMES) - 1
                reminder_prefix = "**Final Reminder:**" if is_final else "**Reminder:**"

                try:
                    await member.send(
                        f"{reminder_prefix} You have **{hours_left:.0f} hours** remaining to introduce yourself in {intro_channel.mention}. "
                        f"Please post your introduction to avoid being removed from the server."
                    )
                    print(f"Sent {reminder_hour}-hour reminder to {member.name}")
                    user_data[reminder_key] = True
                    save_needed = True

                    # Log to mod channel
                    await log_to_mod_channel(
                        f"⏰ Sent {reminder_hour}h reminder to **{member.mention}** ({hours_left:.0f}h remaining)",
                        discord.Color.orange()
                    )
                except discord.Forbidden:
                    print(f"Could not send {reminder_hour}-hour reminder to {member.name}")

        # If grace period has passed, kick the member (with safety checks)
        if hours_elapsed >= member_grace_hours:
            # Check if kicking is enabled
            if not ENABLE_KICKING:
                print(f"[SAFETY] Would kick {member.name} but ENABLE_KICKING=False")
                await log_to_mod_channel(
                    f"🛡️ **SAFETY MODE**: Would kick **{member.mention}** but kicking is disabled. Set ENABLE_KICKING=True to allow kicks.",
                    discord.Color.gold()
                )
                continue

            to_remove.append(user_id)

            # Dry run mode - log but don't actually kick
            if DRY_RUN_MODE:
                print(f"[DRY RUN] Would kick {member.name} for not introducing themselves")
                await log_to_mod_channel(
                    f"🔍 **DRY RUN**: Would kick **{member.mention}** ({member_grace_hours}h expired). Set DRY_RUN_MODE=False to enable real kicks.",
                    discord.Color.orange()
                )
                continue

            try:
                # Log to mod channel BEFORE kicking (so we can mention them)
                await log_to_mod_channel(
                    f"⚠️ About to kick **{member.mention}** for not introducing themselves within {member_grace_hours}h",
                    discord.Color.red()
                )

                # Send final DM before kicking
                try:
                    await member.send(
                        f"You have been removed from the server for not posting an introduction "
                        f"in {intro_channel.mention} within {member_grace_hours} hours."
                    )
                except:
                    pass

                await member.kick(reason=f"Did not post introduction within {member_grace_hours} hours")
                print(f"Kicked {member.name} for not introducing themselves")

                # Log successful kick
                await log_to_mod_channel(
                    f"❌ Kicked **{member.name}** (ID: {member.id}) for not introducing themselves",
                    discord.Color.dark_red()
                )

            except discord.Forbidden:
                print(f"Missing permissions to kick {member.name}")
                await log_to_mod_channel(
                    f"⚠️ Failed to kick **{member.mention}** - missing permissions",
                    discord.Color.red()
                )
            except Exception as e:
                print(f"Error kicking {member.name}: {e}")
                await log_to_mod_channel(
                    f"⚠️ Error kicking **{member.mention}**: {e}",
                    discord.Color.red()
                )

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
    save_config()
    await ctx.send(f"✅ Introductions channel set to {channel.mention} (saved)")

@bot.command(name='setmodlog')
@commands.has_permissions(administrator=True)
async def set_mod_log(ctx, channel: discord.TextChannel):
    """Set the mod log channel"""
    global MOD_LOG_CHANNEL_ID
    MOD_LOG_CHANNEL_ID = channel.id
    save_config()
    await ctx.send(f"✅ Mod log channel set to {channel.mention} (saved)")
    await log_to_mod_channel(
        f"✅ Mod logging enabled by **{ctx.author.mention}**",
        discord.Color.green()
    )

@bot.command(name='setwelcomerole')
@commands.has_permissions(administrator=True)
async def set_welcome_role(ctx, role: discord.Role):
    """Set the welcome role to assign after introductions"""
    global WELCOME_ROLE_ID
    WELCOME_ROLE_ID = role.id
    save_config()
    await ctx.send(f"✅ Welcome role set to {role.mention} (saved)")
    await log_to_mod_channel(
        f"✅ Welcome role set to {role.mention} by **{ctx.author.mention}**",
        discord.Color.green()
    )

@bot.command(name='markintroduced')
@commands.has_permissions(administrator=True)
async def mark_introduced(ctx, member: discord.Member):
    """Manually mark a member as introduced"""
    user_id = str(member.id)

    # Add to introduced cache
    introduced_members.add(member.id)
    save_introduced_members(introduced_members)

    # Remove from pending if tracked
    was_pending = user_id in pending_members
    if was_pending:
        del pending_members[user_id]
        save_pending_members(pending_members)

    # Assign welcome role if configured
    if WELCOME_ROLE_ID != 0:
        try:
            role = ctx.guild.get_role(WELCOME_ROLE_ID)
            if role and role not in member.roles:
                await member.add_roles(role, reason="Manually marked as introduced")
        except discord.Forbidden:
            await ctx.send("Warning: Could not assign welcome role (missing permissions)")

    status = "and removed from tracking" if was_pending else "(was not being tracked)"
    await ctx.send(f"✅ Marked {member.mention} as introduced {status}")

    await log_to_mod_channel(
        f"✅ **{ctx.author.mention}** manually marked **{member.mention}** as introduced",
        discord.Color.green()
    )

@bot.command(name='untrack')
@commands.has_permissions(administrator=True)
async def untrack_member(ctx, member: discord.Member):
    """Remove a member from tracking without kicking them"""
    user_id = str(member.id)

    if user_id not in pending_members:
        await ctx.send(f"{member.mention} is not currently being tracked.")
        return

    del pending_members[user_id]
    save_pending_members(pending_members)

    await ctx.send(f"✅ Stopped tracking {member.mention} (they will not be kicked)")

    await log_to_mod_channel(
        f"⏸️ **{ctx.author.mention}** stopped tracking **{member.mention}**",
        discord.Color.blue()
    )

@bot.command(name='resetcache')
@commands.has_permissions(administrator=True)
async def reset_cache(ctx):
    """Rebuild the introduced members cache from intro channel history"""
    if INTRO_CHANNEL_ID == 0:
        await ctx.send("Please set the introductions channel first using !setintrochannel")
        return

    await ctx.send("Rebuilding cache from intro channel history...")

    # Clear current cache
    introduced_members.clear()

    # Rescan
    await scan_intro_channel_history()

    await ctx.send(f"✅ Cache rebuilt! Now tracking {len(introduced_members)} introduced members.")

@bot.command(name='stats')
@commands.has_permissions(administrator=True)
async def show_stats(ctx):
    """Show bot statistics"""
    embed = discord.Embed(title="Introduction Bot Statistics", color=discord.Color.blue())

    # Pending members
    pending_count = len(pending_members)
    embed.add_field(name="📊 Pending Introductions", value=str(pending_count), inline=True)

    # Introduced members
    introduced_count = len(introduced_members)
    embed.add_field(name="✅ Introduced Members", value=str(introduced_count), inline=True)

    # Total members in server
    total_members = len([m for m in ctx.guild.members if not m.bot])
    embed.add_field(name="👥 Total Members", value=str(total_members), inline=True)

    # Configuration
    config_text = f"Grace Period: {GRACE_PERIOD_HOURS}h\n"
    config_text += f"Reminders: {', '.join([f'{h}h' for h in REMINDER_TIMES])}\n"
    config_text += f"Check Interval: {CHECK_INTERVAL_MINUTES}min\n"

    if BOOSTER_GRACE_HOURS > 0:
        config_text += f"Booster Bonus: +{BOOSTER_GRACE_HOURS}h\n"

    if EXEMPT_ROLE_IDS:
        config_text += f"Exempt Roles: {len(EXEMPT_ROLE_IDS)}\n"

    if WELCOME_ROLE_ID != 0:
        role = ctx.guild.get_role(WELCOME_ROLE_ID)
        config_text += f"Welcome Role: {role.mention if role else 'Not found'}\n"

    if MIN_INTRO_LENGTH > 0:
        config_text += f"Min Intro Length: {MIN_INTRO_LENGTH} chars\n"

    if REQUIRE_KEYWORDS:
        config_text += f"Required Keywords: {', '.join(REQUIRE_KEYWORDS)}\n"

    embed.add_field(name="⚙️ Configuration", value=config_text, inline=False)

    # Recent activity (if we had a stats file, but we don't yet)
    embed.set_footer(text=f"Intro Channel: #{bot.get_channel(INTRO_CHANNEL_ID).name}" if INTRO_CHANNEL_ID != 0 else "Intro channel not set")

    await ctx.send(embed=embed)

@bot.command(name='allo')
async def allo_test(ctx):
    """Test command to verify bot is responding"""
    await ctx.send("Allo! 👋 Bot is working!")

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
        value=f"Use `!trackexisting <hours>` to start tracking these members\nExample: `!trackexisting 72` gives them 72 hours to introduce\n\n⚠️ Recommended: Use `!trackexisting {GRACE_PERIOD_HOURS + STARTUP_GRACE_PERIOD_HOURS}` for first-time setup (includes {STARTUP_GRACE_PERIOD_HOURS}h grace period)",
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
