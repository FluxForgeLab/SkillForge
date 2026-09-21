---
name: diagnose-listen
description: 测量本机/容器监听端点后再解释连通性失败。当出现 connection refused、打不开、localhost、127.0.0.1、ERR_CONNECTION_REFUSED、页面空白、服务已启动但浏览器连不上、Cursor 内置浏览器失败、端口 5173/8000/8080/8088 时使用。
---

# Diagnose Listen

在宣布根因之前，按阶梯测量。约束见 `.cursor/rules/measure-before-story.mdc`。

## 端口身份

| 端口 | 进程 | 谁打开 |
|---|---|---|
| 5173 | Vite `apps/web` | 系统浏览器（绑 `127.0.0.1`） |
| 8000 | FastAPI `skillforge.api` | curl / 前端（C2.4 后） |
| 8080 | 模型 OpenAI-compatible `/v1`，**或** ops-lab backend **容器内** | 不是网页 |
| 8088 | ops-lab nginx（宿主机入口） | curl / 浏览器打 demo 服务 |

## 测量阶梯（不许跳）

```text
1. 这次尝试的 URL / host / port 是什么
2. 解析成元组（IPv4 还是 IPv6）
3. 看 LISTEN
4. 比对：尝试元组 vs LISTEN 元组
5. 仍不通才允许：防火墙、CORS、Cursor 沙箱、打错服务
```

Windows（开发机）：

```powershell
netstat -ano | findstr "LISTENING" | findstr ":5173"
curl.exe -sS -D- --max-time 2 http://127.0.0.1:5173/
```

Linux（DGX）：

```bash
ss -ltnp | grep 5173
curl -sS -D- --max-time 2 http://127.0.0.1:5173/ | head
```

把 `:5173` 换成实际端口。`localhost` 解析成 `::1` 而进程听在 `127.0.0.1`（或相反）时，就是地址族不一致，不是「服务没起」。

## 反例

Vite 打印 `Local: http://localhost:5173/`，实际 LISTEN 在 `[::1]:5173`。用 `127.0.0.1:5173` 得到 `CONNECTION_REFUSED`。正确动作是看监听表并改 `server.host`，不是讲 MCP 浏览器沙箱。

## 结论模板

```text
尝试: AF_INET 127.0.0.1:5173
LISTEN: AF_INET6 ::1:5173
同一端点: 否
结论: 地址族不一致；下一步改 bind 或改连接地址
```
