"""腾讯云 OCR 服务（ADR 0009 §2 图片路径，2026-10-03 用户拍板选定方案）。

背景：成长计划免费包无任何视觉模型（hy3 收图片直接忽略，见 ADR 0009 验证关卡结论），
图片/扫描件路径按用户拍板走腾讯云 OCR 兜底：
- 主路径：TableOCR（表格识别）——课表截图几乎都是表格，它返回**带结构的表格 HTML**
  （TextTable 字段），不是拍平文字，行列关系保留，直接喂混元结构化即可；
- 兜底：GeneralBasicOCR（通用印刷体）——非表格布局的图片（如逐条文字的日程），
  只出扁平文字，交给混元尽力理解；
- 扫描型 PDF：pdfplumber 提不出文字时，用 pymupdf 把前几页渲染成 PNG 再走上面两条路。

密钥纪律：SecretId/Key 只放 .env（TENCENT_SECRET_ID / TENCENT_SECRET_KEY），
不进代码、不进日志、不进交接文档。未配置时 ocr_enabled() 为 False，路由层给明确指引。

额度：通用印刷体识别有每月免费额度（约 1000 次，表格识别类似），演示场景足够。
"""

import base64
import io
import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)

OCR_REGION = "ap-shanghai"  # 与 CloudBase 环境同地域
OCR_TIMEOUT_SECONDS = 30
# 扫描型 PDF 最多送 OCR 的页数（课表类文档前几页必有表格，控额度也控耗时）
MAX_PDF_PAGES_FOR_OCR = 3
# OCR 接口对 base64 图片的大小上限（腾讯云文档：7MB）
MAX_IMAGE_BYTES_FOR_OCR = 7 * 1024 * 1024


def ocr_enabled() -> bool:
    """两个密钥齐了才启用；缺失时由路由层给出可执行的配置指引。"""
    s = get_settings()
    return bool(s.TENCENT_SECRET_ID and s.TENCENT_SECRET_KEY)


def _ocr_client():
    """懒加载腾讯云 OCR 客户端（测试里 monkeypatch 本函数即可断网）。"""
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.ocr.v20181119 import ocr_client

    s = get_settings()
    cred = credential.Credential(s.TENCENT_SECRET_ID, s.TENCENT_SECRET_KEY)
    http = HttpProfile(endpoint="ocr.tencentcloudapi.com", reqTimeout=OCR_TIMEOUT_SECONDS)
    profile = ClientProfile(httpProfile=http)
    return ocr_client.OcrClient(cred, OCR_REGION, profile)


def _image_base64(data: bytes, filename: str) -> str:
    if len(data) > MAX_IMAGE_BYTES_FOR_OCR:
        raise ValueError(f"图片太大（{len(data) // 1024 // 1024}MB），OCR 上限 7MB，请压缩后再试")
    return base64.b64encode(data).decode()


def table_ocr_html(data: bytes, filename: str = "image") -> str:
    """表格识别：返回表格 HTML（保结构）。识别不到表格或接口失败返回空串（调用方降级）。"""
    from tencentcloud.common.exception import TencentCloudSDKException
    from tencentcloud.ocr.v20181119 import models

    try:
        req = models.TableOCRRequest()
        req.ImageBase64 = _image_base64(data, filename)
        resp = _ocr_client().TableOCR(req)
        html = (resp.TextTable or "").strip()
        logger.debug("表格识别 %s：%d 字符 HTML", filename, len(html))
        return html
    except TencentCloudSDKException as e:
        # 表格识别对非表格图片可能直接报错（HasNoTable 之类）——这是正常分支，降级通用识别
        logger.debug("表格识别未命中（%s: %s），降级通用印刷体", e.code, e.message)
        return ""
        # 其他异常（网络/鉴权）原样上抛，由路由层统一转 400 中文提示


def basic_ocr_text(data: bytes, filename: str = "image") -> str:
    """通用印刷体识别：逐条 DetectedText 按行拼回扁平文本。"""
    from tencentcloud.ocr.v20181119 import models

    req = models.GeneralBasicOCRRequest()
    req.ImageBase64 = _image_base64(data, filename)
    resp = _ocr_client().GeneralBasicOCR(req)
    lines = [d.DetectedText for d in (resp.TextDetections or []) if d.DetectedText]
    logger.debug("通用识别 %s：%d 行", filename, len(lines))
    return "\n".join(lines)


def image_to_text(data: bytes, filename: str = "image") -> str:
    """图片 → 文本：表格识别优先（保结构），空了降级通用识别（保覆盖）。"""
    html = table_ocr_html(data, filename)
    if html:
        return html_table_to_text(html)
    return basic_ocr_text(data, filename)


def pdf_to_texts(data: bytes) -> list[str]:
    """扫描型 PDF → 每页文本列表：pymupdf 渲染前 N 页为 PNG，逐页走 image_to_text。"""
    import pymupdf

    doc = pymupdf.open(io.BytesIO(data))
    texts: list[str] = []
    try:
        for page in doc.pages(0, min(len(doc), MAX_PDF_PAGES_FOR_OCR)):
            png = page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
            text = image_to_text(png, f"pdf_page_{page.number + 1}")
            if text.strip():
                texts.append(text)
    finally:
        doc.close()
    return texts


def html_table_to_text(html: str) -> str:
    """表格 HTML → "单元格 | 单元格" 行文本（喂给混元的 _IMPORT_SYSTEM_PROMPT 约定格式）。

    TableOCR 的 HTML 很规整（只有 table/tr/td 标签），正则剥离即可，无需引 HTML 解析器。
    """
    import re

    text = re.sub(r"(?i)</t[dh]>", " | ", html)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    # 行内收尾竖线、空白单元格压缩，保留原始列数信息（空列用空槽占位）
    lines = []
    for raw in text.splitlines():
        line = raw.replace("&nbsp;", " ").strip()
        line = re.sub(r"(\s*\|\s*)+$", "", line)
        if line.strip(" |"):
            lines.append(line)
    logger.debug("表格 HTML → %d 行文本", len(lines))
    return "\n".join(lines)
