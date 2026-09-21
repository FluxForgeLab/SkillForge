worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /tmp/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    keepalive_timeout 65;

    upstream skillforge_backend {
        server backend:__UPSTREAM_PORT__;
    }

    server {
        listen 80;
        server_name _;
        error_page 504 =502 @upstream_down;

        location @upstream_down {
            default_type application/json;
            return 502 '{"status":"bad_gateway"}';
        }

        location / {
            proxy_pass http://skillforge_backend;
            proxy_connect_timeout 1s;
            proxy_send_timeout 2s;
            proxy_read_timeout 2s;
            proxy_intercept_errors on;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
