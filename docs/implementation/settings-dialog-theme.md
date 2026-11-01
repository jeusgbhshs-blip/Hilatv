# 生成设置弹层跟随应用外观

保留既有 HomeStudio 创作区的局部深色样式。仅把生成设置原生 dialog 通过 React portal 挂到 document.body，继承 html 的全局主题 token，避免浅色外观下继续继承创作区 dark。组件不复制颜色、不写死浅色；深色与自动主题同样随全局外观变化。

挂载完成后才访问 document.body，服务端渲染与首次水合均不创建 portal。原生模态、radio 键盘、ESC、关闭后焦点返回、滚动恢复和自定义回车保护保留。现有两主题 E2E 用例增加 DOM 挂载位置、实际 token 背景色与创作区仍深色的断言；本轮不启动浏览器，实际外观由整合后的 CUA 检查。

验证：43 项 Node、73 项 Vitest、全量 ESLint、生产 TypeScript、相关 E2E 的独立严格 TypeScript 编译通过；NEXT_PUBLIC_API_BASE 为空、API origin 为 8014 的生产构建成功并完成静态页渲染。日志覆盖 work/settings-web-{test,lint,types,build}.log。隔离工作树首次构建因既有 node_modules 链接越出 Turbopack 根而失败；仅把现有依赖本地克隆后重试成功，未安装或更新依赖、修改构建配置、重启服务或启动浏览器。
