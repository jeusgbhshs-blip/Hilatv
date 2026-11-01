# 生成前比例和时长：后端合同

`generation_settings` 是保存草稿的一部分，默认
`{"aspect_ratio": null, "duration_s": null}`。比例只接受 16:9、9:16、1:1、
4:3、3:4、3:2、2:3、4:5、21:9；时长只接受 5–180 的 JSON 整数。
未知字段、布尔、浮点数、数字字符串均拒绝。null 保留原有推断。

显式时长代表包含包装的最终整片，不是镜头主体预算。N1 Brief 保留
`generation_settings`，实际 `duration_s` / 唯一主 `aspect_ratios` 服从显式值；
平台冲突只写提示。N3 的正文、卡片和封面请求使用相同比例时长；封面经网关
`params.ratio` 传递。Brief ID 和方案请求内容随显式设置变化。

POST drafts / PUT draft 的 CAS、创建指纹和保存回执包含规范设置；改设置清空旧
preview/selection。输入 hash 与实际保存 hash 分开记录，因此清空旧 selection 后
原保存请求丢失 ACK 仍可原样重试；不同输入或后续修改继续 409。旧本机缺设置草稿
按自动处理，同操作创建重试兼容旧指纹。归档 node 文件保留，失效期间不用于公开
方案状态。新预览成功后清除失效标记；流水线重新生成 N3 时也应清除此标记。

`POST /v1/concepts` 从 owned project + draft_revision 的保存内容读取正文、附件和
设置，响应返回 `generation_settings`，snapshot 冻结
`concept_preview_generation_settings`。传入不一致正文或生成期间草稿变化返回 409。
旧无 project 方案入口继续接受非空正文并使用自动设置。

start 只接受 operation_id + draft_revision，设置随已声明草稿冻结，pending/unknown
重试查询原任务。make_request / prepare / Temporal 请求白名单和 API 重跑、人审继续
路径保留设置。无 SQL schema 迁移；JSONB / 文件存储新增可选字段。回滚前需停止新任务，
旧代码不应继续消费带显式设置的新任务，否则会忽略用户选择。

本提交不修改 activities、N4/N5、N8/N10、媒体合成、网关适配器和前端。协调者负责将
Brief 的显式总时长扣除包装后传给脚本/分镜，接入下游帧预算和实际渲染；不能只凭本层
元数据声称已生成精确几何或精确时长。

隔离、零费用定向验收（仓库根，使用已有 venv）：

```sh
HILATV_LIVE=0 HILATV_BUDGET_CNY=0 HILATV_DAILY_BUDGET_CNY=0 \
PYTHONPATH="$PWD:$PWD/apps/api" /Users/ci/Hilatv/.venv/bin/python -m pytest \
  workers/schemas/tests workers/nodes/n01_brief/tests workers/nodes/n03_concept/tests \
  apps/api/tests/test_generation_settings_api.py apps/api/tests/test_project_drafts.py \
  apps/api/tests/test_concept_drafts.py apps/api/tests/test_brands.py \
  workers/workflow/tests/test_storyboard.py workers/workflow/tests/test_brand.py
```

验收覆盖全部比例和时长端点、非法输入不写盘、明确选择优先、平台冲突不重试、
CAS 并发、跨企业、方案生成中设置变化、旧方案失效、丢 ACK 重试、未知提交不重发、
Temporal 白名单和旧本机创建兼容。没有调用供应商。

本轮结果：280 passed、1 既有数据库 roundtrip skip（需单独 `make accept-t02`）；
其中本次新增 67 项。Ruff check、format check 和 git diff check 通过。
