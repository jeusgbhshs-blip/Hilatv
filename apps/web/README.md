# apps/web

Next.js 15 + TypeScript + Tailwind + shadcn/ui。三页：输入、按镜头进度、成片。

API 要先起来（仓库根目录 `make api`）。页面和 API 不在同一个源时：

```bash
export NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000
export HILATV_WEB_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
npm install
npm run dev
```

`NEXT_PUBLIC_API_BASE` 为空时，浏览器请求同源的 `/v1`，由 Next 转发到 `HILATV_API_ORIGIN`（默认 `http://127.0.0.1:8000`）。

验收：在仓库根目录运行 `make accept-t11`（桌面 1440×900，手机 390×844）。
