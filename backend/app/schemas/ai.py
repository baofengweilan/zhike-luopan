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


# ==== ADR 0009：文件导入课表 ====


class ImportedCourse(BaseModel):
    """从文件解析出的单门课（确认卡片上展示、apply 时入库的原子单位）。"""

    course_name: str = Field(min_length=1, max_length=100)
    teacher: str | None = Field(default=None, max_length=50)
    weekday: int = Field(ge=0, le=6)  # 0=周一，与 CourseTemplate 一致
    start_period: int = Field(ge=1, le=30)
    end_period: int | None = Field(default=None, ge=1, le=30)  # 连堂最后一节，None=单节
    week_pattern: str = Field(default="all", max_length=50)  # all/odd/even/12-13,15
    location: str | None = Field(default=None, max_length=100)


class ImportScheduleApplyRequest(BaseModel):
    """确认卡片点「执行」后的入库请求。"""

    semester_id: str
    courses: list[ImportedCourse] = Field(min_length=1, max_length=200)
    clear_existing: bool = False  # True = 先清空该学期现有模板（覆盖式导入）
