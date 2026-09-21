---
name: ops-lab
description: 启动、复位、注入故障并验证 demo/ops-lab（nginx + backend + mock-db）。当需要跑集成测试、手动复现 F1/F2/F3 故障、调试 verifier 或 agent 对真实环境的操作时使用。
---

# Ops Lab

所有命令在仓库根目录执行。compose project 固定 `skillforge-lab`，nginx 对外端口 8088。

## 生命周期

```bash
docker compose -f demo/ops-lab/docker-compose.yml -p skillforge-lab up -d --build   # 启动
python demo/ops-lab/verifier/verify.py                                              # 健康检查，exit 0 = 健康
python demo/ops-lab/faults/inject.py <fault_id>                                     # 注入故障
python demo/ops-lab/faults/reset.py                                                 # 复位到健康态
docker compose -f demo/ops-lab/docker-compose.yml -p skillforge-lab down -v         # 销毁
```

`just lab-up | lab-verify | lab-inject F1 | lab-reset | lab-down` 是同义快捷方式（C0.5 之后可用）。

## 故障目录（demo/ops-lab/faults/catalog.yaml）

| fault_id | 现象 | verifier 特征 |
|---|---|---|
| `backend_stopped` (F1) | 502 | `backend_running=false` |
| `nginx_wrong_upstream` (F2) | 502 | `upstream_port_matches=false` |
| `nginx_bad_config_reload` (F3) | 502，reload 失败 | `nginx_config_valid=false` 且 `upstream_port_matches=false` |

新增故障：在 catalog 登记 → inject/reset 各加一个分支 → verifier 若需新字段同步 evals 与 evaluator 断言 → `tests/integration/test_ops_lab.py` 加用例。

## 验证 verifier 输出

```bash
python demo/ops-lab/verifier/verify.py | python -m json.tool
```

健康态期望：`http_status=200, backend_running=true, nginx_config_valid=true, upstream_port_matches=true, db_running=true`。

## 排错

- `up` 后 verifier 立即 502：等待 backend 就绪（`docker compose ... logs backend`），verifier 内置 10s 重试。
- 端口冲突：改 compose 中 nginx 的 `8088:80` 映射，同时改 verifier 与 `Settings.ops_lab_base_url`。
- Windows 本机是 x86_64，DGX 是 aarch64：镜像必须是 multi-arch；不要在 Dockerfile 里下载架构相关二进制。
- 不要手动 `docker exec` 改容器内配置来"修好"环境，那会掩盖 inject/reset 的 bug；改 faults 脚本。
