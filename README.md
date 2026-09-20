# Telegram 本地合集下载机器人

使用 Pyrogram 构建的单用户本地媒体下载机器人。收集视频、图片、文件或 Telegram 消息链接后，统一保存到本地合集目录。

## 功能与命令

| 命令 | 说明 |
| --- | --- |
| `/start`、`/help` | 查看使用说明 |
| `/collect <合集名称>` | 开始收集媒体或消息链接到本地合集 |
| `/end` | 结束收集并下载合集中的全部项目 |
| `/resume` | 重启后继续未完成的合集下载 |
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

Compose 默认使用 GHCR 上的 `latest` 镜像；部署指定版本时可设置 `IMAGE_TAG`，例如 `IMAGE_TAG=1.2.3 docker compose pull && IMAGE_TAG=1.2.3 docker compose up -d`。如需从当前源码构建，可执行 `docker build -t tg-dl-bot:local .` 后自行调整 Compose 镜像引用。Dockerfile 使用 `uv` 按 `uv.lock` 执行 frozen 安装；依赖层与应用代码分开复制以复用构建缓存。

运行时下载、会话和诊断文件位于 `downloads/`、`sessions/`、`attached_assets/`，均不会提交到 Git。健康检查服务仅供容器内部使用，不映射到宿主机端口。

### 本地合集下载

使用 `/collect <合集名称>` 开始后，向机器人发送或转发视频、图片、文件，或发送 Telegram 消息链接；发送 `/end` 后，机器人会将媒体下载到 `downloads/<合集名称>/`，不会回传原始媒体。合集状态保存在该目录的隐藏元数据文件中；机器人重启后使用 `/resume` 恢复未完成下载。

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
