from datetime import date, time

from pydantic import BaseModel, Field, model_validator

SEASON_NAMES = ("spring", "summer", "autumn", "winter")


class SemesterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    total_weeks: int = Field(ge=1, le=40)

    @model_validator(mode="after")
    def check_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class SemesterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    total_weeks: int | None = Field(default=None, ge=1, le=40)
    is_active: bool | None = None


class SemesterOut(BaseModel):
    id: str
    name: str
    start_date: date
    end_date: date
    total_weeks: int
    is_active: bool

    model_config = {"from_attributes": True}


class SeasonCreate(BaseModel):
    name: str = Field(pattern="^(spring|summer|autumn|winter)$")
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def check_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date 不能早于 start_date")
        return self


class SeasonOut(BaseModel):
    id: str
    name: str
    start_date: date
    end_date: date

    model_config = {"from_attributes": True}


class BellCreate(BaseModel):
    period_number: int = Field(ge=1, le=30)
    start_time: time
    end_time: time
    is_break: bool = False

    @model_validator(mode="after")
    def check_range(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time 必须晚于 start_time")
        return self


class BellOut(BaseModel):
    id: str
    period_number: int
    start_time: time
    end_time: time
    is_break: bool

    model_config = {"from_attributes": True}
