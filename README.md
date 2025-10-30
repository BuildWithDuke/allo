# Discord Introduction Bot

A Discord bot that automatically kicks members who don't post in an introductions channel within a specified time period.

## Features

- Tracks new members when they join
- Monitors the introductions channel for their first message
- Automatically kicks members who don't introduce themselves within the grace period
- Sends DM reminders to new members
- Admin commands to check pending introductions
- Persistent storage of pending members

## Setup

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section and click "Add Bot"
4. Under "Privileged Gateway Intents", enable:
   - SERVER MEMBERS INTENT
   - MESSAGE CONTENT INTENT
5. Copy the bot token (you'll need this later)

### 2. Invite Bot to Your Server

1. Go to OAuth2 > URL Generator
2. Select scopes: `bot`
3. Select bot permissions:
   - Kick Members
   - Send Messages
   - Read Message History
   - Add Reactions
4. Copy the generated URL and open it in your browser to invite the bot

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the Bot

Set your bot token as an environment variable:

```bash
export DISCORD_BOT_TOKEN='your_token_here'
```

### 5. Get Your Intro Channel ID

1. Enable Developer Mode in Discord (Settings > Advanced > Developer Mode)
2. Right-click your introductions channel and click "Copy ID"
3. Edit `intro_bot.py` and replace `INTRO_CHANNEL_ID = 0` with your channel ID

Or use the `!setintrochannel` command after starting the bot.

### 6. Run the Bot

```bash
python intro_bot.py
```

## Configuration

Edit these variables in `intro_bot.py`:

- `INTRO_CHANNEL_ID`: The channel where members must introduce themselves
- `GRACE_PERIOD_HOURS`: How long members have to post (default: 24 hours)
- `CHECK_INTERVAL_MINUTES`: How often to check for violations (default: 60 minutes)

## Commands

- `!checkpending` - View members who haven't introduced themselves yet (Admin only)
- `!setintrochannel #channel` - Set the introductions channel (Admin only)

## How It Works

1. When a member joins, they're added to a pending list
2. The bot sends them a DM reminder
3. When they post in the intro channel, they're removed from the pending list
4. Every CHECK_INTERVAL_MINUTES, the bot checks if anyone has exceeded the grace period
5. Members who haven't introduced themselves in time are kicked

## Required Bot Permissions

- Kick Members
- Send Messages
- Read Message History
- Add Reactions

## Notes

- The bot ignores other bots
- Pending members are saved to `pending_members.json` for persistence
- The bot reacts with ✅ when someone posts their introduction
