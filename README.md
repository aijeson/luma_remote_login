# Luma 远程浏览器 Demo — boat.dev 无浏览器账号密码弹窗版

这个 Demo 取消了 Nginx HTTP Basic Auth，**不会再出现 Chrome 原生的 Username / Password 弹窗**。打开网页后，管理员只需在 **网页内部** 输入一次 `.env` 里的 `APP_TOKEN`。服务端会签发一个持续 8 小时、`HttpOnly; Secure; SameSite=Strict` 的会话 Cookie。

- 外部唯一入口：boat.dev 的 `https://...-8000.on.ascii.dev`。
- 内部由 Nginx `:8000` 转发到 FastAPI `127.0.0.1:8001` 与 noVNC `127.0.0.1:6080`。
- **noVNC 的静态页面和 WebSocket 都由 Nginx `auth_request` 校验登录 Cookie**。未解锁无法加载远程画面，浏览器不会弹 Basic Auth 对话框。
- Linux Xvfb + Chromium + x11vnc + websockify + Playwright。真实登录输入发生在 Luma 的页面内。
- 手动确认授权后，保存的 `luma.com` 范围浏览器状态以 Fernet 加密写入 `./data/luma-session.enc`。

> 这仍然是**单操作员 Demo**，整个容器中只有一个共享浏览器；**不是支持多个真实用户同时登录的生产系统**。请勿给多个用户共用这个实例。Luma 的反自动化、设备安全和认证策略可能阻止登录或会话复用。

## 1. 在现有 boat.dev 项目升级（保留密钥和数据）

如果之前的项目路径是 `~/luma_remote_login`：

```bash
cd ~/luma_remote_login

# 将 ZIP 放到这个目录，再执行：
mkdir -p /tmp/luma_no_popup
unzip -o luma_remote_login_no_popup.zip -d /tmp/luma_no_popup

# 仅覆盖项目源码。ZIP 不含 .env，也不会删除 ./data
cp -a /tmp/luma_no_popup/luma_remote_login_demo/. ./

docker compose up --build -d --force-recreate
docker compose ps
docker compose logs --tail=80 app
```

注意 ZIP 不包含 `.env`。原 `FERNET_KEY` 不改变，所以之前保存的加密会话仍能解密；`APP_TOKEN` 也不改变。

如在新目录全新安装，先运行 `python3 generate_env.py` 再运行 `docker compose up --build -d`。

## 2. 打开网页

在普通浏览器打开 boat.dev 映射 8000 的 HTTPS 地址，例如：

`https://box-node-XXXX-8000.on.ascii.dev/`

现在会看到**网页内**的 APP_TOKEN 输入框，而不是 Chrome 原生账号密码弹窗。读取原来的密钥：

```bash
cd ~/luma_remote_login
grep '^APP_TOKEN=' .env
```

仅复制等号后面的值，填入网页，点击「解锁远程浏览器」。验证成功后浏览器会自动显示远程 Chromium。然后你可以操作 Luma 登录页、输入自己的邮箱验证码、勾选授权、保存加密会话。

## 3. 验证抓取 Worker

```bash
docker compose exec -T app python worker.py
```

Worker 使用之前加密保存的状态打开 `https://luma.com/home`。是否真的已认证仍需要核对账号专属信息；仅 Cookie 数量或 HTTP 200 不能证明成功。

## 4. 8000/8001/6080/5900 端口规则

| 容器端口 | 用途 | 是否对公网暴露 |
| --- | --- | --- |
| 8000 | Nginx 统一入口 | 仅通过 boat.dev HTTPS 入口访问 |
| 8001 | FastAPI | 不对外开放 |
| 6080 | noVNC/WebSocket | 不对外开放 |
| 5900 | VNC | 不对外开放 |

`docker-compose.yml` 只把 8000 发布到主机 `127.0.0.1`。不要额外发布 5900、6080 或 8001。

## 5. 检查连通性

```bash
# Nginx 配置是否合法
docker compose exec -T app nginx -t -c /app/nginx.conf

# noVNC 后台服务是否响应（容器内部测试）
docker compose exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:6080/vnc.html', timeout=5).status)"

# 未经授权访问 noVNC 必须是 401，**不能是 200**
curl -s -o /dev/null -w 'noVNC unauthenticated: %{http_code}\n' http://127.0.0.1:8000/novnc/vnc.html

# 运行状态和 Nginx 错误
docker compose logs --tail=100 app
```

解锁后浏览器 Network / WS 应能看到 `/novnc/websockify` WebSocket 成功升级（`101 Switching Protocols`）；不要误用 `/websockify`。

## 6. 安全边界与上线要求

- 本版**没有删除鉴权**，只是把 HTTP Basic Auth 改成页面内 Token 登录 + 服务器 HttpOnly Cookie，会话有效 8 小时。Cookie 只会在 HTTPS 连接下发送。
- 因为 boat.dev 提供 HTTPS，本版在开发用 `http://公网IP:8000` **无法正常保存 Secure Cookie**。请通过 boat.dev 的 HTTPS 地址访问，不要禁用 Secure 标志。
- 会话在 Python 内存中；容器重启需重新在网页解锁，**不影响之前保存在 data/ 的 Luma 会话加密文件**。
- 点击「退出本 Demo」会撤销当前管理员会话 Cookie 并卸载本标签页的 iframe；已经建立的 WebSocket 连接可能在其他未关闭的标签页中继续存在一段时间。若需立即终止所有远程会话，请重启容器。
- 所有已解锁的管理员会操作**同一个浏览器**。正式产品必须改为每位用户隔离浏览器实例、平台用户认证、会话隔离与销毁、短期授权链接、限额、审计和滥用控制。
- Chromium 使用 `--no-sandbox` 以适配受限 Docker 沙盒，生产环境建议改为非 root 运行并启用 Chromium 沙盒、限制出口访问以及进程与文件系统权限。
- Luma 登录状态和 `.env` 都是敏感凭据；切勿公开 APP_TOKEN、Cookie、截图中的验证码或 session 文件。
