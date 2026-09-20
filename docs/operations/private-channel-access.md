# 私有频道访问

私有频道访问需要一个 Telegram 用户账号的 `SESSION`，它不同于 Bot Token，必须妥善保密。

## 生成 Session

1. 在 `.env` 中填写 `API_ID` 和 `API_HASH`。
2. 运行：

   ```sh
   python3 scripts/generate_session.py
   ```

3. 按终端提示完成 Telegram 登录；脚本会把生成的 `SESSION` 写入 `.env`。
4. 重启机器人。

## 验证与排查

- 确认该用户账号已加入目标私有频道。
- Session 失效时，重新执行生成脚本。
- 不要将 `.env`、Session 字符串或 `sessions/` 目录提交到仓库。
