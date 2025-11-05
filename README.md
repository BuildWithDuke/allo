# Discord Introduction Bot (Allo)

A feature-rich Discord bot that automatically manages member introductions with reminders, validation, role assignment, and comprehensive logging.

## Features

### Core Functionality
- 🌐 **Multi-Server Support**: Use the bot in multiple Discord servers with independent configurations
- 🎯 **Automatic Tracking**: Tracks new members and requires introductions
- ⏰ **Configurable Reminders**: Send multiple reminders at custom intervals (default: 12h)
- 🥾 **Auto-Kick**: Kicks members who don't introduce themselves within grace period (default: 24h)
- 💾 **Persistent Memory**: Per-guild caches of introduced members across bot restarts
- 🔄 **Automatic Scanning**: Scans intro channel history on startup

### Advanced Features
- 🛡️ **Role-Based Exemptions**: Exempt specific roles from intro requirements (staff, VIPs, etc.)
- 🎁 **Booster Perks**: Give server boosters extra time to introduce themselves
- 🎭 **Welcome Roles**: Automatically assign roles when members post introductions
- 📏 **Intro Validation**: Enforce minimum length and required keywords
- 📊 **Mod Logging**: Log all actions to a dedicated mod channel
- 📈 **Statistics**: View bot stats and configuration

### Admin Tools
- ✅ `!markintroduced` - Manually mark members as introduced
- ⏸️ `!untrack` - Stop tracking a member without kicking
- 🔄 `!resetcache` - Rebuild introduced members cache
- 📊 `!stats` - View bot statistics
- 🔍 `!scanexisting` - Find existing members without intros
- 📝 `!trackexisting` - Start tracking existing members

## Quick Start

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section and click "Add Bot"
4. Under "Privileged Gateway Intents", enable:
   - ✅ **SERVER MEMBERS INTENT**
   - ✅ **MESSAGE CONTENT INTENT**
5. Copy the bot token

### 2. Invite Bot to Your Server

1. Go to OAuth2 > URL Generator
2. Select scopes: `bot`
3. Select bot permissions:
   - Kick Members
   - Manage Roles
   - Send Messages
   - Read Message History
   - Add Reactions
4. Copy the generated URL and open it to invite the bot

### 3. Install and Run

```bash
# Clone the repository
git clone https://github.com/BuildWithDuke/allo.git
cd allo

# Install dependencies
pip install -r requirements.txt

# Set bot token
export DISCORD_BOT_TOKEN='your_token_here'

# Run the bot
python intro_bot.py
```

## Configuration

### Multi-Server Support

The bot now supports multiple Discord servers! Each server gets its own configuration and data files:
- `config_GUILDID.json` - Server-specific settings (intro channel, mod log, roles)
- `pending_GUILDID.json` - Members awaiting introduction in this server
- `introduced_GUILDID.json` - Members who have introduced themselves in this server

Use the setup commands in each server to configure the bot independently.

### Per-Server Settings (configured via commands)

Use these commands in each server to configure the bot:
- `!setintrochannel #channel` - Set the introductions channel
- `!setmodlog #channel` - Set the mod log channel (optional)
- `!setwelcomerole @role` - Set role to assign after intro (optional)

### Global Settings (applies to all servers)

Edit these variables at the top of `intro_bot.py`:

```python
GRACE_PERIOD_HOURS = 24           # Hours before kick (default: 24)
CHECK_INTERVAL_MINUTES = 60       # How often to check (default: 60)
REMINDER_TIMES = [12]             # When to send reminders in hours
MIN_INTRO_LENGTH = 0              # Minimum intro characters (0 = disabled)
REQUIRE_KEYWORDS = []             # Required words in intro (empty = disabled)
BOOSTER_GRACE_HOURS = 0           # Extra hours for boosters (0 = disabled)
```

### Safety Settings

```python
ENABLE_KICKING = False            # Set to True to actually kick members
DRY_RUN_MODE = True               # If True, logs kicks but doesn't execute them
ENABLE_BACKGROUND_CHECKS = True   # If False, disables reminder/kick loop (testing mode)
```

**Testing Mode**: Set `ENABLE_BACKGROUND_CHECKS = False` to test bot features (rescanning, commands, role assignment) without sending any reminder DMs or kicks. Perfect for verifying functionality in production before going live!

### Example Configurations

**Strict Server** (200+ char intro, 48h deadline):
```python
GRACE_PERIOD_HOURS = 48
REMINDER_TIMES = [12, 24, 36]
MIN_INTRO_LENGTH = 200
REQUIRE_KEYWORDS = ["name", "age", "location"]
```
Then in Discord: `!setintrochannel #introductions` and `!setwelcomerole @Member`

**Relaxed Server** (no validation, 1 week deadline):
```python
GRACE_PERIOD_HOURS = 168
REMINDER_TIMES = [72, 120]
BOOSTER_GRACE_HOURS = 72  # Boosters get 10 days total
```
Then in Discord: `!setintrochannel #welcome`

**Gaming Community** (role rewards):
```python
# Global settings already configured (24h grace, 12h reminder)
```
Then in Discord:
- `!setintrochannel #introductions`
- `!setwelcomerole @Member`
- `!setmodlog #mod-logs`

## Commands

All commands require Administrator permissions.

### Configuration Commands
- `!setintrochannel #channel` - Set the introductions channel

### Management Commands
- `!checkpending` - View members pending introduction (with time remaining)
- `!scanexisting` - Find existing members without intros
- `!trackexisting <hours>` - Start tracking existing members with custom grace period

### Override Commands
- `!markintroduced @user` - Manually mark user as introduced (assigns role, removes from tracking)
- `!untrack @user` - Stop tracking user without kicking them
- `!resetcache` - Rebuild cache of introduced members from channel history

### Information Commands
- `!stats` - View bot statistics and configuration

## How It Works

### New Member Flow
1. **Member Joins** → Bot checks if they have an exempt role
2. **Added to Tracking** → DM sent with welcome message and deadline
3. **Reminders Sent** → At configured intervals (e.g., 24h, 48h)
4. **Grace Period Expires** → Member kicked if no intro posted
5. **Or Posts Intro** → Removed from tracking, role assigned (if configured)

### Intro Validation
When a member posts in the intro channel:
1. Check minimum length (if enabled)
2. Check required keywords (if enabled)
3. If validation fails → Message deleted, DM sent with requirements
4. If validation passes → ✅ reaction added, role assigned, tracking stopped

### Mod Logging
All actions are logged to the mod channel (if configured):
- 👋 Member join (with grace period)
- ⏰ Reminders sent (with time remaining)
- ✅ Successful introductions
- ⚠️ Kick warnings (before kick)
- ❌ Members kicked
- Manual admin actions

## Required Bot Permissions

- **Kick Members** - To remove non-introduced members
- **Manage Roles** - To assign welcome role
- **Send Messages** - To send DMs and channel messages
- **Read Message History** - To scan intro channel
- **Add Reactions** - To react to introductions
- **View Channels** - To access configured channels

## Files Generated

- `pending_members.json` - Members currently being tracked
- `introduced_members.json` - Cache of all introduced members
- `.gitignore` - Prevents committing sensitive data

## Tips & Best Practices

1. **Set a Mod Log Channel**: Use `MOD_LOG_CHANNEL_ID` to track all bot actions
2. **Test First**: Use `!trackexisting 1` on yourself to test the bot
3. **Exempt Staff**: Add staff role IDs to `EXEMPT_ROLE_IDS`
4. **Reward Boosters**: Set `BOOSTER_GRACE_HOURS` to give them extra time
5. **Use Role Gates**: Assign a "Member" role that unlocks channels
6. **Monitor Pending**: Regularly check `!checkpending` to see who needs reminders

## Troubleshooting

**Bot not tracking members?**
- Ensure `INTRO_CHANNEL_ID` is set correctly
- Check bot has required permissions
- Verify "Server Members Intent" is enabled

**Members not getting kicked?**
- Check bot has "Kick Members" permission
- Bot's role must be higher than target member's highest role
- Check console for error messages

**Roles not being assigned?**
- Verify `WELCOME_ROLE_ID` is correct
- Bot needs "Manage Roles" permission
- Bot's role must be higher than the role it's assigning

**Cache seems wrong?**
- Use `!resetcache` to rebuild from scratch
- Check intro channel permissions (bot needs read history)

## Contributing

Pull requests are welcome! For major changes, please open an issue first.

## License

MIT

## Credits

Built with [discord.py](https://discordpy.readthedocs.io/)
