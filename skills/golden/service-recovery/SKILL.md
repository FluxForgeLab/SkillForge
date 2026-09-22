---
name: service-recovery
description: Diagnose and recover the skillforge-lab edge service. Use when GET /health returns HTTP 502, a backend is reported unavailable, or a health check fails.
version: 0.1.0
triggers: [HTTP 502, backend unavailable, health check failed]
tools: [docker.inspect, docker.logs, docker.restart, nginx.read_config, nginx.write_config, nginx.test, nginx.reload, http.get]
permissions:
  filesystem: {read: [/workspace], write: [/workspace/runtime]}
  network: {allow: [localhost]}
  shell: {destructive_commands: false}
---

# Service Recovery

## When to use

The edge proxy for compose project skillforge-lab returns HTTP 502, or a health check reports the backend unavailable.

## Procedure

ins_01 docker.inspect backend, nginx, and mock-db in compose project skillforge-lab.
ins_02 docker.logs the last 100 lines of the backend container.
ins_03 If the backend container is not running, docker.restart the service named backend.
ins_04 http.get http://127.0.0.1:8088/health. HTTP 200 ends this branch.
ins_05 If the health check is still not HTTP 200, nginx.read_config.
ins_06 If the upstream line is not `server backend:8080;`, replace only that line with `server backend:8080;`, nginx.write_config the full file, then nginx.reload. Leave every other line unchanged. If reload fails, stop and report the error.
ins_07 http.get http://127.0.0.1:8088/health again.

## Never do

ins_20 Do not delete volumes.
ins_21 Do not restart or stop mock-db.
ins_22 Do not use sudo, mount, shutdown, or rm -rf.

## Verification

Success on this branch is HTTP 200 from the health check in ins_04 or ins_07.
