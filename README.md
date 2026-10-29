# HiLatv

企业用户说一句话（可附产品图、Logo、链接），HiLatv 自动交付一条可直接发布的商业短视频。（文档代号「一句成片」）

- 产品与技术规格：[SPEC.md](./SPEC.md)（唯一事实来源）
- AI 编码代理规则：[AGENTS.md](./AGENTS.md)
- 进度：[docs/progress.md](./docs/progress.md)

> 所有实现以 SPEC.md 为准，按第 13 章任务清单顺序推进，每完成一项跑对应验收。

## 本地开发

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
make test
make up && make accept-t01
```

没有 `.env` 时，`make` 读取 `.env.example` 里的开发默认值。API：`make api`（<http://localhost:8000/health>）。前端：`cd apps/web && npm install && npm run dev`。

开源依赖许可证见 [docs/licenses.md](./docs/licenses.md)。

© 青岛涌现言源智能科技有限公司 · 私有仓库
