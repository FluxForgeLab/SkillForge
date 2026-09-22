# service-recovery

版本 0.1.0。诊断并恢复 skillforge-lab 边缘服务（宿主 `http://127.0.0.1:8088/health`）。

## 何时使用

HTTP 502、backend 不可用、健康检查失败。

## 工具

`docker.inspect`、`docker.logs`、`docker.restart`、`nginx.read_config`、`nginx.write_config`、`nginx.test`、`nginx.reload`、`http.get`

## 步骤

1. ins_01 检查 skillforge-lab 中的 backend、nginx、mock-db
2. ins_02 读取 backend 最近 100 行日志
3. ins_03 backend 未运行时只重启 backend
4. ins_04 GET `http://127.0.0.1:8088/health`
5. ins_05 仍失败则读取 nginx 配置
6. ins_06 只把 upstream 改回 `server backend:8080;` 后 reload
7. ins_07 再次健康检查

## 边界

不删除 volume，不重启或停止 mock-db，不使用 sudo、mount、shutdown、rm -rf。

## 评测

- eval_backend_stopped
- eval_nginx_wrong_upstream
- eval_nginx_bad_config_reload
