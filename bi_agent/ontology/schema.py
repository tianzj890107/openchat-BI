"""
Ontology data classes matching the real ChatBI业务元数据_光峰财务管理.xlsx structure.

Nine ontology sheets, each mapped to a dataclass:
    Term            — 术语 (business terminology)
    BusinessObject  — 业务对象 (BO level, a domain concept)
    LogicalEntity   — 逻辑实体 (LE level, concrete data entity under a BO)
    Attribute       — 业务属性 (AT level, a column on an LE)
    EntityRelation  — 实体关系 (ER between LEs)
    Metric          — 指标 (measurable quantity, atom or composite)
    Activity        — 活动 (business activity, may have upstream dependency)
    BusinessRule    — 业务规则 (rule attached to an activity)
    DimMatrix       — 指标维度矩阵 (which dims apply to which metric)

Levels: BusinessObject (BO) -> LogicalEntity (LE) -> Attribute (AT).
A BO may have multiple LEs; each LE has its own physical table and attributes.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------

@dataclass
class Term:
    """一个业务术语及其定义."""
    code: str                     # T000001
    name: str                     # 组织
    aliases: list[str] = field(default_factory=list)
    english: str = ""
    definition: str = ""
    category: str = ""            # 术语分类 e.g. 组织主数据
    department: str = ""          # 解释部门

    def to_prompt(self) -> str:
        lines = [f"术语 [{self.code}] {self.name}"]
        if self.aliases:
            lines.append(f"  别名: {', '.join(self.aliases)}")
        if self.english:
            lines.append(f"  英文: {self.english}")
        if self.definition:
            lines.append(f"  定义: {self.definition}")
        if self.category:
            lines.append(f"  分类: {self.category}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Business Objects (BO)
# ---------------------------------------------------------------------------

@dataclass
class BusinessObject:
    """业务对象 — 领域层面的概念."""
    code: str                     # BO0001
    name: str                     # 管报损益
    english: str = ""             # Management PnL
    definition: str = ""
    type: str = ""                # 数据模型 / 业务对象类型
    physical_table: str = ""      # 关联物理表

    def to_prompt(self) -> str:
        header = f"业务对象 [{self.code}] {self.name}"
        if self.english:
            header += f" ({self.english})"
        lines = [header]
        if self.type:
            lines.append(f"  类型: {self.type}")
        if self.physical_table:
            lines.append(f"  物理表: {self.physical_table}")
        if self.definition:
            lines.append(f"  定义: {self.definition}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Logical Entities (LE)
# ---------------------------------------------------------------------------

@dataclass
class LogicalEntity:
    """逻辑实体 — BO 之下的具体数据实体,一对一映射物理表."""
    code: str                     # LE00001
    name: str                     # 组织
    english: str = ""             # organization
    definition: str = ""
    physical_table: str = ""      # T_ORG_Organizations
    bo_code: str = ""             # BO0002 (parent BO)
    bo_name: str = ""             # 组织

    def to_prompt(self) -> str:
        header = f"逻辑实体 [{self.code}] {self.name}"
        if self.english:
            header += f" ({self.english})"
        lines = [header]
        if self.physical_table:
            lines.append(f"  物理表: {self.physical_table}")
        if self.bo_code:
            lines.append(f"  所属业务对象: [{self.bo_code}] {self.bo_name}")
        if self.definition:
            lines.append(f"  定义: {self.definition}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Attributes (AT)
# ---------------------------------------------------------------------------

@dataclass
class Attribute:
    """业务属性 — LE 上的一个具体字段,对应物理列."""
    code: str                     # AT00001
    name: str                     # 组织内码
    english: str = ""             # FOrgId (physical column)
    definition: str = ""
    data_type: str = ""           # NVARCHAR(36)
    is_primary_key: bool = False
    le_code: str = ""             # LE00001
    le_name: str = ""
    le_english: str = ""

    def to_prompt(self) -> str:
        parts = [f"[{self.code}]", self.name]
        if self.english:
            parts.append(f"({self.english})")
        parts.append(self.data_type or "?")
        if self.is_primary_key:
            parts.append("[PK]")
        line = " ".join(parts)
        if self.definition:
            line += f" — {self.definition}"
        return line


# ---------------------------------------------------------------------------
# Entity Relations (ER)
# ---------------------------------------------------------------------------

@dataclass
class EntityRelation:
    """实体关系 — 两个 LE 之间的业务关系."""
    code: str                     # ER001
    source_code: str              # LE00001
    source_name: str
    target_code: str
    target_name: str
    cardinality: str = ""         # 1:N / N:1 / N:N / 1:1
    description: str = ""         # 业务语义描述
    foreign_key: str = ""         # FParentOrgId -> FOrgId

    def to_prompt(self) -> str:
        arrow = f"{self.source_name} --[{self.cardinality or '?'}]-> {self.target_name}"
        lines = [f"[{self.code}] {arrow}"]
        if self.description:
            lines.append(f"  含义: {self.description}")
        if self.foreign_key:
            lines.append(f"  外键: {self.foreign_key}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Metrics (M)
# ---------------------------------------------------------------------------

# Metric types
METRIC_TYPE_COMPOSITE = 1
METRIC_TYPE_ATOMIC = 2


@dataclass
class Metric:
    """指标 — 业务可测量的量,带完整的计算口径和维度适用性."""
    code: str                     # M001
    name: str                     # 管报收入
    aliases: list[str] = field(default_factory=list)
    english: str = ""             # Management Revenue
    definition: str = ""
    formula_business: str = ""    # SUM(FAmount) WHERE FMgmtCategory=收入
    scope: str = ""               # 统计口径 (范围 + 维度描述)
    metric_type: int = METRIC_TYPE_ATOMIC  # 1=复合, 2=原子
    formula_technical: str = ""
    table: str = ""               # T_FM_MgmtPnL
    agg_column: str = ""          # FAmount
    agg_type: str = ""            # SUM / AVG / COUNT ...
    join_condition: str = ""
    filter_condition: str = ""    # FMgmtCategory = '收入'
    dim_columns: str = ""
    version: str = ""
    change_note: str = ""
    applicable_dimensions: list[str] = field(default_factory=list)  # filled from DimMatrix

    @property
    def is_atomic(self) -> bool:
        return self.metric_type == METRIC_TYPE_ATOMIC

    def to_prompt(self) -> str:
        kind = "原子指标" if self.is_atomic else "复合指标"
        header = f"指标 [{self.code}] {self.name} ({kind})"
        if self.english:
            header += f" — {self.english}"
        lines = [header]
        if self.aliases:
            lines.append(f"  别名: {', '.join(self.aliases)}")
        if self.definition:
            lines.append(f"  定义: {self.definition}")
        if self.formula_business:
            lines.append(f"  业务公式: {self.formula_business}")
        if self.scope:
            lines.append(f"  统计口径: {self.scope}")
        if self.table:
            base = f"  SQL: {self.agg_type or 'SUM'}({self.agg_column}) FROM {self.table}"
            if self.filter_condition:
                base += f" WHERE {self.filter_condition}"
            if self.join_condition:
                base += f" JOIN: {self.join_condition}"
            lines.append(base)
        if self.applicable_dimensions:
            lines.append(f"  适用维度: {', '.join(self.applicable_dimensions)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Activities (A)
# ---------------------------------------------------------------------------

@dataclass
class Activity:
    """业务活动 — 一段有明确产出的业务工作,通常对应一个报表或流程节点."""
    code: str                     # A001
    name: str                     # 编制管报收入成本表
    description: str = ""
    upstream_codes: list[str] = field(default_factory=list)  # 上游活动
    role: str = ""                # 业务角色
    object_codes: list[str] = field(default_factory=list)    # BO codes
    object_names: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        lines = [f"活动 [{self.code}] {self.name}"]
        if self.description:
            lines.append(f"  描述: {self.description}")
        if self.upstream_codes:
            lines.append(f"  上游活动: {', '.join(self.upstream_codes)}")
        if self.role:
            lines.append(f"  角色: {self.role}")
        if self.object_names:
            lines.append(f"  涉及对象: {', '.join(self.object_names)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Business Rules (R)
# ---------------------------------------------------------------------------

@dataclass
class BusinessRule:
    """业务规则 — 挂在活动上的一条硬性业务约束."""
    code: str                     # R001
    rule: str                     # 规则内容
    activity_code: str = ""       # 所属活动
    activity_name: str = ""
    category: str = ""            # 数据来源/分摊规则/校验/...
    department: str = ""

    def to_prompt(self) -> str:
        lines = [f"规则 [{self.code}] ({self.category})"]
        lines.append(f"  {self.rule}")
        if self.activity_code:
            lines.append(f"  所属活动: [{self.activity_code}] {self.activity_name}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dimension Matrix entry
# ---------------------------------------------------------------------------

@dataclass
class DimMatrixEntry:
    """指标 × 维度的一行: 这个指标适用哪些维度."""
    metric_code: str
    metric_name: str
    dimensions: dict[str, bool] = field(default_factory=dict)  # dim_name -> True if applicable

    def applicable(self) -> list[str]:
        return [d for d, v in self.dimensions.items() if v]
