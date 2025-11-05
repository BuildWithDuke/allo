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

# Global configuration (applies to all guilds)
GRACE_PERIOD_HOURS = 24  # Time users have to post before being kicked
CHECK_INTERVAL_MINUTES = 60  # How often to check for non-introduced members
REMINDER_TIMES = [12]  # Hours after join to send reminders
MIN_INTRO_LENGTH = 0  # Minimum intro message length (0 = disabled)
REQUIRE_KEYWORDS = []  # Keywords required in intro (empty = disabled)
BOOSTER_GRACE_HOURS = 0  # Extra hours for server boosters (0 = same as normal)

# Safety settings
ENABLE_KICKING = False  # MUST be True to actually kick members (safety switch)
DRY_RUN_MODE = True  # If True, logs what would happen but doesn't kick
ENABLE_BACKGROUND_CHECKS = False  # If False, disables reminder/kick loop entirely (testing mode)
STARTUP_GRACE_PERIOD_HOURS = 24  # Extra hours added to existing members on first startup

# Per-guild file storage - each guild gets its own files
def get_guild_file(guild_id, file_type):
    """Get the filename for a specific guild and file type"""
    return f'{file_type}_{guild_id}.json'

def load_guild_config(guild_id):
    """Load configuration for a specific guild"""
    filename = get_guild_file(guild_id, 'config')
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {
        'intro_channel_id': 0,
        'mod_log_channel_id': 0,
        'welcome_role_id': 0,
        'exempt_role_ids': []
    }

def save_guild_config(guild_id, config):
    """Save configuration for a specific guild"""
    filename = get_guild_file(guild_id, 'config')
    with open(filename, 'w') as f:
        json.dump(config, f, indent=2)

def load_guild_pending(guild_id):
    """Load pending members for a specific guild"""
    filename = get_guild_file(guild_id, 'pending')
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            data = json.load(f)
            # Migrate old format if needed
            for user_id, value in data.items():
                if isinstance(value, str):
                    data[user_id] = {
                        'join_time': value,
                        'reminded_12': False
                    }
            return data
    return {}

def save_guild_pending(guild_id, pending_members):
    """Save pending members for a specific guild"""
    filename = get_guild_file(guild_id, 'pending')
    with open(filename, 'w') as f:
        json.dump(pending_members, f, indent=2)

def load_guild_introduced(guild_id):
    """Load introduced members for a specific guild"""
    filename = get_guild_file(guild_id, 'introduced')
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return set(json.load(f))
    return set()

def save_guild_introduced(guild_id, introduced_members):
    """Save introduced members for a specific guild"""
    filename = get_guild_file(guild_id, 'introduced')
    with open(filename, 'w') as f:
        json.dump(list(introduced_members), f, indent=2)

# Guild-specific data will be loaded on-demand when needed
guild_data_cache = {}  # {guild_id: {'config': {}, 'pending': {}, 'introduced': set()}}

def get_guild_data(guild_id):
    """Get all data for a guild (loads from file if not cached)"""
    guild_id_str = str(guild_id)
    if guild_id_str not in guild_data_cache:
        guild_data_cache[guild_id_str] = {
            'config': load_guild_config(guild_id_str),
            'pending': load_guild_pending(guild_id_str),
            'introduced': load_guild_introduced(guild_id_str)
        }
    return guild_data_cache[guild_id_str]

def is_member_exempt(member, exempt_role_ids):
    """Check if a member is exempt from intro requirements"""
    if not exempt_role_ids:
        return False
    member_role_ids = [role.id for role in member.roles]
    return any(role_id in exempt_role_ids for role_id in member_role_ids)

def get_member_grace_period(member):
    """Get grace period for a member (accounts for booster status)"""
    if BOOSTER_GRACE_HOURS > 0 and member.premium_since:
        return GRACE_PERIOD_HOURS + BOOSTER_GRACE_HOURS
    return GRACE_PERIOD_HOURS

async def log_to_mod_channel(guild_id, message, color=discord.Color.orange()):
    """Log a message to the mod log channel if configured"""
    config = get_guild_data(guild_id)['config']
    mod_log_channel_id = config.get('mod_log_channel_id', 0)

    if mod_log_channel_id == 0:
        return

    mod_channel = bot.get_channel(mod_log_channel_id)
    if mod_channel:
        try:
            embed = discord.Embed(description=message, color=color, timestamp=datetime.utcnow())
            await mod_channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to log to mod channel: {e}")

async def scan_intro_channel_history(guild_id, intro_channel_id):
    """Scan intro channel history to build/update the introduced members cache"""
    if intro_channel_id == 0:
        print(f"Guild {guild_id}: Intro channel not set, skipping scan")
        return

    intro_channel = bot.get_channel(intro_channel_id)
    if not intro_channel:
        print(f"Guild {guild_id}: Could not find intro channel {intro_channel_id}")
        return

    print(f"Guild {guild_id}: Scanning intro channel history...")

    # Use cached data to avoid losing recent changes
    guild_data = get_guild_data(guild_id)
    introduced_members = guild_data['introduced']
    pending_members = guild_data['pending']

    try:
        message_count = 0
        new_members = 0
        reactions_added = 0
        removed_from_pending = 0

        async for message in intro_channel.history(limit=10000):
            message_count += 1
            if not message.author.bot and message.author.id not in introduced_members:
                introduced_members.add(message.author.id)
                new_members += 1

                # Remove from pending if they were being tracked
                user_id = str(message.author.id)
                if user_id in pending_members:
                    del pending_members[user_id]
                    removed_from_pending += 1

                # Add checkmark reaction if it doesn't have one yet
                try:
                    has_checkmark = any(str(reaction.emoji) == '✅' for reaction in message.reactions)
                    if not has_checkmark:
                        await message.add_reaction('✅')
                        reactions_added += 1
                except discord.Forbidden:
                    pass  # Missing permissions to add reaction
                except Exception as e:
                    print(f"Guild {guild_id}: Could not add reaction to message {message.id}: {e}")

        save_guild_introduced(guild_id, introduced_members)
        if removed_from_pending > 0:
            save_guild_pending(guild_id, pending_members)

        print(f"Guild {guild_id}: Scanned {message_count} messages, found {new_members} new intros")
        print(f"Guild {guild_id}: Total introduced members: {len(introduced_members)}")
        if reactions_added > 0:
            print(f"Guild {guild_id}: Added ✅ to {reactions_added} messages")
        if removed_from_pending > 0:
            print(f"Guild {guild_id}: Removed {removed_from_pending} members from pending list")

        # Update cache
        if str(guild_id) in guild_data_cache:
            guild_data_cache[str(guild_id)]['introduced'] = introduced_members
            guild_data_cache[str(guild_id)]['pending'] = pending_members

    except discord.Forbidden:
        print(f"Guild {guild_id}: Missing permissions to read intro channel history")
    except Exception as e:
        print(f"Guild {guild_id}: Error scanning intro channel: {e}")

@bot.event
async def on_ready():
    """Called when bot is ready"""
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guild(s)')

    # Scan intro channel history for ALL guilds on startup
    for guild in bot.guilds:
        guild_id = str(guild.id)
        config = load_guild_config(guild_id)
        intro_channel_id = config.get('intro_channel_id', 0)
        await scan_intro_channel_history(guild_id, intro_channel_id)

    # Start the background task to check for non-introduced members (if enabled)
    if ENABLE_BACKGROUND_CHECKS:
        if not check_introductions.is_running():
            check_introductions.start()
            print("Background reminder/kick checks: ENABLED")
    else:
        print("⚠️ Background reminder/kick checks: DISABLED (set ENABLE_BACKGROUND_CHECKS=True to enable)")

@bot.event
async def on_member_join(member):
    """Track when a new member joins"""
    if member.bot:
        return  # Ignore bots

    # Load guild-specific data
    guild_id = str(member.guild.id)
    guild_data = get_guild_data(guild_id)
    config = guild_data['config']
    pending_members = guild_data['pending']

    exempt_role_ids = config.get('exempt_role_ids', [])
    intro_channel_id = config.get('intro_channel_id', 0)

    # Check if member is exempt
    if is_member_exempt(member, exempt_role_ids):
        print(f'Guild {guild_id}: {member.name} joined (exempt from intro requirement)')
        return

    print(f'Guild {guild_id}: {member.name} joined the server')

    # Get grace period for this member
    grace_hours = get_member_grace_period(member)

    # Add to pending members with current timestamp and dynamic reminder keys
    reminder_data = {'join_time': datetime.utcnow().isoformat()}
    for reminder_hour in REMINDER_TIMES:
        reminder_data[f'reminded_{reminder_hour}'] = False

    pending_members[str(member.id)] = reminder_data
    save_guild_pending(guild_id, pending_members)

    # Send initial welcome DM
    try:
        intro_channel = bot.get_channel(intro_channel_id)
        booster_msg = f" (Server boosters get {grace_hours} hours!)" if member.premium_since and BOOSTER_GRACE_HOURS > 0 else ""
        await member.send(
            f"Welcome to the server! Please introduce yourself in {intro_channel.mention} "
            f"within {grace_hours} hours to avoid being removed.{booster_msg}"
        )
    except discord.Forbidden:
        print(f"Guild {guild_id}: Could not send DM to {member.name}")

    # Log to mod channel
    await log_to_mod_channel(guild_id, f"👋 **{member.mention}** joined - tracking for introduction ({grace_hours}h grace period)", discord.Color.blue())

@bot.event
async def on_message(message):
    """Check if message is in intro channel"""
    if message.author.bot:
        return

    # Load guild-specific data
    guild_id = str(message.guild.id)
    guild_data = get_guild_data(guild_id)
    config = guild_data['config']
    pending_members = guild_data['pending']
    introduced_members = guild_data['introduced']

    intro_channel_id = config.get('intro_channel_id', 0)
    welcome_role_id = config.get('welcome_role_id', 0)

    # If message is in intro channel, validate and process introduction
    if message.channel.id == intro_channel_id:
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
            save_guild_introduced(guild_id, introduced_members)

        # Remove from pending if they were being tracked
        was_pending = user_id in pending_members
        if was_pending:
            print(f'Guild {guild_id}: {message.author.name} posted introduction')
            del pending_members[user_id]
            save_guild_pending(guild_id, pending_members)

        # Assign welcome role if configured
        if welcome_role_id != 0:
            try:
                role = message.guild.get_role(welcome_role_id)
                if role and role not in message.author.roles:
                    await message.author.add_roles(role, reason="Posted introduction")
                    print(f"Guild {guild_id}: Assigned welcome role to {message.author.name}")
            except discord.Forbidden:
                print(f"Guild {guild_id}: Missing permissions to assign welcome role to {message.author.name}")

        # React to their intro
        await message.add_reaction('✅')

        # Log to mod channel
        if was_pending:
            await log_to_mod_channel(
                guild_id,
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

    # Check ALL guilds
    for guild in bot.guilds:
        guild_id = str(guild.id)
        guild_data = get_guild_data(guild_id)
        config = guild_data['config']
        pending_members = guild_data['pending']

        intro_channel_id = config.get('intro_channel_id', 0)
        intro_channel = bot.get_channel(intro_channel_id)

        to_remove = []
        save_needed = False

        # Use list() to create snapshot and avoid "dictionary changed size during iteration" error
        for user_id, user_data in list(pending_members.items()):
            join_time = datetime.fromisoformat(user_data['join_time'])
            time_elapsed = current_time - join_time
            hours_elapsed = time_elapsed.total_seconds() / 3600

            # Find the member in this guild
            member = guild.get_member(int(user_id))

            if not member:
                # Member left the server - remove from tracking
                to_remove.append(user_id)
                print(f"Guild {guild_id}: Member {user_id} left server, removing from tracking")
                continue

            # Get grace period for this member
            # Use custom grace_hours if set (from !trackexisting), otherwise use default
            if 'grace_hours' in user_data:
                member_grace_hours = user_data['grace_hours']
            else:
                # Use default grace period (might be different for boosters)
                member_grace_hours = get_member_grace_period(member)

            # Send reminders based on REMINDER_TIMES config
            # Only send ONE reminder per check cycle to avoid spam
            reminder_sent_this_cycle = False

            for i, reminder_hour in enumerate(REMINDER_TIMES):
                reminder_key = f'reminded_{reminder_hour}'

                # Initialize reminder key if it doesn't exist (for backwards compatibility)
                if reminder_key not in user_data:
                    user_data[reminder_key] = False

                # Skip if already sent
                if user_data[reminder_key]:
                    continue

                # Check if it's time for this reminder
                if hours_elapsed >= reminder_hour and not reminder_sent_this_cycle:
                    # For catch-up: only send the LAST unsent reminder, skip earlier ones
                    # Check if there are later reminders we should send instead
                    should_skip = False
                    for j in range(i + 1, len(REMINDER_TIMES)):
                        later_reminder_hour = REMINDER_TIMES[j]
                        if hours_elapsed >= later_reminder_hour:
                            # There's a later reminder we should send instead
                            should_skip = True
                            # Mark this one as sent so we don't try again
                            user_data[reminder_key] = True
                            save_needed = True
                            print(f"Guild {guild_id}: Skipped {reminder_hour}-hour reminder for {member.name} (sending later reminder instead)")
                            break

                    if not should_skip:
                        hours_left = member_grace_hours - hours_elapsed

                        # Determine if this is the final reminder
                        is_final = i == len(REMINDER_TIMES) - 1
                        reminder_prefix = "**Final Reminder:**" if is_final else "**Reminder:**"

                        try:
                            await member.send(
                                f"{reminder_prefix} You have **{hours_left:.0f} hours** remaining to introduce yourself in {intro_channel.mention}. "
                                f"Please post your introduction to avoid being removed from the server."
                            )
                            print(f"Guild {guild_id}: Sent {reminder_hour}-hour reminder to {member.name}")
                            user_data[reminder_key] = True
                            save_needed = True
                            reminder_sent_this_cycle = True

                            # Log to mod channel
                            await log_to_mod_channel(
                                guild_id,
                                f"⏰ Sent {reminder_hour}h reminder to **{member.mention}** ({hours_left:.0f}h remaining)",
                                discord.Color.orange()
                            )
                        except discord.Forbidden:
                            print(f"Guild {guild_id}: Could not send {reminder_hour}-hour reminder to {member.name}")

                        # Stop after sending one reminder
                        break

            # If grace period has passed, kick the member (with safety checks)
            if hours_elapsed >= member_grace_hours:
                # Check if kicking is enabled
                if not ENABLE_KICKING:
                    print(f"[{guild.name}] [SAFETY] Would kick {member.name} but ENABLE_KICKING=False")
                    await log_to_mod_channel(
                        guild_id,
                        f"🛡️ **SAFETY MODE**: Would kick **{member.mention}** but kicking is disabled. Set ENABLE_KICKING=True to allow kicks.",
                        discord.Color.gold()
                    )
                    continue

                to_remove.append(user_id)

                # Dry run mode - log but don't actually kick
                if DRY_RUN_MODE:
                    print(f"[{guild.name}] [DRY RUN] Would kick {member.name} for not introducing themselves")
                    await log_to_mod_channel(
                        guild_id,
                        f"🔍 **DRY RUN**: Would kick **{member.mention}** ({member_grace_hours}h expired). Set DRY_RUN_MODE=False to enable real kicks.",
                        discord.Color.orange()
                    )
                    continue

                try:
                    # Log to mod channel BEFORE kicking (so we can mention them)
                    await log_to_mod_channel(
                        guild_id,
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
                    print(f"[{guild.name}] Kicked {member.name} for not introducing themselves")

                    # Log successful kick
                    await log_to_mod_channel(
                        guild_id,
                        f"❌ Kicked **{member.name}** (ID: {member.id}) for not introducing themselves",
                        discord.Color.dark_red()
                    )

                except discord.Forbidden:
                    print(f"[{guild.name}] Missing permissions to kick {member.name}")
                    await log_to_mod_channel(
                        guild_id,
                        f"⚠️ Failed to kick **{member.mention}** - missing permissions",
                        discord.Color.red()
                    )
                except Exception as e:
                    print(f"[{guild.name}] Error kicking {member.name}: {e}")
                    await log_to_mod_channel(
                        guild_id,
                        f"⚠️ Error kicking **{member.mention}**: {e}",
                        discord.Color.red()
                    )

        # Remove kicked members from pending list
        for user_id in to_remove:
            del pending_members[user_id]

        if to_remove or save_needed:
            save_guild_pending(guild_id, pending_members)

@check_introductions.before_loop
async def before_check():
    """Wait until bot is ready before starting checks"""
    await bot.wait_until_ready()

# Admin commands
@bot.command(name='checkpending')
@commands.has_permissions(administrator=True)
async def check_pending(ctx):
    """Check how many members are pending introduction"""
    guild_id = str(ctx.guild.id)
    guild_data = get_guild_data(guild_id)
    pending_members = guild_data['pending']

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
            for reminder_hour in REMINDER_TIMES:
                reminder_key = f'reminded_{reminder_hour}'
                if user_data.get(reminder_key, False):
                    status.append(f"{reminder_hour}hr ✓")
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
    guild_id = str(ctx.guild.id)

    # Update cached config in-place to avoid race conditions
    guild_data = get_guild_data(guild_id)
    guild_data['config']['intro_channel_id'] = channel.id
    save_guild_config(guild_id, guild_data['config'])

    await ctx.send(f"✅ Introductions channel set to {channel.mention} (saved)")

@bot.command(name='setmodlog')
@commands.has_permissions(administrator=True)
async def set_mod_log(ctx, channel: discord.TextChannel):
    """Set the mod log channel"""
    guild_id = str(ctx.guild.id)

    # Update cached config in-place to avoid race conditions
    guild_data = get_guild_data(guild_id)
    guild_data['config']['mod_log_channel_id'] = channel.id
    save_guild_config(guild_id, guild_data['config'])

    await ctx.send(f"✅ Mod log channel set to {channel.mention} (saved)")
    await log_to_mod_channel(
        guild_id,
        f"✅ Mod logging enabled by **{ctx.author.mention}**",
        discord.Color.green()
    )

@bot.command(name='setwelcomerole')
@commands.has_permissions(administrator=True)
async def set_welcome_role(ctx, role: discord.Role):
    """Set the welcome role to assign after introductions"""
    guild_id = str(ctx.guild.id)

    # Update cached config in-place to avoid race conditions
    guild_data = get_guild_data(guild_id)
    guild_data['config']['welcome_role_id'] = role.id
    save_guild_config(guild_id, guild_data['config'])

    await ctx.send(f"✅ Welcome role set to {role.mention} (saved)")
    await log_to_mod_channel(
        guild_id,
        f"✅ Welcome role set to {role.mention} by **{ctx.author.mention}**",
        discord.Color.green()
    )

@bot.command(name='markintroduced')
@commands.has_permissions(administrator=True)
async def mark_introduced(ctx, member: discord.Member):
    """Manually mark a member as introduced"""
    guild_id = str(ctx.guild.id)
    guild_data = get_guild_data(guild_id)
    config = guild_data['config']
    pending_members = guild_data['pending']
    introduced_members = guild_data['introduced']

    user_id = str(member.id)

    # Add to introduced cache
    introduced_members.add(member.id)
    save_guild_introduced(guild_id, introduced_members)

    # Remove from pending if tracked
    was_pending = user_id in pending_members
    if was_pending:
        del pending_members[user_id]
        save_guild_pending(guild_id, pending_members)

    # Assign welcome role if configured
    welcome_role_id = config.get('welcome_role_id', 0)
    if welcome_role_id != 0:
        try:
            role = ctx.guild.get_role(welcome_role_id)
            if role and role not in member.roles:
                await member.add_roles(role, reason="Manually marked as introduced")
        except discord.Forbidden:
            await ctx.send("Warning: Could not assign welcome role (missing permissions)")

    status = "and removed from tracking" if was_pending else "(was not being tracked)"
    await ctx.send(f"✅ Marked {member.mention} as introduced {status}")

    await log_to_mod_channel(
        guild_id,
        f"✅ **{ctx.author.mention}** manually marked **{member.mention}** as introduced",
        discord.Color.green()
    )

@bot.command(name='untrack')
@commands.has_permissions(administrator=True)
async def untrack_member(ctx, member: discord.Member):
    """Remove a member from tracking without kicking them"""
    guild_id = str(ctx.guild.id)
    guild_data = get_guild_data(guild_id)
    pending_members = guild_data['pending']

    user_id = str(member.id)

    if user_id not in pending_members:
        await ctx.send(f"{member.mention} is not currently being tracked.")
        return

    del pending_members[user_id]
    save_guild_pending(guild_id, pending_members)

    await ctx.send(f"✅ Stopped tracking {member.mention} (they will not be kicked)")

    await log_to_mod_channel(
        guild_id,
        f"⏸️ **{ctx.author.mention}** stopped tracking **{member.mention}**",
        discord.Color.blue()
    )

@bot.command(name='resetcache')
@commands.has_permissions(administrator=True)
async def reset_cache(ctx):
    """Rebuild the introduced members cache from intro channel history"""
    guild_id = str(ctx.guild.id)
    config = load_guild_config(guild_id)
    intro_channel_id = config.get('intro_channel_id', 0)

    if intro_channel_id == 0:
        await ctx.send("Please set the introductions channel first using !setintrochannel")
        return

    await ctx.send("Rebuilding cache from intro channel history...")

    # Clear current cache
    guild_data = get_guild_data(guild_id)
    introduced_members = guild_data['introduced']
    introduced_members.clear()

    # Rescan
    await scan_intro_channel_history(guild_id, intro_channel_id)

    # Reload to get updated count
    guild_data = get_guild_data(guild_id)
    introduced_members = guild_data['introduced']

    await ctx.send(f"✅ Cache rebuilt! Now tracking {len(introduced_members)} introduced members.")

@bot.command(name='cleanup')
@commands.has_permissions(administrator=True)
async def cleanup_tracking(ctx):
    """Remove members who left the server from tracking lists"""
    guild_id = str(ctx.guild.id)
    guild_data = get_guild_data(guild_id)
    pending_members = guild_data['pending']
    introduced_members = guild_data['introduced']

    # Clean up pending members
    pending_removed = []
    for user_id in list(pending_members.keys()):
        member = ctx.guild.get_member(int(user_id))
        if not member:
            pending_removed.append(user_id)
            del pending_members[user_id]

    if pending_removed:
        save_guild_pending(guild_id, pending_members)

    # Clean up introduced members
    current_member_ids = {m.id for m in ctx.guild.members}
    introduced_removed = []
    for user_id in list(introduced_members):
        if user_id not in current_member_ids:
            introduced_removed.append(user_id)
            introduced_members.remove(user_id)

    if introduced_removed:
        save_guild_introduced(guild_id, introduced_members)

    # Report
    embed = discord.Embed(title="Cleanup Complete", color=discord.Color.green())
    embed.add_field(name="Pending List", value=f"Removed {len(pending_removed)} members who left", inline=True)
    embed.add_field(name="Introduced List", value=f"Removed {len(introduced_removed)} members who left", inline=True)
    embed.add_field(name="Total Cleaned", value=str(len(pending_removed) + len(introduced_removed)), inline=True)

    await ctx.send(embed=embed)

@bot.command(name='stats')
@commands.has_permissions(administrator=True)
async def show_stats(ctx):
    """Show bot statistics"""
    guild_id = str(ctx.guild.id)
    guild_data = get_guild_data(guild_id)
    config = guild_data['config']
    pending_members = guild_data['pending']
    introduced_members = guild_data['introduced']

    embed = discord.Embed(title="Introduction Bot Statistics", color=discord.Color.blue())

    # Clean up pending members who left the server
    to_remove = []
    for user_id in pending_members.keys():
        member = ctx.guild.get_member(int(user_id))
        if not member:
            to_remove.append(user_id)

    for user_id in to_remove:
        del pending_members[user_id]

    if to_remove:
        save_guild_pending(guild_id, pending_members)

    # Pending members (still in server)
    pending_count = len(pending_members)
    embed.add_field(name="📊 Pending Introductions", value=str(pending_count), inline=True)

    # Introduced members (still in server)
    current_member_ids = {m.id for m in ctx.guild.members if not m.bot}
    introduced_in_server = len(introduced_members & current_member_ids)
    embed.add_field(name="✅ Introduced Members", value=str(introduced_in_server), inline=True)

    # Total members in server
    total_members = len([m for m in ctx.guild.members if not m.bot])
    embed.add_field(name="👥 Total Members", value=str(total_members), inline=True)

    # Show breakdown
    untracked = total_members - pending_count - introduced_in_server
    if untracked > 0:
        embed.add_field(
            name="⚠️ Untracked Members",
            value=f"{untracked} members (use !scanexisting to find them)",
            inline=False
        )

    # Configuration
    config_text = f"Grace Period: {GRACE_PERIOD_HOURS}h\n"
    config_text += f"Reminders: {', '.join([f'{h}h' for h in REMINDER_TIMES])}\n"
    config_text += f"Check Interval: {CHECK_INTERVAL_MINUTES}min\n"

    if BOOSTER_GRACE_HOURS > 0:
        config_text += f"Booster Bonus: +{BOOSTER_GRACE_HOURS}h\n"

    exempt_role_ids = config.get('exempt_role_ids', [])
    if exempt_role_ids:
        config_text += f"Exempt Roles: {len(exempt_role_ids)}\n"

    welcome_role_id = config.get('welcome_role_id', 0)
    if welcome_role_id != 0:
        role = ctx.guild.get_role(welcome_role_id)
        config_text += f"Welcome Role: {role.mention if role else 'Not found'}\n"

    if MIN_INTRO_LENGTH > 0:
        config_text += f"Min Intro Length: {MIN_INTRO_LENGTH} chars\n"

    if REQUIRE_KEYWORDS:
        config_text += f"Required Keywords: {', '.join(REQUIRE_KEYWORDS)}\n"

    embed.add_field(name="⚙️ Configuration", value=config_text, inline=False)

    # Recent activity (if we had a stats file, but we don't yet)
    intro_channel_id = config.get('intro_channel_id', 0)
    embed.set_footer(text=f"Intro Channel: #{bot.get_channel(intro_channel_id).name}" if intro_channel_id != 0 else "Intro channel not set")

    await ctx.send(embed=embed)

@bot.command(name='allo')
async def allo_test(ctx):
    """Test command to verify bot is responding"""
    await ctx.send("Allo! 👋 Bot is working!")

@bot.command(name='commands')
async def show_help(ctx):
    """Show all available commands"""
    embed = discord.Embed(
        title="Allo Bot - Command Reference",
        description="Introduction enforcement bot with reminders and auto-kick",
        color=discord.Color.blue()
    )

    # Basic Commands
    embed.add_field(
        name="🧪 Testing",
        value="`!allo` - Test if bot is responding",
        inline=False
    )

    # Setup Commands
    setup_cmds = (
        "`!setintrochannel #channel` - Set introductions channel\n"
        "`!setmodlog #channel` - Set mod log channel\n"
        "`!setwelcomerole @role` - Set role to assign after intro"
    )
    embed.add_field(name="⚙️ Setup Commands (Admin)", value=setup_cmds, inline=False)

    # Management Commands
    manage_cmds = (
        "`!checkpending` - View members pending introduction\n"
        "`!scanexisting` - Find existing members without intros\n"
        "`!trackexisting <hours>` - Start tracking existing members\n"
        "`!stats` - View bot statistics and config"
    )
    embed.add_field(name="📊 Management Commands (Admin)", value=manage_cmds, inline=False)

    # Override Commands
    override_cmds = (
        "`!markintroduced @user` - Manually mark user as introduced\n"
        "`!untrack @user` - Stop tracking without kicking\n"
        "`!cleanup` - Remove left members from tracking\n"
        "`!resetcache` - Rebuild intro cache from history"
    )
    embed.add_field(name="🔧 Override Commands (Admin)", value=override_cmds, inline=False)

    # Current Config
    config_info = (
        f"Grace Period: **{GRACE_PERIOD_HOURS}h**\n"
        f"Reminders: **{', '.join([f'{h}h' for h in REMINDER_TIMES])}**\n"
        f"Kicking: **{'✅ Enabled' if ENABLE_KICKING else '🛡️ Disabled (Safety)'}**\n"
        f"Dry Run: **{'🔍 Yes (No kicks)' if DRY_RUN_MODE else '❌ No (Live)'}**"
    )
    embed.add_field(name="⚡ Current Settings", value=config_info, inline=False)

    embed.set_footer(text="Use !stats for detailed statistics | All admin commands require Administrator permission")

    await ctx.send(embed=embed)

@bot.command(name='scanexisting')
@commands.has_permissions(administrator=True)
async def scan_existing(ctx, page: int = 1):
    """Scan existing members to find who hasn't posted in introductions"""
    guild_id = str(ctx.guild.id)
    guild_data = get_guild_data(guild_id)
    config = guild_data['config']
    pending_members = guild_data['pending']
    introduced_members = guild_data['introduced']

    intro_channel_id = config.get('intro_channel_id', 0)
    if intro_channel_id == 0:
        await ctx.send("Please set the introductions channel first using !setintrochannel")
        return

    await ctx.send("Scanning all members using cached data...")

    intro_channel = bot.get_channel(intro_channel_id)
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

    # Pagination
    per_page = 25
    total_pages = (len(unintroduced) + per_page - 1) // per_page  # Ceiling division
    requested_page = page
    page = max(1, min(page, total_pages))  # Clamp to valid range

    # Show warning if page was out of range
    if requested_page != page:
        if requested_page < 1:
            await ctx.send(f"⚠️ Page {requested_page} doesn't exist. Showing page 1 instead.")
        else:
            await ctx.send(f"⚠️ Page {requested_page} doesn't exist (only {total_pages} page{'s' if total_pages > 1 else ''}). Showing page {total_pages} instead.")

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_members = unintroduced[start_idx:end_idx]

    # Create embed showing results
    title = "Unintroduced Existing Members"
    if total_pages > 1:
        title += f" (Page {page}/{total_pages})"

    embed = discord.Embed(
        title=title,
        description=f"Found {len(unintroduced)} members who haven't posted in {intro_channel.mention}",
        color=discord.Color.red()
    )

    # Show members for this page
    member_list = "\n".join([f"• {member.mention} ({member.name})" for member in page_members])
    embed.add_field(name="Members", value=member_list or "None", inline=False)

    if total_pages > 1:
        embed.set_footer(text=f"Page {page}/{total_pages} • Use !scanexisting {page+1 if page < total_pages else 1} for next page")

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
    guild_id = str(ctx.guild.id)
    guild_data = get_guild_data(guild_id)
    config = guild_data['config']
    pending_members = guild_data['pending']
    introduced_members = guild_data['introduced']

    intro_channel_id = config.get('intro_channel_id', 0)
    if intro_channel_id == 0:
        await ctx.send("Please set the introductions channel first using !setintrochannel")
        return

    if grace_hours is None:
        await ctx.send(f"Please specify how many hours to give them.\nExample: `!trackexisting 72`")
        return

    if grace_hours < 1 or grace_hours > 168:
        await ctx.send("Grace period must be between 1 and 168 hours (1 week).")
        return

    await ctx.send("Adding unintroduced members to tracking list...")

    intro_channel = bot.get_channel(intro_channel_id)
    if not intro_channel:
        await ctx.send("Could not find the introductions channel.")
        return

    # Use cached introduced_members (already loaded from persistent storage)
    # Add unintroduced members to tracking
    added_count = 0
    current_time = datetime.utcnow()

    for member in ctx.guild.members:
        if member.bot:
            continue
        if member.id not in introduced_members and str(member.id) not in pending_members:
            # Initialize with dynamic reminder keys based on REMINDER_TIMES
            # Store join_time as NOW and custom grace_hours for this batch
            reminder_data = {
                'join_time': current_time.isoformat(),
                'grace_hours': grace_hours  # Custom grace period for trackexisting
            }
            for reminder_hour in REMINDER_TIMES:
                reminder_data[f'reminded_{reminder_hour}'] = False

            pending_members[str(member.id)] = reminder_data
            added_count += 1

            # Send them a DM notification (only if background checks are enabled)
            if ENABLE_BACKGROUND_CHECKS:
                try:
                    await member.send(
                        f"Hello! Our server now requires all members to post an introduction in {intro_channel.mention}. "
                        f"You have **{grace_hours} hours** to introduce yourself or you will be removed from the server. "
                        f"Thank you for understanding!"
                    )
                except discord.Forbidden:
                    print(f"[{ctx.guild.name}] Could not send DM to {member.name}")
            else:
                print(f"[{ctx.guild.name}] Skipped DM to {member.name} (ENABLE_BACKGROUND_CHECKS=False)")

    save_guild_pending(guild_id, pending_members)

    # Build response message
    response = f"Added {added_count} existing members to the tracking list. "
    if ENABLE_BACKGROUND_CHECKS:
        response += f"They have {grace_hours} hours to introduce themselves."
    else:
        response += f"⚠️ DMs NOT sent (ENABLE_BACKGROUND_CHECKS=False). They have {grace_hours} hours configured."

    await ctx.send(response)

# Run the bot
if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')

    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set")
        print("Please set it with: export DISCORD_BOT_TOKEN='your_token_here'")
    else:
        print("Starting Allo Bot with multi-server support...")
        print("Use !setintrochannel in each server to configure the bot.")
        bot.run(TOKEN)
