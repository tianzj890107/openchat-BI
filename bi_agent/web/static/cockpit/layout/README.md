# V3 原型布局快照

本目录保存 `V3-总裁驾驶舱.html` 的看板 DOM 与样式快照，用于逐项复现卡片、按钮和图表空位的原始排列。

- 原型 SHA-256：`8faad500847468d61c279bcab1f6212ce3e521d25bb0743f307621da39303329`
- `prototype.css`：原型内联样式的完整快照。
- `views.json`：15 个看板视图、119 个缺失空位及其原型尺寸；生成后保留来源文件与哈希。
- `scripts/extract_cockpit_layout.mjs`：通过本机 Chrome DevTools Protocol 重新生成快照。

## 页面映射

| 路由 | 默认视图 | 可选参数 |
| --- | --- | --- |
| `/cockpit/overview` | `overview` | `metric=sales|volume` |
| `/cockpit/operations` | `operations` | `stage=opportunity|guidance|quotation|technical|bid|order|shipment` |
| `/cockpit/analysis` | `analysis-shipment` | `stage=opportunity|bid|order|shipment` |

三个页面只渲染看板，顶部保留首页、全局经营看板、运营 360 整体分析、穿透式问题分析四个驾驶舱 Tab；
不再包含原型宿主的工作区、会话区、页面标题或筛选栏。`/cockpit` 仅以 `307` 跳转到 `/cockpit/overview`。

可确认的年度图和头盔图空位由 `metadata/runtime.json` 挂载 ProUI 组件；其余缺项保留本目录记录的原始宽高。

## 生成方式

```bash
node scripts/extract_cockpit_layout.mjs /path/to/V3-总裁驾驶舱.html http://127.0.0.1:9337
```

脚本会执行原型自身的只读渲染函数，统一以 1440px 视口提取 DOM，移除脚本、内联事件和外部资源，并将无法由交付元数据逐项还原的图表、卡片、头盔与操作区清空。清空节点保留原始宽高；这也是页面比对时看到的白色空位。

`views.json` 中的视图不连接 AP、本体或生产数据库；业务事实仍来自冻结的原型 fixture。新增或更新原型时必须重新生成本目录并复核哈希、空位数量和三条路由。
