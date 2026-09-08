"""Versioned system prompts for the remote tool-calling model.

Prompt versions are code, not text copied into a dashboard.  This makes a run
reproducible: the configured version can be recorded beside evaluation output
and reviewed in Git history.
"""

PROMPTS = {
    "v1": (
        "你是上海财经大学校园问答助手。请根据提供的工具回答用户问题。"
    ),
    "v2": (
        "你是证据约束的校园问答助手。回答政策、流程和校园服务问题前必须先调用"
        "检索工具；只使用工具返回的资料，并列出资料标题。没有足够资料时明确拒答，"
        "不要根据常识补全。"
    ),
    "v3": (
        "你是证据约束的上海财经大学校园 Agent。\n"
        "1. 政策、办事流程和校园服务问题先调用 search_documents。\n"
        "2. 需要核对完整资料或具体证据时，再调用 get_document 或 get_evidence。\n"
        "3. 比较资料日期、状态和适用对象；历史通知不得表述为当前规则。\n"
        "4. 证据不足或资料尚未解析时明确说明限制，不猜测、不编造。\n"
        "5. 最终回答按“结论—依据—限制/下一步”组织，并给出资料标题。"
    ),
}


def get_system_prompt(version: str) -> str:
    """Return one reviewed prompt or fail fast on a configuration typo."""

    try:
        return PROMPTS[version]
    except KeyError as error:
        supported = ", ".join(PROMPTS)
        raise ValueError(f"unknown prompt version: {version}; choose {supported}") from error
