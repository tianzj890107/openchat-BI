# 图 11 · 企业智能体平台整体架构

> 面向业务与产品视角的全景架构图。**正文只用业务语言**：讲清平台由哪些能力组成、业务请求
> 怎么流转、每层分别承担什么职责；不出现接口名、字段名、存储或部署等技术实现细节。
>
> 图形文件：`docs/diagrams/archify/platform-architecture.architecture.html`（双击即可打开，
> 可切换深浅色、可导出图片与矢量图）。
> 图形源：`docs/diagrams/archify/platform-architecture.architecture.json`。

---

## 一图读法

整张图自上而下是**四层能力**，每一层用一个横向贯通的能力区块表示，区块左上角标注层名：

| 顺序 | 层次 | 这一层回答的问题 |
|---|---|---|
| 第一层 | 应用接入层 | 业务用户和外部伙伴从哪里进入平台 |
| 第二层 | 智能体与能力层 | 谁负责接待请求、谁负责编排、能力从哪里来 |
| 第三层 | 语义层 | 平台凭什么理解业务口径，而不是只会查数 |
| 第四层 | 数据层 | 业务事实与知识分别沉淀在哪里 |

块与块之间的连线表示业务动作的流转方向，连线上的文字就是这一步在业务上做了什么。

---

## 分层与配色对照

配色由组件的**类型**自动决定，同一类组件在图中永远是同一个色系，便于跨图对照：

| 层次 | 能力单元 | 类型 | 色系 |
|---|---|---|---|
| 应用接入层 | 伏羲客户端 | `frontend` | 青色 Verified Cyan |
| 应用接入层 | API 接入系统 | `external` | 石板灰 External Slate |
| 智能体与能力层 | AI 网关 | `cloud` | 琥珀色 Cloud Amber |
| 智能体与能力层 | AIP 开发平台 | `backend` | 绿色 Proof Green |
| 智能体与能力层 | Skill / Tool 市场 | `messagebus` | 橙色 Transit Orange |
| 语义层 | 本体语义层 | `security` | 玫瑰色 Boundary Rose |
| 数据层 | 关系库 / 知识库 | `database` | 紫色 Database Violet |

---

## 业务流转

1. **业务提问与操作**：业务用户在伏羲客户端上提问、下单、发起分析，请求直接进入 AI 网关。
2. **系统对接请求**：外部系统与合作伙伴通过 API 接入系统把业务事件送进同一入口；两类入口
   汇入同一个网关，避免各系统各接一套智能能力。
3. **请求分发与编排**：AI 网关统一受理后交给 AIP 开发平台，由它决定这次请求该由哪个智能体、
   按什么顺序去完成。
4. **能力加载与调用**：AIP 开发平台按需从 Skill / Tool 市场取用能力，能力在市场上集中注册、
   集中共享，而不是每个智能体各写一份。
5. **业务语义查询**：智能体执行过程中向本体语义层确认业务口径——金额怎么算、指标包含哪些范围、
   对象之间什么关系，保证回答和业务口径一致。
6. **结构化数据**：语义层确认口径后，关系库提供结构化业务事实。
7. **文档与知识**：同一层同时向知识库取用文档与沉淀知识，与业务事实合并成完整答复。

---

## 一句话结论

**入口统一、能力共享、口径统一、数据分治**：业务侧只需要面对一个入口，能力在平台内复用，
回答的口径由语义层统一裁决，而事实数据与知识文档各自沉淀、由语义层统一引用。

---

## 维护说明（面向文档维护者，不属于图示内容）

- 图形由 [Archify](https://github.com/tt-a1i/archify) 从同目录 JSON 图形源生成，**不要手改 HTML**，
  改内容请改 JSON 后重新生成。
- 重新生成（在 Archify 仓库根目录执行）：

  ```bash
  node archify/bin/archify.mjs validate architecture <本仓库>/docs/diagrams/archify/platform-architecture.architecture.json --quality showcase --json
  node archify/bin/archify.mjs deliver  architecture <本仓库>/docs/diagrams/archify/platform-architecture.architecture.json \
         <本仓库>/docs/diagrams/archify/platform-architecture.architecture.html --quality showcase --json
  ```

- 质量门禁：`validate` 必须 `checksPassed 9/9`、`errors 0`、`warnings 0`；生成后再跑
  `node archify/bin/archify.mjs visual-check <输出 HTML> --json`，要求 1440×900 / 1600×1000 /
  1920×1080 / 2048×1320 四个视口均 `ok: true`（当前实测：画布 1352×602，1440×900 视口
  `scrollHeight 900`，刚好铺满一屏不出现滚动条）。
- 四层能力区块是贯通整幅画布的通栏底色，因此不存在大片空白；调整节点位置时保持四层的
  左右边界一致，避免出现某一层明显短于其它层。
- 只使用业务语言：新增节点或连线时，文案应描述业务角色、业务对象与业务动作，不要写入接口名、
  表名、字段名、部署方式或任何凭据信息。
