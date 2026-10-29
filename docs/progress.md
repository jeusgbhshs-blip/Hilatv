# HiLatv 开发进度

> 每合并一个任务更新状态表；每天结束追加一条简短日志。

## 任务状态

| 任务 | 名称 | 依赖 | 状态 | 分支 / PR | 备注 |
|---|---|---|---|---|---|
| T01 | monorepo + Docker Compose | – | ✅ | [t01-monorepo-compose](https://github.com/jeusgbhshs-blip/Hilatv/pull/21) | 已合并 |
| T02 | 第 5 章 Pydantic 模型 + 迁移 | T01 | ✅ | [t02-schemas-migrations](https://github.com/jeusgbhshs-blip/Hilatv/pull/22) | 已合并。revision `t02_business_0001` |
| T03 | 模型网关 + LLM adapter + 路由/缓存/日志 + 费用上限 | T01 | ✅ | [t03-model-gateway](https://github.com/jeusgbhshs-blip/Hilatv/pull/23) | 已合并。`call_logs`/`alerts` 为 `t03_gateway_0002`。假设见下方 |
| T04 | 图像/视频/TTS adapter | T03 | ✅ | [t04-media-adapters](https://github.com/jeusgbhshs-blip/Hilatv/pull/24) | 已合并。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T05 | N1 需求理解 + 行业默认值表 | T02, T03 | ✅ | [t05-n1-brief](https://github.com/jeusgbhshs-blip/Hilatv/pull/25) | 已合并。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T06 | N4 脚本 + N5 分镜 | T05 | ✅ | [t06-script-storyboard](https://github.com/jeusgbhshs-blip/Hilatv/pull/26) | 已合并。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T07 | N6 TTS + 时间戳回写 | T04, T06 | ⬜ | – | |
| T08 | N8 关键帧 + N10 图生视频 | T04, T06 | 🔵 | [t08-keyframe-video](https://github.com/jeusgbhshs-blip/Hilatv/pull/28) | 验收中。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
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
- 合并了哪些：T01（PR #21）、T02（PR #22，`t02_business_0001`）、T03（PR #23，`t03_gateway_0002`）、T04（PR #24，无新迁移）、T05（PR #25，无新迁移）、T06（PR #26，无新迁移）
- 正在做什么：T08 N8 关键帧 + N10 图生视频，分支 `t08-keyframe-video`。无 Key，`make accept-t08` 走 mock。不新增迁移，Alembic 仍是单一 head `t03_gateway_0002`
- 需要提供什么：LLM / 图像 / 视频 / TTS 的 Key，以及非零预算后才可打开 `HILATV_LIVE=1`

## T08 假设

- N7 锚点和 `product_composite` 实拍合成留给 T13。N8 仍为每个可生成镜头出关键帧。`product_composite` 的提示词把产品写成无标识的占位体，不在这里做抠图合成。没有锚点图时，场景句用 `scene_ref`，风格句用 Brief 的 `style`。调用方可以另给一段文字描述。
- `motion_graphics` 不调用图像或视频模型，留给渲染层 / T14。验收里的「每镜 ≥ 3 候选」统计可生成镜头。参数镜和行动号召镜被跳过。
- 需要尾帧的运镜是 `gentle_arc`、`slow_push_in`、`slow_pull_back`、`rise_reveal`，外加 `generation_mode=first_last_frame`。N5 目前不会写出 `first_last_frame`。尾帧与首帧共用同一组 seed，选中的尾帧与选中的首帧是同一个 seed。
- 关键帧和视频都默认 4 条候选（不少于 3，不超过 8）。视频候选用不同 seed。网关路由按镜头族选模型；可灵、万相还没有 adapter，没 Key 时也会落到 mock。候选上的 `model` 是实际跑起来的模型（mock 下是 `mock-image` / `mock-video`）。提示词模板跟路由表里的首选模型名走，所以人物镜用可灵模板，氛围镜用万相模板，产品和 Seedance 用各自的模板。
- 镜头族：目的里有「人物」或引用以 `person:` 开头 → `person`；`reference_to_video` 且至少两个引用、又不是人物 → `multi_ref`；`product_composite`、`reference_to_video` 或带 `product:` 引用 → `product`；其余 → `atmosphere`。`motion_graphics` 不进路由。
- 产品镜头运动强度强制为 `low`。氛围镜头若预设是 `low`，提高到 `medium`。其余沿用镜头语言库里的强度。
- 生成时长：`duration_s + 2 × 余量 ≤ 5` 时用 5 秒，否则用 10 秒。余量默认 0.2 秒（`HILATV_TRIM_MARGIN_S`）。裁切窗口长度等于 `duration_s`，起点是首部余量，尾部余量是生成片里剩下的部分。对象存储里拿得到字节时，用 ffmpeg 重编码这个窗口，候选 `uri` 指向裁后的文件。只有 `mock://`、没有字节时，保留裁切参数和原 uri。验收用内存对象存储，所以文件会被真正裁短。mock 视频改成按请求的 `duration_s` 出片；不传时长时仍是 1 秒，原有测试不变。
- T12 之前不做 VLM 打分。每条候选带一个占位 `QAReport`（`evaluator=rule-select-v0`，五项都是 8）。每个镜头只选 1 条首帧：若有候选的模型等于路由首选模型就选它，否则选最小 seed。尾帧选同一个 seed。视频同样。
- 画面文字、Logo、价格、电话从提示词里删掉，并写入网关那条「无文字」负面约束。屏幕上的徽章句子不会进提示词。
- 镜头级并行，线程数默认 4（`HILATV_SHOT_WORKERS`）。一个镜头抛错只记日志，不取消其他镜头。节点重试时只重跑还没成功的镜头。超时仍让整个节点失败。
- 候选就是第 5 章的 `Candidate`，节点结果里的 JSON 就是 `candidates.document` 的形状。只有调用方给了 `enterprise_id` 且 Postgres 可达时才插入 `candidates` 表。验收不提供企业 id，因此不写库。本任务不新增 Alembic revision，head 仍是 `t03_gateway_0002`。
- N10 一律从 N8 选中的首帧做图生视频，包含分镜里标成 `text_to_video` 的镜头。本任务没有单独的文生视频调用。有选中尾帧时，把地址放进 `last_frame_url`。当前 Seedance adapter 只提交一张首帧图，尾帧地址留在参数里给以后的 adapter。
- 不新增厂商 SDK。路由表里的 `kling` / `wanx` 只是首选名字，没有对应 adapter 时会被跳过。
- `candidate_id` 用 `uuid5(project_id + shot_id + node + frame + seed)`，同一输入重跑结果稳定。
- 验收脚本自己建 mock 网关和内存对象存储，不读 MinIO，也不因为 `HILATV_LIVE=1` 去打真实接口。

## T06 假设

- N3 不在本任务。N4 只读 Brief 和可选 Brand Kit。输出是 `workers.schemas.Script`。N5 在同一份 Script 上写入 `shots`。
- 无 Key 时草稿和自评都走 T03 mock。草稿 schema 用空默认值，mock 不会把 `"mock"` 写进文案。规则拼装器负责交出能过质检的稿。模型稿只有在不含禁用词、数字都能对上出处、钩子不超过 3 秒、卖点不超过 3 条且能在资料里找到时才采用。自评调用失败时不中断，规则质检仍然要过；自评明确给出 false 则重试。
- 中文按汉字、数字和拉丁字母计字，4 字/秒。其他语种按词计，夹在英文里的汉字每个字算 1 个词，2.5 词/秒。目标字数 = 时长 × 速率 × 0.85，允许与目标相差 5%。钩子按未打折的速率，必须在 3 秒内说完。
- 数字只认数字串（含小数），不把「三十」这类汉字数词当数字。出处是 Brief 的原话、must_include、goal、audience、style、video_type、平台、语种和时长，以及 Brand Kit 的企业名、产品名、卖点、禁改项、电话、网址、调性和已授权人物身份。不算 assumptions、色值、OSS 地址和内部 id。
- 有 Brand Kit 时用它自己的 `banned_words`（T02 允许显式短表）；没有则用广告法默认表。卖点先用产品 selling_points，再补 must_include 里还没被覆盖的句子，最多 3 条。证明句只复述资料里已经出现的工厂、认证、检测或客户，没有就写「按资料说明」，不补认证。
- 多语种先写中文母版。其他语种是另一套句式，不是逐句翻译。MOQ、交期、认证只有资料里写了才强调。无 Key 时英文句式把资料原句嵌进去，避免编出新数字。
- 画面文字只放在 `on_screen_text`。视觉描述和提示词都带「无文字、无 Logo、无价格、无电话」。本任务不调用图像或视频模型。
- 宣传片（`video_type` 为 product_showcase、factory_strength、brand_film、corporate，或原文里有「宣传片」）单镜 4–8 秒，其余 2–6 秒。镜头数落在这个区间里，并且不超过时长/2。时长按毫秒摊平，总和等于 Brief 时长。
- `generation_mode` 的优先级：参数、流程、行动号召用 `motion_graphics`；已授权且有照片、并且至少两镜连续出镜的人物用 `reference_to_video`；卖点镜有抠图用 `product_composite`，只有原图用 `reference_to_video`，没有真实产品图用 `image_to_video`；钩子和证明这类空镜用 `text_to_video`。本任务没有场景静帧。N5 的四条规则没有 `first_last_frame`，所以不用它。单镜成片时人物不算连续出镜。
- 产品首次出现看 `subject_refs` 里第一个 `product:`，景别只能是 `medium` 或 `close_up`。景别用 `wide` / `medium` / `close_up`。人物镜不挂产品引用。第二个及之后带数字的卖点改成参数镜，数字卡片由后期叠加。
- 不新增数据库迁移。Alembic 仍是单一 head `t03_gateway_0002`。
- 镜头语言库是自写 YAML，每个预设有提示词片段和推荐模型名。SPEC 第 9 章的「每预设 20 次测试」不在本任务。
- `script_id` 用 `uuid5(project_id + brief_id + language)`，同一输入重跑结果稳定。验收把网关日志放到独立 SQLite。

## T05 假设

- Brief 没有行业字段。行业只用来选择 `templates/industries/` 里的 6 份模板，并写进 `assumptions`。原话判断不了时，若输入里带了 Brand Kit，就沿用它的 `industry`；仍然没有，就先按制造业继续，并提一个带默认项的问题。
- 无 Key 时 LLM 走 T03 mock。抽取模型的字段都有空默认值，mock 不会填出 `"mock"` 这种假值。时长、平台、语种、比例、类型先从原话用规则抽出，空的再用行业模板补，并在 `assumptions` 里说明。Live 模型只填空位，不覆盖原话里已经写明的事实。
- 只有会改掉成片走向、且模板不能唯一决定的缺口才追问，最多 2 个，推荐项同时写进 Brief：行业不明、同一行业有多种主推类型且原话没点明、用户指定的比例不被该平台接受。其余缺口只写 `assumptions`。推荐默认值已经落在 Brief 里，流程不阻塞。
- 平台和比例的允许关系是自建的：抖音 / TikTok 以 9:16 为主，YouTube / 官网以 16:9 为主，视频号两者都允许。某个平台在当前比例里一个都对不上时，补上该平台的推荐比例。
- 时长超出 5–180 秒时夹到边界并写入 `assumptions`，质检看到的是夹完之后的值。
- 网址用 httpx 抓取，HTML 用标准库解析，按 UTF-8 解码。PDF 文本用 pypdf（BSD-3-Clause，已写入 `docs/licenses.md`）。图片分类先看文件名和 alt；判断不了再经 gateway 做一次文本分类，不把像素送给视觉厂商，也不引入视觉 SDK。
- 制造业和外贸在没有工厂成片附件时写入「未提供工厂视频，使用 AI 生成工厂场景」，与 SPEC §5.2 示例一致。Logo、价格、电话只作为需求记录，提示词写明后期叠加。
- 不新增数据库迁移。Brand Kit 由调用方放在输入 JSON 里，本任务不实现 N2。`brief_id` 用 `uuid5(project_id + raw_input)`，同一输入重跑结果稳定。
- 验收脚本把网关日志放到独立 SQLite，不依赖 Postgres。`HILATV_LIVE=1` 且有 Key、预算大于 0 时走真实 LLM，此时只校验 Brief 合法，不锁定 mock 下的字段级期望。

## T03 假设

- Postgres 上的 `call_logs` / `alerts` 只由 Alembic revision `t03_gateway_0002` 创建，单一 head。网关不再自带建表 SQL。单元测试仍用 SQLite，在进程内建同结构的表。
- `generate_text(..., schema=Brief)` 接受任意 Pydantic 模型或 JSON Schema 字典。测试里的 Brief 按 SPEC §5.2 字段自建，不改 T02 的模型模块。
- 真实 LLM 只用 httpx 打 OpenAI 兼容接口（DeepSeek / 通义 compatible-mode / 火山方舟）。不引入厂商 SDK。方舟的 model 常是接入点 ID，可用 `ARK_MODEL` 覆盖路由表。
- 单价在 `gateway/pricing.yaml`（CNY / 1M tokens），按公开价近似，可改配置。未返回 usage 时按约 4 字符 1 token 估算，输出按 512 token 预估。
- 预算「日」是 Asia/Shanghai 自然日。只累计 live 且非缓存命中的 `cost_cny`。失败、超时、缓存、mock 记 0。`HILATV_LIVE!=1` 或没有 Key 时直接 mock，不发 `budget_exceeded`。仅当 live adapter 可用但预估会使总额或当日额达到上限时才回退 mock 并告警。
- `alerts` 每次超限一行；`docs/progress.md` 相同文案不重复追加。总上限调高后无需重启（每次调用重读环境变量）。
- 缓存键含规范化输入、seed 和路由指纹。预算回退的 mock 结果不写入缓存。Redis 不可用时用进程内缓存，CI 无 Redis 仍可通过；单元测试用 fakeredis 覆盖 Redis 客户端。
- 图像/视频提示词在网关追加「无文字 / 无 Logo / 无价格 / 无电话」负面约束。非 LLM 任务本任务只有 mock。全部候选都失败时抛 `GatewayError`（已记错误日志）。`qa_score` 列先空着。

## T04 假设

- 图像、视频、TTS 各接 1 家，全部用 httpx。不引入厂商 SDK，也不引入 boto3 / MinIO SDK。对象存储是自写的 SigV4 客户端：本地 MinIO 用 path-style，生产阿里云 OSS 把 `S3_ADDRESSING=virtual`。返回的 URI 默认 `oss://bucket/key`（`HILATV_OBJECT_URI_SCHEME=s3` 可改）。
- 图像是火山方舟 Seedream，`POST /images/generations`，默认同模型 `doubao-seedream-4-0-250828`。该接口是同步的，不轮询。请求里 `watermark: false`。当前文档没有 `seed` 字段，live 请求不传 seed；seed 仍进入缓存键和调用日志。`SEEDREAM_API_KEY` 为空时用 `ARK_API_KEY`。
- 视频是火山方舟 Seedance，`POST/GET /contents/generations/tasks`，默认模型 `doubao-seedance-1-0-pro-250528`。状态：queued / running / succeeded / failed / cancelled / expired。`watermark: false`。轮询间隔 `HILATV_POLL_INTERVAL_S`（默认 2 秒），总超时用路由 `timeout_s`。时长按 2–10 秒取整，默认 5 秒。
- TTS 用豆包语音 v1 HTTP `POST /api/v1/tts`（官方标为不推荐，但一次返回 base64 音频，并用 `with_timestamp=1` 取字级时间戳）。需要 `VOLC_TTS_APP_ID` 和 `VOLC_TTS_API_KEY`。鉴权头是 `Bearer;{token}`。`zh_male_steady` 映射到 `zh_male_M392_conversation_wvae_bigtts`。时间戳统一成秒。v3 流式接口未接。
- 画面上的文字、Logo、价格、电话继续只靠网关负面约束，不让图像/视频模型画。Mock 图是纯色 PNG，mock 视频是 ffmpeg `color` 源加 libx264，不用 drawtext。
- 单价写在 `gateway/pricing.yaml`，是配置不是合同：图像按张 ¥0.20，视频按秒 ¥0.50，TTS 按千字 ¥2.00。模型不在表里时用 `task_defaults`。视频即使厂商返回 token，也按秒计。
- 没配对象存储时，mock 仍返回 `mock://`，好让 T03 单测不用 MinIO。配了存储之后，图像/视频/TTS 必须转存成功才返回 `oss://`。Live adapter 没有存储配置时失败，网关回退 mock。
- 不新增数据库迁移。媒体只进对象存储，调用日志沿用 `call_logs`。Alembic 仍然只有 head `t03_gateway_0002`。
- 没有 Key，本轮不贴真实厂商样例。`HILATV_LIVE=1` 且预算和对应 Key 都有时，`make accept-t04` 会额外各跑一条 live。

