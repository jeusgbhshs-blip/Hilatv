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
| T07 | N6 TTS + 时间戳回写 | T04, T06 | ✅ | [t07-n6-voiceover](https://github.com/jeusgbhshs-blip/Hilatv/pull/27) | 已合并。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T08 | N8 关键帧 + N10 图生视频 | T04, T06 | ✅ | [t08-keyframe-video](https://github.com/jeusgbhshs-blip/Hilatv/pull/28) | 已合并。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T09 | N13 字幕 + N14 包装 + N15 合成 | T02, T07 | ✅ | [t09-render](https://github.com/jeusgbhshs-blip/Hilatv/pull/29) | 已合并。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T10 | Temporal 主工作流 + WebSocket 进度 | T05–T09 | ✅ | [t10-temporal-workflow](https://github.com/jeusgbhshs-blip/Hilatv/pull/30) | 已合并。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T11 | 前端：输入页、进度页、成片页 | T10 | ✅ | [cursor/t11-frontend-pages-3df2](https://github.com/jeusgbhshs-blip/Hilatv/pull/38) | 已合并（9c7e524）。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T12 | N9/N11 质检 + 导演 Agent 决策循环 | T08, T10 | ✅ | [cursor/t12-qa-director-cdd4](https://github.com/jeusgbhshs-blip/Hilatv/pull/40) | 已合并（7a7725f）。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T13 | N7 锚点 + 产品合成模式 | T08, T12 | ✅ | [cursor/t13-anchors-composite-f261](https://github.com/jeusgbhshs-blip/Hilatv/pull/47) | 已合并（d326c69）。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T14 | 降级方案 6.10 | T12, T13 | ⬜ | – | |
| T15 | N3 方案卡 + N2 Brand Kit 后台 | T10, T11 | ✅ | [t15-brand-concept](https://github.com/jeusgbhshs-blip/Hilatv/pull/44) | 已合并（5e15a75）。假设见下方 |
| T16 | N18 对话改稿 + 版本管理 | T10, T12 | ✅ | [cursor/t16-n18-revision-2fcd](https://github.com/jeusgbhshs-blip/Hilatv/pull/45) | 已合并（70e1553）。改稿历史走 `/revisions`。假设见下方 |
| T17 | 多比例、多语种导出 | T06, T09, T10 | ✅ | [cursor/t17-multi-export-9a5c](https://github.com/jeusgbhshs-blip/Hilatv/pull/42) | 已合并（a44d931）。比例、语种、时长仍走 `/versions`。假设见下方 |
| T18 | eval/ 基准测试 + 报告 | T10, T12 | ✅ | [t18-eval-benchmark](https://github.com/jeusgbhshs-blip/Hilatv/pull/31) | 已合并（bbe69f9）。只有 `visual_reviewed is True` 算已评审。假设见下方 |
| T19 | 专家模式画布 | T10, T11, T12 | ⬜ | – | |
| T20 | 合规：AI 标识、内容审核、授权存档 | T09, T15 | 🔵 | [cursor/t20-compliance-49e6](https://github.com/jeusgbhshs-blip/Hilatv/pull/49) | 验收中。显式角标按解码帧量字高。授权记录用 N12 的 `LicenseRecord`。无新迁移，head 仍是 `t03_gateway_0002`。假设见下方 |
| T21 | N12 音乐与音效 | T07, T09, T10 | ✅ | [cursor/t21-n12-music-2ceb](https://github.com/jeusgbhshs-blip/Hilatv/pull/46) | 已合并（18cf1ff）。无新迁移。假设见下方 |
| T23 | 分镜预览（可跳过） | T11, T16 | 🔵 | [cursor/t23-storyboard-preview-acde](https://github.com/jeusgbhshs-blip/Hilatv/pull/51) | 验收中。N9 之后可暂停看分镜。假设见下方 |
| SEC-01 | 素材链接防 SSRF | T05 | ✅ | [sec01-ssrf](https://github.com/jeusgbhshs-blip/Hilatv/pull/43) | 已合并（d845705）。无密钥。假设见下方 |
| T25 | 其余 4 套行业模板 + 镜头语言库首批 | T05, T06 | ✅ | [cursor/t25-industry-templates-3f0b](https://github.com/jeusgbhshs-blip/Hilatv/pull/41) | 已合并（66306cc）。预设全部「试用」，未做 20 次实测。假设见下方 |

状态：⬜ 未开始 · 🟡 开发中 · 🔵 验收中 · ✅ 已合并 · ⛔ 阻塞

## 密钥 / 账号（mock ↔ live）

| 项目 | 用于 | 状态 |
|---|---|---|
| LLM Key（DeepSeek / 通义 / 豆包 任一） | T03+ | mock |
| 图像 Key（如 Seedream） | T04, T08, T13 | mock |
| 视频 Key（如 Seedance / 火山方舟） | T04, T08 | mock |
| 豆包/火山 TTS Key（公司已有） | T04, T07 | mock |
| 豆包/火山 ASR Key | T07 | mock |
| VLM 评审 Key | T12 | mock |
| 内容安全服务 Key | T20 | mock |
| 音乐 Key（Mureka / Suno，须先确认商用授权） | T21 | mock。未购买曲库 |
| 预算上限 `HILATV_BUDGET_CNY` / `HILATV_DAILY_BUDGET_CNY` | 网关 | 未设置（= 不允许 live） |

## 告警（预算超限等，由网关自动追加）

<!-- 例：- 2026-11-05 14:20 budget_exceeded：已花费 ¥xxx / 上限 ¥xxx，live 调用已暂停并回退 mock -->

<!-- hilatv:alerts -->

## 上线前

- 导出并发上限只在单个 API 进程里计数（`apps/api/app/deliveries.py` 的 `_EXPORTS_IN_FLIGHT` 和线程锁，环境变量 `HILATV_N17_EXPORT_SLOTS`，默认 2）。多 worker 时每个进程各算各的，总并发会按进程数放大。上多进程之前要换成跨进程锁（Redis 或数据库）。

## 上线前合规（未做，待 song / 法务）

- 用户协议文本：若将来按《人工智能生成合成内容标识办法》第九条提供无显式标识文件，须在协议里写明用户的标识义务和使用责任，并留存提供对象日志不少于六个月。当前产品拒绝去掉标识，这条协议还没写。
- 生成式人工智能服务备案或安全评估：上线前咨询山东省 / 青岛市网信部门，确认要办的手续。本仓库不代办。
- 安全事件处置机制：还没有事件分级、上报路径和值班约定。
- 日志留存不少于 6 个月：调用日志和标识相关日志的保留期还没按这个下限落地。
- 内容安全厂商、接口和单价（`content-security` 在 `gateway/pricing.yaml` 里只是占位）待 song 确认后才能打开 live。
- 服务提供者编码 `HILATV_CONTENT_PRODUCER`、隐式标识 HMAC 密钥，以及短于 2 秒的成片是否允许导出（`HILATV_AI_LABEL_MIN_S`），待 song 确认。

## 每日日志

<!-- 模板：
### YYYY-MM-DD
- 合并了哪些：
- 正在做什么：
- 需要提供什么：
-->

### 2026-10-30
- 合并了哪些：main 现为 `70e1553`（T16 PR #45）。同日已在 main：T13、T21。都无新迁移
- 正在做什么：T23 分镜预览。关键帧质检之后可以停下看卡片、改一镜旁白；选了直接出片就不停。无 Key，`make accept-t23` 走 mock。mock 没有可看的关键帧，画面预览记未测。Alembic 仍是单一 head `t03_gateway_0002`
- 需要提供什么：LLM / 图像 / 视频 / TTS / ASR / VLM 的 Key，以及非零预算后才可打开 `HILATV_LIVE=1`。音乐商用授权仍未批。校准用的 200 张人工打分图。T25 的预设转正要等 Key 之后另做 20 次实测

### 2026-10-30
- 合并了哪些：main 现为 `18cf1ff`（T21 PR #46）。更早同日已在 main：T09–T12、T15、T17、T18、T25、SEC-01。都无新迁移
- 正在做什么：T16 对话改稿。改稿历史用 `/revisions`，比例语种时长仍用 T17 的 `/versions`。无 Key，改稿走 mock。方案卡若是模板兜底（`/v1/concepts` 可 200 且 ok=false），成片页会标明，版本不能标成质检通过。重生次数只记在 `regen_budget.json`。Alembic 仍是单一 head `t03_gateway_0002`
- 需要提供什么：LLM / 图像 / 视频 / TTS / ASR / VLM 的 Key，以及非零预算后才可打开 `HILATV_LIVE=1`。音乐商用授权（Mureka/Suno 或正版曲库）要另批，未批之前保持 mock。校准用的 200 张人工打分图。T25 的预设转正要等 Key 之后另做 20 次实测。T18 的 60 条样例仍待换成真实企业需求

## T21 假设

- 旁白目标是 -16 LUFS，成片目标是 -14 LUFS。SPEC 没有写容差。成片按 -14 ± 1 LU 验收，旁白同样按 ± 1 LU 当作「附近」。这是假设，不是 SPEC 里的数字。
- 压低量取区间中点 11 dB。测量的是旁白区段里、躲开点击之后的底乐：未压低的音乐和压低后的音乐用 ffmpeg `volumedetect` 的 mean volume 相减。节拍误差用渲染出来的音乐文件重新检测，不拿节点自己记下的节拍表跟切点比。
- 响度用 ffmpeg `ebur128` 的 Integrated loudness。旁白和成片分开测。成片的电平只靠抬或压背景乐，不改已经归一到 -16 的旁白，这样压低比例不会被整轨增益冲掉。
- 无 Key 时音乐走 gateway `music`，路由仍是 mock。Mock 按情绪从仓库内的测试曲库挑一条，节拍是代码合成的点击加底乐，许可证记 `CC0-1.0`，来源是 `hilatv-test-library/...`。音效同样是代码合成的短声，来源是 `hilatv-test-sfx/...`。没有第三方录音，也没有把音频文件放进仓库。
- 画面切点对齐：**未达标 / 遗留**。T10 成片仍按 N6 时长切画面，没有把 N12 对齐后的时长写进时间轴，也没有在成片上量切点。计划切点和测试曲点击落在同一网格上只是内部一致性检查，不能当作 SPEC 的 ≤80ms 验收。后续任务：把 N12 的对齐时长接到 T10 时间轴，并在最终成片上测量切点误差。
- 压低量是从成片混音里减去旁白后，比较旁白区段和空隙区段的响度，不是拿未压低文件和乘上固定增益的副本互比。成片整体响度除了混音 wav，还用 ffmpeg `ebur128` 量 N15 导出的 mp4 音轨，目标 -14 ± 1。
- T20 还没在 main 上。授权记录定义在 `workers/nodes/n12_music/schema.py` 的 `LicenseRecord` / `LicensingSummary`。除了 `source` 和 `license`，还有 `evidence_ref`（授权证明）、`expires_on`（到期日，CC0 测试音记 `none`）、`usage_scope`（使用范围）。T20 以后应原样收进成片授权说明。缺任一项时 N12 不交出音轨。`HILATV_LIVE=1` 时拒绝用 mock 测试曲库的 CC0 许可证交付。
- N12 与 N13、N14 并行，都进 N15。N15 只增加可选的 `audio_track` 和 `licenses`。三条导出（成片、无字幕、无配音）的滤镜结构没改。没有音轨时行为和 T09 一样。无配音版仍然去掉全部音轨。
- 不接用户上传音乐做 MV。不新增 Mureka/Suno adapter，`.env.example` 里这两个 Key 留空。不新增 Python 依赖，也不新增迁移。Alembic head 仍是单一 head `t03_gateway_0002`。
- 画面上的字、Logo、价格、电话仍只由 N13/N14/N15 叠加。音乐提示词要求无歌词、无口播、无文字。

- T18：60 条基准需求的 mock 评分表。`make accept-t18` 走 N1–N5，并调用已合并的 T12 `review_shot`。mock 没有画面，镜头标为未评审。T12 导入不到时记 `review_error`，不再用网关单独打分。报告分开写「管线和报告结构」和「质量是否达标」。需要团队提供真实企业需求替换 `eval/briefs/`；VLM Key 与非零预算后，`--mode live` 才会让视觉评审看实帧
- 需要提供什么：LLM / 图像 / 视频 / TTS / ASR / VLM 的 Key，以及非零预算后才可打开 `HILATV_LIVE=1`。校准用的 200 张人工打分图。T11 本身不调用模型。T25 的预设转正要等 Key 之后另做 20 次实测。SEC-01 的 URL 测试用 mock 解析器，不走真实网络
- T20：合规标识、内容审核和素材授权说明。无内容安全 Key，`make accept-t20` 走 mock。内容安全厂商、服务提供者编码和 HMAC 密钥待 song 确认

## T20 假设

- 显式标识用角标「AI生成」（含「AI」和「生成」）。依据《人工智能生成合成内容标识办法》第四条第四项：视频在起始画面的适当位置添加显著提示标识；第五条：文件元数据写入内容属性、服务提供者名称或编码、内容编号。办法成文 2025-03-07，国家网信办 2025-03-14 公布（国信办通字〔2025〕2号），2025-09-01 施行。文本：https://www.gov.cn/zhengce/zhengceku/202503/content_7014286.htm 。字高按墨迹包围盒量，不少于画面短边的 5%（GB 45438-2025 §5.4），从第一帧起停留不少于 2 秒。短于 `HILATV_AI_LABEL_MIN_S`（默认 2）的成片拒绝导出，是否放宽待 song 确认。
- 隐式标识按 GB 45438-2025 附录 E 和 TC260 视频实践指南，用 ffmpeg `-metadata AIGC` 加 `-movflags use_metadata_tags` 写入 `moov.udta.meta`。七个字段是 Label、ContentProducer、ProduceID、ReservedCode1、ContentPropagator、PropagateID、ReservedCode2。ContentProducer 读 `HILATV_CONTENT_PRODUCER`（占位 `PENDING-SONG-CONFIRM`，待 song 确认，不用产品名 HiLatv）。每次渲染新建 ProduceID。ReservedCode1 是这些字段的 HMAC；mock 用测试密钥，live 没有 `HILATV_AIGC_HMAC_KEY` 就拒绝签名。
- 推断：不实现办法第九条的「无显式标识导出」。改稿指令「去掉 AI 标识」、`omit_ai_label` 之类的开关、以及 N18 的 `RevisionDirective` 都会被拒绝。N15 即使收到一份没有角标的元素表，也会自己再画一层。
- 内容安全是网关任务 `content_safety`。无 Key 或 `HILATV_LIVE` 关闭时走 mock，费用记 0。mock 在文本含 `HILATV_UNSAFE_SAMPLE` 时判定不通过。推断：live adapter 向 `{CONTENT_SAFETY_BASE_URL}/moderate` 发送 `{"text","stage"}`，这只是占位，不是某一家云厂商的正式协议。
- 输入审查在编码前，输出审查在成片写入之后。任一次不通过都不会把结果当成交付。极限词沿用品牌 `banned_words`，没有品牌表时用广告法默认表（「最」是子串，可能命中「最后」这类词，这是现有 `find_banned_words` 的行为）。医疗、食品、金融是关键词标记，不单独阻断文件。行业模板上的 `manual_review`（目前只有政企为 true）同样只打人工审核标记，不阻断。
- 人物和克隆声只从 `enterprise_id` 对应的品牌档案取出，再经 `people_for_use` / `release_kit`。请求里的 `brand_archived` 和自报 `consent=true` 不作数。旁白 `voice_id` 只允许两处：网关服务端内置表 `BUILTIN_TTS_VOICES`（`zh_male_steady`、`zh_female_steady`、以及豆包映射 `zh_male_M392_conversation_wvae_bigtts`），或该企业档案里已经放出的克隆声。请求资料里有没有这个人，都不参与判断。表外且档案没有的 `voice_id` 拒绝。`zh_female_steady` 是 N18 的库存女声，不是克隆。
- 授权记录只用 main 上 N12 的 `LicenseRecord` / `LicensingSummary`（`workers/nodes/n12_music/schema.py`），没有第二套类。T20 只把 `kind` 扩成也包含 `font` 和 `voice`，给字体和库存旁白用。缺来源、许可、证明、到期或使用范围时，沿用 N12 的 `incomplete_reason` 阻断。`expires_on` 为 `none` 表示不到期；ISO 日期早于今天（上海时区，当天仍有效）也阻断。`HILATV_LIVE=1` 时拒绝 `hilatv-test-` 来源和 `CC0-1.0` 测试曲库许可，与 N12 相同。
- 素材说明写在项目目录 `compliance/materials-and-licences.txt`，路径由服务端生成。客户给的绝对路径必须落在项目目录内。http(s) 证明默认只做 SSRF 分类，不下载；`HILATV_FETCH_LICENCE_PROOF=1` 时才经 SEC-01 的 `fetch_bytes` 拉取。
- 不新增 Alembic revision，head 仍是 `t03_gateway_0002`。备案登记和私有化部署不在本任务。

## T18 假设

- 60 条是自写的企业口吻样例，按 6 个行业各 10 条放在 `eval/briefs/*.yaml`。团队收集的真实需求还没到。替换这些句子后，同一条命令会改跑新句子。
- `make accept-t18` 是 mock：按 T10 的顺序调用 N1、N2 读取、N3 自动选定、N4、N5。不启动 Temporal，也不编码 MP4，因此没有关键帧或视频。`--mode live` 才调用 `workers.workflow.service.run_and_wait`，走出片工作流。
- 评测调用已合并的 `workers.qa.service.review_shot`。调用前的画面检查与 `workers.qa.pixels` 相同：拒绝 `http`/`https`、`mock://`，以及解析后落在 `HILATV_PROJECT_DIR` 外面的路径。图片要能解码；视频要能在项目目录里抽出帧。打不开就不调用。返回只有 `visual_reviewed is True` 才算已评审。Mock 下 T12 不把规则分 8.6 或无画面的分数当成看过画面。调用或结果解析抛错记 `review_error`。`coerce_judge` 缺维度报错，标为无效。
- 有选中视频候选时，评审节点记 `n11_video`，模型名用候选上的 `model`。mock 只有分镜，节点记 `n09_keyframe`，模型记 `not-rendered`。镜头类型用分镜里的运镜预设 id。
- 硬伤按已评审镜头计：`QAReport.hard_fail` 非空算 1 个硬伤镜头。质量达标要同时满足：60 条都在、失败 0 条、未评审和评审异常都是 0、已评审镜头数大于 0，并且硬伤率不超过 5%。分母为 0 不能算通过。失败或超时的样例即使镜头数记成 0，也不能让其余样例单独达标。
- 报告和 `summary.json` 写评审来源、未评审镜头数，以及两个结论：管线和报告结构是否完整、质量是否达标。`--strict` 的退出码只看结构和「未评审被当成质量通过」这种假通过。mock 没有画面，质量结论是未达标，验收命令仍然可以在 CI 里跑完。
- 没有可打开的画面时不调用 T12，报告写「只评了文字，不计入质量结论」。`review_shot` 导入不到时该镜记 `review_error`，算进未通过，不再另走网关打分。
- 状态接口读 `project.json` 时，写入改为先写临时文件、`fsync`、再替换，然后 `fsync` 目录。`Path.write_text` 会先把目标截成空文件，CI 里 `test_create_progress_and_rerun` 的进度轮询因此读到空 JSON。替换之后读者看到的是上一份完整文件或新文件；目录 fsync 让新文件名落盘。
- 盲评包只给匿名 pair id 和成片路径。对照组成片不在本任务里，key 里标 `withheld`。
- 费用是该项目在网关 `call_logs.cost_cny` 的合计。mock 为 0。调用仍经过网关预算守卫。
- 耗时是单条样例的墙钟秒。mock 不拿它去卡 SPEC §1.4 的 15 分钟。
- 画面文字、Logo、价格、电话仍只留在分镜的 `on_screen_text`。评审提示词要求模型不要把它们画进画面。
- 不新增数据库迁移。Alembic head 仍是 `t03_gateway_0002`。
- 样例句子都写了 15 秒，避免 mock 跑出行业模板里的 30 秒或 60 秒分镜。N1 若仍留下开放问题，不挡住评分。
- 已把 main `7a7725f`（T12）合并进本分支。评测调用真实的 `workers.qa.service.review_shot`。画面能不能打开与 `workers.qa.pixels` 同一范围：拒绝 `http`/`https`、`mock://`，以及 `HILATV_PROJECT_DIR` 以外的路径。只有返回里 `visual_reviewed is True` 才算已评审。

- 合并了哪些：T09（PR #29，无新迁移）、T10（PR #30，无新迁移）。main 现为 `d845705`（含 T11、T25、SEC-01）
- 正在做什么：T12 N9/N11 质检和导演决策循环，已合入最新 main。无 Key，`make accept-t12` 走本地规则和 mock judge。埋入坏图拦截率 47/47，质检未校准（0/200）。T11 输入页、进度页、成片页。SEC-01 拦住 N1 抓用户链接时访问本机和内网。T25 补电商、本地生活、教育、政企模板和镜头预设（全部「试用」）。Alembic 仍是单一 head `t03_gateway_0002`
- 合并了哪些：T09（PR #29）、T10（PR #30）、T11（9c7e524）、T25（66306cc）、SEC-01（d845705）、T12（7a7725f）。都无新迁移
- 正在做什么：T17 多比例、多语种导出和成片页版本切换。合并前补上：缺质检字段不算通过，deliveries.json 先 fsync，mock 听写不计入核对，并发上限按进程。无 Key，`make accept-t17` 走 mock。Alembic 仍是单一 head `t03_gateway_0002`
- 需要提供什么：LLM / 图像 / 视频 / TTS / ASR / VLM 的 Key，以及非零预算后才可打开 `HILATV_LIVE=1`。校准用的 200 张人工打分图。T11 本身不调用模型。T25 的预设转正要等 Key 之后另做 20 次实测。SEC-01 的 URL 测试用 mock 解析器，不走真实网络

### 2026-10-30 T13
- 合并了哪些：main 为 `5e15a75`（T15、T17、T12、SEC-01 已在 main）。本分支从这份 main 拉出，没有改 SPEC。
- 正在做什么：N7 产品锚点、人物三视图、场景和风格锚点、`product_composite`。`make accept-t13`：deformation=未测形变，pixel_matches=6405，face_cosine_min=0.939（阈值 0.75，正/侧/背不是镜像）。三视图失败不写锚点、不扣重生次数。
- 需要提供什么：没有新的 Key。BiRefNet / RMBG / IC-Light 权重未接入。测试图是代码绘制的。

## T13 假设

- 抠图和重打光是网关任务 `matte`、`relight`。路由指向 `local_matting`（接口名 `birefnet-rmbg-2.0-local`）和 `local_relight`（接口名 `ic-light-local`）。没有下载 BiRefNet、RMBG-2.0 或 IC-Light 的权重。抠图仍调用 `workers.brand_kit.matting` 的纯色去底。重打光只在产品下方压暗并加一条浅反射，然后把 alpha 为 255 的产品像素按原图 RGB 抄回去。这两项 `billable` 为 false，费用记 0，不看 `HILATV_LIVE`。注册表里没有本地适配器时，mock 走同一段代码。
- 产品合成不做透视重采样，所以不能拿「把同一张抠图再贴一遍」的余弦当成形变分。候选参数写 `deformation=未测形变`，不写 similarity。N11 的 0.90 阈值仍只用于 N11。这里核对的是 alpha 为 255 的像素和原图 RGB 是否一致。
- 透视四边形记在候选参数里（上边内收最多 4 像素），不拿去重采样抠图。重采样会改掉 Logo 和包装。比对的是合成图里 alpha 为 255 的区域和原图 RGB，原图与合成图不是同一个文件。半透明边缘可以和背景混合。
- 人物三视图只采用图像网关交回的三张图。余弦低于 0.75、三张里有重复或镜像、或画面有乱码，节点失败，状态是需要人工确认，不把任何锚点写入品牌库，也不为了换一张卡通脸去扣重生次数。节点不会自己画脸。验收用的正、侧、背是三张不同的图（侧视是侧面，背面是头发和脖子，不是正面的镜像）。嵌入仍是 N11 的 8×8 肤色亮度网格，阈值 0.75。人物只从 `release_kit` / `people_for_use` 来。档案外的 inline kit 即使自报 `consent=true` 也没有人。未授权的人及其照片不会出现在结果里。
- 场景图走图像网关，提示词带「无文字」。`garbled_text` 或 `extra_text` 会通过 `open_project_budget` 再花一次项目重生额度，额度用完就停。没有单独的 3 次上限。风格锚点是品牌色条，另外保存一张通过文字检查的氛围图。画面上的字、Logo、价格、电话不交给模型画。
- `/v1/concepts` 的结果可以是降级的。`template_fallback`、`degraded=true` 或 `ok=false` 记成 `concept_status=degraded`、`concept_passed=false`，风格改用 Brief，不用方案卡上的风格词。节点 `ok` 只表示锚点做完了，不表示方案卡通过。
- 重生预算只在 `workers.qa.budget_store.open_project_budget`。这是其他任务（包括 T16）要调用的唯一接口。文件是 `{HILATV_PROJECT_DIR}/{project_id}/regen_budget.json`，加锁并 fsync，只增不减。它不写入项目快照或版本快照。版本回滚不能把 `used` 改小，也不能用旧文件盖掉它。上限仍是 `HILATV_QA_PROJECT_RETRIES`（默认 12）。N7、N9、N11 都读这一份。
- 合成镜头的 `counts_as_reviewed` 等于 `review_shot` 返回的 `visual_reviewed`。只有该值为 true 且 `is_quality_pass` 时才 `selected`。Mock 评审看不到实帧，`visual_reviewed` 为 false，不把这张图当成已审通过。
- 产品图地址只接受 `image_b64`、本企业的 `brand://`，或 http(s)。http(s) 走 SEC-01 的 `fetch_bytes`。调用方传来的文件路径直接拒绝。写出的文件由节点生成，`resolve` 之后必须在项目目录里。
- N7 没有放进 T10 的 `PIPELINE`。那条链路仍是配音之后直接关键帧。产品合成候选的 `node` 是 `N7`，调用方单独跑 `n07_anchor`。
- 侧面和背面仍用 `workers.brand_kit.complete_angles`，`on_screen` 为 false，复制进品牌库的 `anchors`，不写入 `photos` 或 `cutouts`。同一企业下一次再跑，若抠图和角度还在，就不再调用 `matte`。
- 不新增表，也不新增依赖。Alembic head 仍是 `t03_gateway_0002`。测试用的产品和脸是代码画的，不是客户照片，也不是真实品牌。

## T17 假设

- N17 不进 T10 的 `PIPELINE`。那条链路仍停在 `n15_compose`。成片页在母版就绪后调用 `POST /v1/projects/{id}/deliveries`。导出在这次请求里做完，不另起 Temporal。
- 母版是没有烧字的 16:9（`master_plate`）。主体框由调用方传入，视觉追踪留给 T12。某个镜头没有框时不裁切，整幅模糊填充，并标 `needs_review`。
- 主体能放进目标窗口时，按主体中心裁切，框沿直线移动。主体比窗口更宽或更高时，整幅母版缩小放进画面（contain），空出来的地方用去色模糊填充，这样主体不会被裁掉。`HILATV_N17_REGENERATE=1` 时，竖版改为经网关要一张竖版底图再把母版叠上去；1:1 仍用模糊填充。底图提示词带「无文字」。
- 输出长边默认等于母版长边。`long_edge` 或 `HILATV_N17_LONG_EDGE` 可以改小。验收用 320。
- 语种默认中文和英文，再加 Brief 里的其他语种。本地化先走网关 LLM。Mock 交回空草稿，就用 N4 的规则作者按资料重写，不是逐句翻译。英文句子里可以嵌资料里的中文产品名。配音和 ASR 仍走现有 gateway `tts` / `asr`，不新接 ElevenLabs。画面时长锁在母版上；旁白更长就用 atempo 压进镜头。
- 字幕走 N13。卖点卡、字幕和「AI生成」都是 PNG，落在各平台安全区的并集里。滤镜图里没有 drawtext。
- 时长默认出整段母版。Brief 超过 15 秒且平台含抖音 / TikTok / 视频号时，再出一条 15 秒：保留开头和结尾，去掉中间放不下的镜头。要求的时长比母版还长时，就出母版本身。验收片子是 2 秒（两镜各 1 秒），Brief 时长是 5 秒，所以只有一个时长版本。
- 每个版本都是带配音和烧录文字的成片。N15 的无字幕、无配音文件不按版本再导一份。
- 不新增表。版本写在项目目录的 `deliveries.json`。Alembic head 仍是 `t03_gateway_0002`。
- 分享链接是 `/v1/shares/{token}`，不登录。不发布到抖音、视频号或 YouTube。
- 主体是否出画：验收片在母版上叠一块红矩形（不是字）。检出的红框要和计划框对得上。镜头交界的两帧不参与比对。
- 成片页的比例、语种、时长切换接在 T11 的成片页上，读上面的版本接口。T11 原来的占位换成这组切换。
- 请求体不能指定母版路径。母版只取项目快照或检查点里的地址，`resolve` 之后必须落在该项目目录内，否则 422。符号链接若指到目录外，同样拒绝。
- 没有真实主体框的镜头不裁切，整幅用模糊填充。版本标 `subject_box_source=default`、`qa_status=needs_review`，不算质检通过。有真实框时，几何检查对照调用方的框，并做红框像素检查。
- 同时导出最多 `HILATV_N17_EXPORT_SLOTS`（默认 2）路，超出 429。这个上限只在当前进程里计数，多 worker 见「上线前」。`deliveries.json` 在锁内先 fsync 再原子替换。分享链接默认 7 天，`DELETE .../share` 可撤销。每个版本都要有「AI生成」。`subject_box_source` 和 `qa_status` 缺省是 `default` / `needs_review`，缺字段不算通过。Mock ASR 会回显参考句，配音是否听清记为 `not_verified_in_mock`，验收报告写明 heard-dub check 未在 mock 中核对。真实 ASR（`mock` 不为 true）才把字幕和听到的文本比对。

## T12 假设

- QAReport 仍用第 5 章的五项：`product_fidelity`、`motion_quality`、`aesthetics`、`prompt_match`、`artifact_free`。N9 写的「品牌一致」并进 aesthetics，N11 的「时间一致性」并进 motion_quality，并写在 notes。不改模型，不加迁移。Alembic head 仍是 `t03_gateway_0002`。
- 仓库里没有 DINOv2 权重，也不引入 torch。产品形变是相对边框色的 32×32 占空网格余弦，低于 0.90 记 `product_deform`。视频里任一采样帧低于该值就否决。人脸与锚点的余弦沿用 SPEC 的 0.75。
- 没有云 OCR，也没有人脸 SDK。多余文字和乱码看高对比笔画带；人脸是肤色连通域加上眼睛暗块。分辨率看长边，低于 240px 算不够。这 240 不是 SPEC 里的数字。320×180 的预览可以通过。
- 双评审走网关两条 judge 路由：Qwen-VL（`DASHSCOPE_API_KEY`，模型 `qwen-vl-max`）和 Gemini（`GEMINI_API_KEY`）。没 Key，或 `HILATV_LIVE` 不是 1，都落到 mock。两边总分差 ≥ 2 时取更严的一边。像素规则标出的硬伤不能被 VLM 翻掉。Mock 按 JSON Schema 填出来的全 0 当作「没有意见」，不把它当成 0 分。
- 没有可审像素的镜头不能通过。缺文件、打不开、`mock://` 和坏链接记成错误，`hard_fail` 为 `not_reviewed`，总分为 0，notes 里写明 missing / broken / unreadable。故意无画面（`text_only` 或 `motion_graphics` 且没有媒体地址）同样不能通过，但 notes 写 `media=text_only`，不当成文件错误。导演对这两种都不会返回 pass。
- `QAReport.visual_reviewed` 只有在至少一家视觉评审真正看过实帧（不是 `mock://`、不是缺图或坏图）并且五项分数都合法时才是 true。没图、坏图、mock 评审、评审报错、超时、解析失败、缺维度，以及只靠规则打出的约 8.6 分，都是 false，并且 `hard_fail` 含 `not_reviewed` 或 `judge_unavailable`，不能当成通过。这个字段不在 SPEC 样例里，默认 false，旧 JSON 仍能读。T18 用它区分有没有看过画面。
- `HILATV_LIVE=1` 时两个评审都没有合法意见，镜头失败：`hard_fail` 含 `judge_unavailable`，总分为 0。只回来一个合法评审时，notes 写 `judges_used=1; degraded=true`，`visual_reviewed` 仍可以是 true。缺维度是错误，不补默认分。Mock 不把规则分当成通过。
- 形变余弦、人脸余弦、长边、闪烁阈值和项目级重生上限在环境变量里，默认 0.90、0.75、240、0.22 和 12。相似度必须在 (0, 1]，次数和边长必须是 ≥ 1 的整数。超出范围会在评审开始时抛错，不会悄悄改回默认值。每镜 3 次和 7.5 分不变。项目上限只存在这次进程里，不落盘，持久化留给 T13。用完后再要重生，决策改成 fallback。
- 本地图片和视频路径用 `resolve()` 收进 `HILATV_PROJECT_DIR`（没设时是系统临时目录下的 `hilatv-projects`）。目录外的路径记 `not_reviewed`，不读文件。
- 单评审降级是 QAReport 上的 `judges_used` 和 `degraded`，不只写在 notes 里。一家评审看过实帧时 `judges_used` 为 1、`degraded` 为 true。
- 通过线是总分 ≥ 7.5 且 `hard_fail` 为空。低于 7.5、又不是模型类硬伤，决策是 `regenerate`。产品形变、人脸、闪烁走 `switch_model`。`sensitive` 走 `ask_user`。第 3 次仍失败走 `fallback`，`max_attempts_left` 为 0。降级方案的执行留给 T14，这里只出决策。`max_attempts_left = 3 - attempt`，attempt 从 1 计。
- 导演会经 `gateway.generate_text` 问一次。模型必须给出能通过 DirectorDecision 的 JSON，并且不能把失败镜头改成通过，也不能把次数上限抬高。Mock 不返回合法决策，所以无 Key 时用上面这条规则。
- T10 的 ProduceFilm 测试要求管线里还没有 N9/N11。这次不改那条管线，也不改 PR #31 的分支。单镜循环在 `workers.qa.loop.run_shot_loop`：每次只返回一个决策，由调用方执行重生。
- 拦截率用的坏图是 Pillow 现画的，不是照片，也不是真人脸。平涂车间底，中间一块金属色矩形当产品；促销词和电话用仓库里的思源黑体画上去；乱码是随机笔画；形变是同一块相对锚点做剪切、收腰或鼓包；崩坏脸是椭圆上三只眼睛；另外有黑边、角落周期线、被裁切的主体、过小主体，以及长边只有 96px 的小图。视频是 4fps、8 帧：连续两帧（0.5 秒）形变，或单独一帧白闪。6 个干净对照（5 张图加 1 段视频）不能被标成内容硬伤，也不放进拦截率的分母。Mock 下它们的 `visual_reviewed` 仍是 false。
- 200 张人工打分图不在仓库。校准读 `workers/qa/calibration/manifest.json`。文件不在，或不足 200 张，状态是 `pending_team`。满 200 张之后，排序一致率低于 80% 才会让验收失败。
- N16 只留 `workers.qa.final.review_film`。调用会抛 `NotImplementedError`。
- 画面上的字、Logo、价格、电话仍然只由后期叠加。重生决策的 `changes` 带上现有的无文字负面约束。
- 同一个镜头的候选逐张评审，避免网关日志并发写。

## SEC-01 假设

- 只允许 http/https。DNS 解析后，只要有一个地址是回环、私有、链路本地、保留、多播、未指定、站点本地，或不是全局可达地址，就整段拒绝，并连到校验过的那个 IP。这样同一主机同时给出公网和内网地址时不会被挑到内网，也能挡住解析完再改指向的 DNS rebinding。
- IPv4-mapped IPv6 按里面的 IPv4 判断。NAT64（`64:ff9b::/96`）、6to4、Teredo、已废弃的 IPv4 兼容地址整段拒绝，避免借 IPv6 前缀摸到内网 IPv4。云元数据额外点名 `169.254.169.254`、`169.254.170.2`（ECS）、`100.100.100.200`（阿里云 / 腾讯云，落在 `100.64.0.0/10`，Python 不把它标成 private）、`fd00:ec2::254`。
- 重定向只跟随 301/302/303/307/308，最多 5 次。每一跳重新解析并校验。跳到 `file:` 或 `ftp:` 拒绝。带用户名或密码的 URL 拒绝。不读取 `HTTP(S)_PROXY` / `ALL_PROXY`（`trust_env=False`），避免代理把请求转到内网。调用方传入的 `httpx.Client` 不再用于抓 URL。
- 十进制、八进制、十六进制和缺段的 IPv4（如 `2130706433`、`0177.0.0.1`、`0x7f000001`、`127.1`）先还原成地址再校验，不交给 DNS。
- 超时仍是 `min(HILATV_N1_FETCH_TIMEOUT_S, 节点剩余时间)`，并且包住整条重定向链。`getaddrinfo` 最多用掉剩余时间，超时就停。请求带 `Accept-Encoding: identity`。若响应仍是 gzip 或 deflate，解压时按块计数，超过 `HILATV_N1_FETCH_MAX_BYTES`（默认 2_000_000）就停，避免压缩包膨胀。抓取失败记在附件 `error` 上，不中断 Brief。不新增环境变量，也不新增依赖。
- T05 画册验收不再监听 `127.0.0.1`。夹具用保留域名 `assets.hilatv.test`，测试解析器把它指到公网地址 `93.184.216.34`，MockTransport 按路径读本地文件。
- 画面上的文字、Logo、价格、电话仍只由后期叠加。本改动不调用模型，无密钥，无费用。

### 2026-10-30 T15
- 合并了哪些：T11（PR #38）、T25（PR #41，`66306cc`）已在 main。本分支已并入这份 main。
- 正在做什么：T15 N2 品牌资料和 N3 方案卡。抠图、去底、单色版、色彩、肖像授权和锚点补全放在 `workers/brand_kit`，给 T13 复用。无 Key，`make accept-t15` 走 mock。inline 资料不写档案；未授权人物不进入下游；模型稿过不了相似度就明确降级。
- 需要提供什么：没有新的 Key。Logo 和产品图用自绘样张，不使用客户实拍。

## T15 假设

- 抠图、Logo 去底、白版和黑版、安全边距、色彩、卖点、肖像授权、偏好回写、侧面/背面锚点，都在 `workers/brand_kit`。N2 只编排。T13 应调用这个包，不要在节点里再写一套。当前抠图是本地纯色去底，用来在没有 BiRefNet / RMBG 权重时通过质检；接口是 `matte()` 返回透明 PNG 和边缘报告。
- 第 5 章 `LogoAsset` 只有 `mono_white`，没有黑版字段。黑版写在资料旁边的 `mono_black`，不改 BrandKit 模型，也不新增迁移。Alembic head 仍是 `t03_gateway_0002`。
- 多角度补全走图像网关，提示词写明不直接上屏，并且带上「无文字」约束。生成结果只放在 `anchors`（`on_screen` 为 false），不写入 `photos` 或 `cutouts`。
- 卖点只保留人工填写的句子，以及原文里已经出现的句子。模型多写的参数丢掉。用户改卖点或删掉的句子写回资料；删掉的句子追加进 `banned_words`，下一条片子不会再念。
- 肖像授权只认品牌资料流程写入档案的 `consent=true`。项目里附带的资料（inline kit）即使自报 `consent=true` 也不算授权，人物和照片都不会进入下游。未授权的人可以留在档案里，但照片和声音编号会被清掉；`people_for_use` / `release_kit` 给 T13 和其他节点的结果里没有他们。`usable_people` 每次按当前授权重算，不沿用旧列表。未授权却填写 `voice_id` 时直接失败。
- TODO(auth): `/v1/brands` 和创建项目时的 `enterprise_id` 由客户端自己填写，T15 没有登录态，也不校验调用者属于该企业。全局认证不在本任务。认证任务落地前，不能把这些接口当成已隔离的生产入口。
- 企业资料存在 `HILATV_BRAND_DIR`（默认 `<项目目录>/_brands`）的 JSON 里。同一 `enterprise_id` 再开项目、且请求里不带 inline kit 时，按 Logo、色彩、字体、CTA、卖点套用。inline kit 只用于这一次项目，不会写回档案。`brand://` 必须带本企业的 UUID，路径必须落在该企业的存储目录内。按 `brand_id` 查文件只查当前企业，不扫描别的企业。没有 `enterprise_id` 时拒绝这次查询，不再按 `brand_id` 去 Postgres 做不限企业的读取。
- N3 读取 T25 写进行业模板的 `narrative_structures`（每行业 3–5 套），从中取 3 套做方案卡。不改 `templates/`。模型稿若两两余弦 ≥ 0.85、含禁用词或不可用，会带反馈再生成，最多 3 次；仍然不行就明确降级为 `source=template_fallback` 且 `degraded=true`，不能假装是模型通过。嵌入是本地字符二元组，不调用嵌入接口。
- 封面和锚点图必须读到真实图片字节。`mock://` 或读不出来的地址是 `not_ready`，不写入可用锚点，也不用纯色图冒充封面。无 Key 时方案卡因此是降级结果，主流程仍可继续，但 `ok` 不是 true。
- 主流程不暂停等选卡。没有 `concept_selection` 时 N3 仍生成三张卡，并自动记下「你帮我选」，所以 T10 的出片验收继续往下走。用户在方案页点了某一张，创建项目时带上那个方向 id。
- 画面上的字、Logo、价格、电话仍然只由后期叠加。本任务不改 N15、`workers/qa`、`eval/`。

## T23 假设

- 分镜暂停点在 `n09_keyframe_qa` 活动返回之后、`n10_video` 之前。请求里 `skip_storyboard` 不是 true 才等。页面默认「先看分镜」，会显式传 false。省略这个字段时按「直接出片」，这样现有的命令行、T10 验收和评测不会停在没人点的确认上。
- 这一步的 N9 只调用 `review_shot` 记下 `visual_reviewed`，不调用导演决策，也不扣重生次数。Mock 关键帧过不了质检；如果在这里按未通过去重生，会把 N8 选中的帧清掉，后面的图生视频没有首帧，还会在用户还没看卡片时花掉项目重生额度。完整的 N9 重生循环仍留在 `workers/nodes/n09_keyframe_qa`，给单独调用。
- 卡片上的旁白由前端画。改字写回 Script，只重跑该镜的 N6，并经 T16 的 `_voice` / `_keyframes` 重做该镜画面。不把旁白或画面字写进图像、视频提示词。其他镜头的配音文件不打开重写。
- 画面能不能当预览：`mock://`、http(s)、项目目录外的路径、打不开的文件，以及整张只有一种颜色的色块，都是 `unavailable`，不给图片地址。`visual_reviewed` 只有预览可用且 `review_shot` 的该字段为 true 时才是 true。Mock 下关键帧像素记「未测」。
- 改旁白若要重生该镜关键帧，先 `open_project_budget.try_take()`。额度用完就只更新配音，不调用图像模型。次数只在 `regen_budget.json`，不写入 `project.json`。配音本身不另扣一次。
- 这一步不改时长去贴整片 Brief。该镜时长跟新的配音走，其他镜时长不动。总长可能因此和 Brief 有偏差，成片仍由后面的 N15 按脚本时长剪。
- 「AI生成」是页面上单独的一块，不在旁白框里，请求体多一个字段会被拒绝。继续出片之后 N14 仍会叠上这一行，改旁白去不掉它。
- 不新增表，也不新增环境变量。Alembic head 仍是 `t03_gateway_0002`。人物、链接抓取、客户图片都不经过这条编辑接口。

## T16 假设

- 解析以网关 LLM 为主。规则只做安全校验：拒绝未知镜头、空改动、以及没说「全部」却重做每一镜。做不到的类别（合成镜头、换衣服、改字幕语种、改节奏、改 Logo 大小或位置、改成傍晚或夜景）直接返回不支持，不会改成全片重生。对不上镜头或改动时返回需要澄清的问题，不提交新版本，也不调用图像或视频生成。
- 手写 25 句和另写的 32 句未见集分开计成功率。85% 只要求未见集。mock LLM 不读句子，只填占位，所以支持的改动会变成澄清，未见集在 mock 下过不了 85%，验收会如实打印，不以这句话去凑分。
- 「再短两秒」按缩短一档（时长 × 0.8）理解，不按字面减 2 秒。
- 旁白或时长变化会重跑该镜的 N6，并重做该镜视频长度（N10）。只改音色时不重做视频，并把镜头时长留在改前。Logo、价格、电话只重渲 N14/N15。去掉 Logo 去掉片头和角标；片尾仍留一张 Logo，因为 N15 的片尾合同要求 Logo 加 CTA。
- 局部重跑在进程里做。现有 Temporal 工作流只会从某个节点一路往后、并且每个镜头都跑，做不到「只动这一镜」。导演仍只返回 `RevisionDirective`，由这段运行器执行。
- 版本号是服务端 `uuid4` 的 32 位十六进制。请求里不能带路径；镜头号必须是当前分镜里的 id。版本目录、成片回放文件都落在项目目录内。索引和清单先写入临时文件，`fsync` 后再改名，整个写入拿着项目锁。
- 重生镜头只在 `review_shot` 的 `visual_reviewed` 为真且 `is_quality_pass` 为真时才算通过。mock 评审达不到，所以改稿版本的 `quality_pass` 在无密钥时是 false。项目级重生上限沿用 `HILATV_QA_PROJECT_RETRIES`；到顶后不再调用视频生成，决定记为 fallback。
- 方案卡如果带 `degraded`、`ok: false` 或 `text_source` / 卡片 `source` 为 `template_fallback`（含 `POST /v1/concepts` 返回 200 的这种降级），成片页会写明不能当作质检通过，版本也不会标成通过。改稿不重新请求 `/v1/concepts`。没有这些标记的旧 N3 结果不当成降级。
- 人物只经 `people_for_use` / `release_kit`。项目上的 Brand Kit 是内联副本，不是品牌档案，所以 `trust_consent` 为 false，肖像和克隆声线都不会进改稿。模块暂时不可导入时，人物列表直接清空，同样不读取原始人物字段。
- 改稿走 `get_gateway()`。`HILATV_LIVE` 未开或没有预算时是 mock，不挂对象存储，配音是 `mock://`。生产路径里，镜头文件缺失或视频没有字节时保留上一版画面，状态是未完成，并告诉用户哪些镜头留了原文件；不用色块冒充新画面。色块只出现在测试夹具里。
- 去掉 Logo 会说明片头和角标已去掉、片尾仍保留 Logo 和行动号召。接口的 `notice` 和成片页的 `revision_notice` 都写这句话。
- 项目重生次数只走 `workers.qa.budget_store.open_project_budget`。文件是 `regen_budget.json`，加锁并 fsync，只增不减。不写进 `project.json`，也不写进版本清单。回滚不打开这个文件，版本目录里的同名文件也不会盖掉它。上限仍是 `HILATV_QA_PROJECT_RETRIES`。
- 版本恢复先写入临时目录再换入。换到一半留下 `.restore-inflight` 时，下次读取会把 `.restore-prev` 整树换回，包括快照和成片。
- 项目锁只包住状态的读和写。单镜重生（每镜最长约 180 秒）在锁外执行，进度查询不会被挡在锁上。
- 画面文字、Logo、价格、电话仍只由 N13/N14/N15 叠加。换 Logo 若句子里带 http(s) 地址，只走 SEC-01 的 `fetch_bytes`。测试图是代码画的色块。
- 不新增迁移。Alembic head 仍是 `t03_gateway_0002`。改稿历史是 `/v1/projects/{id}/revisions`，不占用 T17 的 `/versions`（比例、语种、时长）。

## T11 假设

- 仓库已经用 npm（`apps/web/package-lock.json`，CI 按这个文件缓存）。`make accept-t11` 跑 `npm run test:e2e`，不另起 pnpm workspace。issue 注释里的 `pnpm --filter web` 指的是同一条桌面加手机的 Playwright。包名是 `hilatv-web`，对不上 filter `web`。
- 浏览器在设置了 `NEXT_PUBLIC_API_BASE` 时直连 API。没设置时，页面走同源 `/v1`，由 Next rewrite 转到 `HILATV_API_ORIGIN`。WebSocket 在设置了 base 时直连 API；浏览器对 WebSocket 不看 CORS。REST 的跨域来源由 `HILATV_WEB_ORIGINS` 决定，进程启动时读一次。
- 图片和 PDF 经 `POST /v1/uploads` 写到 `HILATV_PROJECT_DIR/uploads/<id>/`。响应只给不透明的 `upload_id`，不给服务器路径。创建项目用这个 id；服务端解析并确认真实路径落在 `uploads/` 里（解开符号链接，拒绝 `..` 和其他路径），否则 422。交给 N1 的仍是解析后的本地路径。状态接口和进度页不展示服务器路径。链接只收 http 或 https。类型必须同时符合 MIME 和扩展名，拒绝 SVG。单文件默认不超过 8MB，按块读取，超出即停（`HILATV_UPLOAD_MAX_BYTES`）。不新增表。
- 成片下载接口仍返回 `Content-Disposition: attachment`。播放器先把成片取成 blob 再交给 `<video>`，下载按钮再取一次并保存为 `master.mp4`。不做 Range。
- 版本切换和改稿框只是占位，不调用重跑，也不改稿。方案卡、分镜预览、专家画布、企业后台不在本任务。五个用户状态用 T10 已有的 phase。镜头行显示 WebSocket 事件里的「第 N 镜：…」；断线后靠轮询快照补上。分镜出来之前页面写当前环节，不用转圈当唯一反馈。
- 六个行业入口对应 `templates/industries` 的名称。点击只是填一句可改的示例，不单独调模型。
- 画面上的字、Logo、价格、电话仍然只由 N13/N14/N15 叠加。前端不调用模型，也不绕过 gateway。
- `make accept-t11` 用一句 15 秒中文宣传片，画布 320×180，并清掉对象存储变量，这样 mock 不连 MinIO。桌面 1440×900、手机 390×844 各跑一遍。手机视口用 Chromium 模拟触摸和手机 UA，不另装 WebKit。
- shadcn/ui 是复制进 `apps/web/components/ui` 的组件。不引入 React Flow。新依赖登记在 `docs/licenses.md`。

## T25 假设

- T05 已经放了 6 份行业默认值表。本任务不改这些默认时长、平台、关键词和视频类型，避免 N1 选行业的结果变掉。补上的是 `shot_plan`、3–5 套 `narrative_structures`，以及每份模板上的 `manual_review`。`narrative` 仍是 SPEC 第 7 章表格里的默认结构；变体留给以后的 N3，本任务不实现 N3。
- 表格里的措辞和 YAML 用了可核对的别名：制造业「工厂与检测 / 行动号召」对应「工厂/检测 / CTA」，外贸的「优势」对应「优势（价格/交期/MOQ）」，电商钩子写成「3秒钩子」。
- `manual_review` 只定义在行业模板上。政企为 true，其余为 false。N1 加载时会拒绝缺这个标记的政企模板，也不会让其他行业打开它。Brief 不新增字段，出片也不在这里拦截。T20 以后读这个字段。
- 镜头预设增加 `status`、`formal`、`tested_runs`。本批全部是「试用」、`formal: false`、`tested_runs: 0`。没有成功率数字，因为没有实测。模型不接受「正式」或非 0 的实测次数，所以不能只改 YAML 就把预设送进正式库。
- 为了让现有加载器读得下这些字段，N1 的行业模型和 N5 的预设模型各加了上述字段。没有改 N15、前端和 `workers/qa`。
- 新增运镜提示词是自写英文短句，负面约束包含无文字、无 Logo、无价格、无电话。推荐模型名仍是库里已有的 seedance / kling / wan，不新增 adapter，也不调用模型。
- 电商批量出片仍是 T24。模板只保留「批量 SKU」这条要求。教育模板写明数字人讲解可选，这里不接数字人。
- 不新增环境变量，也不新增依赖。验收强制走 mock 网关，不看 `HILATV_LIVE`。

## T10 假设

- 默认 `HILATV_TEMPORAL_MODE=embedded`：用 temporalio 在进程里拉起 dev server（真实时间，`HILATV_TEMPORAL_CLOCK=local`）。不依赖 Compose 里的 Temporal。`remote` 才连 `TEMPORAL_ADDRESS`，活动要另起 `hilatv worker`。单元测试里的断点续跑用 time-skipping 测试服务器，同一套 Workflow。
- Worker 关掉 workflow cache，新进程可以马上接上未完成的 run，不用等 sticky queue 超时。
- 节点内部 `max_attempts=1`。重试在 Temporal Activity 上，最多 3 次。质检标了 `retryable=False` 的错误不再重试。
- N2 在 T15 之前只读：请求里的 Brand Kit 优先；否则按 `brand_id` 读 `brand_kits`。库不在或没有记录就当没有资料，不创建。N3 不调用模型，也不做 3 张方案卡，固定「你帮我选」，方向用 Brief 的 `video_type`。N4 仍然只吃 Brief 和 Brand Kit。
- N1 若还有开放问题，不挡住出片。推荐项已经写进 Brief。
- 主链路每镜候选默认 3（不低于 SPEC 的 3，可用环境变量调到 8）。不传 `enterprise_id`，不写 `candidates` 表。
- 交给 N13/N14/N15 的脚本是 N6 回写过时长的那份。N8/N10 的候选单独保存。N15 现有输入没有视频地址，成片底板仍是它自己的纯色画面，字和 Logo 只在后期叠。N10 的片子留在候选里。
- 画面上的字、Logo、价格、电话仍然只由 N13/N14/N15 叠加。
- 项目状态写在 `HILATV_PROJECT_DIR`（默认系统临时目录）。不新增表。Alembic head 仍是 `t03_gateway_0002`。
- `start_from` 会重跑该节点和它后面的节点。n13 与 n14 并行；从 n13 重跑时 n14 会再跑一次，从 n14 重跑则留下已有字幕。
- `elapsed_s` 是从开跑到成片的墙钟秒数。mock 和 live 都记，不跟 SPEC §1.4 的 15 分钟比。
- `make accept-t10` 用一句 15 秒中文宣传片，画布 320×180，并清掉对象存储变量，这样 mock 不连 MinIO。issue 里的 30 秒英文 live 命令不在这条验收里执行。
- 创建项目的句子最长 4000 字。
- N13 对重复出现的词，按这一行自己的起点去对时间戳，不再总是用第一次出现。否则真实 N6 稿里第二个「工厂」会对不上，误差会超过 100ms。

### 2026-10-29
- 合并了哪些：T01（PR #21）、T02（PR #22，`t02_business_0001`）、T03（PR #23，`t03_gateway_0002`）、T04（PR #24，无新迁移）、T05（PR #25，无新迁移）、T06（PR #26，无新迁移）、T08（PR #28，无新迁移）
- 正在做什么：T07 N6 配音先行，已变基到含 T08 的 main。无 Key，`make accept-t07` 走 mock TTS / mock ASR。Alembic 仍是单一 head `t03_gateway_0002`
- 需要提供什么：LLM / 图像 / 视频 / TTS / ASR 的 Key，以及非零预算后才可打开 `HILATV_LIVE=1`

## T09 假设

- N13、N14、N15 不调用任何模型。字幕、徽章、价格、电话、Logo、CTA、AI 角标都由渲染层用 Pillow 画成 PNG，再由 FFmpeg `overlay` 叠上去。没有外部服务，因此也没有 mock adapter 切换。网关预算守卫碰不到这条链路。
- 第 5 章没有字幕或时间轴模型。节点自己的模型是 `SubtitleCue`、`PackageElement` 和 `Timeline`。`Script`、`Shot`、`OnScreenText`、`Asset`、`BrandKit`、`Brief` 仍用第 5 章。不新增迁移，Alembic head 仍是 `t03_gateway_0002`。
- 字幕时钟来自 N6 的逐词时间戳。中文时间戳是逐字的，所以「不拆词」靠 `templates/packaging/words.yaml` 加上品牌名、产品名、卖点。只有能放进一行的词才会整段保住。中文一行按非空白字符计，上限 16。英文按字符计（含空格），上限 42。句末标点另起一行。
- 对齐误差是字幕行首尾和对应时间戳首尾的差，必须 ≤ 100ms。节点把行首尾直接落在这些时间戳上。
- 产品主体框由调用方传入（归一化矩形）。本任务没有视觉模型，主体检测留给 T12。冲突时字幕上移，直到离开主体或顶到安全区。
- 多平台同时出现时，安全区取各平台里最大的那一圈。抖音和视频号的底部、右侧比 YouTube 更宽。样式在 `templates/packaging/safe_areas.yaml`。
- 片头三套模板是 `fade`、`rise`、`scale`，时长 1.6 秒，不超过 2 秒。成片不超过 15 秒，或平台是抖音 / 视频号时，默认无片头。也可以显式指定。片尾固定 2.4 秒，Logo 加 CTA（电话、官网；都空则写「联系我们」）。角标 Logo 默认开。AI 显式标识只放「AI生成」四个字，隐式元数据留给 T20。
- 默认转场是硬切。`transition_out` 为 dissolve / fade / xfade 时，两镜之间用 0.3 秒叠化。验收片子全是硬切。
- 调色是同一份 `templates/packaging/lut/unified.cube`，再加同一组 `eq`。白平衡是把后面镜头的底色增益拉向第一段，不是对实拍做直方图匹配。超分、插帧、多比例重构不在本任务。
- 没有成片文件时，镜头是纯色底板，上面没有字。旁白 `mock://` 用和 N6 相同的本地 WAV。对象存储不参与验收。
- 导出三份：成片、无字幕（仍保留徽章、Logo、CTA、AI 角标和旁白）、无配音（画面与成片相同，没有音轨）。
- 文字像素对照发生在 H.264 之前：同一套参数重画 PNG，以及 FFmpeg `overlay=format=rgb` 把这张 PNG 叠到纯色底上，和 Pillow 合成逐像素相同。成片是 yuv420p，字边做不到逐字节相同。时间轴引用的就是这些 PNG。
- 时间轴 JSON 重放时，libx264 `threads=1` 且 `-fflags +bitexact`，两次成片字节相同。
- 字体是随仓库附带的 Noto Sans CJK SC（思源黑体）Regular / Bold，OFL 1.1。品牌字体名映射到这两个文件。
- 字幕资产是 JSON 台词表，烧录用 PNG，不用 libass。ASS 的栅格和 Pillow 对不齐。

## T07 假设

- N6 的输入是第 5 章的 `Script`，可选 `BrandKit` 和 `Brief`。回写的是同一份 `Script` 里每个 `Shot.duration_s`，旁白文件是 `Asset`（`kind=voiceover`）。第 5 章的 Shot 没有逐字时间戳，时间戳放在节点输出的 `voiceovers` 里，给 N13 用。不改 Shot 的字段，也不新增迁移。Alembic 仍是单一 head `t03_gateway_0002`。
- 先配音，再改时长。Mock TTS 按 N4 的语速计时：中文 4 字/秒（每字 250ms），英文 2.5 词/秒（每词 400ms）。镜头 `duration_s` 不短于该句音频（含规定停顿）。旁白短于 Brief 时，缺口按各句音频比例做成画面停留（hold），分镜总时长落到 Brief 上。旁白长过 Brief 的 5% 时，先把语速最多再提高 15%；仍然超长就记 `copy_over_long` / `trim_copy`，交给 N4 删文案，并且不重试。SPEC N5 的总时长误差 ≤ 5% 是这条线的验收阈值。没有 Brief 时不补时长，镜头等于音频。
- 语速基准是 Brand Kit 的 `voice.speed`，没有资料时是 1.0。钩子镜 ×1.05，结尾 CTA ×0.90 并在句尾加 0.4 秒停顿。同一镜既是钩子又是结尾 CTA（例如 5 秒成片被收成一镜）时按结尾 CTA。更早的 CTA 镜只放慢，不停顿。语速夹在 0.2–3.0。音色用 `voice.tts_voice`，否则 `zh_male_steady`。
- 这些数放进 gateway `tts` 的 `speed` 和 `pause_s`。火山 v1 请求把它们写成 `audio.speed_ratio` 和 `request.silence_duration`（毫秒）。多音字和术语在 `workers/nodes/n06_voiceover/lexicon.yaml`，命中后由 adapter 包成 SSML `<phoneme alphabet="py">`。更长的词优先，所以「柱塞泵」不会再标成「柱塞」。
- 质检：ASR 回听字错率必须小于 2%（等于 2% 也不过）。比较前去掉空白和标点。响度用 RMS dBFS 近似 LUFS，窗口 -28 到 -12，对应旁白大约 -16。任一采样点顶到 16-bit 满幅（±32767）算爆音。无 Key 时 mock ASR 回放请求里的 `reference_text`，字错率比对逻辑用植入错字的单测验收。Live 火山 ASR 不把 `reference_text` 发给厂商。
- 画面上的字、Logo、价格、电话仍只留在 `on_screen_text`。N6 不调用图像或视频模型，也不把卡片上的电话拼进旁白。镜头变长或变短时，卡片的 in/out 按比例缩进新时长。
- 真人录音只留 `align_user_recording`，本任务不把它当验收项。ASR 走豆包录音文件极速识别 HTTP（`volc.bigasr.auc_turbo`），单价写在 `gateway/pricing.yaml`，是配置不是合同：¥0.004/秒。没有 `VOLC_ASR_APP_ID` 和 `VOLC_ASR_API_KEY` 时走 mock。TTS Key 不会顺便打开 ASR。
- 不新增数据库迁移。验收把网关日志放到独立 SQLite，并清掉对象存储环境变量，避免连到没启动的 MinIO。`mock://` 音频按同一语速和停顿在本地重放成 WAV 再做响度和爆音检测。画面停留不写进音频文件，只加在镜头时长上，避免静音把响度拉出窗口。

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

