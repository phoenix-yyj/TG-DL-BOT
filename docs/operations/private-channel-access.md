# 私有频道访问

私有频道访问需要一个 Telegram 用户账号的 `SESSION`，它不同于 Bot Token，必须妥善保密。

## 生成 Session

先在部署目录的 `.env` 中填写 `API_ID` 和 `API_HASH`。Session 是用户账号的登录凭据，只在需要读取私有频道时才需要。

### Docker Compose 部署

在包含 `docker-compose.yml` 的部署目录下运行一次性容器。它复用 Compose 的 `.env` 环境变量和已发布镜像，不会启动机器人服务：

```sh
docker compose run --rm --no-deps -it --entrypoint python telegram-bot -c '
import asyncio, os
from pyrogram import Client

async def main():
    app = Client(
        "session_generator",
        api_id=int(os.environ["API_ID"]),
        api_hash=os.environ["API_HASH"],
        in_memory=True,
    )
    async with app:
        print("\nSESSION=" + await app.export_session_string())

asyncio.run(main())
'
```

按提示输入手机号、Telegram 验证码及两步验证密码（如有）。命令输出 `SESSION=...` 后，将等号后的整段值填入服务器 `.env` 的 `SESSION=`。不要把它发到聊天、工单或提交到 Git。

然后重建容器以加载新的环境变量：

```sh
docker compose up -d --force-recreate
```

### 从源码运行

也可以在已安装项目依赖的源码目录中运行生成脚本：

```sh
uv sync --no-dev
uv run python scripts/generate_session.py
```

按终端提示完成登录；脚本会将 `SESSION` 写入当前目录的 `.env`，然后重新创建 Compose 容器以加载新配置。

## 验证与排查

- 确认该用户账号已加入目标私有频道。
- Session 失效时，重新执行生成脚本。
- 不要将 `.env`、Session 字符串或 `sessions/` 目录提交到仓库。
