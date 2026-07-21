"""
Monitor join requests for the required group.
Bot does NOT auto-approve — it only logs the request to the monitor group.
Admin must manually approve/decline from the group.
"""

from pyrogram import Client, filters, enums

from config import REQUIRED_GROUP_ID, LOG_GROUP_ID


@Client.on_chat_join_request(
    filters.chat(REQUIRED_GROUP_ID) if REQUIRED_GROUP_ID else filters.chat([])
)
async def observe_join_request(client, join_request):
    """Log every join request to the monitor group — do NOT approve."""
    if not LOG_GROUP_ID:
        return

    user = join_request.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else "N/A"
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"

    try:
        await client.send_message(
            chat_id=LOG_GROUP_ID,
            text=(
                "🔔 <b>নতুন Join Request</b>\n\n"
                f"👤 Name: {name}\n"
                f"🔖 Username: {username}\n"
                f"🆔 ID: <code>{user_id}</code>\n\n"
                "⚠️ Bot approve করবে না — Admin manually করবে।"
            ),
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        print(f"[LOG-SEND-FAILED] join_approve.py (chat_id={LOG_GROUP_ID}): {e!r}")
