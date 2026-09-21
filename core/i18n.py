"""机器人面向用户文本的轻量国际化支持。"""
from __future__ import annotations

import os
from typing import Any

DEFAULT_LOCALE = os.getenv("BOT_LOCALE", "zh_CN")

TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh_CN": {
        "start": "[START] **欢迎使用本地合集下载机器人！**\n\n"
        "闲置时直接发送 Telegram 链接或单个媒体，会自动下载到 downloads/。\n"
        "批量收集使用 /collect <合集名称>，发送完成后用 /end 开始下载。\n\n使用 /help 查看详情。",
        "help": "[INFO] **本地合集下载机器人 - 帮助**\n\n"
        "**命令：**\n"
        "• /start - 显示开始说明\n"
        "• /help - 显示此帮助信息\n"
        "• /stats - 查看性能和磁盘统计\n\n"
        "**本地合集：**\n"
        "• /collect <合集名称> [消息链接] - 收集；附链接时立即下载单项\n"
        "• /end - 结束收集并下载所有项目\n"
        "• /resume [合集名称] - 重启后继续未完成下载\n\n"
        "闲置时直接发送 Telegram 链接或单个文件，会自动下载到 downloads/。\n\n"
        "**支持的链接格式：**\n"
        "• https://t.me/channel/123（公开频道）\n"
        "• https://t.me/c/123456/789（私有频道）\n\n"
        "**说明：**访问私有频道需要配置 userbot。",
        "private_access": "[WARNING] **需要私有频道访问权限**\n\n"
        "这是私有频道，但尚未配置 userbot。\n\n**配置步骤：**\n"
        "1. 使用 scripts/generate_session.py 生成会话\n"
        "2. 将生成的 SESSION 添加到 .env 文件\n3. 重启机器人",
        "stats": "[METRICS] **性能统计**\n\n"
        "**下载次数：**{downloads}\n**已下载数据：**{downloaded} MB\n"
        "**平均下载速度：**{download_speed} MB/s\n**失败操作：**{failed}\n"
        "**重试次数：**{retries}\n**运行时间：**{uptime}s\n\n"
        "**磁盘使用：**\n• 文件数：{files}\n• 大小：{size:.1f} MB\n"
        "• 可用空间：{free_gb:.1f} GB",
        "low_disk": "\n\n[WARNING] 磁盘可用空间不足。",
        "stats_failed": "[ERROR] 无法获取统计信息：{error}",
        "collect_usage": "[INFO] 用法：/collect <合集名称> [Telegram 消息链接]\n"
        "多项收集仍可先发送 /collect <合集名称>，最后发送 /end。",
        "collect_started": "[OK] **已开始收集合集：{name}**\n\n"
        "请继续发送视频、图片、文件或 Telegram 消息链接。\n"
        "发送 /end 后将统一下载到：`{directory}`",
        "collect_start_failed": "[ERROR] 无法开始收集：{error}",
        "collect_none": "[INFO] 没有可操作的合集。请先使用 /collect <合集名称>。",
        "collect_downloading": "[INFO] 该合集正在下载中，请稍候。",
        "collect_already_ended": "[INFO] 该合集已结束。若下载被中断，请使用 /resume 继续未完成项目。",
        "collect_no_items": "[INFO] 合集中没有待下载项目。",
        "collect_ending": "[DOWNLOAD] **正在下载本地合集**\n\n待处理：{total} 项\n目录：`{directory}`",
        "collect_resuming": "[DOWNLOAD] **正在继续本地合集下载**\n\n待处理：{total} 项\n目录：`{directory}`",
        "collect_item_added": "[OK] 已加入合集（第 {sequence} 项）。",
        "collect_invalid_link": "[WARNING] 未识别的 Telegram 消息链接，已忽略。",
        "collect_text_ignored": "[INFO] 纯文本不会保存，已忽略。",
        "single_item_started": "[DOWNLOAD] **已开始单项下载**\n\n目录：`{directory}`",
        "single_item_progress": "[DOWNLOAD] **正在下载单项**\n\n目录：`{directory}`",
        "single_item_complete": "[{result}] **单项下载{state}**\n\n目录：`{directory}`\n{details}",
        "collect_progress": "[DOWNLOAD] **正在下载合集：{name}**\n\n进度：{done}/{total}\n"
        "成功：{success}，跳过：{skipped}，失败：{failed}",
        "collect_complete": "[SUCCESS] **合集下载完成：{name}**\n\n目录：`{directory}`\n"
        "下载成功：{success}\n跳过：{skipped}\n下载失败：{failed}\n"
        "规则处理成功：{processed}\n未命中规则：{unmatched}\n规则处理失败：{processing_failed}",
        "collect_failed": "[ERROR] 合集下载任务失败：{error}",
    }
}


def get_locale(source: Any = None) -> str:
    language = getattr(getattr(source, "from_user", None), "language_code", None)
    if language and language.replace("-", "_").lower().startswith("zh"):
        return "zh_CN"
    return DEFAULT_LOCALE if DEFAULT_LOCALE in TRANSLATIONS else "zh_CN"


def tr(source: Any, key: str, /, **kwargs: Any) -> str:
    text = TRANSLATIONS.get(get_locale(source), TRANSLATIONS["zh_CN"]).get(key, key)
    return text.format(**kwargs)
