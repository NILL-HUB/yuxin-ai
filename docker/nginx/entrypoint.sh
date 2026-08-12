#!/bin/bash

# Nginx 容器启动脚本
# 用途: 根据环境变量动态生成 Nginx 配置

set -e

echo "=========================================="
echo "  Nginx 配置生成"
echo "=========================================="

# 设置默认值（使用 NGINX_* 前缀，避免与应用侧变量冲突）
export NGINX_DOMAIN_NAME=${NGINX_DOMAIN_NAME:-${DOMAIN_NAME:-localhost}}
export NGINX_SSL_CERT_FILE=${NGINX_SSL_CERT_FILE:-server.crt}
export NGINX_SSL_KEY_FILE=${NGINX_SSL_KEY_FILE:-server.key}
export NGINX_ENABLE_HTTPS=${NGINX_ENABLE_HTTPS:-${ENABLE_HTTPS:-false}}
export NGINX_CONF_DIR=${NGINX_CONF_DIR:-/etc/nginx/conf.d}
export NGINX_SSL_DIR=${NGINX_SSL_DIR:-/etc/ssl}
ENABLE_HTTPS_NORMALIZED="$(echo "$NGINX_ENABLE_HTTPS" | tr '[:upper:]' '[:lower:]')"
export API_UPSTREAM_HOST=${API_UPSTREAM_HOST:-llmops-api}
export API_UPSTREAM_PORT=${API_UPSTREAM_PORT:-5001}
export UI_UPSTREAM_HOST=${UI_UPSTREAM_HOST:-llmops-ui}
export UI_UPSTREAM_PORT=${UI_UPSTREAM_PORT:-3000}
export KKFILEVIEW_UPSTREAM_HOST=${KKFILEVIEW_UPSTREAM_HOST:-llmops-kkfileview}
export KKFILEVIEW_UPSTREAM_PORT=${KKFILEVIEW_UPSTREAM_PORT:-8012}
DEFAULT_CONF_PATH="${NGINX_CONF_DIR}/default.conf"

echo "域名: $NGINX_DOMAIN_NAME"
echo "SSL 证书: $NGINX_SSL_CERT_FILE"
echo "SSL 私钥: $NGINX_SSL_KEY_FILE"
echo "启用 HTTPS: $NGINX_ENABLE_HTTPS"
echo "API 上游: ${API_UPSTREAM_HOST}:${API_UPSTREAM_PORT}"
echo "UI 上游: ${UI_UPSTREAM_HOST}:${UI_UPSTREAM_PORT}"
echo "kkFileView 上游: ${KKFILEVIEW_UPSTREAM_HOST}:${KKFILEVIEW_UPSTREAM_PORT}"
echo ""

# 检查 SSL 证书文件是否存在
if [ "$ENABLE_HTTPS_NORMALIZED" = "true" ]; then
    if [ ! -f "${NGINX_SSL_DIR}/$NGINX_SSL_CERT_FILE" ]; then
        echo "❌ 错误: SSL 证书文件不存在: ${NGINX_SSL_DIR}/$NGINX_SSL_CERT_FILE"
        echo "请将 SSL 证书上传到服务器的 docker/nginx/ssl/ 目录"
        exit 1
    fi

    if [ ! -f "${NGINX_SSL_DIR}/$NGINX_SSL_KEY_FILE" ]; then
        echo "❌ 错误: SSL 私钥文件不存在: ${NGINX_SSL_DIR}/$NGINX_SSL_KEY_FILE"
        echo "请将 SSL 私钥上传到服务器的 docker/nginx/ssl/ 目录"
        exit 1
    fi

    echo "✓ SSL 证书文件检查通过"
fi

# 生成 Nginx 配置
echo "正在生成 Nginx 配置..."
mkdir -p "$NGINX_CONF_DIR"
if [ "$ENABLE_HTTPS_NORMALIZED" = "true" ]; then
    cat > "$DEFAULT_CONF_PATH" <<EOF
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    server_name ${NGINX_DOMAIN_NAME};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name ${NGINX_DOMAIN_NAME};

    ssl_certificate /etc/ssl/${NGINX_SSL_CERT_FILE};
    ssl_certificate_key /etc/ssl/${NGINX_SSL_KEY_FILE};

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    # 使用 Docker 内嵌 DNS 动态解析上游，容器重建更换 IP 后无需重启 nginx 即可恢复
    resolver 127.0.0.11 valid=10s ipv6=off;
    set \$api_upstream_host ${API_UPSTREAM_HOST};
    set \$api_upstream_port ${API_UPSTREAM_PORT};
    set \$ui_upstream_host ${UI_UPSTREAM_HOST};
    set \$ui_upstream_port ${UI_UPSTREAM_PORT};
    set \$kkfileview_upstream_host ${KKFILEVIEW_UPSTREAM_HOST};
    set \$kkfileview_upstream_port ${KKFILEVIEW_UPSTREAM_PORT};

    location /api/socket.io/ {
        rewrite ^/api/socket\.io/(.*)\$ /socket.io/\$1 break;
        proxy_pass http://\$api_upstream_host:\$api_upstream_port;
        include /etc/nginx/proxy.conf;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
    }

    location /api/ {
        rewrite ^/api/(.*)\$ /\$1 break;
        proxy_pass http://\$api_upstream_host:\$api_upstream_port;
        include /etc/nginx/proxy.conf;
    }

    location /storage/local/ {
        proxy_pass http://\$api_upstream_host:\$api_upstream_port\$request_uri;
        include /etc/nginx/proxy.conf;
    }

    # kkFileView 多格式文件预览（页面资源前缀与 UI 的 /assets 不冲突）
    location /kkfileview/ {
        rewrite ^/kkfileview/(.*)\$ /\$1 break;
        proxy_pass http://\$kkfileview_upstream_host:\$kkfileview_upstream_port;
        include /etc/nginx/proxy.conf;
        # kkFileView 模板把 bootstrap 放在 jQuery 之前，浏览器会报
        # "Bootstrap's JavaScript requires jQuery"；这里把 jQuery 提前注入。
        sub_filter_once on;
        sub_filter_types text/html;
        sub_filter '<script src="bootstrap/js/bootstrap.min.js"' '<script src="js/jquery-3.6.1.min.js"></script><script src="bootstrap/js/bootstrap.min.js"';
    }
    location ~ ^/(js|css|img|fonts|pdfjs|bootstrap)/ {
        proxy_pass http://\$kkfileview_upstream_host:\$kkfileview_upstream_port;
        include /etc/nginx/proxy.conf;
    }

    location / {
        proxy_pass http://\$ui_upstream_host:\$ui_upstream_port;
        include /etc/nginx/proxy.conf;
    }
}
EOF
else
    cat > "$DEFAULT_CONF_PATH" <<EOF
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    server_name ${NGINX_DOMAIN_NAME};

    # 使用 Docker 内嵌 DNS 动态解析上游，容器重建更换 IP 后无需重启 nginx 即可恢复
    resolver 127.0.0.11 valid=10s ipv6=off;
    set \$api_upstream_host ${API_UPSTREAM_HOST};
    set \$api_upstream_port ${API_UPSTREAM_PORT};
    set \$ui_upstream_host ${UI_UPSTREAM_HOST};
    set \$ui_upstream_port ${UI_UPSTREAM_PORT};
    set \$kkfileview_upstream_host ${KKFILEVIEW_UPSTREAM_HOST};
    set \$kkfileview_upstream_port ${KKFILEVIEW_UPSTREAM_PORT};

    location /api/socket.io/ {
        rewrite ^/api/socket\.io/(.*)\$ /socket.io/\$1 break;
        proxy_pass http://\$api_upstream_host:\$api_upstream_port;
        include /etc/nginx/proxy.conf;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
    }

    location /api/ {
        rewrite ^/api/(.*)\$ /\$1 break;
        proxy_pass http://\$api_upstream_host:\$api_upstream_port;
        include /etc/nginx/proxy.conf;
    }

    location /storage/local/ {
        proxy_pass http://\$api_upstream_host:\$api_upstream_port\$request_uri;
        include /etc/nginx/proxy.conf;
    }

    # kkFileView 多格式文件预览（页面资源前缀与 UI 的 /assets 不冲突）
    location /kkfileview/ {
        rewrite ^/kkfileview/(.*)\$ /\$1 break;
        proxy_pass http://\$kkfileview_upstream_host:\$kkfileview_upstream_port;
        include /etc/nginx/proxy.conf;
        # kkFileView 模板把 bootstrap 放在 jQuery 之前，浏览器会报
        # "Bootstrap's JavaScript requires jQuery"；这里把 jQuery 提前注入。
        sub_filter_once on;
        sub_filter_types text/html;
        sub_filter '<script src="bootstrap/js/bootstrap.min.js"' '<script src="js/jquery-3.6.1.min.js"></script><script src="bootstrap/js/bootstrap.min.js"';
    }
    location ~ ^/(js|css|img|fonts|pdfjs|bootstrap)/ {
        proxy_pass http://\$kkfileview_upstream_host:\$kkfileview_upstream_port;
        include /etc/nginx/proxy.conf;
    }

    location / {
        proxy_pass http://\$ui_upstream_host:\$ui_upstream_port;
        include /etc/nginx/proxy.conf;
    }
}
EOF
fi

echo "✓ Nginx 配置生成完成"
echo ""
echo "=========================================="
echo "  生成的配置:"
echo "=========================================="
cat "$DEFAULT_CONF_PATH"
echo ""
echo "=========================================="

# 测试 Nginx 配置
nginx -t

# 启动 Nginx
exec nginx -g "daemon off;"
