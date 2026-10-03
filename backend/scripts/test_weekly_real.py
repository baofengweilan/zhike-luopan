"""3.docx 逐周表格精确管道实测（ADR 0009 验证关卡验收）。

用真实混元拆分课名/教室，输出课程草稿供人工比对周次归属是否精确。
用法：.venv\\Scripts\\python.exe scripts\\test_weekly_real.py [docx路径]
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from app.services.importer import parse_weekly_grid_docx


def main() -> None:
    docx_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\wings\Downloads\3.docx"
    data = Path(docx_path).read_bytes()
    result = parse_weekly_grid_docx(data)
    if result is None:
        print("未识别为逐周表格格式")
        return
    courses, warnings, raw_chars = result
    print(f"\n警告: {warnings}")
    print(f"单元格原文总量: {raw_chars} 字")
    print(f"课程草稿 {len(courses)} 条：")
    for c in sorted(courses, key=lambda x: (x.weekday, x.start_period)):
        end = f"-{c.end_period}" if c.end_period and c.end_period != c.start_period else ""
        loc = f" @{c.location}" if c.location else ""
        teacher = f" [{c.teacher}]" if c.teacher else ""
        print(f"  周{c.weekday + 1} 第{c.start_period}{end}节 {c.course_name}{teacher}{loc}  周次={c.week_pattern}")


if __name__ == "__main__":
    main()
