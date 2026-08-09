"""AI Agent 任务拆解演示（终极挑战加分项）。

场景：Agent 收到需求 + 整套系统技术文档，判断——
1. 该需求需要改哪几个微服务？
2. 哪些改动可以同时进行（互不影响）？
3. 哪些改动必须按先后顺序（有依赖关系）？

三步拆解流程（对应 项目说明.md 第 5 节设计）：
Step 1 需求实体抽取：LLM 把自然语言需求解析为结构化三元组（触发事件/动作/数据依赖）
Step 2 服务匹配：基于能力清单（system_docs.md）检索候选服务 + LLM 裁决
Step 3 依赖图构建：LLM 按接口/事件/数据依赖输出并行组与串行链 + Mermaid 图

用法（backend/ 目录下）：
    .venv\\Scripts\\python agent_demo/agent.py "用户下单后自动发送短信通知"
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.services.llm import chat_json  # noqa: E402

SYSTEM_DOCS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_docs.md")

# Step 1：需求实体抽取
EXTRACT_PROMPT = """你是软件工程需求分析师。请把用户需求解析为结构化 JSON：
{{
  "trigger": "触发事件（业务动作，如'下单成功'）",
  "action": "需要执行的动作（如'发送短信通知'）",
  "data_dependencies": ["动作依赖的数据（如'用户手机号、订单号、通知模板'）"],
  "user_visible": "用户能否感知到该变化（true/false）"
}}
仅输出 JSON。需求：{requirement}"""

# Step 2/3：服务匹配 + 依赖分析（能力清单全文注入，LLM 检索 + 裁决）
PLAN_PROMPT = """你是资深架构师。根据【系统技术文档】判断实现该需求需要改动哪些微服务，并规划执行顺序。

【系统技术文档】
{docs}

【需求实体】
{entities}

【需求原文】
{requirement}

请输出 JSON（不要输出其他内容）：
{{
  "services": [
    {{"service": "服务名", "change": "具体改动内容（涉及哪个接口/数据表/事件）", "depends_on": ["依赖的其他服务改动（无则空数组）"]}}
  ],
  "parallel_groups": [["可同时进行的改动，互不影响（服务名）"]],
  "serial_chain": ["必须按先后顺序执行的服务改动（如 A→B→C，A 是 B 的输入依赖）"],
  "rationale": "依赖判定依据（哪个接口/事件/字段构成了依赖关系，200字内）"
}}"""

DEFAULT_REQUIREMENT = "用户下单后自动发送短信通知"


def load_system_docs() -> str:
    with open(SYSTEM_DOCS_PATH, encoding="utf-8") as f:
        return f.read()


async def decompose(requirement: str) -> dict:
    """三步拆解：实体抽取 → 计划生成（含服务匹配与依赖分析）。"""
    docs = load_system_docs()

    # Step 1：实体抽取
    entities = await chat_json(
        [
            {"role": "system", "content": "你是软件工程需求分析师。"},
            {"role": "user", "content": EXTRACT_PROMPT.format(requirement=requirement)},
        ],
        temperature=0.1,
        max_tokens=300,
    )
    if not entities:
        entities = {"trigger": requirement, "action": requirement, "data_dependencies": [], "user_visible": True}

    # Step 2+3：注入能力清单，LLM 完成服务匹配与依赖分析
    plan = await chat_json(
        [
            {"role": "system", "content": "你是资深微服务架构师，依据文档事实做判断，不得臆造文档中不存在的接口。"},
            {
                "role": "user",
                "content": PLAN_PROMPT.format(
                    docs=docs[:8000], entities=json.dumps(entities, ensure_ascii=False), requirement=requirement
                ),
            },
        ],
        temperature=0.1,
        max_tokens=1500,
    )
    return {"requirement": requirement, "entities": entities, **plan}


def render_mermaid(plan: dict) -> str:
    """把执行计划渲染为 Mermaid 依赖图（并行组并排，串行链纵向）。"""
    lines = ["graph LR"]
    services = plan.get("services", [])
    serial = plan.get("serial_chain", [])
    for i, s in enumerate(services):
        sid = f"S{i}"
        lines.append(f'    {sid}["{s.get("service", "?")}"]')
    # 依赖边
    for i, s in enumerate(services):
        for dep in s.get("depends_on", []):
            for j, other in enumerate(services):
                if other.get("service") == dep:
                    lines.append(f"    S{j} --> S{i}")
    # 并行组标注
    for g in plan.get("parallel_groups", []):
        names = " & ".join(g)
        lines.append(f'    subgraph PG["可并行: {names}"]')
        for name in g:
            for i, s in enumerate(services):
                if s.get("service") == name:
                    lines.append(f"    S{i}")
        lines.append("    end")
    return "\n".join(lines)


def format_plan(plan: dict) -> str:
    out = [f"## 需求：{plan.get('requirement', '')}", ""]
    ent = plan.get("entities", {})
    out.append(f"- **触发事件**：{ent.get('trigger', '?')}")
    out.append(f"- **执行动作**：{ent.get('action', '?')}")
    out.append(f"- **数据依赖**：{', '.join(ent.get('data_dependencies', []) or [])}")
    out.append("")
    out.append("### 需要改动的服务")
    for s in plan.get("services", []):
        deps = s.get("depends_on", [])
        dep_str = f"（依赖：{'、'.join(deps)}）" if deps else "（无依赖）"
        out.append(f"- **{s.get('service')}** {dep_str}：{s.get('change')}")
    out.append("")
    out.append("### 执行顺序")
    for i, g in enumerate(plan.get("parallel_groups", [])):
        out.append(f"- 第 {i+1} 批（可并行）：{'、'.join(g)}")
    chain = plan.get("serial_chain", [])
    if chain:
        out.append(f"- 串行链：{' → '.join(chain)}")
    out.append("")
    out.append(f"### 判定依据\n{plan.get('rationale', '')}")
    out.append("")
    out.append("### 依赖图")
    out.append("```mermaid")
    out.append(render_mermaid(plan))
    out.append("```")
    return "\n".join(out)


def main():
    requirement = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REQUIREMENT
    plan = asyncio.run(decompose(requirement))
    print(format_plan(plan))


if __name__ == "__main__":
    main()
