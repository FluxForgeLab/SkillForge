#Requires -Version 5.1
<#
.SYNOPSIS
    SkillForge 开发入口（Windows；未安装 just 时使用）。
.EXAMPLE
    .\scripts\dev.ps1 lint
    .\scripts\dev.ps1 lab-inject backend_stopped
#>
param(
    [Parameter(Position = 0)]
    [string]$Command = "",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Block
    )
    & $Block
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

switch ($Command) {
    "api" {
        Invoke-Checked { uv run uvicorn skillforge.api.main:app --reload --port 8000 }
    }
    "web" {
        Invoke-Checked { pnpm -C apps/web dev }
    }
    "lint" {
        Invoke-Checked { uv run ruff check . }
        Invoke-Checked { uv run ruff format --check . }
        Invoke-Checked { pnpm -C apps/web lint }
    }
    "test" {
        Invoke-Checked { uv run pytest -m "not integration" }
    }
    "lab-up" {
        Invoke-Checked {
            docker compose -f demo/ops-lab/docker-compose.yml -p skillforge-lab up -d --build
        }
    }
    "lab-down" {
        Invoke-Checked {
            docker compose -f demo/ops-lab/docker-compose.yml -p skillforge-lab down
        }
    }
    "lab-reset" {
        Invoke-Checked { uv run python demo/ops-lab/faults/reset.py }
    }
    "lab-reset-all" {
        Invoke-Checked { uv run python demo/ops-lab/faults/reset_all.py }
    }
    "lab-verify" {
        Invoke-Checked { uv run python demo/ops-lab/verifier/verify.py }
    }
    "lab-inject" {
        if ($CommandArgs.Count -lt 1 -or [string]::IsNullOrWhiteSpace($CommandArgs[0])) {
            Write-Error "usage: .\scripts\dev.ps1 lab-inject <fault_id>"
            exit 1
        }
        $faultId = $CommandArgs[0]
        Invoke-Checked { uv run python demo/ops-lab/faults/inject.py $faultId }
    }
    default {
        Write-Host @"
usage: .\scripts\dev.ps1 <command> [args]
  api          FastAPI :8000 (C2.4+)
  web          Vite http://127.0.0.1:5173
  lint         ruff + apps/web lint
  test         pytest -m "not integration"
  lab-up       ops-lab compose up (C1.2+)
  lab-down     ops-lab compose down (no -v)
  lab-reset    faults/reset.py (C1.4+)
  lab-reset-all faults/reset_all.py (C1.6+, same as lab-reset)
  lab-verify   verifier/verify.py (C1.3+)
  lab-inject   faults/inject.py <fault_id>
"@
        if ($Command -ne "") {
            exit 1
        }
        exit 0
    }
}
