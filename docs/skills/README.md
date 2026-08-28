# Capability design documents

本目录中的文件都是面向研发和产品的设计文档，**不是运行时 Skill**。ChatBI 不会从
`docs/skills/` 加载或执行任何文件，也不会因为文档放在这个目录就自动获得对应能力。

本目录当前包含：

- `AI工艺对话UI设计规范.md`: conversational UI design specification
- `图库检索规则_上下文提取与根因分析.md`: graph retrieval and root-cause analysis rules
- `报表生成能力_设计文档.md`: management-report generation capability
- `智能分析软件运作思路_现阶段版本.md`: current intelligent-analysis workflow and boundaries

运行时 Skill 只会从用户级 `~/.claude/skills/`、项目级 `.claude/skills/`、兼容目录
`.claude/commands/` 或程序内置 Skill 注册表加载。当前项目没有项目级
`.claude/skills/`；实际 Skill 名称见 `../ChatBI_Skills.md`。

`Ontology-GraphContext`、`Ontology-GraphExpand`、`Ontology-FactQuery`、图表和表格生成等能力属于 Agent Tools，
不是 Skill；实际 Tool 名称见 `../ChatBI_Tools.md`。
