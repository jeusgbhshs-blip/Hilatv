# HiLatv 开发进度

> 每合并一个任务更新状态表；每天结束追加一条简短日志。

## 任务状态

| 任务 | 名称 | 依赖 | 状态 | 分支 / PR | 备注 |
|---|---|---|---|---|---|
| T01 | monorepo + Docker Compose | – | ✅ | [t01-monorepo-compose](https://github.com/jeusgbhshs-blip/Hilatv/pull/21) | 已合并 |
| T02 | 第 5 章 Pydantic 模型 + 迁移 | T01 | ✅ | [t02-schemas-migrations](https://github.com/jeusgbhshs-blip/Hilatv/pull/22) | 已合并。revision `t02_business_0001` |
| T03 | 模型网关 + LLM adapter + 路由/缓存/日志 + 费用上限 | T01 | 🔵 | [t03-model-gateway](https://github.com/jeusgbhshs-blip/Hilatv/pull/23) | 验收中。`call_logs`/`alerts` 为 `t03_gateway_0002`。假设见下方 |
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

<!-- hilatv:alerts -->

## 每日日志

<!-- 模板：
### YYYY-MM-DD
- 合并了哪些：
- 正在做什么：
- 需要提供什么：
-->

### 2026-10-29
- 合并了哪些：T01（PR #21）、T02（PR #22，`t02_business_0001`）
- 正在做什么：T03 模型网关。`call_logs` / `alerts` 接在 Alembic `t03_gateway_0002`（down_revision `t02_business_0001`）。无 Key，验收走 mock
- 需要提供什么：LLM Key 与非零预算后才可打开 `HILATV_LIVE=1`

## T03 假设

- Postgres 上的 `call_logs` / `alerts` 只由 Alembic revision `t03_gateway_0002` 创建，单一 head。网关不再自带建表 SQL。单元测试仍用 SQLite，在进程内建同结构的表。
- `generate_text(..., schema=Brief)` 接受任意 Pydantic 模型或 JSON Schema 字典。测试里的 Brief 按 SPEC §5.2 字段自建，不改 T02 的模型模块。
- 真实 LLM 只用 httpx 打 OpenAI 兼容接口（DeepSeek / 通义 compatible-mode / 火山方舟）。不引入厂商 SDK。方舟的 model 常是接入点 ID，可用 `ARK_MODEL` 覆盖路由表。
- 单价在 `gateway/pricing.yaml`（CNY / 1M tokens），按公开价近似，可改配置。未返回 usage 时按约 4 字符 1 token 估算，输出按 512 token 预估。
- 预算「日」是 Asia/Shanghai 自然日。只累计 live 且非缓存命中的 `cost_cny`。失败、超时、缓存、mock 记 0。`HILATV_LIVE!=1` 或没有 Key 时直接 mock，不发 `budget_exceeded`。仅当 live adapter 可用但预估会使总额或当日额达到上限时才回退 mock 并告警。
- `alerts` 每次超限一行；`docs/progress.md` 相同文案不重复追加。总上限调高后无需重启（每次调用重读环境变量）。
- 缓存键含规范化输入、seed 和路由指纹。预算回退的 mock 结果不写入缓存。Redis 不可用时用进程内缓存，CI 无 Redis 仍可通过；单元测试用 fakeredis 覆盖 Redis 客户端。
- 图像/视频提示词在网关追加「无文字 / 无 Logo / 无价格 / 无电话」负面约束。非 LLM 任务本任务只有 mock。全部候选都失败时抛 `GatewayError`（已记错误日志）。`qa_score` 列先空着。

