"""2026 年国家法定节假日种子数据（ADR-0005：静态随代码走，运行时零外部 API）。

来源：《国务院办公厅关于 2026 年部分节假日安排的通知》（2025-11 发布）。

补班日（workday）的 follow_weekday 官方不规定，本种子采用通用惯例并可被用户在校历中修改：
节前补班按周五（weekday=4）上课，节后补班按周一（weekday=0）上课。
"""

from datetime import date

# (日期, day_type, follow_weekday, note)
HOLIDAYS_2026: list[tuple[date, str, int | None, str]] = [
    # 元旦：1月1日（周四）放假 1 天，不调休
    (date(2026, 1, 1), "holiday", None, "元旦"),
    # 春节：2月15日（周日，除夕）至 22日 放假调休共 8 天；2月14日（周六）上班
    *[(date(2026, 2, d), "holiday", None, "春节") for d in range(15, 23)],
    (date(2026, 2, 14), "workday", 4, "春节调休补班（默认按周五课表，可改）"),
    # 清明节：4月4日（周六）至 6日 放假共 3 天
    (date(2026, 4, 4), "holiday", None, "清明节"),
    (date(2026, 4, 5), "holiday", None, "清明节"),
    (date(2026, 4, 6), "holiday", None, "清明节"),
    # 劳动节：5月1日（周五）至 5日 放假调休共 5 天；4月26日（周日）上班
    *[(date(2026, 5, d), "holiday", None, "劳动节") for d in range(1, 6)],
    (date(2026, 4, 26), "workday", 4, "劳动节调休补班（默认按周五课表，可改）"),
    # 端午节：6月19日（周五）至 21日 放假共 3 天
    (date(2026, 6, 19), "holiday", None, "端午节"),
    (date(2026, 6, 20), "holiday", None, "端午节"),
    (date(2026, 6, 21), "holiday", None, "端午节"),
    # 中秋节：9月25日（周五）至 27日 放假共 3 天，不调休
    (date(2026, 9, 25), "holiday", None, "中秋节"),
    (date(2026, 9, 26), "holiday", None, "中秋节"),
    (date(2026, 9, 27), "holiday", None, "中秋节"),
    # 国庆节：10月1日（周四）至 7日 放假调休共 7 天；9月20日（周日）、10月10日（周六）上班
    *[(date(2026, 10, d), "holiday", None, "国庆节") for d in range(1, 8)],
    (date(2026, 9, 20), "workday", 4, "国庆节调休补班（默认按周五课表，可改）"),
    (date(2026, 10, 10), "workday", 0, "国庆节调休补班（默认按周一课表，可改）"),
]
