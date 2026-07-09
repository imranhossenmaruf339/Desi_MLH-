# Telegram Video Sharing Bot

This bot sends random videos from a database with a cooldown system and 12-hour limits. It is designed to be deployed on Railway.

## Features
- Random video delivery via `/video` command.
- 7-day cooldown (won't send the same video to the same user within 7 days).
- 12-hour video limits (resets at 00:00 and 12:00 UTC).
- Automatic video indexing from a specific channel.
- Admin panel for manual video management and user statistics.
- Group support with private message redirection.

## Deployment on Railway
1. Fork/Clone this repository.
2. Create a new project on Railway and connect your GitHub repo.
3. Set the following Environment Variables:
   - `BOT_TOKEN`: Your Telegram Bot Token from @BotFather.
   - `API_ID`: Your Telegram API ID.
   - `API_HASH`: Your Telegram API Hash.
   - `OWNER_ID`: Your Telegram User ID.
   - `MONGO_URI`: Your MongoDB Atlas connection string.
   - `LOG_GROUP_ID`: ID of the group where logs will be sent.
   - `VIDEO_CHANNEL_ID`: ID of the channel to index videos from.
   - `VIP_CHANNEL_ID`: (Optional) ID of the VIP channel for limit unlocks.
   - `VIDEO_DAILY_LIMIT`: (Default: 10) Number of videos per 12-hour window.

## Commands
- `/start`: Start the bot.
- `/help`: Show help menu.
- `/video`: Get a random video.
- `/profile`: View your stats.
- `/stats`: (Admin) View bot statistics.
- `/broadcast`: (Admin) Send a message to all users.
