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
| httpx | ≥ 0.28 | BSD-3-Clause | API 测试客户端；网关 OpenAI 兼容 HTTP（运行时） |
| PyYAML | ≥ 6.0 | MIT | 路由表与单价表 |
| redis-py | ≥ 5.2 | MIT | 网关响应缓存 |
| jsonschema | ≥ 4.23 | MIT | 字典形式 JSON Schema 校验 |
| pypdf | ≥ 5.1 | BSD-3-Clause | N1 从 PDF / 画册抽取文本 |
| Pillow | ≥ 10.4 | HPND | N13–N15 把字幕、徽章、CTA、Logo 画成 PNG。画面文字不交给图像模型 |
| fakeredis | ≥ 2.26 | MIT | 缓存单元测试（开发依赖） |
| Ruff | ≥ 0.8 | MIT | Python lint / format |
| SQLAlchemy | ≥ 2.0.36 | MIT | 迁移与数据库类型 |
| Alembic | ≥ 1.14 | MIT | 数据库迁移（业务表与 call_logs/alerts） |
| psycopg | ≥ 3.2 | LGPL-3.0 | PostgreSQL 驱动（`psycopg-binary` 同上） |
| pytest-cov | ≥ 6.0 | MIT | 模型模块覆盖率 |
| PostgreSQL | 16（`pgvector/pgvector:0.8.7-pg16`） | PostgreSQL License | 业务库 |
| pgvector | 0.8.7 | PostgreSQL License | 向量检索扩展 |
| Redis | 7.2.17-alpine | BSD-3-Clause | 缓存。钉在 7.2，避开 7.4+ 的 RSALv2 / SSPL |
| MinIO server | Bitnami 构建 `bitnamilegacy/minio:2025.7.23-debian-12-r5`（服务端 DEVELOPMENT / 2025.7 线） | AGPL-3.0（MinIO 服务端）；镜像打包脚本 Apache-2.0 | 本地对象存储 |
| Temporal server | `temporalio/auto-setup:1.29.1` | MIT | 工作流 |
| temporalio | ≥ 1.9, < 2 | MIT | Python Workflow / Activity SDK。验收默认在进程内启动 dev server，不另起 Compose |
| Temporal UI | `temporalio/ui:2.34.0` | MIT | 工作流界面 |
| Temporal development-sql dynamic config | 与 `temporalio/docker-compose` 中同名文件一致 | MIT | 让 auto-setup 在 Postgres 上启动 |
| FFmpeg | 系统包（开发机 / CI `apt install ffmpeg`；编码器 libx264） | LGPL / GPL（取决于发行版编译选项；libx264 为 GPL） | mock 视频样例编码；T04 验收时解码 PNG / MP4 / WAV；N10 用 ffprobe 量时长并用 libx264 裁到镜头时长；N15 用 libx264 合成 H.264，并用 lut3d / overlay 做调色和后期叠字。未作为 Python 依赖链接进进程 |
| Tesseract OCR | 系统包（`tesseract-ocr` 与 `tesseract-ocr-chi-sim`） | Apache-2.0 | T20 对解码后的成片帧做 OCR，检查角标「AI生成」。未作为 Python 依赖链接进进程 |
| Noto Sans CJK SC（思源黑体简体） | Sans 2.004，`templates/packaging/fonts/NotoSansSC-Regular.otf` 与 `NotoSansSC-Bold.otf` | SIL OFL 1.1（同目录 `LICENSE.txt`） | N13–N15 字幕、徽章、CTA、AI 标识。版权归 Adobe 与 Noto CJK 项目。不改字体名 |
| python-multipart | ≥ 0.0.18 | Apache-2.0 | 输入页上传图片 / PDF 的 multipart 解析 |
| @radix-ui/react-slot | 1.x | MIT | shadcn/ui Button 的 `asChild` |
| class-variance-authority | 0.7.x | Apache-2.0 | shadcn/ui 按钮变体 |
| clsx | 2.x | MIT | 条件类名 |
| tailwind-merge | 3.x | MIT | 合并 Tailwind 类名 |
| lucide-react | 0.x | ISC | 输入页上传图标 |
| shadcn/ui | 组件源码在 `apps/web/components/ui` | MIT | 按钮、输入、文本域、标签、卡片、徽章。不是运行时依赖 |
| Playwright | 1.x（`@playwright/test`） | Apache-2.0 | T11 桌面与手机视口 E2E |
| @xyflow/react | 12.8.6 | MIT | T19 专家模式节点画布。界面是自写节点，不用第三方画布素材 |

尚未引入、因此未登记：Remotion、厂商模型 SDK、boto3、MinIO Python SDK、librosa。对象存储走自写的 SigV4 HTTP 客户端。

T21 的测试音乐和音效由节点代码合成（正弦底乐、节拍点击、短噪声），不新增 Python 依赖，也不把第三方录音放进仓库。许可证在每段上记为 `CC0-1.0`，来源是 `hilatv-test-library` / `hilatv-test-sfx`。响度和压低量用已经登记的 FFmpeg（`ebur128`、`volumedetect`）在渲染结果上测量。

MinIO 说明：Docker Hub 上的 `minio/minio` 目前无法匿名拉取，`dl.min.io` 返回 HTTP 410。T01 改用仍包含官方 MinIO 服务端的 Bitnami 构建，并固定版本标签。
