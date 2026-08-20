"""通知模块：渲染 Markdown 报告并通过 console / webhook / SMTP 推送。

接口契约（见 SPEC 第 5 节）：
- render_markdown(result: ScanResult, events: list[ChangeEvent]) -> str
- notify(result, events, settings)：console 打印；webhook_url 非空则按企业微信
  markdown 格式 POST；smtp.enabled 则发邮件；全部失败仅告警不崩溃。
"""

from __future__ import annotations

import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText

import requests

from gjjwatch.models import ChangeEvent, ScanResult

logger = logging.getLogger(__name__)


def render_markdown(result: ScanResult, events: list[ChangeEvent]) -> str:
    """把一次巡检结果渲染为 Markdown 报告文本。"""
    lines: list[str] = []
    lines.append("# 公积金政策监测报告")
    lines.append("")
    lines.append(f"- 运行时间：{result.run_at}")
    lines.append(f"- 新发现公告：{len(result.announcements)} 条")
    lines.append(f"- 关键词命中：{len(result.hits)} 条")
    lines.append(f"- 数据库变更事件：{len(events)} 条")
    lines.append(f"- 错误：{len(result.errors)} 条")

    if result.hits:
        lines.append("")
        lines.append("## 关键词命中")
        for ann in result.hits:
            date_str = ann.date or "日期未知"
            lines.append(f"- [{ann.city}] [{ann.title}]({ann.url})（{date_str}，{ann.channel}）")

    if result.announcements:
        lines.append("")
        lines.append("## 新发现公告")
        for ann in result.announcements:
            date_str = ann.date or "日期未知"
            lines.append(f"- [{ann.city}] [{ann.title}]({ann.url})（{date_str}，{ann.channel}）")

    if events:
        lines.append("")
        lines.append("## 数据库变更事件")
        for ev in events:
            lines.append(
                f"- [{ev.city}] `{ev.field_path}`: {ev.old_value!r} → {ev.new_value!r}"
                f"（来源：{ev.source_url}）")

    if result.errors:
        lines.append("")
        lines.append("## 错误")
        for err in result.errors:
            lines.append(f"- {err}")

    return "\n".join(lines)


def _notify_console(markdown: str) -> None:
    """控制台输出报告。"""
    print(markdown)


def _notify_webhook(markdown: str, webhook_url: str, timeout: int = 15) -> None:
    """按企业微信 markdown 消息格式 POST 到 webhook（飞书自定义机器人亦兼容该结构时可用）。"""
    payload = {"msgtype": "markdown", "markdown": {"content": markdown}}
    resp = requests.post(webhook_url, json=payload, timeout=timeout)
    resp.raise_for_status()


def _notify_smtp(markdown: str, smtp_cfg: dict) -> None:
    """通过 SMTP 发送纯文本邮件。"""
    host = smtp_cfg.get("host", "")
    port = int(smtp_cfg.get("port", 465))
    user = smtp_cfg.get("user", "")
    recipients = smtp_cfg.get("to") or []
    if not host or not recipients:
        logger.warning("SMTP 配置不完整（host/to 缺失），跳过邮件通知")
        return
    msg = MIMEText(markdown, "plain", "utf-8")
    msg["Subject"] = Header("公积金政策监测报告", "utf-8")
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    # 465 端口默认使用 SSL；其余端口尝试 STARTTLS
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            if user and smtp_cfg.get("password"):
                server.login(user, smtp_cfg["password"])
            server.sendmail(user, recipients, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            if user and smtp_cfg.get("password"):
                server.login(user, smtp_cfg["password"])
            server.sendmail(user, recipients, msg.as_string())


def notify(result: ScanResult, events: list[ChangeEvent], settings: dict) -> None:
    """按 settings["notify"] 配置推送报告；任何渠道失败仅告警，不抛异常。"""
    notify_cfg = settings.get("notify", {})
    markdown = render_markdown(result, events)

    if notify_cfg.get("console", True):
        try:
            _notify_console(markdown)
        except Exception as exc:  # noqa: BLE001
            logger.warning("console 通知失败：%s", exc)

    webhook_url = notify_cfg.get("webhook_url") or ""
    if webhook_url:
        try:
            _notify_webhook(markdown, webhook_url,
                            timeout=int(settings.get("request_timeout", 15)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("webhook 通知失败：%s", exc)

    smtp_cfg = notify_cfg.get("smtp") or {}
    if smtp_cfg.get("enabled"):
        try:
            _notify_smtp(markdown, smtp_cfg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SMTP 邮件通知失败：%s", exc)
