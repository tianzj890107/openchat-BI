"""360 智能分析: the analysis agent that works on the 流程360全局本体.

It is separate from the general 智能分析 agent (openchat BI ontology) and from
the cockpit cards' own node ontologies.  The access strategy follows
《流程360全局本体_智能分析Agent访问策略_V1.0》: resolve the scope, assemble the
minimal subgraph, run registered queries only, record three-state judgements
with their evidence, and draft advice for a person to confirm.
"""

from .ontology import load_config

AGENT_NAME = "analysis360"

__all__ = ["AGENT_NAME", "load_config"]
