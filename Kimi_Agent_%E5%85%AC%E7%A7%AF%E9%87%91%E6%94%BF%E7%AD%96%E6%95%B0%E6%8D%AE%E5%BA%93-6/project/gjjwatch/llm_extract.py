"""LLM 变更补丁抽取模块（可选能力）。

llm.enabled=false 或未设置 OPENAI_API_KEY 时直接返回 None；
开启时抓取公告正文，调用 OpenAI 兼容 chat API，要求其输出符合
{"city", "changes", "confidence"} JSON Schema 的补丁，解析失败返回 None。

接口契约（见 SPEC 第 5 节）：
- extract_patch(announcement, settings) -> dict | None
"""

from __future__ import annotations

import json
import logging
import os
import re

import requests
from bs4 import BeautifulSoup

from gjjwatch.models import Announcement

logger = logging.getLogger(__name__)

# 正文截断上限，防止超长页面打爆 token
_MAX_CONTENT_CHARS = 8000

# 目标 JSON Schema（内嵌于提示词）
_PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": "string", "description": "城市名，与数据库中 city 字段一致"},
        "changes": {
            "type": "object",
            "description": "字段路径到新值的映射，如 {\"loan.max_family\": 120}",
            "additionalProperties": True,
        },
        "confidence": {"type": "number", "description": "0~1 之间的置信度"},
    },
    "required": ["city", "changes", "confidence"],
}


def _fetch_page_text(url: str, settings: dict) -> str | None:
    """抓取公告页面并提取纯文本正文；失败返回 None。"""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": settings.get(
                "user_agent", "Mozilla/5.0 (compatible; gjj-policy-watch/1.0)")},
            timeout=settings.get("request_timeout", 15),
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # 去掉脚本/样式等噪声
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:_MAX_CONTENT_CHARS] or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("抓取公告正文失败 %s：%s", url, exc)
        return None


def _build_prompt(announcement: Announcement, content: str) -> str:
    """构造提示词，内嵌目标 JSON Schema，要求仅输出 JSON。"""
    schema_str = json.dumps(_PATCH_SCHEMA, ensure_ascii=False, indent=2)
    return (
        "你是住房公积金政策数据库维护助手。请阅读以下公告内容，抽取其中涉及的政策变更，"
        "输出一个 JSON 补丁对象。\n"
        "要求：\n"
        "1. 仅输出 JSON 本体，不要输出任何解释、Markdown 代码围栏或其他文字；\n"
        "2. JSON 必须符合以下 JSON Schema：\n"
        f"{schema_str}\n"
        "3. city 字段必须与给定城市名一致；changes 的键为字段路径（如 loan.max_family、"
        "deposit.base_upper），值为新政策数值或文本；\n"
        "4. 如果公告中没有可抽取的明确政策变更，输出 "
        '{"city": "%s", "changes": {}, "confidence": 0}。\n\n'
        "城市：%s\n"
        "公告标题：%s\n"
        "公告日期：%s\n"
        "公告正文：\n%s"
    ) % (announcement.city, announcement.city, announcement.title,
         announcement.date or "未知", content)


def _extract_json(text: str) -> dict | None:
    """从模型输出中提取首个 JSON 对象；容忍 ```json 代码围栏；失败返回 None。"""
    if not text:
        return None
    # 去掉可能的 Markdown 代码围栏
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else None
    if candidate is None:
        # 退而求其次：取第一个 { 到最后一个 } 之间的内容
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = text[start:end + 1]
    try:
        patch = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(patch, dict):
        return None
    # 基本结构校验
    if not isinstance(patch.get("city"), str):
        return None
    if not isinstance(patch.get("changes"), dict):
        return None
    if "confidence" not in patch:
        patch["confidence"] = 0.0
    return patch


def extract_patch(announcement: Announcement, settings: dict) -> dict | None:
    """从公告中抽取数据库变更补丁；任何环节失败均返回 None，绝不抛异常。"""
    llm_cfg = settings.get("llm", {})
    if not llm_cfg.get("enabled"):
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("llm.enabled=true 但未设置 OPENAI_API_KEY，跳过 LLM 抽取")
        return None

    content = _fetch_page_text(announcement.url, settings)
    if content is None:
        # 抓不到正文时退化为用标题+摘要做抽取
        content = f"{announcement.title}\n{announcement.snippet}".strip()
        if not content:
            return None

    base_url = llm_cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
    model = llm_cfg.get("model", "gpt-4o-mini")
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user",
                              "content": _build_prompt(announcement, content)}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=int(settings.get("request_timeout", 15)) * 4,  # LLM 调用给更长的超时
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 抽取请求失败（%s）：%s", announcement.url, exc)
        return None

    patch = _extract_json(text)
    if patch is None:
        logger.warning("LLM 输出无法解析为补丁 JSON：%s", text[:200])
        return None
    return patch
