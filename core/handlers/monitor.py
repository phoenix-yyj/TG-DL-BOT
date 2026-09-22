"""Commands for inspecting automatic chat monitoring."""
from pyrogram.types import Message


async def monitor_command(client, message: Message) -> None:
    from ..bot import auto_monitor, safe_execute_send

    if not auto_monitor:
        text = "[INFO] 自动群聊监听未启用（需要 AUTO_DOWNLOAD_ENABLED=true 和 SESSION）。"
    else:
        lines = [f"[AUTO_MONITOR] 已配置 {len(auto_monitor.rules)} 个群聊："]
        for chat_id, rule in auto_monitor.rules.items():
            count = len(auto_monitor.store.items_for_chat(int(chat_id)))
            lines.append(f"• {rule['name']} ({chat_id})：本地记录 {count} 条")
        text = "\n".join(lines)
    await safe_execute_send(message.chat.id, message.reply_text, text)
