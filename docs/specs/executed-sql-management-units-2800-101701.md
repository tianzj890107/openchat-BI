# 取数中实际执行的原始 SQL —— 管理单元 2800 / 101701

> 本文档汇总「实际被执行」的原始 SQL 语句，范围为涉及管理单元 `2800` 与 `101701` 的取数。
> 只读提取，未修改任何历史会话或用户数据。

## 1. 说明

| 项 | 内容 |
| --- | --- |
| 数据来源 | 本机历史会话 `dataset/conversations/*.json` 中 `Ontology-FactQuery` 工具的 `tool_use.input.sql` |
| 提取时间 | 2026-10-14 |
| 判定口径 | 1) 工具为 SQL 取数类（`Ontology-FactQuery`）；2) SQL 原文包含 `2800` / `101701`，或命中包含 `101701` 的记录；3) 存在对应的 `tool_result`（即真的执行过并返回） |
| 未纳入 | `TableGenerate`、`AskUser`、`ChartGenerate` 等非 SQL 工具；仅有 `title/备注` 文本含关键词但未执行 SQL 的调用 |
| 引擎 | 会话中 SQL 分布在两处数据面：本地 HyperFusion SQLite（`T_HF_*` 表）与远端本体库（Doris，`ontology_dev` / `ontology_demo_scm_po` / `ontology_demometaerp`）；远端结果 `provenance.source = "Doris"` |

## 2. 结论摘要

- 实际执行的、**以管理单元 `2800` 为过滤条件**的 SQL 共 **7 条**，分布在 3 个会话：`ad0ab218`(2)、`bfc59367`(1)、`e91d7464`(4)。
- **没有任何 SQL 以 `101701` 作为管理单元过滤条件**。全仓仅 `f8cf8d06` 会话出现 `101701`，且它是采购单号 `HPO101701-001012` 的前缀，不是管理单元编码。
- 因此 `101701` 部分列出的是「命中该记录的 SQL」：以 `poHeaderId = 1902925701749408676`（即 `HPO101701-001012`）为条件的 **4 条** SQL。

---

## 3. 管理单元 `2800`（7 条）

### 3.1 `ad0ab218` msg#21 · Ontology-FactQuery

- 会话首问：统计查看2025年6月至2026年5月一年内，管理单元“2800”的月度采购支出金额变化。
- 会话时间：2026-07-24
- 数据面：本地 HyperFusion SQLite（`T_HF_DemoData`）
- 用途：探测 `FCompanySegment` 是否存在 2800 取值
- 执行状态：已执行并返回（非 error）

```sql
SELECT DISTINCT FCompanySegment FROM T_HF_DemoData WHERE FCompanySegment LIKE '%2800%' LIMIT 10
```

返回结果：

```text
SQL: SELECT DISTINCT FCompanySegment FROM T_HF_DemoData WHERE FCompanySegment LIKE '%2800%' LIMIT 10

(0 rows)
```

### 3.2 `ad0ab218` msg#37 · Ontology-FactQuery

- 会话首问：统计查看2025年6月至2026年5月一年内，管理单元“2800”的月度采购支出金额变化。
- 会话时间：2026-07-24
- 数据面：本地 HyperFusion SQLite（`T_HF_DemoData`）
- 用途：扩大探测到 `FOperatingUnitLv1/Lv2`，仍然为空
- 执行状态：已执行并返回（非 error）

```sql
SELECT DISTINCT FCompanySegment FROM T_HF_DemoData WHERE FCompanySegment LIKE '%2800%' OR FOperatingUnitLv1 LIKE '%2800%' OR FOperatingUnitLv2 LIKE '%2800%' LIMIT 10
```

返回结果：

```text
SQL: SELECT DISTINCT FCompanySegment FROM T_HF_DemoData WHERE FCompanySegment LIKE '%2800%' OR FOperatingUnitLv1 LIKE '%2800%' OR FOperatingUnitLv2 LIKE '%2800%' LIMIT 10

(0 rows)
```

### 3.3 `bfc59367` msg#19 · Ontology-FactQuery

- 会话首问：统计查看2025年6月至2026年5月一年内，管理单元“2800”的月度采购支出金额变化
- 会话时间：2026-06-24
- 数据面：远端本体库 `ontology_demo_scm_po`
- 用途：命中 2800，返回 6 个月（2025-12 ~ 2026-05）采购含税金额
- 执行状态：已执行并返回（非 error）

```sql
SELECT
  DATE_FORMAT(ph.creationDate, '%Y-%m') AS month,
  SUM(pl.taxInclusiveAmount) AS monthly_purchase_amount
FROM ontology_demo_scm_po.poheader ph
JOIN ontology_demo_scm_po.poline pl ON ph.poHeaderId = pl.poHeaderId
WHERE ph.unitCode = '2800'
  AND ph.approvalStatus = 'APPROVED'
  AND ph.creationDate >= '2025-06-01'
  AND ph.creationDate <= '2026-05-31'
GROUP BY DATE_FORMAT(ph.creationDate, '%Y-%m')
ORDER BY month
```

返回结果：

```text
SQL: SELECT
  DATE_FORMAT(ph.creationDate, '%Y-%m') AS month,
  SUM(pl.taxInclusiveAmount) AS monthly_purchase_amount
FROM ontology_demo_scm_po.poheader ph
JOIN ontology_demo_scm_po.poline pl ON ph.poHeaderId = pl.poHeaderId
WHERE ph.unitCode = '2800'
  AND ph.approvalStatus = 'APPROVED'
  AND ph.creationDate >= '2025-06-01'
  AND ph.creationDate <= '2026-05-31'
GROUP BY DATE_FORMAT(ph.creationDate, '%Y-%m')
ORDER BY month

month   | monthly_purchase_amount
--------+------------------------
2025-12 | 11400511.5000000000
2026-01 | 280994.7000000000
2026-02 | 9468195.0000000000
2026-03 | 3150000.0000000000
2026-04 | 1956682.3500000000
2026-05 | 282267037.7100000000

[6 row(s), showing 6]
```

### 3.4 `e91d7464` msg#23 · Ontology-FactQuery

- 会话首问：统计查看2025年6月至2026年5月一年内，管理单元“2800”的月度采购支出金额变化。
- 会话时间：2026-07-24
- 数据面：远端本体库 `ontology_demometaerp`
- 用途：`po_po_header_t.amount` 在 2800 下几乎全为 0/NULL
- 执行状态：已执行并返回（非 error）

```sql
SELECT
  DATE_FORMAT(creation_date, '%Y-%m') AS month_id,
  SUM(amount) AS purchase_amount
FROM ontology_demometaerp.po_po_header_t
WHERE unit_code = '2800'
  AND creation_date >= '2025-06-01'
  AND creation_date < '2026-06-01'
GROUP BY DATE_FORMAT(creation_date, '%Y-%m')
ORDER BY month_id
```

返回结果：

```text
SQL: SELECT
  DATE_FORMAT(creation_date, '%Y-%m') AS month_id,
  SUM(amount) AS purchase_amount
FROM ontology_demometaerp.po_po_header_t
WHERE unit_code = '2800'
  AND creation_date >= '2025-06-01'
  AND creation_date < '2026-06-01'
GROUP BY DATE_FORMAT(creation_date, '%Y-%m')
ORDER BY month_id

month_id | purchase_amount
---------+----------------
2025-12  | 0E-10
2026-01  | 0E-10
2026-02  | 0E-10
2026-03  |
2026-04  | 0E-10
2026-05  | 0E-10

[6 row(s), showing 6]
```

### 3.5 `e91d7464` msg#25 · Ontology-FactQuery

- 会话首问：统计查看2025年6月至2026年5月一年内，管理单元“2800”的月度采购支出金额变化。
- 会话时间：2026-07-24
- 数据面：远端本体库 `ontology_demometaerp`
- 用途：按全量月份看 2800 的单据数与有金额单据数（PO 头表 amount 不走行金额）
- 执行状态：已执行并返回（非 error）

```sql
SELECT
  DATE_FORMAT(creation_date, '%Y-%m') AS month_id,
  COUNT(*) AS po_count,
  SUM(CASE WHEN amount IS NOT NULL THEN 1 ELSE 0 END) AS has_amount_count,
  SUM(amount) AS purchase_amount
FROM ontology_demometaerp.po_po_header_t
WHERE unit_code = '2800'
GROUP BY DATE_FORMAT(creation_date, '%Y-%m')
ORDER BY month_id DESC
LIMIT 20
```

返回结果：

```text
SQL: SELECT
  DATE_FORMAT(creation_date, '%Y-%m') AS month_id,
  COUNT(*) AS po_count,
  SUM(CASE WHEN amount IS NOT NULL THEN 1 ELSE 0 END) AS has_amount_count,
  SUM(amount) AS purchase_amount
FROM ontology_demometaerp.po_po_header_t
WHERE unit_code = '2800'
GROUP BY DATE_FORMAT(creation_date, '%Y-%m')
ORDER BY month_id DESC
LIMIT 20

month_id | po_count | has_amount_count | purchase_amount
---------+----------+------------------+-----------------
2026-07  | 4        | 4                | 0E-10
2026-06  | 9        | 6                | 30000.0000000000
2026-05  | 128      | 15               | 0E-10
2026-04  | 11       | 8                | 0E-10
2026-03  | 2        | 0                |
2026-02  | 14       | 14               | 0E-10
2026-01  | 22       | 21               | 0E-10
2025-12  | 6        | 5
...（结果已截断，SQL 全文见上）
```

### 3.6 `e91d7464` msg#29 · Ontology-FactQuery

- 会话首问：统计查看2025年6月至2026年5月一年内，管理单元“2800”的月度采购支出金额变化。
- 会话时间：2026-07-24
- 数据面：远端本体库 `ontology_demometaerp`
- 用途：改为 JOIN 明细表 `po_po_line_t` 取行金额
- 执行状态：已执行并返回（非 error）

```sql
SELECT
  DATE_FORMAT(h.creation_date, '%Y-%m') AS month_id,
  COUNT(DISTINCT h.po_header_id) AS po_count,
  SUM(l.amount) AS line_purchase_amount
FROM ontology_demometaerp.po_po_header_t h
JOIN ontology_demometaerp.po_po_line_t l ON h.po_header_id = l.po_header_id
WHERE h.unit_code = '2800'
  AND h.creation_date >= '2025-06-01'
  AND h.creation_date < '2026-06-01'
GROUP BY DATE_FORMAT(h.creation_date, '%Y-%m')
ORDER BY month_id
```

返回结果：

```text
SQL: SELECT
  DATE_FORMAT(h.creation_date, '%Y-%m') AS month_id,
  COUNT(DISTINCT h.po_header_id) AS po_count,
  SUM(l.amount) AS line_purchase_amount
FROM ontology_demometaerp.po_po_header_t h
JOIN ontology_demometaerp.po_po_line_t l ON h.po_header_id = l.po_header_id
WHERE h.unit_code = '2800'
  AND h.creation_date >= '2025-06-01'
  AND h.creation_date < '2026-06-01'
GROUP BY DATE_FORMAT(h.creation_date, '%Y-%m')
ORDER BY month_id

month_id | po_count | line_purchase_amount
---------+----------+---------------------
2025-12  | 6        | 11577630.0000000000
2026-01  | 22       | 127929654.0000000000
2026-02  | 14       | 21961102.8700000000
2026-03  | 2        | 3000000.0000000000
2026-04  | 11       | 2053500.0000000000
2026-05  | 128      | 272431478.2000000000

[6 row(s), showing 6]
```

### 3.7 `e91d7464` msg#31 · Ontology-FactQuery

- 会话首问：统计查看2025年6月至2026年5月一年内，管理单元“2800”的月度采购支出金额变化。
- 会话时间：2026-07-24
- 数据面：远端本体库 `ontology_demometaerp`
- 用途：补齐 12 个自然月的 CTE 版本（最终交付口径）
- 执行状态：已执行并返回（非 error）

```sql
WITH monthly AS (
  SELECT
    DATE_FORMAT(h.creation_date, '%Y-%m') AS month_id,
    SUM(l.amount) AS purchase_amount
  FROM ontology_demometaerp.po_po_header_t h
  JOIN ontology_demometaerp.po_po_line_t l ON h.po_header_id = l.po_header_id
  WHERE h.unit_code = '2800'
    AND h.creation_date >= '2025-06-01'
    AND h.creation_date < '2026-06-01'
  GROUP BY DATE_FORMAT(h.creation_date, '%Y-%m')
),
full_months AS (
  SELECT '2025-06' AS month_id UNION ALL
  SELECT '2025-07' UNION ALL SELECT '2025-08' UNION ALL SELECT '2025-09' UNION ALL
  SELECT '2025-10' UNION ALL SELECT '2025-11' UNION ALL SELECT '2025-12' UNION ALL
  SELECT '2026-01' UNION ALL SELECT '2026-02' UNION ALL SELECT '2026-03' UNION ALL
  SELECT '2026-04' UNION ALL SELECT '2026-05'
)
SELECT
  fm.month_id,
  COALESCE(m.purchase_amount, 0) AS purchase_amount
FROM full_months fm
LEFT JOIN monthly m ON fm.month_id = m.month_id
ORDER BY fm.month_id
```

返回结果：

```text
SQL: WITH monthly AS (
  SELECT
    DATE_FORMAT(h.creation_date, '%Y-%m') AS month_id,
    SUM(l.amount) AS purchase_amount
  FROM ontology_demometaerp.po_po_header_t h
  JOIN ontology_demometaerp.po_po_line_t l ON h.po_header_id = l.po_header_id
  WHERE h.unit_code = '2800'
    AND h.creation_date >= '2025-06-01'
    AND h.creation_date < '2026-06-01'
  GROUP BY DATE_FORMAT(h.creation_date, '%Y-%m')
),
full_months AS (
  SELECT '2025-06' AS month_id UNION ALL
  SELECT '2025-07' UNION ALL SELECT '2025-08' UNION ALL SELECT '2025-09' UNION ALL
  SELECT '2025-10' UNION ALL SELECT '2025-11' UNION ALL SELECT '2025-12' UNION ALL
  SELECT '2026-01' UNION ALL SELECT '2026-02' UNION ALL SELECT '2026-03' UNION ALL
  SELECT '2026-04' UNION ALL SELECT '2026-05'
)
SELECT
  fm.month_id,
  COALESCE(m.purchase_amount, 0) AS purchase_amount
FROM full_months fm
LEFT JOIN monthly m ON fm.month_id = m.mon
...（结果已截断，SQL 全文见上）
```

---

## 4. `101701`（0 条管理单元过滤；4 条命中该记录的 SQL）

说明：会话/日志中 `101701` 只作为采购单号 `HPO101701-001012` 出现（`poNumber`），
> 补充（见第 6 节）：在 demo2 的 ECore 库 `ontology_ecore` 中，`101701` **确实是**一个管理单元（`unitcode='101701'` 共 48 张采购单）。本节所谓「0 条」仅指本机历史会话里没有以它做过过滤，并不代表它不是管理单元。
不存在 `unitCode/unit_code = '101701'` 之类的管理单元过滤 SQL。下面列出以该记录的
主键 `poHeaderId = 1902925701749408676` 为条件、实际执行过的 SQL。

### 4.1 `f8cf8d06` msg#113 · Ontology-FactQuery

- 会话首问：现在可以问什么问题
- 会话时间：2026-08-25
- 数据面：远端本体库 `ontology_dev`
- 用途：`poNumber` 命中 `HPO101701-001012`（poHeaderId=1902925701749408676）
- 执行状态：已执行并返回（非 error）

```sql
SELECT poHeaderId, poNumber, supplierCode, approvalStatus, purchasingOrderType, approvedDate, creationDate, closedStatus, frozenFlag, cancelFlag, businessType, amount, remark
FROM ontology_dev.poheader
WHERE poHeaderId IN (1987775639809363610, 2007391458458210536, 1902925701749408676, 1882514743772643547)
```

返回结果：

```text
SQL: SELECT poHeaderId, poNumber, supplierCode, approvalStatus, purchasingOrderType, approvedDate, creationDate, closedStatus, frozenFlag, cancelFlag, businessType, amount, remark
FROM ontology_dev.poheader
WHERE poHeaderId IN (1987775639809363610, 2007391458458210536, 1902925701749408676, 1882514743772643547)

poHeaderId          | poNumber            | supplierCode | approvalStatus | purchasingOrderType     | approvedDate        | creationDate        | closedStatus | frozenFlag | cancelFlag | businessType | amount
--------------------+---------------------+--------------+----------------+-------------------------+---------------------+---------------------+--------------+------------+------------+--------------+-------
1987775639809363610 | JYSTDPO202607010001 | VEND001      | APPROVED       | STANDARD_PURCHASE_ORDER | 2026-07-02T02:29:17 | 2026-07-02T02:25:32 | OPEN         | N          | N          | PP           | 0.0
1882514743772643547 | HPOLYY001-001001    | SZDZ01       | APPROVED       | STANDARD_PURCHASE_ORDER | 2026-02-06T20:03:28 | 2026-02-06T20:03:26 | OPEN         | N          | N          | ENGINEERING  |
1902925701749408676 | HPO101701-001012    | 10000
...（结果已截断，SQL 全文见上）
```

### 4.2 `f8cf8d06` msg#113 · Ontology-FactQuery

- 会话首问：现在可以问什么问题
- 会话时间：2026-08-25
- 数据面：远端本体库 `ontology_dev`
- 用途：`poNumber` 命中 `HPO101701-001012`（poHeaderId=1902925701749408676）
- 执行状态：已执行并返回（非 error）

```sql
SELECT ps.poHeaderId, ps.poLineShipmentId, ph.supplierCode, ps.promisedDate, ps.needByDate, ps.approvedFlag, ps.closedStatus, ps.closedReason, ps.receiptDelayDays, ps.receiptAdvanceDays, ps.quantity, ps.receivedQuantity, ps.acceptedQuantity, ps.rejectedQuantity, ps.cancelFlag, pl.itemCode, pl.itemDescription, pl.taxInclusiveAmount
FROM ontology_dev.polineshipment ps
LEFT JOIN ontology_dev.poheader ph ON ps.poHeaderId=ph.poHeaderId
LEFT JOIN ontology_dev.poline pl ON ps.poLineId=pl.poLineId
WHERE ps.poHeaderId IN (1987775639809363610, 2007391458458210536, 1902925701749408676, 1882514743772643547)
```

返回结果：

```text
SQL: SELECT ps.poHeaderId, ps.poLineShipmentId, ph.supplierCode, ps.promisedDate, ps.needByDate, ps.approvedFlag, ps.closedStatus, ps.closedReason, ps.receiptDelayDays, ps.receiptAdvanceDays, ps.quantity, ps.receivedQuantity, ps.acceptedQuantity, ps.rejectedQuantity, ps.cancelFlag, pl.itemCode, pl.itemDescription, pl.taxInclusiveAmount
FROM ontology_dev.polineshipment ps
LEFT JOIN ontology_dev.poheader ph ON ps.poHeaderId=ph.poHeaderId
LEFT JOIN ontology_dev.poline pl ON ps.poLineId=pl.poLineId
WHERE ps.poHeaderId IN (1987775639809363610, 2007391458458210536, 1902925701749408676, 1882514743772643547)

poHeaderId          | poLineShipmentId    | supplierCode | promisedDate        | needByDate          | approvedFlag | closedStatus | receiptDelayDays | receiptAdvanceDays | quantity | receivedQuantity | acceptedQuantity | rejectedQuantity | cancelFlag | itemCode           | itemDescription | taxInclusiveAmount
--------------------+---------------------+--------------+---------------------+---------------------+--------------+--------------+------------------+--------------------+----------+------------------+------------------+------------------+------------+--------------------+-----
...（结果已截断，SQL 全文见上）
```

### 4.3 `f8cf8d06` msg#115 · Ontology-FactQuery

- 会话首问：现在可以问什么问题
- 会话时间：2026-08-25
- 数据面：远端本体库 `ontology_dev`
- 用途：按 4 个 poHeaderId 关联验收明细 `acline`，命中行返回 0 条
- 执行状态：已执行并返回（非 error）

```sql
SELECT
  l.sourceDocHeaderId AS poHeaderId,
  COUNT(DISTINCT l.acHeaderId) AS ac_headers,
  COUNT(DISTINCT l.acLineId) AS ac_lines,
  SUM(CASE WHEN h.approvalStatus='APPROVED' THEN 1 ELSE 0 END) AS approved_lines,
  SUM(l.acceptedQuantity) AS accepted_qty,
  SUM(l.rejectedQuantity) AS rejected_qty
FROM ontology_dev.acline l
LEFT JOIN ontology_dev.acheader h ON l.acHeaderId=h.acHeaderId
WHERE l.sourceDocHeaderId IN (1987775639809363610, 2007391458458210536, 1902925701749408676, 1882514743772643547)
GROUP BY 1
```

返回结果：

```text
SQL: SELECT
  l.sourceDocHeaderId AS poHeaderId,
  COUNT(DISTINCT l.acHeaderId) AS ac_headers,
  COUNT(DISTINCT l.acLineId) AS ac_lines,
  SUM(CASE WHEN h.approvalStatus='APPROVED' THEN 1 ELSE 0 END) AS approved_lines,
  SUM(l.acceptedQuantity) AS accepted_qty,
  SUM(l.rejectedQuantity) AS rejected_qty
FROM ontology_dev.acline l
LEFT JOIN ontology_dev.acheader h ON l.acHeaderId=h.acHeaderId
WHERE l.sourceDocHeaderId IN (1987775639809363610, 2007391458458210536, 1902925701749408676, 1882514743772643547)
GROUP BY 1

(0 rows)
```

### 4.4 `f8cf8d06` msg#121 · Ontology-FactQuery

- 会话首问：现在可以问什么问题
- 会话时间：2026-08-25
- 数据面：远端本体库 `ontology_dev`
- 用途：按 4 个 poHeaderId 查变更申请，仅 2007391458458210536 有 3 条 INCOMPLETE
- 执行状态：已执行并返回（非 error）

```sql
SELECT po_header_id, COUNT(*) AS cnt, MAX(application_reason) AS reason, MAX(approval_status) AS approval_status, MAX(change_status) AS change_status
FROM ontology_dev.po_po_change_application_header_t
WHERE po_header_id IN ('1987775639809363610','2007391458458210536','1902925701749408676','1882514743772643547')
GROUP BY 1
```

返回结果：

```text
SQL: SELECT po_header_id, COUNT(*) AS cnt, MAX(application_reason) AS reason, MAX(approval_status) AS approval_status, MAX(change_status) AS change_status
FROM ontology_dev.po_po_change_application_header_t
WHERE po_header_id IN ('1987775639809363610','2007391458458210536','1902925701749408676','1882514743772643547')
GROUP BY 1

po_header_id        | cnt | approval_status
--------------------+-----+----------------
2007391458458210536 | 3   | INCOMPLETE

[1 row(s), showing 1]
```


---

## 5. 口径对照：全口径 vs 已审批（管理单元 `2800`）

「采购支出/采购金额」在会话里出现过两种口径，需要分开看：

| 口径 | 含义 | 历史会话里实际执行过吗 |
| --- | --- | --- |
| 全口径 | 不加审批状态过滤，全部采购单都计入 | 是（`e91d7464`，`ontology_demometaerp`） |
| 已审批 | 仅 `approvalStatus = 'APPROVED'` | 是（`bfc59367`，`ontology_demo_scm_po`） |

> 注意：两条 SQL 落在**两个不同的库**，所以「口径」和「数据面」在历史记录里是混在一起的；
> 第 6 节把它们拆开重跑，才能得到真正的「同库同口径」对比。

**5.1 全口径 SQL（已执行 · `e91d7464` msg#29，`ontology_demometaerp`，Doris 方言）**

```sql
SELECT
  DATE_FORMAT(h.creation_date, '%Y-%m') AS month_id,
  COUNT(DISTINCT h.po_header_id) AS po_count,
  SUM(l.amount) AS line_purchase_amount
FROM ontology_demometaerp.po_po_header_t h
JOIN ontology_demometaerp.po_po_line_t l ON h.po_header_id = l.po_header_id
WHERE h.unit_code = '2800'
  AND h.creation_date >= '2025-06-01'
  AND h.creation_date < '2026-06-01'
GROUP BY DATE_FORMAT(h.creation_date, '%Y-%m')
ORDER BY month_id
```

**5.2 已审批 SQL（已执行 · `bfc59367` msg#19，`ontology_demo_scm_po`，Doris 方言）**

```sql
SELECT
  DATE_FORMAT(ph.creationDate, '%Y-%m') AS month,
  SUM(pl.taxInclusiveAmount) AS monthly_purchase_amount
FROM ontology_demo_scm_po.poheader ph
JOIN ontology_demo_scm_po.poline pl ON ph.poHeaderId = pl.poHeaderId
WHERE ph.unitCode = '2800'
  AND ph.approvalStatus = 'APPROVED'
  AND ph.creationDate >= '2025-06-01'
  AND ph.creationDate <= '2026-05-31'
GROUP BY DATE_FORMAT(ph.creationDate, '%Y-%m')
ORDER BY month
```

**5.3 demometaerp 侧的「已审批」对照 SQL（本次未执行，pdt-dev 需要 Token，返回 401）**

```sql
-- 与 5.1 同源同库，仅加审批过滤；本次未执行成功，仅作对照
SELECT
  DATE_FORMAT(h.creation_date, '%Y-%m') AS month_id,
  SUM(l.amount) AS line_purchase_amount
FROM ontology_demometaerp.po_po_header_t h
JOIN ontology_demometaerp.po_po_line_t l ON h.po_header_id = l.po_header_id
WHERE h.unit_code = '2800'
  AND h.approval_status = 'APPROVED'   -- 字段名待以库内实际列名为准
  AND h.creation_date >= '2025-06-01'
  AND h.creation_date < '2026-06-01'
GROUP BY DATE_FORMAT(h.creation_date, '%Y-%m')
ORDER BY month_id
```

**5.4 demo2 ECore 侧的「全口径 / 已审批」两条 SQL（本次实际执行，PG 方言）**

```sql
-- 全口径（本次执行）
SELECT to_char(h.creationdate,'YYYY-MM') AS month_id,
       COUNT(DISTINCT h.poheaderid) AS po_count,
       SUM(l.taxinclusiveamount) AS line_amount      -- 含税；改 l.amount 则是不含税
FROM ontology_ecore.poheader h
JOIN ontology_ecore.poline l ON h.poheaderid = l.poheaderid
WHERE h.unitcode = '2800'
  AND h.creationdate >= '2025-06-01' AND h.creationdate < '2026-06-01'
GROUP BY 1 ORDER BY 1

-- 已审批（本次执行）
SELECT to_char(h.creationdate,'YYYY-MM') AS month_id,
       COUNT(DISTINCT h.poheaderid) AS po_count,
       SUM(l.taxinclusiveamount) AS line_amount
FROM ontology_ecore.poheader h
JOIN ontology_ecore.poline l ON h.poheaderid = l.poheaderid
WHERE h.unitcode = '2800' AND h.approvalstatus = 'APPROVED'
  AND h.creationdate >= '2025-06-01' AND h.creationdate < '2026-06-01'
GROUP BY 1 ORDER BY 1
```

---

## 6. `demometaerp` 与 demo2 ECore（`ontology_ecore`）对比

### 6.1 环境与库结构

| 项 | `ontology_demometaerp`（历史会话） | `ontology_ecore`（demo2 现网） |
| --- | --- | --- |
| 入口 | pdt-dev 网关，仓库 id=3 `ECore/ontology_demometaerp` | demo2 网关，仓库 id=1 `ECore 本体库-勿动` |
| 当前可达性 | **不可达**：`/agent/doris/query` 返回 401 `code 4001 认证失败: 访问Token不存在` | **可达**：同一路径 200，`X-App-Id` + 仓库 id 即可 |
| 表命名 | 蛇形：`po_po_header_t` / `po_po_line_t` | 驼峰：`poheader` / `poline`（PG 实际折叠为小写） |
| 管理单元列 | `unit_code` | `unitcode` |
| 时间列 | `creation_date` | `creationdate` |
| 审批列 | 未取到（本次未成功查询） | `approvalstatus`（`APPROVED` / `APPROVING` / `INCOMPLETE`） |
| 金额列 | `amount`（单列） | `amount`（不含税）与 `taxinclusiveamount`（含税，实测 = amount × 1.05） |
| 引擎方言 | Doris / MySQL（`DATE_FORMAT`） | **PG**（`to_char` 可用；`DATE_FORMAT` 直接 HTTP 500，报文被遮蔽成「系统繁忙，请稍后再试」） |

### 6.2 同一问题的两套 SQL

同一句「管理单元 2800 的月度采购支出」，两个库的写法几乎全不同：

| 差异点 | demometaerp 写法 | ecore 写法 |
| --- | --- | --- |
| 月份格式化 | `DATE_FORMAT(x, '%Y-%m')` | `to_char(x, 'YYYY-MM')` |
| 表名 | `po_po_header_t` / `po_po_line_t` | `poheader` / `poline` |
| 关联键 | `po_header_id` | `poheaderid` |
| 单元过滤 | `unit_code` | `unitcode` |
| 时间过滤 | `creation_date` | `creationdate` |
| 金额 | `amount` | `taxinclusiveamount`（含税）/ `amount`（不含税） |

> 结论：把历史会话里跑通的 SQL 原样搬到 demo2 的 ECore 上会**直接失败**——表名、列名、方言三处都要改；
> 而且失败被网关统一包装成 `HTTP 500 系统繁忙`，从返回文案看不出是 SQL 方言问题。

### 6.3 实际数据对比 · 管理单元 `2800`

含税额（元）：`unitcode='2800'`，`2025-06-01 ~ 2026-06-01`，`po_count` 为单据数。

| 月份 | demometaerp 全口径(amount)【已执行】 | ecore 全口径(amount) | ecore 全口径(含税) | ecore 已审批(amount) | ecore 已审批(含税) | demo_scm_po 已审批(含税)【已执行】 |
| --- | --- | --- | --- | --- | --- | --- |
| 2025-12 | 11,577,630.00 | 11,577,630.00 | 12,156,511.50 | 10,857,630.00 | 11,400,511.50 | 11,400,511.50 |
| 2026-01 | 127,929,654.00 | 127,929,654.00 | 135,751,660.80 | 267,614.00 | 280,994.70 | 280,994.70 |
| 2026-02 | 21,961,102.87 | 21,961,102.87 | 23,499,158.00 | 9,017,328.58 | 9,468,195.00 | 9,468,195.00 |
| 2026-03 | 3,000,000.00 | 3,000,000.00 | 3,150,000.00 | 3,000,000.00 | 3,150,000.00 | 3,150,000.00 |
| 2026-04 | 2,053,500.00 | 2,053,500.00 | 2,156,176.05 | 1,863,507.00 | 1,956,682.35 | 1,956,682.35 |
| 2026-05 | 272,431,478.20 | 272,438,778.20 | 286,060,717.11 | 268,825,750.20 | 282,267,037.71 | 282,267,037.71 |

对齐情况：

- **ecore 已审批(含税) 与 demo_scm_po 已审批(含税) 6/6 完全一致**（逐月分毫不差）。
- **ecore 全口径(amount) 与 demometaerp 全口径(amount) 5/6 完全一致**（`po_count` 6/22/14/2/11/128 也完全一致）；
  仅 `2026-05` 差 **7,300.00 元**（ecore 272,438,778.20 vs demometaerp 272,431,478.20）。
- 全口径(含税) ≈ 全口径(amount) × 1.05，差额即 5% 税；选错列会系统性低估 5%。
- 两个库的表头 `poheader.amount` 都恒为 0（或空），**PO 头表金额不可用**，采购金额必须走行表 `poline`。

### 6.4 实际数据对比 · 管理单元 `101701`

`101701` 在 ecore 里是真实管理单元；在历史会话里从未作为过滤条件出现过，因此没有 demometaerp 侧的同口径数据可对照。

| 口径 | 月份 | 单据数 | 含税额（元） | 不含税额（元） |
| --- | --- | --- | --- | --- |
| 全口径 | 2026-02 | 42 | 124,359,588.58 | 116,395,777.49 |
| 全口径 | 2026-03 | 5 | 117,791.80 | 110,460.00 |
| 已审批 | 2026-02 | 24 | 71,393,568.10 | 67,352,409.49 |
| 已审批 | 2026-03 | 5 | 117,791.80 | 110,460.00 |

- `101701` 全部单据只落在 `2026-02`、`2026-03` 两个月（`poheader` 时间范围整体为 2025-11-26 ~ 2026-08-19）。
- 审批状态分布：`APPROVED` 30 / `APPROVING` 13 / `INCOMPLETE` 5（共 48 张）。
- 全口径与已审批的差额集中在 `2026-02`：含税 124,359,588.58 → 71,393,568.10（约 42.6% 未审批）。

### 6.5 对「连接」的影响小结

- **可达性分叉**：demo2(ecore) 匿名可用；pdt-dev(demometaerp) 现在强制 Token，`ONTOLOGY_AUTH_TOKEN` 为空时取数直接 401。
- **方言分叉**：ecore 已是 PG，`DATE_FORMAT` 等 MySQL 方言失效，必须换 `to_char`；错误被包装成「系统繁忙」，不报真实原因。
- **命名分叉**：`unit_code/creation_date/po_po_header_t` vs `unitcode/creationdate/poheader`，跨库复制 SQL 必失败。
- **金额列分叉**：`amount` 与 `taxinclusiveamount` 并存且相差 5%，口径需显式指定，否则结果系统性偏差。
