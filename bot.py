import bot_info
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, LOG_GROUP_ID, SUPPORT_GROUP_ID
from database import ensure_indexes

app = Client(
    "UnityBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)


async def _check_group(client, group_id: int, label: str):
    """Send a startup ping to verify the bot can reach a group."""
    if not group_id:
        print(f"[STARTUP] {label} is not set — skipping.")
        return
    try:
        await client.send_message(
            chat_id=group_id,
            text=f"✅ <b>Bot Started</b> — {label} সংযোগ ঠিক আছে।",
            parse_mode="html",
        )
        print(f"[STARTUP] {label} ({group_id}) ✓ reachable")
    except Exception as e:
        print(f"[STARTUP-ERROR] {label} ({group_id}) ✗ unreachable: {e!r}")
        print(f"[STARTUP-ERROR] নিশ্চিত করুন bot ওই group-এ Admin হিসেবে আছে।")


async def main():
    await ensure_indexes()
    await app.start()

    me = await app.get_me()
    bot_info.BOT_USERNAME = me.username or ""
    bot_info.BOT_ID = me.id

    print(f"Bot Started — @{bot_info.BOT_USERNAME} (ID: {bot_info.BOT_ID})")

    # Connectivity checks for both groups
    await _check_group(app, LOG_GROUP_ID,     "Monitor Group (LOG_CHANNEL_ID)")
    await _check_group(app, SUPPORT_GROUP_ID, "Control/Support Group (SUPPORT_GROUP_ID)")

    await idle()
    await app.stop()


app.run(main())
