# SkillForge 开发入口。Windows 若未装 just，用 scripts/dev.ps1。

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

# FastAPI 控制面（C2.4 之后才有 app）
api:
    uv run uvicorn skillforge.api.main:app --reload --port 8000

# Vite 前端，127.0.0.1:5173
web:
    pnpm -C apps/web dev

# ruff + 前端 lint（不含 build）
lint:
    uv run ruff check .
    uv run ruff format --check .
    pnpm -C apps/web lint

# 单测，不含 integration
test:
    uv run pytest -m "not integration"

# ops-lab 启动（C1.2 之后）
lab-up:
    docker compose -f demo/ops-lab/docker-compose.yml -p skillforge-lab up -d --build

# 停止 ops-lab，不删 volume
lab-down:
    docker compose -f demo/ops-lab/docker-compose.yml -p skillforge-lab down

# 复位到健康态（C1.4 之后）
lab-reset:
    uv run python demo/ops-lab/faults/reset.py

# verifier 健康检查（C1.3 之后）
lab-verify:
    uv run python demo/ops-lab/verifier/verify.py

# 注入故障：just lab-inject backend_stopped
lab-inject FAULT:
    uv run python demo/ops-lab/faults/inject.py {{FAULT}}
