# Service Recovery Runbook

This runbook recovers the skillforge-lab edge service when GET http://127.0.0.1:8088/health fails.

## Service Down

Trigger: backend unavailable

When the backend container is stopped, GET http://127.0.0.1:8088/health returns HTTP 502.

1. docker.inspect backend, nginx, and mock-db in compose project skillforge-lab.
2. docker.logs the backend container.
3. If the backend container is not running, docker.restart the service named backend.
4. GET http://127.0.0.1:8088/health. HTTP 200 means the service recovered.

Do not restart mock-db. Do not delete volumes.

## 502 from proxy

Trigger: HTTP 502 from reverse proxy

When GET /health returns HTTP 502 and the backend container is running, the reverse proxy upstream may be wrong.

1. nginx.read_config.
2. Check the upstream. The healthy line is server backend:8080;.
3. If that line differs, replace only that line with server backend:8080;.
4. nginx.write_config the full file, then nginx.reload.
5. If reload fails, stop and report the error.
6. GET http://127.0.0.1:8088/health. HTTP 200 means the service recovered.

## Appendix B: Reverse Proxy Troubleshooting

This section is a diagnostic rule. Apply it when nginx reload has already failed.

Trigger: nginx reload failed / upstream mismatch

When nginx reload failed because of an upstream mismatch, or the edge still returns HTTP 502 after a config change:

1. Run nginx -t before any nginx reload.
2. Compare the upstream port in nginx.conf with the port the backend process is listening on. The healthy upstream line is server backend:8080;. A wrong upstream line is server backend:8081;.
3. Remove invalid directives such as this_is_not_valid_nginx; from nginx.conf.
4. Write the corrected file, run nginx -t again, and nginx.reload only after the test passes.
5. GET http://127.0.0.1:8088/health. HTTP 200 means the service recovered.
