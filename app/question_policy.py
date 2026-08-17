"""Small deterministic boundaries for the offline Agent demonstration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuestionPolicyResult:
    allowed: bool
    code: str | None = None
    message: str | None = None


RULES = (
    (("破解", "校园网密码"), "UNSAFE_REQUEST", "不能协助获取或破解账号、密码等访问凭据。"),
    (
        ("私人手机号", "私人电话", "个人手机号"),
        "PRIVATE_INFORMATION",
        "不能提供个人私密联系方式，可查询学校公开办事入口。",
    ),
    (
        ("预测", "一定能", "肯定会", "肯定能"),
        "UNCERTAIN_PREDICTION",
        "现有资料只能解释规则，不能对未来结果作确定性预测。",
    ),
    (
        ("火锅店", "上证指数", "量子传送", "外星宠物", "火星交换生", "诊断"),
        "OUT_OF_SCOPE",
        "该问题不属于当前校园知识库可回答范围。",
    ),
)


def assess_question(question: str) -> QuestionPolicyResult:
    text = question.strip().lower()
    for phrases, code, message in RULES:
        if any(phrase.lower() in text for phrase in phrases):
            return QuestionPolicyResult(False, code, message)
    return QuestionPolicyResult(True)
