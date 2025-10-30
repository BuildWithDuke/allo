module.exports = {
  apps: [{
    name: 'allo-bot',
    script: 'intro_bot.py',
    interpreter: 'python3',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',
    env: {
      NODE_ENV: 'production'
    },
    error_file: './logs/err.log',
    out_file: './logs/out.log',
    log_file: './logs/combined.log',
    time: true,
    // Restart the bot at 3 AM daily for maintenance
    cron_restart: '0 3 * * *',
    // Wait 10 seconds before considering the app as online
    min_uptime: '10s',
    // Max 3 restarts within 1 min before stopping
    max_restarts: 3,
    restart_delay: 4000
  }]
};
