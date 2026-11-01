# 专家节点重跑传递总片时钟

专家调用采用主工作流的 production_clock/story_clock，并以保存快照 generation_settings 和当前 state 构造统一时钟输入。N1 转发保存设置；N4/N5 只向脚本/分镜传递故事段时长，N4 将完整 production_clock 留在补丁中；整片 N6、N12、N14 转发总片预算。

非空 shot_id 的 N6 不传整片 target/intro/outro，继续采用原脚本单镜时长；它不会把整片预算分给一镜。N15 只从时钟取 target_duration_s，片头片尾仍用保存的实际值，并与主工作流保持一致：包装偏差超过一帧时要求重新生成包装。人工视觉评审、字体许可与 AI 标识门禁保留。

每次 N15 使用 render/n15/renders/<uuid> 子目录，失败重跑不能覆盖旧母版目录；返回节点实际 timeline、exports 和 clean_picture_path，不伪造时长或通过状态。本补丁未扩展 canvas timeline_edit。

验证：新增 13 项定向回归通过，覆盖节点调用边界真实组装、统一 helper 输入、N4 保存时钟、单镜 N6 排除全片预算、旧历史无新增目标、实际包装时长、独立渲染目录与旧字节保护、实际 timeline/clean picture 返回，以及原审核/字体/标识门禁。测试仅替换时钟计算 helper 与节点最外层 run；无真实厂商调用、渲染、依赖安装或付费请求。完整新时钟/真实节点验证依赖协调者整合并行的 workers.media.timing 补丁后执行。
