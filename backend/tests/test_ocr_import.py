"""ADR 0009 图片路径：腾讯云 OCR 导入管道（OCR 与 LLM 全程 mock，不联网不烧额度）。"""

import json

from app.services.ocr import html_table_to_text

# ==== 单元：表格 HTML → 管道约定文本 ====


def test_html_table_to_text_keeps_structure():
    html = (
        "<table><tr><td>周一</td><td>周二</td></tr>"
        "<tr><td>高等数学 宝教二102</td><td></td></tr></table>"
    )
    text = html_table_to_text(html)
    lines = text.splitlines()
    assert lines[0] == "周一 | 周二"
    assert lines[1] == "高等数学 宝教二102"  # 行尾空单元格的竖线被清理（中部空槽保留）
    assert "<" not in text


# ==== 端到端：图片/扫描 PDF 走 OCR → 混元结构化（mock）====

PIPE_TEXT = "周一 | 周三\n高等数学 宝教二102 | 大学英语 宝教二102"

LLM_JSON = json.dumps(
    {
        "courses": [
            {"name": "高等数学", "weekday": 0, "start_period": 1, "weeks": "all", "location": "宝教二102"},
            {"name": "大学英语", "weekday": 2, "start_period": 3, "weeks": "all", "location": "宝教二102"},
        ]
    },
    ensure_ascii=False,
)


def _turn_ai_on(client, monkeypatch):
    from tests.test_import_schedule import LLM_JSON as _  # noqa: F401 确保两个用例同构

    monkeypatch.setattr("app.services.ai.ai_enabled", lambda: True)
    monkeypatch.setattr("app.services.ai._llm_chat", lambda s, u, timeout=30: LLM_JSON)


def _auth(client):
    resp = client.post("/api/auth/wx-login", json={"code": "ocr"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_image_import_via_ocr(client, mock_wx, monkeypatch):
    _turn_ai_on(client, monkeypatch)
    monkeypatch.setattr("app.services.ocr.ocr_enabled", lambda: True)
    monkeypatch.setattr("app.services.ocr.image_to_text", lambda data, filename="image": PIPE_TEXT)

    auth = _auth(client)
    resp = client.post(
        "/api/ai/import-schedule/parse",
        files={"file": ("课表截图.png", b"\x89PNG-fake", "image/png")},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["file_type"] == "图片(OCR)"
    assert [c["course_name"] for c in data["courses"]] == ["高等数学", "大学英语"]
    assert any("OCR" in w for w in data["warnings"])  # 提醒用户核对周次


def test_image_without_ocr_keys_gives_guidance(client, mock_wx, monkeypatch):
    """未配密钥 → 400 且带可执行指引（去哪建密钥、配哪个键）。"""
    monkeypatch.setattr("app.services.ocr.ocr_enabled", lambda: False)
    auth = _auth(client)
    resp = client.post(
        "/api/ai/import-schedule/parse",
        files={"file": ("课表截图.jpg", b"fake", "image/jpeg")},
        headers=auth,
    )
    assert resp.status_code == 400
    assert "TENCENT_SECRET_ID" in resp.json()["detail"]


def test_image_with_no_text_detected(client, mock_wx, monkeypatch):
    _turn_ai_on(client, monkeypatch)
    monkeypatch.setattr("app.services.ocr.ocr_enabled", lambda: True)
    monkeypatch.setattr("app.services.ocr.image_to_text", lambda data, filename="image": "")
    auth = _auth(client)
    resp = client.post(
        "/api/ai/import-schedule/parse",
        files={"file": ("课表截图.png", b"\x89PNG-fake", "image/png")},
        headers=auth,
    )
    assert resp.status_code == 400
    assert "没识别到文字或表格" in resp.json()["detail"]


def test_scanned_pdf_falls_back_to_ocr(client, mock_wx, monkeypatch):
    """文本型提取为空的 PDF → 渲染页面走 OCR（mock pdf_to_texts）。"""
    import pymupdf

    _turn_ai_on(client, monkeypatch)
    monkeypatch.setattr("app.services.ocr.ocr_enabled", lambda: True)
    monkeypatch.setattr("app.services.ocr.pdf_to_texts", lambda data: [PIPE_TEXT])
    # 造一个合法但无文字的 PDF（真扫描版的样子），假字节骗不过 pdfplumber
    doc = pymupdf.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()
    auth = _auth(client)
    resp = client.post(
        "/api/ai/import-schedule/parse",
        files={"file": ("扫描课表.pdf", pdf_bytes, "application/pdf")},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["file_type"] == "PDF(OCR)"
    assert len(data["courses"]) == 2
