# Telegram 本地合集下载机器人

使用 Pyrogram 构建的单用户本地媒体下载机器人。收集视频、图片、文件或 Telegram 消息链接后，统一保存到本地合集目录。

## 功能与命令

| 命令 | 说明 |
| --- | --- |
| `/start`、`/help` | 查看使用说明 |
| `/collect <合集名称> [消息链接]` | 开始收集；附单个 Telegram 消息链接时自动下载 |
| `/end` | 结束收集并下载合集中的全部项目 |
| `/resume` | 重启后继续未完成的合集下载 |
| `/queue` | 查看全局活动与等待中的下载 |
| `/cancel [合集名称]` | 取消合集任务，未完成项可恢复 |
| `/stats` | 查看传输与磁盘统计 |

## 语言

机器人回复默认使用简体中文，命令名保持不变（例如 `/help`、`/collect`）。
在 `.env` 中设置 `BOT_LOCALE=zh_CN` 可显式指定默认语言；用户 Telegram 语言为中文时也会自动使用简体中文。翻译文案集中在 `core/i18n.py`，新增语言时按相同消息键补充词条即可。

## 前置条件

- Python 3.11+，或 Docker 与 Docker Compose。
- 从 [my.telegram.org](https://my.telegram.org) 获取 `API_ID` 和 `API_HASH`。
- 从 [@BotFather](https://t.me/BotFather) 获取 `BOT_TOKEN`。
- 在 `OWNER_USER_ID` 中填写自己的 Telegram 数字用户 ID；未配置时机器人拒绝启动。
- 私有频道访问可选配置 `SESSION`。

## 配置与启动

```sh
cp .env.example .env
# 编辑 .env，填写 API_ID、API_HASH、BOT_TOKEN
```

本地运行：

```sh
uv sync --no-dev
uv run --no-sync python main.py
```

Docker Compose（推荐的部署方式）：

```sh
docker compose pull
docker compose up -d
# 或使用部署脚本（兼容旧版 Compose）：./scripts/deploy-compose.sh
docker compose logs -f
```

在 Linux 服务器上也可以下载并运行初始化脚本。默认会在执行命令时的当前目录下创建 `tg-dl-bot/`：

```sh
curl -fsSL https://raw.githubusercontent.com/phoenix-yyj/TG-DL-BOT/main/scripts/install.sh | sh
```

脚本会下载 Compose 配置和 `.env.example`、仅在 `.env` 不存在时生成配置文件，并创建 `downloads/`、`sessions/`、`attached_assets/`。填写 `.env` 后再按提示拉取镜像并启动。

Compose 默认使用 GHCR 上的 `latest` 镜像；部署指定版本时可设置 `IMAGE_TAG`，例如 `IMAGE_TAG=1.2.3 docker compose pull && IMAGE_TAG=1.2.3 docker compose up -d`。如需从当前源码构建，可执行 `docker build -t tg-dl-bot:local .` 后自行调整 Compose 镜像引用。Dockerfile 使用 `uv` 按 `uv.lock` 执行 frozen 安装；依赖层与应用代码分开复制以复用构建缓存。

运行时下载、会话和诊断文件位于 `downloads/`、`sessions/`、`attached_assets/`，均不会提交到 Git。健康检查服务仅供容器内部使用，不映射到宿主机端口。

### 本地合集下载

闲置时直接发送 Telegram 消息链接，或上传/转发一个媒体文件，机器人会自动开始下载到 `downloads/` 根目录，无需输入命令或指定合集名称。多项内容使用 `/collect <合集名称>` 开始收集，逐项发送或转发媒体及链接，最后发送 `/end`。所有单项和合集下载共享全局轮转队列；并发默认立即使用配置上限，遇到 FloodWait/网络超时才降速，并在健康冷却期后自动恢复，降低普通坏链接导致长期串行的风险。可用 `/queue` 查看队列，用 `/cancel [合集名称]` 取消任务，之后用 `/resume [合集名称]` 恢复未完成项。合集清单使用 JSONL 变更日志并定期生成原子检查点，兼容已有 JSON 清单。

### 压缩包处理

容器内置 7-Zip，支持 ZIP、7z、RAR 解包。首次配置可将 `docs/operations/archive_rules.example.json` 复制为 `attached_assets/archive_rules.json`，该目录已通过 Compose 挂载；初始化脚本会把模板放在 `attached_assets/archive_rules.example.json`。也可用 `ARCHIVE_RULES_PATH` 指定其他路径。配置文件按顺序定义通用密码表 `passwords` 和群规则 `rules`：`chat_title` 与 Telegram 来源群/频道标题精确匹配；同标题多条规则依序回退，直到某条 `steps` 全部完成。

步骤支持 `extract`（可选 `passwords` 覆盖通用密码表）、`rename_extension`（`from`/`to`）和 `recompress`（`format` 为 `zip` 或 `7z`，可选 `output`）。重复声明 `extract` 可处理多层压缩包；例如外层解包后先把 `.dat` 改为 `.7z`，再声明一次解包。RAR 可解包，但 7-Zip 不支持创建 RAR，因此解密后的 RAR 单项下载会输出未加密 ZIP。

直接发送的单个压缩包会按密码表尝试解包并重新压缩为无密码包；链接下载则按来源标题应用群规则。原始下载保留，处理结果单独存放在 `*_processed/` 目录；每个合集清单记录规则状态、命中规则、产物及失败原因。未命中规则的链接压缩包保持原样。

## 测试

```sh
uv sync
uv run pytest
```

## 文档

- [私有频道 Session 配置](docs/operations/private-channel-access.md)
- [FloodWait 与限流机制](docs/architecture/flood-wait-handling.md)
- [历史实现与部署记录](docs/archive/)

## 安全说明

不要提交 `.env`、Telegram session、下载内容、运行日志或上传恢复 URL。若曾提交过凭据或上传会话，应在对应服务端使其失效并重新生成。
