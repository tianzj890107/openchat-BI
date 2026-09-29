# 图 9 · 评测与发布门禁

> 智能分析 Agent 全链路流程图 · 第 9/9 张 —— CI 作业链、release gate 的六类必过门与被阻断条件、live canary 的边界。
> 基线 2026-09-20，仓库工作区当前代码；不含真实凭据、密钥或内部绝对路径。
> 返回 [图目录](README.md) ｜ 节点 → 代码位置见 [README §10](README.md#10-节点--代码位置索引)。

---

```mermaid
flowchart TD
    P0["push / MR 触发 pipeline"] --> J1["unit-tests<br/>pytest -q tests"]
    P0 --> J2["analytics-eval-smoke"]
    J2 --> J3["analytics-eval-regression"]
    J3 --> J4["analytics-eval-recorded-provider<br/>离线录制回放"]
    J4 --> J5["analytics-eval-repeat-stability<br/>--repeat 2"]

    J5 --> RG{"release gate<br/>--release"}
    J7["analytics-eval-live-canary<br/>manual · allow_failure · 无 Key 则 not_measured"] --> RG

    RG --> M1{"P0 契约全通过？"}
    RG --> M2{"known gap allowlist 为空 / 已审计？"}
    RG --> M3{"精确数字 / schema / 证据覆盖 = 1.0？"}
    RG --> M4{"未支撑数字 / 跨会话泄漏 = 0.0？"}
    RG --> M5{"因果越界 = 0.0 · 代理披露 = 1.0？"}
    RG --> M6{"repeat stability 已测量且无漂移？"}

    M1 -->|否| FAIL["阻断发布"]
    M2 -->|否| FAIL
    M3 -->|否| FAIL
    M4 -->|否| FAIL
    M5 -->|否| FAIL
    M6 -->|否| FAIL
    M1 -->|是| PASS["允许发布"]
    M2 -->|是| PASS
    M3 -->|是| PASS
    M4 -->|是| PASS
    M5 -->|是| PASS
    M6 -->|是| PASS
```

要点：

- **普通开发 pipeline** 快速、确定性、可单次运行；`repeat_stability` 允许显示 `not_measured`。
- **正式 release gate** 必须真实重复运行并比较语义指纹；`not_measured` / 零样本 / 第二次 skip 一律阻断。
- **live canary** 是独立的外部测量层，缺 Provider Key 时为 `not_measured`，**不得**写成 pass，也不得用生产 Key 冒充。
