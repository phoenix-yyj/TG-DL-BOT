# Telegram Message Saver Bot

使用 Pyrogram 构建的 Telegram 下载与转存机器人，支持公开/私有频道消息、批量处理、进度显示和 FloodWait 重试。

## 功能与命令

| 命令 | 说明 |
| --- | --- |
| `/start`、`/help`、`/test` | 查看或验证机器人状态 |
| `/download <t.me 链接>` | 下载单条消息 |
| `/batch` | 按提示批量处理消息 |
| `/batch_status`、`/batch_pause`、`/batch_resume`、`/batch_cancel` | 管理批处理任务 |
| `/cancel` | 取消当前操作 |
| `/speed` | 执行网络测速 |
| `/stats` | 查看传输与磁盘统计 |
| `/cleanup` | 删除 `downloads/` 中超过 24 小时的文件 |

## 前置条件

- Python 3.11+，或 Docker 与 Docker Compose。
- 从 [my.telegram.org](https://my.telegram.org) 获取 `API_ID` 和 `API_HASH`。
- 从 [@BotFather](https://t.me/BotFather) 获取 `BOT_TOKEN`。
- 私有频道访问可选配置 `SESSION`。

## 配置与启动

```sh
cp .env.example .env
# 编辑 .env，填写 API_ID、API_HASH、BOT_TOKEN
```

本地运行：

```sh
python3 -m pip install -r requirements.txt
python3 main.py
```

Docker Compose（推荐的部署方式）：

```sh
docker compose up --build -d
# 或兼容旧版 Compose：./scripts/deploy-compose.sh
docker compose logs -f
```

运行时下载、会话和诊断文件位于 `downloads/`、`sessions/`、`attached_assets/`，均不会提交到 Git。健康检查为 `http://localhost:3000/health`。

## 测试

```sh
python3 -m pip install -r requirements-dev.txt
pytest
```

## 文档

- [私有频道 Session 配置](docs/operations/private-channel-access.md)
- [FloodWait 与限流机制](docs/architecture/flood-wait-handling.md)
- [历史实现与部署记录](docs/archive/)

## 安全说明

不要提交 `.env`、Telegram session、下载内容、运行日志或上传恢复 URL。若曾提交过凭据或上传会话，应在对应服务端使其失效并重新生成。
