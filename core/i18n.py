"""机器人面向用户文本的轻量国际化支持。

不依赖系统 locale 或编译后的 ``.mo`` 文件，便于在 Docker 中运行；新增语言只需在
``TRANSLATIONS`` 中补充相同的消息键即可。命令名不是可翻译内容，始终保持 Telegram
注册的英文命令。
"""

from __future__ import annotations

import os
from typing import Any


DEFAULT_LOCALE = os.getenv("BOT_LOCALE", "zh_CN")


TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh_CN": {
        "start": "[START] **欢迎使用 Telegram 消息保存机器人！**\n\n"
        "[OK] 机器人运行正常。\n\n"
        "**常用命令：**\n"
        "• /download <链接> - 下载单条消息\n"
        "• /batch - 开始批量处理\n"
        "• /help - 查看全部命令\n"
        "• /test - 测试机器人功能\n\n"
        "**状态：**所有系统运行正常！\n\n"
        "向我发送一条 Telegram 消息链接即可开始。",
        "help": "[INFO] **Telegram 消息保存机器人 - 帮助**\n\n"
        "**基础命令：**\n"
        "• /start - 启动机器人\n"
        "• /test - 测试机器人功能\n"
        "• /help - 显示此帮助信息\n"
        "• /speed - 运行网络测速\n"
        "• /stats - 查看性能和磁盘统计\n"
        "• /cleanup - 删除旧下载文件\n\n"
        "**下载命令：**\n"
        "• /download <链接> - 下载单条消息\n"
        "• 直接发送任意 Telegram 消息链接 - 下载该消息\n\n"
        "**批量命令：**\n"
        "• /batch - 开始批量处理（并行模式）\n"
        "• /batch_status - 查看批量进度\n"
        "• /batch_pause - 暂停当前批量任务\n"
        "• /batch_resume - 继续已暂停的批量任务\n"
        "• /batch_cancel - 取消当前批量任务\n\n"
        "**通用：**\n"
        "• /cancel - 取消当前操作\n\n"
        "**支持的链接格式：**\n"
        "• https://t.me/channel/123（公开频道）\n"
        "• https://t.me/c/123456/789（私有频道）\n\n"
        "**说明：**访问私有频道需要配置 userbot。",
        "test": "[OK] **测试成功！**\n\n机器人可以正常响应命令。",
        "cancel": "[OK] **操作已取消**\n\n所有当前操作均已停止。",
        "download_in_progress": "[WARNING] **下载进行中**\n\n请等待当前下载完成。",
        "download_prompt": "[DOWNLOAD] **单条下载**\n\n请发送要下载的消息链接。\n\n"
        "**示例：**\n• https://t.me/channel/123\n• https://t.me/c/123456/789\n\n"
        "或使用：/download <链接>",
        "invalid_link": "[ERROR] **链接格式无效**\n\n"
        "**支持的格式：**\n• https://t.me/channel/123（公开频道）\n"
        "• https://t.me/c/123456/789（私有频道）\n\n请检查链接后重试。",
        "private_access": "[WARNING] **需要私有频道访问权限**\n\n"
        "这是私有频道，但尚未配置 userbot。\n\n**配置步骤：**\n"
        "1. 使用 scripts/generate_session.py 生成会话\n"
        "2. 将生成的 SESSION 添加到 .env 文件\n3. 重启机器人\n\n如需帮助请联系管理员。",
        "fetching": "[SEARCH] **正在获取消息…**",
        "message_not_found": "[ERROR] **消息不存在或已被删除**",
        "download_complete": "[SUCCESS] **下载已完成！**",
        "processing_failed": "[ERROR] **处理失败**：{error}",
        "batch_setup": "[INFO] **批量处理设置**\n\n第 1 步：请发送作为起点的**第一条消息链接**。\n\n"
        "**支持的格式：**\n• https://t.me/channel/123（公开频道）\n"
        "• https://t.me/c/123456/789（私有频道）\n\n"
        "**说明：**机器人将从该位置开始按顺序下载消息。\n\n发送 /cancel 可取消设置。",
        "no_active_batch": "[INFO] **没有正在进行的批量任务**\n\n使用 /batch 开始新的批量任务。",
        "batch_running": "[WARNING] **批量任务进行中**\n\n当前进度：{current}/{total}\n"
        "状态：{state}\n\n使用 /batch_status 查看进度\n使用 /batch_cancel 取消当前任务",
        "batch_status": "[METRICS] **批量任务状态**\n\n**进度：**{current}/{total} ({percent:.1f}%)\n"
        "**状态：**{state}\n**已用时间：**{elapsed}\n**最后处理：**消息 {last_id}\n\n",
        "batch_controls_running": "**操作：**\n• /batch_pause - 暂停任务\n• /batch_cancel - 取消任务",
        "batch_controls_paused": "**操作：**\n• /batch_resume - 继续任务\n• /batch_cancel - 取消任务",
        "batch_completed": "[SUCCESS] **批量任务已成功完成！**",
        "batch_was_cancelled": "[WARNING] **批量任务已取消**",
        "batch_paused": "[OK] **批量任务已暂停**\n\n使用 /batch_resume 继续，或使用 /batch_cancel 取消。",
        "no_batch_to_pause": "[WARNING] **没有可暂停的批量任务**\n\n使用 /batch 开始新的批量任务。",
        "no_paused_batch": "[WARNING] **没有已暂停的批量任务**\n\n使用 /batch 开始新的批量任务。",
        "batch_resumed": "[OK] **批量任务已继续**\n\n使用 /batch_status 查看进度。",
        "batch_resume_failed": "[ERROR] **无法继续批量任务**\n\n请重试或开始新的批量任务。",
        "batch_cancelled": "[OK] **批量任务已取消**\n\n所有操作均已停止。使用 /batch 开始新的批量任务。",
        "no_operation_to_cancel": "[INFO] **没有可取消的活动操作**",
        "speed_failed": "[ERROR] 测速失败：{error}",
        "cleanup_start": "[INFO] **正在清理旧文件…**",
        "cleanup_none": "[INFO] **没有可清理的文件**\n\n下载目录为空。",
        "cleanup_complete": "[SUCCESS] **清理完成**\n\n**已删除文件：**{cleaned}\n"
        "**剩余文件：**{total_files}\n**总大小：**{size:.1f} MB\n**可用空间：**{free_gb:.1f} GB",
        "cleanup_failed": "[ERROR] 清理失败：{error}",
        "stats": "[METRICS] **性能统计**\n\n"
        "**下载次数：**{downloads}\n**上传次数：**{uploads}\n"
        "**已下载数据：**{downloaded} MB\n**已上传数据：**{uploaded} MB\n"
        "**平均下载速度：**{download_speed} MB/s\n**平均上传速度：**{upload_speed} MB/s\n"
        "**成功率：**{success_rate}%\n**失败操作：**{failed}\n**重试次数：**{retries}\n"
        "**运行时间：**{uptime}s\n\n**下载管理器：**\n• 最大并发：{max_concurrent}\n"
        "• 活动任务：{active_tasks}\n• 可用槽位：{available_slots}\n\n**磁盘使用：**\n"
        "• 文件数：{files}\n• 大小：{size:.1f} MB\n• 可用空间：{free_gb:.1f} GB",
        "low_disk": "\n\n[WARNING] 磁盘可用空间不足！请使用 /cleanup",
        "stats_failed": "[ERROR] 无法获取统计信息：{error}",
    }
}


def get_locale(source: Any = None) -> str:
    """根据 Telegram 用户语言选择目录；未支持语言使用默认语言。"""
    language = getattr(getattr(source, "from_user", None), "language_code", None)
    if language:
        normalized = language.replace("-", "_").lower()
        if normalized.startswith("zh"):
            return "zh_CN"
    return DEFAULT_LOCALE if DEFAULT_LOCALE in TRANSLATIONS else "zh_CN"


def tr(source: Any, key: str, /, **kwargs: Any) -> str:
    """返回按用户语言本地化的文本，并支持命名占位符。"""
    # 中文是当前默认语言；缺失键显式保留键名，方便开发阶段发现漏翻。
    text = TRANSLATIONS.get(get_locale(source), TRANSLATIONS["zh_CN"]).get(key, key)
    return text.format(**kwargs)
