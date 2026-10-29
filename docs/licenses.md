# 开源依赖许可证

登记范围：T01 实际引入的运行时与开发依赖。后续任务新增依赖时追加行。版本以清单为准；Python 库的下限写在 `pyproject.toml`。

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| Next.js | 15.5.28 | MIT | 前端 |
| React / React DOM | 19.1.0 | MIT | 前端 |
| Tailwind CSS | 4.x | MIT | 样式 |
| TypeScript | 5.x | Apache-2.0 | 前端类型 |
| ESLint | 9.x | MIT | 前端 lint |
| FastAPI | ≥ 0.115 | MIT | HTTP API |
| Uvicorn | ≥ 0.34 | BSD-3-Clause | ASGI 服务器 |
| Pydantic | ≥ 2.10 | MIT | 数据校验 |
| pydantic-settings | ≥ 2.7 | MIT | 环境配置 |
| Jinja2 | ≥ 3.1 | BSD-3-Clause | 节点提示词模板 |
| pytest | ≥ 8.3 | MIT | 单元测试 |
| httpx | ≥ 0.28 | BSD-3-Clause | API 测试客户端 |
| Ruff | ≥ 0.8 | MIT | Python lint / format |
| PostgreSQL | 16（`pgvector/pgvector:0.8.7-pg16`） | PostgreSQL License | 业务库 |
| pgvector | 0.8.7 | PostgreSQL License | 向量检索扩展 |
| Redis | 7.2.17-alpine | BSD-3-Clause | 缓存。钉在 7.2，避开 7.4+ 的 RSALv2 / SSPL |
| MinIO server | Bitnami 构建 `bitnamilegacy/minio:2025.7.23-debian-12-r5`（服务端 DEVELOPMENT / 2025.7 线） | AGPL-3.0（MinIO 服务端）；镜像打包脚本 Apache-2.0 | 本地对象存储 |
| Temporal server | `temporalio/auto-setup:1.29.1` | MIT | 工作流 |
| Temporal UI | `temporalio/ui:2.34.0` | MIT | 工作流界面 |
| Temporal development-sql dynamic config | 与 `temporalio/docker-compose` 中同名文件一致 | MIT | 让 auto-setup 在 Postgres 上启动 |

尚未引入、因此未登记：FFmpeg、React Flow（`@xyflow/react`）、shadcn/ui、Remotion、厂商模型 SDK。

MinIO 说明：Docker Hub 上的 `minio/minio` 目前无法匿名拉取，`dl.min.io` 返回 HTTP 410。T01 改用仍包含官方 MinIO 服务端的 Bitnami 构建，并固定版本标签。
