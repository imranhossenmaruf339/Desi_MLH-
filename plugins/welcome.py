from pyrogram import Client, filters, enums

from config import LOG_GROUP_ID


@Client.on_message(filters.new_chat_members & filters.group)
async def on_new_chat_members(client, message):
    """
    - When the bot itself is added to a group → notify the monitor group.
    - When a real user joins → send the welcome message in the group.
    """
    import bot_info
    from plugins.start import WELCOME_TEXT, _make_welcome_keyboard

    me_id = bot_info.BOT_ID

    for member in message.new_chat_members:

        # ── Bot was added to a group ──────────────────────────────────────────
        if member.id == me_id:
            added_by = message.from_user
            if added_by:
                adder_name = added_by.first_name or added_by.username or "Unknown"
                adder_tag = f"@{added_by.username}" if added_by.username else "N/A"
                adder_id = added_by.id
            else:
                adder_name = adder_tag = "Unknown"
                adder_id = "N/A"

            group_title = message.chat.title or "Unknown Group"
            group_id = message.chat.id

            try:
                await client.send_message(
                    chat_id=LOG_GROUP_ID,
                    text=(
                        "🤖 <b>Bot Added to a Group</b>\n\n"
                        f"📌 Group: <b>{group_title}</b>\n"
                        f"🆔 Group ID: <code>{group_id}</code>\n\n"
                        f"👤 Added By: {adder_name}\n"
                        f"🔖 Username: {adder_tag}\n"
                        f"🆔 User ID: <code>{adder_id}</code>"
                    ),
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
            continue   # no welcome needed for the bot itself

        # ── Skip other bots ───────────────────────────────────────────────────
        if member.is_bot:
            continue

        # ── Real user joined → send welcome ───────────────────────────────────
        name = member.first_name or member.username or "Friend"
        keyboard = _make_welcome_keyboard(bot_info.BOT_USERNAME) if bot_info.BOT_USERNAME else None

        try:
            await message.reply_text(
                WELCOME_TEXT.format(name=name),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=keyboard,
            )
        except Exception:
            pass
