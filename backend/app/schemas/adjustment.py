"""阶段五 schema：调整请求/结果、调整历史、反馈。"""

from datetime import date, datetime, time

from pydantic import BaseModel, Field, model_validator


class AdjustRequest(BaseModel):
    """实例调整请求。所有字段可选，只改传了的；new_date/new_period 用于换时段。

    force=False（默认）：有冲突直接 409 返回冲突列表；
    force=True：忽略冲突强行应用（reason 里会记录"强行应用"）。
    """

    new_date: date | None = None
    new_period: int | None = Field(default=None, ge=1, le=30)
    new_start_time: time | None = None
    new_end_time: time | None = None
    new_location: str | None = Field(default=None, max_length=100)
    new_teacher: str | None = Field(default=None, max_length=50)
    cancel: bool = False  # true = 取消这节课（status=cancelled）
    reason: str | None = Field(default=None, max_length=500)
    force: bool = False

    @model_validator(mode="after")
    def check_something_to_do(self):
        fields = [self.new_date, self.new_period, self.new_start_time, self.new_end_time, self.new_location, self.new_teacher]
        if not self.cancel and all(v is None for v in fields):
            raise ValueError("没有任何调整内容：至少填一项，或 cancel=true")
        if (
            self.new_start_time is not None
            and self.new_end_time is not None
            and self.new_end_time <= self.new_start_time
        ):
            raise ValueError("结束时间必须晚于开始时间")
        return self


class ConflictOut(BaseModel):
    conflicts: list[str]


class AdjustmentOut(BaseModel):
    id: str
    instance_id: str
    old_value: dict
    new_value: dict
    reason: str | None
    source: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AdjustResult(BaseModel):
    instance_id: str
    status: str
    adjustment_id: str
    version: int
    summary: str


class RollbackResult(BaseModel):
    instance_id: str
    restored: dict
    adjustment_id: str
    version: int


class FeedbackCreate(BaseModel):
    semester_id: str | None = None
    instance_id: str | None = None
    feedback_type: str = Field(pattern="^(wrong_time|wrong_holiday|wrong_week|wrong_textbook)$")
    description: str = Field(min_length=1, max_length=500)


class FeedbackOut(BaseModel):
    id: str
    instance_id: str | None
    semester_id: str | None
    feedback_type: str
    description: str
    resolved: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ConstraintOut(BaseModel):
    id: str
    constraint_json: dict
    applied: bool

    model_config = {"from_attributes": True}
