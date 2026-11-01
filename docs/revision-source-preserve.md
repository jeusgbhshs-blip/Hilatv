# N18 保留真实镜头画面

改稿合成现在从上次 `rendered_script` 的实际镜头时长开始，向 N15 明确传递每个镜头的
源文件。未重生镜头优先使用上一版未叠字 timeline plate，其次为保存的 shot_clips，
再兼容项目内 `media/<shot_id>.bin` 的合法视频/图片。全部源必须位于本项目且能探测
有效画面；完整 master、nosub、novo 和 full clean picture 都不能冒充单镜源。

新镜头字节另存到内容 hash 命名的路径，失败不会改写旧媒体。缺损、越项目、不可读取
或新返回字节无效时明确报错，保留上一版，不生成替代色板，也不把旧镜头伪称新结果。
只改包装不调用视频生成。旧 motion cards 按本次 on_screen_text 过滤，已删除价格不会
重新烧回；现存对齐脚本和源映射与本次脚本保持一致。

本次 N15 输出保存 clean source、timeline、rendered_script、shot_clips 和 production_clock。
原有 mock picture 标记随未重生镜头保留，明确 mock 的新候选也继续标记，不能因再次
编码成文件而被改称真实来源。修改新 render 的时间线元数据，不改旧时间线或旧成片。
正式交付仍需要独立 readiness 核验；本提交不增加放行权限。

未扩大旧记录恢复范围：只有完整烧字母版、没有项目内单镜源的记录会明确失败，需先
恢复源或重生成相应镜头。未增加供应商、依赖或数据库迁移。

零费用定向验收：

```sh
HILATV_LIVE=0 HILATV_BUDGET_CNY=0 HILATV_DAILY_BUDGET_CNY=0 \
PYTHONPATH="$PWD:$PWD/apps/api" /Users/ci/Hilatv/.venv/bin/python -m pytest \
 workers/workflow/tests/test_revision_source_preserve.py \
 workers/workflow/tests/test_generation_clock.py workers/workflow/tests/test_revise_cap.py \
 apps/api/tests/test_revisions.py workers/nodes/n18_revision/tests
```

使用真实 FFmpeg 字节和像素验证包装改稿保留原红色画面、新绿镜头与未改红镜头并存，
原文件字节不变；同时覆盖缺损、越项目、误传整片、无效新结果、mock 来源、实际 cuts、
clock 持久化及已有 API/重生额度回归。

本轮结果：33 passed（新增 10 项）；Ruff check、format check、git diff check 通过。
所有测试使用隔离项目和零费用配置，未调用供应商。
