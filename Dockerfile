# =============================================================================
# doc-parser-service 多阶段构建镜像
#
# 阶段 1（frontend-build）：用 Node 安装依赖并执行 Vite 构建，产出 static 资源
# 阶段 2（最终镜像）：Python 3.12 slim，安装后端依赖，拷贝业务代码，并从阶段 1 拷贝前端 dist
#
# 构建上下文：一般在仓库根目录执行 docker build / docker compose build，
#            上下文根目录下的文件才可通过 COPY 进入镜像（受 .dockerignore 约束）
#
# 说明：
# - 最终运行镜像不包含 node_modules，仅包含 frontend/dist，体积小于在运行镜像里装 Node
# - node:20-alpine 为 LTS；拉取失败多为镜像加速器/网络，见 README「Docker 构建」
# =============================================================================

# -----------------------------------------------------------------------------
# 阶段 1：前端构建（命名为 frontend-build，供后续 COPY --from 引用）
# -----------------------------------------------------------------------------
FROM node:20-alpine AS frontend-build

# 镜像内工作目录；后续 RUN/COPY 的相对路径均相对此目录
WORKDIR /front

# 先只拷贝依赖清单，利用 Docker 层缓存：仅当 package*.json 变化时才重新 npm ci
COPY frontend/package.json frontend/package-lock.json ./

# 按 lock 文件可复现安装（生产/CI 推荐；与 npm install 不同，会删 node_modules 后重装）
RUN npm ci

# 再拷贝前端源码（含 vite.config、src、index.html 等），触发构建
COPY frontend/ ./

# 执行 package.json 中 "build" 脚本（vite build），生成 /front/dist
RUN npm run build

# -----------------------------------------------------------------------------
# 阶段 2：API / Worker 共用运行镜像（默认无阶段名，即最终镜像）
# -----------------------------------------------------------------------------
FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE=1：不写 .pyc，减小层体积、适合容器
# PYTHONUNBUFFERED=1：日志实时输出到 stdout，不被缓冲（便于 docker logs 排查）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 应用根目录；与 docker-compose 中 WORKDIR /app、uvicorn app.main:app 一致
WORKDIR /app

# 先单独拷贝依赖文件，利用缓存：仅 requirements.txt 变更时才重新 pip install
COPY requirements.txt ./

# --no-cache-dir：不把 wheel 缓存在镜像内，减小体积
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝构建上下文中的项目文件（app/、alembic/、docker-compose 等；.dockerignore 会排除 node_modules 等）
COPY . .

# 从前端构建阶段镜像中仅拷贝打包结果到运行镜像，供 FastAPI StaticFiles 挂载 /ui
# 源：阶段 1 中 npm run build 产生的 /front/dist
# 目标：运行镜像内 ./frontend/dist（与 app/main.py 中 frontend/dist 路径一致）
COPY --from=frontend-build /front/dist ./frontend/dist
