"""把 3.pdf 渲染成 PNG（视觉模型验证素材，ADR 0009 §2 验证关卡用）。

用法：.venv\\Scripts\\python.exe scripts\\render_docx_pages.py <pdf路径> <输出目录>
2 倍缩放渲染，保证课表小字清晰可读。只打前 5 页的日志，其余静默。
"""

import sys
from pathlib import Path

import pymupdf


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\1111\tmp\3.pdf")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(r"D:\1111\tmp")
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    print(f"页数: {len(doc)}")
    for i, page in enumerate(doc):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
        out = out_dir / f"3_p{i + 1:02d}.png"
        pix.save(out)
        if i < 5:
            print(f"{out}  {pix.width}x{pix.height}")
    print(f"共渲染 {len(doc)} 页 → {out_dir}")
    doc.close()


if __name__ == "__main__":
    main()
