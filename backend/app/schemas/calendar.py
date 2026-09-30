from datetime import date, time

from pydantic import BaseModel, Field, model_validator

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


class VersionOut(BaseModel):
    id: str
    version: int
    source: str
    note: str | None
    is_current: bool
    override_count: int = 0

    model_config = {"from_attributes": True}


class OverrideCreate(BaseModel):
    date: date
    day_type: str = Field(pattern="^(holiday|workday|school_holiday|temp_cancel)$")
    follow_weekday: int | None = Field(default=None, ge=0, le=6)
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def check_follow_weekday(self):
        if self.day_type == "workday" and self.follow_weekday is None:
            raise ValueError("调休补班必须指定按周几的课表执行（follow_weekday）")
        return self


class OverrideOut(BaseModel):
    id: str
    date: date
    day_type: str
    follow_weekday: int | None
    note: str | None

    model_config = {"from_attributes": True}


class TemplateCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0=周一
    period_number: int = Field(ge=1, le=30)
    week_pattern: str = Field(default="all", max_length=50)
    course_name: str = Field(min_length=1, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    teacher: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, max_length=20)


class TemplateOut(BaseModel):
    id: str
    weekday: int
    period_number: int
    week_pattern: str
    course_name: str
    location: str | None
    teacher: str | None
    color: str

    model_config = {"from_attributes": True}


class InstanceOut(BaseModel):
    id: str
    date: date
    period_number: int
    start_time: time
    end_time: time
    course_name: str
    location: str | None
    teacher: str | None
    color: str
    status: str
    textbook_id: str | None = None
    textbook_cover: str | None = None  # 本地封面路径（/uploads/{path}）

    model_config = {"from_attributes": True}


class GenerateResult(BaseModel):
    created: int
    skipped: int
    version: int
