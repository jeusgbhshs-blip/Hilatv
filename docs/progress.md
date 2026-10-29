# HiLatv 开发进度

> 每合并一个任务更新状态表；每天结束追加一条简短日志。

## 任务状态

| 任务 | 名称 | 依赖 | 状态 | 分支 / PR | 备注 |
|---|---|---|---|---|---|
| T01 | monorepo + Docker Compose | – | 🔵 | [t01-monorepo-compose](https://github.com/jeusgbhshs-blip/Hilatv/pull/21) | 验收中。假设见 PR #21 |
| T02 | 第 5 章 Pydantic 模型 + 迁移 | T01 | ⬜ | – | |
| T03 | 模型网关 + LLM adapter + 路由/缓存/日志 + 费用上限 | T01 | ⬜ | – | |
| T04 | 图像/视频/TTS adapter | T03 | ⬜ | – | |
| T05 | N1 需求理解 + 行业默认值表 | T02, T03 | ⬜ | – | |
| T06 | N4 脚本 + N5 分镜 | T05 | ⬜ | – | |
| T07 | N6 TTS + 时间戳回写 | T04, T06 | ⬜ | – | |
| T08 | N8 关键帧 + N10 图生视频 | T04, T06 | ⬜ | – | |
| T09 | N13 字幕 + N14 包装 + N15 合成 | T02, T07 | ⬜ | – | |
| T10 | Temporal 主工作流 + WebSocket 进度 | T05–T09 | ⬜ | – | |
| T11 | 前端：输入页、进度页、成片页 | T10 | ⬜ | – | |
| T12 | N9/N11 质检 + 导演 Agent 决策循环 | T08, T10 | ⬜ | – | |
| T13 | N7 锚点 + 产品合成模式 | T08, T12 | ⬜ | – | |
| T14 | 降级方案 6.10 | T12, T13 | ⬜ | – | |
| T15 | N3 方案卡 + N2 Brand Kit 后台 | T10, T11 | ⬜ | – | |
| T16 | N18 对话改稿 + 版本管理 | T10, T12 | ⬜ | – | |
| T17 | 多比例、多语种导出 | T06, T09, T10 | ⬜ | – | |
| T18 | eval/ 基准测试 + 报告 | T10, T12 | ⬜ | – | |
| T19 | 专家模式画布 | T10, T11, T12 | ⬜ | – | |
| T20 | 合规：AI 标识、内容审核、授权存档 | T09, T15 | ⬜ | – | |

状态：⬜ 未开始 · 🟡 开发中 · 🔵 验收中 · ✅ 已合并 · ⛔ 阻塞

## 密钥 / 账号（mock ↔ live）

| 项目 | 用于 | 状态 |
|---|---|---|
| LLM Key（DeepSeek / 通义 / 豆包 任一） | T03+ | mock |
| 图像 Key（如 Seedream） | T04, T08, T13 | mock |
| 视频 Key（如 Seedance / 火山方舟） | T04, T08 | mock |
| 豆包/火山 TTS Key（公司已有） | T04, T07 | mock |
| VLM 评审 Key | T12 | mock |
| 内容安全服务 Key | T20 | mock |
| 预算上限 `HILATV_BUDGET_CNY` / `HILATV_DAILY_BUDGET_CNY` | 网关 | 未设置（= 不允许 live） |

## 告警（预算超限等，由网关自动追加）

<!-- 例：- 2026-11-05 14:20 budget_exceeded：已花费 ¥xxx / 上限 ¥xxx，live 调用已暂停并回退 mock -->

## 每日日志

<!-- 模板：
### YYYY-MM-DD
- 合并了哪些：
- 正在做什么：
- 需要提供什么：
-->

### 2026-10-29
- 合并了哪些：无（T01 验收中，尚未合并）
- 正在做什么：T01 monorepo 骨架、Docker Compose（Postgres 16 + pgvector、Redis、MinIO、Temporal + UI）、基础 CI（PR #21）
- 需要提供什么：无

