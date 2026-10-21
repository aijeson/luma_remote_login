# Luma Demo · boat.dev HTTPS 单入口修正版

本版修复了原 Demo 把 iframe 写死为 `https://当前主机:6080` 的问题。外部只需访问 boat.dev 已映射的 **8000 HTTPS 入口**，由容器内 Nginx 将 `/novnc/` 安全转发给私有的 noVNC/WebSocket。6080 和 5900 **不对宿主机发布**。

**重要：本项目依然是单用户开发测试 Demo，不是面向真实多租户的 SaaS 系统。** 全部登录操作发生在唯一一个共享 Chromium 实例中。不得让多个真实用户同时使用，正式产品需要每用户独立容器/上下文和短期会话权限、审计、回收机制。仅使用本人拥有或明确获得授权的 Luma 账号。

## 升级已部署项目（请保留你的 `.env` 和 `data/`）

1. 备份：`cp .env .env.bak` 并备份 `data/`（备份文件同样含敏感密钥，请勿分享）。
2. 解压本修正版 ZIP，覆盖原项目同名文件（ZIP **不含** `.env`，不会更换原有密钥）。
3. `docker compose up --build -d --force-recreate`
4. `docker compose ps`、`docker compose logs --tail=80 app`
5. 打开 boat.dev 绑定 **8000 端口**的现有 HTTPS URL（例如 `https://...-8000.on.ascii.dev/`）。
6. 浏览器可能弹出原生 HTTP 登录框：**用户名 `operator`，密码为 `.env` 的 `APP_TOKEN`**。注意不是 Luma 的密码。
7. 页面内部的 `APP_TOKEN` 字段也填写同一值，点击“查看状态”。左侧应显示容器里的远程 Chromium，再手动登录 Luma。
8. 完成 Luma 登录后按原流程勾选授权并保存，加密会话会保留在 `./data/`。

### 首次在新目录部署

```bash
python3 generate_env.py
docker compose up --build -d
```

检查容器内部（不会打印密钥）：

```bash
docker compose exec -T app python -c "import urllib.request; u=urllib.request.urlopen('http://127.0.0.1:6080/vnc.html'); print('internal noVNC:',u.status)"
docker compose exec -T app nginx -t -c /app/nginx.conf
docker compose ps
```

预期内网 noVNC 是 200、Nginx 配置检查成功。HTTP Basic 401（未输入管理认证）是预期保护，不是坏掉。

### 注意

- 外部仅需 HTTPS 8000 入口。不要将 6080、5900 的裸 VNC/WebSocket 开放到公网。
- 8000 后的 HTTPS 由 boat.dev 托管。若改为直接公网 IP:8000，需自行配置 TLS，不能让 HTTP Basic 密码走明文网络。
- Boat 公网代理必须支持 WebSocket Upgrade；如果登录后仍灰屏，在 Chrome DevTools Network 的 WS 里找 `/novnc/websockify`，并贴状态码（不要发送 Token、Cookie）。
- 该 Demo 仍保存单个本地 Luma 授权状态，APP_TOKEN 是演示系统密钥，不是 Luma Cookie。
- 页面/登录态实际能否成功访问 Luma 由站点策略决定，不保证所有 Google/Passkey 等登录方式可用。
