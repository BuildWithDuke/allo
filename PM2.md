# PM2 Setup for Allo Bot

## Quick Start

```bash
# Start the bot with PM2
pm2 start ecosystem.config.js

# Or start directly with Python interpreter
pm2 start intro_bot.py --name allo-bot --interpreter python3

# Save PM2 process list (persist across reboots)
pm2 save
pm2 startup
```

## Useful PM2 Commands

```bash
# View logs
pm2 logs allo-bot

# Monitor status
pm2 status
pm2 monit

# Restart bot
pm2 restart allo-bot

# Stop bot
pm2 stop allo-bot

# Delete from PM2
pm2 delete allo-bot

# View detailed info
pm2 info allo-bot
```

## Environment Variables

Make sure to export your Discord token before starting:

```bash
export DISCORD_BOT_TOKEN='your_token_here'
```

Or use PM2's ecosystem file env settings.
