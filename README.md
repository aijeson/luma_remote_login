# Luma 远程浏览器登录授权 Demo（Linux）

一个可部署的 **单操作员 / 单账号** 端到端演示。使用 Docker + Chromium（headed）+ Xvfb + x11vnc + noVNC + Python Playwright + FastAPI，让操作者通过 SSH 隧道远程操作 Linux 上的浏览器登录 [Luma](https://luma.com/signin?next=%2Fhome)。用户确认授权后，只保存 Luma 域内会话状态，用 Fernet 加密存盘，再由独立的无头 Worker 加载，访问 `/home`。

**限制：这个项目是本地/SSH 隧道演示，不是公开 SaaS 的生产版本。** 没有多租户隔离、审计、队列调度、凭据轮换、实时高可靠账号有效性判断或标准化用户 OAuth 授权。只能测试本人账号或具有明确授权的账号。遵守 Luma 服务条款、访问频率和隐私规则。不要用它绕过验证码或反自动化保护。

## 0. 系统需求

- Linux x86_64/arm64（推荐 Ubuntu 22.04/24.04 或 Debian 12），有 Docker Engine 和 Docker Compose v2。
- 能够从服务器连通 `https://luma.com`；拉取 Docker 镜像和 apt/pip 软件包。
- 建议至少 2 vCPU、4 GB RAM、可用磁盘 3 GB 以上（Chromium 镜像较大）。
- 本地电脑能使用 `ssh` 和浏览器。

## 1. 首次准备（在 Linux 服务器执行）

```bash
unzip luma_remote_login_demo.zip
cd luma_remote_login_demo
python3 generate_env.py
# 查看 APP_TOKEN，复制其值以便填写到网页中。不要泄露 FERNET_KEY。
grep '^APP_TOKEN=' .env

docker compose up --build -d
docker compose logs --tail=50 -f app
```

看到 `Application startup complete`、`Luma sign-in page is ready` 后按 Ctrl+C 退出日志查看（容器继续运行）。如果看到初始访问 Luma 失败，请检查服务器网络；容器仍可能正常启动。

端口 **仅绑定服务器的 127.0.0.1**，默认无法直接通过服务器公网 IP 访问，减少登录态和浏览器暴露的风险。

## 2. 把远程浏览器安全地打开在你的电脑上

如果 Linux 是远程服务器，在你 **自己的电脑终端** 执行（替换用户名及服务器地址）：

```bash
ssh -N \
  -L 8000:127.0.0.1:8000 \
  -L 6080:127.0.0.1:6080 \
  linux_user@YOUR_SERVER_IP
```

保持这个终端打开。然后在**本地电脑浏览器**打开：

`http://127.0.0.1:8000`

如果 Docker 和浏览器都在同一台 Linux 机器，就不需要 SSH 隧道，直接访问该地址。

## 3. 登录并保存会话

1. 页面左侧有 Chromium 实际桌面画面。打开的是 `https://luma.com/signin?next=%2Fhome`。
2. 推荐选择邮箱登录；输入你的邮箱，收取 Luma 官方邮件中的 6 位验证码，并**直接在远程 Chromium 中**完成验证。
3. 等浏览器跳转到已登录的 Luma 页面。可点击网页右上角头像/账号区域核对，确保不是公开游客页面。
4. 右上角输入 `.env` 的 `APP_TOKEN`，点击「查看状态」。它只展示当前 URL、标题、Luma 域内 Cookie 数量，**不展示 Cookie 值**。
5. 勾选本人账号授权确认，点击「保存加密登录会话」。服务器在 `/data/luma-session.enc` 保存经过加密的 Luma 域名状态（宿主机在 `./data/luma-session.enc`）。
6. 点击「验证已保存会话」。该功能打开**新的独立 Playwright Context**，加载磁盘加密会话，访问 Luma `/home`。结果是登录状态的**启发式**判断，并非保证，必须人工检查实际登录身份。

部分情况下（Google OAuth、Passkeys、浏览器检测、IP 变化或其它目标站机制），自动化浏览器可能不被允许或要求补充验证。不要尝试规避安全检查。

## 4. 模拟 Linux 后台抓取 Worker

继续在 Linux 服务器项目目录下执行：

```bash
docker compose exec -T app python worker.py
```

会输出类似下面的**示例格式**（不是预先获取的 Luma 实测结果）：

```json
{
  "visited_url": "https://luma.com/home",
  "title": "Events · Luma",
  "http_status": 200,
  "redirected_to_signin": false,
  "sign_in_link_visible": false,
  "note": "This is a connectivity/session smoke test, not definitive auth proof."
}
```

这个 Worker 的重点是证明：**独立进程**确实能解密会话，并在新的浏览器 Context 中加载，而不是依赖用户登录时那个仍然打开的页面。若 Luma 拒绝重用会话，结果可能显示跳回登录页面；这是实际测试结果，不能保证必然成功。

## 5. 清理、断开与关闭

在网页点击「删除本地授权 / 清空浏览器」：删除 `./data/luma-session.enc`、关闭当前 Context 并重新打开一个全新登录页。**只是本地删除，不表示在 Luma 侧强制下线或撤销所有会话。**

关闭容器：

```bash
docker compose down
```

如果需要删除整个演示数据：

```bash
docker compose down
rm -f data/luma-session.enc
```

不要随便删除 `.env`，否则原来的 Fernet 加密会话无法再解密。

## 6. 故障排查

**页面打开，但是远程浏览器黑屏或打不开：** 确保本地 SSH 隧道同时转发 `8000` 和 `6080`，浏览器开发者工具可检查 WebSocket；在 Linux 查看 `docker compose logs app`、`/tmp/x11vnc.log`、`/tmp/websockify.log`。

**远程桌面显示 Luma 登录失败：** Linux 网络可能受限，先在 Linux 执行 `curl -I https://luma.com/signin`；网站也可能对云服务器/自动化浏览器有限制。保持真实登录流程，不要规避反机器人检查。

**点击保存报错：** 检查是否真的从 `/signin` 跳转，且浏览器已进入已登录页面。有些账号页面仅包含公开内容，不能把看到 `/home` 当作已登录。

**独立 Worker 仍显示 Sign In：** Cookie 可能已过期、站点可能使用其他域上的凭据或浏览器指纹/IP 校验。只能提示用户重新登录或改用官方 API，不能保证会话无限期可用。

**Google 登录或 Passkey 不成功：** 优先用 Luma 邮箱验证码；第三方身份提供方可能拒绝不受支持的自动化浏览器，Passkey 通常依赖本地硬件、账号同步和浏览器支持。

## 7. 演示架构与安全边界

```text
本地浏览器 http://127.0.0.1:8000
    |
    | SSH Tunnel: 8000 + 6080
    v
Linux Docker Container
    FastAPI :8000 --- POST /api/save, /api/verify, /api/disconnect
    noVNC :6080 --- websockify -> x11vnc :5900 -> Xvfb :99
                                          |
                                     Chromium headed
                                     Luma 登录页面
                                          |
                                   Playwright Context
                                          |
                        Luma-only storage_state(indexed_db=True)
                                          |
                                   Fernet encrypted
                                          |
                           ./data/luma-session.enc
                                          |
                   independent worker.py -> Chromium headless
```

- API 用 `X-Admin-Token` 鉴权；公网未开放，SSH 负责访问通道；VNC 自身没有密码，因此**绝对不能开放 Docker 的 6080 端口到公网**。演示仅限单名可信操作者使用。
- `storage_state` 可能包含能代表用户身份的 Cookie 或认证令牌；会话加密文件、APP_TOKEN、FERNET_KEY 都必须按机密处理。特别是 Fernet Key 不能和加密文件一起外泄。
- 只保留域名 `luma.com` 与子域匹配的 Cookie / origin 数据。若 Luma 使用站外身份提供方的状态，这个最小化处理可能导致无法复用；这是故意做的隐私限制。
- 实际产品要引入**每用户独立隔离实例和存储、独立授权票据、TLS、租户身份验证、授权撤销机制、审计与访问频控、KMS/密钥轮换、SSRF 防护、任务权限校验、明确的用户同意**，不能直接把本 Demo 对公网开放。

## 8. 参考

- Luma 登录说明：https://help.luma.com/p/signing-in
- Luma API 文档：https://docs.luma.com/reference/getting-started-with-your-api
- Playwright Python 认证状态：https://playwright.dev/python/docs/auth
- Playwright BrowserContext.storage_state：https://playwright.dev/python/docs/api/class-browsercontext
