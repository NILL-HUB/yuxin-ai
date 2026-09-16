# 使用 Python3.12 版本作为基础镜像（3.13 部分依赖如 pipreqs/unstructured 尚未完全兼容）
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# 官方 Node 24（glibc 变体）。本架构统一 Node 24；详见下方说明。
ARG NODE_IMAGE=node:24-bookworm-slim

# ---- 阶段一：官方 Node 运行时（只用于拷贝二进制，不增加最终镜像体积）----
# 为什么不 `apt-get install nodejs`：Debian bookworm 仓库里是 Node 18（已于 2025-04 EOL），
# 而 npx 类 MCP stdio server 需要更新版本；且本架构统一 Node 24。
# 为什么用 bookworm-slim 而不是 alpine：alpine 的 node 链接 musl（libc.musl-x86_64.so.1），
# 拷进本 Debian(glibc) 镜像会因缺 ld-musl 起不来。libc 必须与并入的镜像一致。
FROM ${NODE_IMAGE} AS node

FROM ${PYTHON_IMAGE} AS base

# 设置 shell 为 bash（可选）
SHELL ["/bin/bash", "-c"]

# 设置工作目录
WORKDIR /app/api

# 安装系统依赖（包括 curl 用于下载 tiktoken 文件）
# 注意：Node 不在这里装——见文件头的阶段一说明（统一 Node 24，glibc）。
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 curl tzdata && rm -rf /var/lib/apt/lists/*

# 预下载 tiktoken 编码文件到缓存目录
RUN mkdir -p /root/.cache/tiktoken && \
    curl -o /root/.cache/tiktoken/cl100k_base.tiktoken \
    https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken

# 复制 requirements 并安装依赖
COPY requirements.txt .
RUN pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    rm -rf /root/.cache


# 复制代码文件
COPY . .

# ---- Node 24 运行时：从阶段一拷入 /usr/local（优先于 /usr/bin），供 npx 类 MCP stdio server 使用 ----
# 放在 COPY 之后是刻意的：Node 版本变更只需重建最后这几层，不必重跑 pip install。
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN set -eux; \
    ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm; \
    ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx; \
    node --version; npm --version; npx --version; \
    node -e 'const v=process.versions.node.split(".").map(Number); if(v[0]<22){console.error("需要 Node >= 22（npx 类 MCP stdio server 依赖）"); process.exit(1)}'

# 设置镜像级固定环境变量（业务配置通过 env_file/.env 注入）
ENV NLTK_DATA=/app/api/internal/core/unstructured/nltk_data \
    TZ=Asia/Shanghai

RUN ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime && echo ${TZ} > /etc/timezone

# 启动脚本
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5001

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
