# 画布与历史版本的生成目标

Canvas DTO 公开规范 `generation_settings`；旧项目未保存的字段返回 null，读取不写盘。
版本 manifest 冻结 `generation_settings` 和 `resolved_generation_settings`，版本 DTO
返回该版本自身目标。后者只保留 aspect_ratio、duration_s、language 三字段，表示解析目标，
不声称文件实际尺寸或时长。

恢复时仅将这两项生产意图随原媒体/节点事务恢复。旧 manifest 缺字段时，读取归档
state.brief：明确设置来自 brief.generation_settings，解析目标来自主比例/时长/第一语种；
完全没有归档目标时置为未知，避免把当前项目的新目标标签套到旧片。非法目标在发布前
拒绝，不修改活动项目。保留现有媒体 hash 校验、恢复事务和中断回滚。

不从归档恢复企业、owner、成员、授权或费用/重生账本。没有数据库迁移或供应商调用。

零费用隔离定向验收：

```sh
HILATV_LIVE=0 HILATV_BUDGET_CNY=0 HILATV_DAILY_BUDGET_CNY=0 \
PYTHONPATH="$PWD:$PWD/apps/api" /Users/ci/Hilatv/.venv/bin/python -m pytest \
  workers/expert/tests/test_canvas_generation_settings.py \
  workers/workflow/tests/test_generation_version_intent.py \
  workers/workflow/tests/test_versions.py apps/api/tests/test_canvas_api.py
```

结果：26 passed；Ruff check/format check、git diff check 通过。覆盖规范读取、归档/恢复、
旧 Brief 回退、未知目标清除、非法输入不发布、现有权限/预算保留、hash 拒绝和崩溃回滚。
