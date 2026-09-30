from pydantic import BaseModel, Field


class ParseRuleRequest(BaseModel):
    semester_id: str
    text: str = Field(min_length=1, max_length=500)


class ScheduleRule(BaseModel):
    """AI 解析出的课表操作规则。"""

    action: str = Field(pattern="^(move|add|delete)$")
    weekday: int = Field(ge=0, le=6)
    period: int = Field(ge=1, le=30)
    to_weekday: int | None = Field(default=None, ge=0, le=6)
    to_period: int | None = Field(default=None, ge=1, le=30)
    course_name: str | None = Field(default=None, max_length=100)
    week_pattern: str | None = Field(default=None, max_length=50)


class ParseRuleResponse(BaseModel):
    rule: ScheduleRule | None
    applied: bool
    message: str
    regenerate: dict | None = None  # {"created": n, "skipped": n}


class AskRequest(BaseModel):
    semester_id: str | None = None
    question: str = Field(min_length=1, max_length=500)


class AskResponse(BaseModel):
    answer: str
