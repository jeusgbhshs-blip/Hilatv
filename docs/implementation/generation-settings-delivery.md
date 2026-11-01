# 生成设置在专家入口与成片页的衔接

CanvasClient 保存完整草稿时保留服务器 generation_settings。画布和项目快照中的设置不一致，或待确认提交的文字相同但设置改变时，返回明确冲突，不覆盖设置、不复用旧操作编号重新提交。兼容旧快照缺字段时的自动设置。

进度页与成片页展示用户主画幅/目标时长；自动设置采用 resolved_generation_settings 的已解析目标。实际文件的 width、height、duration_s 来自当前文件探测，播放器 metadata 仅作实际数据回退，不把目标、分镜或时间轴数字伪装成分辨率。未知尺寸保持完整画面适配，实际竖屏按真实尺寸呈现；旧 Blob 的 metadata 不能用于新文件。

导出面板提供九种画幅的显式选择，默认用户设置、解析目标或实际文件对应比例。每次只请求一个画幅和当前语种：优先 resolved_generation_settings.language，再用所选版本语种，最后中文；不会默认生成英文或额外画幅。所有画幅选项复用同一前端常量，服务端仍负责支持能力和最终校验。弹层提示异形参考图将完整保留并补边。

服务端公开合同：project/canvas 的 generation_settings；project 的 resolved_generation_settings={aspect_ratio,duration_s,language}；当前文件与 media_hash 对应的实际 width/height/duration_s。解析目标不充当实际文件元数据。

验证：35 项 Node 与 73 项 Vitest 单测通过；新增用例验证设置完整保存、旧提交参数冲突、目标与实际尺寸分离、竖屏/方形/未知尺寸、九种单画幅单语种请求和无效尺寸拒绝。生产 TypeScript、改动文件 ESLint、两份相关浏览器用例的独立严格 TypeScript 编译和 diff 检查通过。versions E2E 增加真实尺寸与单画幅请求断言，但未启动浏览器/执行 E2E、构建或启停原服务。整合后的两主题、375px 与实际播放器布局由 CUA 验收。
