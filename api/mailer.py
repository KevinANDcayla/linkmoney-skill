"""
LinkMoney Mailer — SMTP 邮件发送模块

支持:
- RFQ 提交时通知供应商（新询盘提醒）
- 供应商报价后通知采购方（报价已回复）
- 邮件覆盖机制：LINKMONEY_RFQ_OVERRIDE_EMAIL 将所有通知转发到指定邮箱
- 通过环境变量配置 SMTP 参数

环境变量:
  LINKMONEY_SMTP_HOST          SMTP 服务器地址（默认 smtp.qq.com）
  LINKMONEY_SMTP_PORT          SMTP 端口（默认 587）
  LINKMONEY_SMTP_USER          SMTP 用户名
  LINKMONEY_SMTP_PASSWORD      SMTP 密码/授权码
  LINKMONEY_SMTP_FROM          发件人地址
  LINKMONEY_SMTP_USE_TLS       是否使用 TLS（默认 true）
  LINKMONEY_MAIL_ENABLED       是否启用邮件发送（默认 false，生产环境改为 true）
  LINKMONEY_RFQ_OVERRIDE_EMAIL 邮件覆盖地址（前期所有通知发到此邮箱，有真实工厂后删除此变量）
"""

import os
import logging
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger("linkmoney.mailer")


class Mailer:
    """SMTP 邮件发送器，在后台线程中异步发送，不阻塞 API 响应"""

    def __init__(self):
        self.enabled = os.getenv("LINKMONEY_MAIL_ENABLED", "false").lower() == "true"
        self.host = os.getenv("LINKMONEY_SMTP_HOST", "smtp.qq.com")
        self.port = int(os.getenv("LINKMONEY_SMTP_PORT", "587"))
        self.user = os.getenv("LINKMONEY_SMTP_USER", "")
        self.password = os.getenv("LINKMONEY_SMTP_PASSWORD", "")
        self.from_addr = os.getenv("LINKMONEY_SMTP_FROM", self.user)
        self.use_tls = os.getenv("LINKMONEY_SMTP_USE_TLS", "true").lower() == "true"
        # 邮件覆盖：前期所有 RFQ 通知统一发到这个地址
        self.override_email = os.getenv("LINKMONEY_RFQ_OVERRIDE_EMAIL", "").strip()

    def _send(self, to_email: str, subject: str, html_body: str):
        """实际发送邮件（同步）"""
        if not self.enabled:
            logger.info(f"[MAIL DISABLED] To: {to_email} | Subject: {subject}")
            return False

        if not self.user or not self.password:
            logger.warning(f"[MAIL SKIP] SMTP 未配置用户名/密码，跳过发送 To: {to_email}")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"LinkMoney <{self.from_addr}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            server = smtplib.SMTP(self.host, self.port, timeout=15)
            if self.use_tls:
                server.starttls()
            server.login(self.user, self.password)
            server.sendmail(self.from_addr, [to_email], msg.as_string())
            server.quit()
            logger.info(f"[MAIL SENT] To: {to_email} | Subject: {subject}")
            return True
        except Exception as e:
            logger.error(f"[MAIL FAIL] To: {to_email} | Error: {e}")
            return False

    def send_async(self, to_email: str, subject: str, html_body: str):
        """异步发送邮件（后台线程，不阻塞请求）"""
        thread = threading.Thread(target=self._send, args=(to_email, subject, html_body), daemon=True)
        thread.start()

    def _resolve_to(self, original_email: str, label: str = "") -> tuple:
        """
        解析收件人：如果设置了 override_email，则统一发送到覆盖地址，
        并在邮件主题中标注原始收件人信息。
        返回 (actual_to_email, subject_suffix)
        """
        if self.override_email:
            suffix = f" [原收件人: {original_email}]" if original_email else ""
            logger.info(f"[MAIL OVERRIDE] {label} → {self.override_email} (原: {original_email})")
            return self.override_email, suffix
        return original_email, ""

    # ---- 业务邮件模板 ----

    def notify_supplier_new_rfq(self, supplier: dict, buyer: dict, rfq: dict, product_name: str):
        """通知中国供应商：有新询盘"""
        original_email = supplier.get("email", "")
        to_email, suffix = self._resolve_to(original_email, f"供应商 {supplier.get('name_zh', '')}")

        subject = f"[LinkMoney RFQ] 您收到了来自 {buyer.get('company', '海外买家')} 的新询盘 - {product_name}{suffix}"

        body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #0A0E27, #1a1f4a); color: #fff; padding: 24px; border-radius: 12px 12px 0 0;">
                <h1 style="margin:0; font-size:24px;">🔗 LinkMoney 新询盘通知</h1>
                <p style="margin:8px 0 0; opacity:0.8;">Agent 时代的 B2B 贸易链接器</p>
            </div>

            <div style="background: #F5F7FA; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p><strong>{supplier.get('name_zh', '')}</strong> 负责人您好，</p>

                <p>您的 LinkMoney Skill 收到了一条来自海外采购方的询盘：</p>

                <table style="width:100%; border-collapse:collapse; margin: 16px 0;">
                    <tr><td style="padding:8px; font-weight:bold; width:120px;">RFQ 编号</td><td style="padding:8px;">{rfq['id']}</td></tr>
                    <tr style="background:#fff;"><td style="padding:8px; font-weight:bold;">采购方</td><td style="padding:8px;">{buyer.get('company', 'N/A')} ({buyer.get('country', 'N/A')})</td></tr>
                    <tr><td style="padding:8px; font-weight:bold;">采购方邮箱</td><td style="padding:8px;">{rfq.get('contact_email', buyer.get('email', '未提供'))}</td></tr>
                    <tr style="background:#fff;"><td style="padding:8px; font-weight:bold;">产品</td><td style="padding:8px;">{product_name} ({rfq['sku']})</td></tr>
                    <tr><td style="padding:8px; font-weight:bold;">数量</td><td style="padding:8px;">{rfq['quantity']:,} {rfq.get('unit', 'pcs')}</td></tr>
                    <tr style="background:#fff;"><td style="padding:8px; font-weight:bold;">目标价</td><td style="padding:8px;">USD {rfq['target_price_usd']}/pc</td></tr>
                    <tr><td style="padding:8px; font-weight:bold;">贸易条款</td><td style="padding:8px;">{rfq['incoterms']} {rfq['port']}</td></tr>
                    <tr style="background:#fff;"><td style="padding:8px; font-weight:bold;">交期要求</td><td style="padding:8px;">{rfq.get('delivery_deadline', '未指定')}</td></tr>
                </table>

                <div style="background: #FFF3CD; border: 1px solid #FFB800; border-radius: 8px; padding: 16px; margin: 16px 0;">
                    <strong>⏰ 请尽快回复报价</strong><br>
                    建议在 24 小时内回复报价，提高成交率。
                </div>

                <div style="margin-top: 16px;">
                    <p><strong>下一步操作：</strong></p>
                    <ol>
                        <li>让您的 Agent 调用 <code>get_my_rfqs?supplier_id={supplier['id']}</code> 查看完整 RFQ 详情</li>
                        <li>准备好报价后，让 Agent 调用 <code>send_quote</code> 发送报价给采购方</li>
                        <li>或直接回复此邮件联系采购方</li>
                    </ol>
                </div>
            </div>

            <div style="text-align:center; color:#999; font-size:12px; margin-top:16px;">
                LinkMoney（连钱）— 让钱通过 Agent 流动<br>
                <a href="https://linkmoney.online" style="color:#0066FF;">linkmoney.online</a>
            </div>
        </div>
        """
        self.send_async(to_email, subject, body)

    def notify_buyer_rfq_received(self, buyer: dict, supplier: dict, rfq: dict, matches: list):
        """通知海外采购方：RFQ 已收到 + 匹配到的中国工厂信息 + 预计 5 工作日回复"""
        original_email = buyer.get("email", rfq.get("contact_email", ""))
        to_email, suffix = self._resolve_to(original_email, f"采购方 {buyer.get('company', '')}")

        subject = f"[LinkMoney] Your RFQ #{rfq['id']} has been received - {len(matches)} Chinese factories matched{suffix}"

        # 构建匹配工厂列表（最多 5 家）
        factory_rows = ""
        for i, m in enumerate(matches[:5], 1):
            name_en = m.get("name_en", m.get("name_zh", ""))
            name_zh = m.get("name_zh", "")
            loc = m.get("location", {})
            city = loc.get("city", "?") if isinstance(loc, dict) else str(loc)
            province = loc.get("province", "") if isinstance(loc, dict) else ""
            certs = ", ".join(m.get("certifications", []) or [])
            score = m.get("match_score", 0)
            moq = m.get("moq", 0)
            skill_badge = "Skill Installed" if m.get("has_skill") else "Cached Profile"
            mcp = m.get("mcp_endpoint", "")

            factory_rows += f"""
                <tr style="background:#fff;">
                    <td style="padding:10px; border-bottom:1px solid #eee;">
                        <strong>{i}. {name_en}</strong><br>
                        <span style="color:#666; font-size:12px;">{name_zh}</span><br>
                        <span style="color:#888; font-size:11px;">📍 {city}, {province} | 📋 {certs}</span><br>
                        <span style="color:#888; font-size:11px;">⭐ Match Score: {score}/100 | MOQ: {moq:,} pcs | 🔧 {skill_badge}</span>
                        {f'<br><span style="color:#0066FF; font-size:11px;">🔗 MCP: {mcp}</span>' if mcp else ''}
                    </td>
                </tr>"""

        body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 640px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #0A0E27, #1a1f4a); color: #fff; padding: 24px; border-radius: 12px 12px 0 0;">
                <h1 style="margin:0; font-size:24px;">🔗 LinkMoney RFQ Received</h1>
                <p style="margin:8px 0 0; opacity:0.8;">Agent-Powered B2B Trade Connector</p>
            </div>

            <div style="background: #F5F7FA; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p>Dear <strong>{buyer.get('contact_person', buyer.get('company', 'Buyer'))}</strong>,</p>

                <p>Good news! Your RFQ has been successfully submitted and we've matched you with <strong>{len(matches)} Chinese factories</strong> from our verified supplier network.</p>

                <table style="width:100%; border-collapse:collapse; margin: 16px 0;">
                    <tr><td style="padding:8px; font-weight:bold; width:140px;">RFQ ID</td><td style="padding:8px;">{rfq['id']}</td></tr>
                    <tr style="background:#fff;"><td style="padding:8px; font-weight:bold;">Product</td><td style="padding:8px;">{rfq['sku']}</td></tr>
                    <tr><td style="padding:8px; font-weight:bold;">Quantity</td><td style="padding:8px;">{rfq['quantity']:,} pcs</td></tr>
                    <tr style="background:#fff;"><td style="padding:8px; font-weight:bold;">Target Price</td><td style="padding:8px;">USD {rfq['target_price_usd']}/pc</td></tr>
                    <tr><td style="padding:8px; font-weight:bold;">Trade Terms</td><td style="padding:8px;">{rfq['incoterms']} {rfq['port']}</td></tr>
                </table>

                <h3 style="color:#0A0E27; margin-top:24px;">🏭 Matched Chinese Factories</h3>
                <table style="width:100%; border-collapse:collapse; margin: 8px 0 16px;">
                    <tr style="background:#0A0E27; color:#fff;">
                        <td style="padding:10px; font-weight:bold;">Factory Details</td>
                    </tr>
                    {factory_rows}
                </table>

                <div style="background: #D4EDDA; border: 1px solid #28A745; border-radius: 8px; padding: 16px; margin: 16px 0;">
                    <strong>⏱ Estimated Response Time: 5 Business Days</strong><br>
                    The selected factory <strong>{supplier.get('name_en', supplier.get('name_zh', ''))}</strong> has been notified of your inquiry.
                    You can expect a formal quote within <strong>5 business days</strong>.
                </div>

                <div style="margin-top: 16px;">
                    <p><strong>What happens next?</strong></p>
                    <ol>
                        <li>The factory reviews your RFQ and prepares a quote</li>
                        <li>You'll receive another email when the quote is ready</li>
                        <li>Your Agent can check status anytime: <code>get_my_rfqs</code></li>
                        <li>Factories with <strong>🔧 Skill Installed</strong> support real-time pricing via MCP</li>
                    </ol>
                </div>

                <div style="background: #E2E3FF; border-radius: 8px; padding: 12px; margin: 16px 0;">
                    <strong>Need help?</strong><br>
                    Reply to this email or contact LinkMoney support<br>
                    Website: <a href="https://linkmoney.online" style="color:#0066FF;">linkmoney.online</a>
                </div>
            </div>

            <div style="text-align:center; color:#999; font-size:12px; margin-top:16px;">
                LinkMoney — Link the Money, Link the World<br>
                <a href="https://linkmoney.online" style="color:#0066FF;">linkmoney.online</a>
            </div>
        </div>
        """
        self.send_async(to_email, subject, body)

    def notify_buyer_quote_received(self, buyer: dict, supplier: dict, rfq: dict, quote: dict):
        """通知海外采购方：中国供应商已报价"""
        original_email = buyer.get("email", rfq.get("contact_email", ""))
        to_email, suffix = self._resolve_to(original_email, f"采购方 {buyer.get('company', '')}")

        subject = f"[LinkMoney Quote] {supplier.get('name_en', 'Chinese Supplier')} has quoted your RFQ #{rfq['id']}{suffix}"

        status_labels = {
            "quoted": "Quoted",
            "negotiating": "Under Negotiation",
            "accepted": "Accepted",
            "closed": "Closed",
        }

        body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #0A0E27, #1a1f4a); color: #fff; padding: 24px; border-radius: 12px 12px 0 0;">
                <h1 style="margin:0; font-size:24px;">🔗 LinkMoney Quote Update</h1>
                <p style="margin:8px 0 0; opacity:0.8;">Agent-Powered B2B Trade Connector</p>
            </div>

            <div style="background: #F5F7FA; padding: 24px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p>Dear <strong>{buyer.get('contact_person', buyer.get('company', 'Buyer'))}</strong>,</p>

                <p>Good news! A Chinese supplier has responded to your RFQ:</p>

                <table style="width:100%; border-collapse:collapse; margin: 16px 0;">
                    <tr><td style="padding:8px; font-weight:bold; width:140px;">RFQ ID</td><td style="padding:8px;">{rfq['id']}</td></tr>
                    <tr style="background:#fff;"><td style="padding:8px; font-weight:bold;">Supplier</td><td style="padding:8px;">{supplier.get('name_en', '')} ({supplier.get('name_zh', '')})</td></tr>
                    <tr><td style="padding:8px; font-weight:bold;">Contact</td><td style="padding:8px;">{supplier.get('contact_person', '')} | {supplier.get('email', '')} | {supplier.get('phone', '')}</td></tr>
                    <tr style="background:#fff;"><td style="padding:8px; font-weight:bold;">Product</td><td style="padding:8px;">{rfq['sku']}</td></tr>
                    <tr><td style="padding:8px; font-weight:bold;">Quantity</td><td style="padding:8px;">{rfq['quantity']:,} pcs</td></tr>
                </table>

                <div style="background: #D4EDDA; border: 1px solid #28A745; border-radius: 8px; padding: 16px; margin: 16px 0;">
                    <strong>Quoted Price:</strong> USD {quote.get('unit_price_usd', 0)}/pc<br>
                    <strong>Total:</strong> USD {quote.get('total_price_usd', 0):,.2f}<br>
                    <strong>Lead Time:</strong> {quote.get('lead_time_days', 0)} days<br>
                    <strong>Status:</strong> {status_labels.get(quote.get('status', 'quoted'), 'Quoted')}
                </div>

                <div style="margin-top: 16px;">
                    <p><strong>Next Steps:</strong></p>
                    <ol>
                        <li>Review the quote details above</li>
                        <li>Reply to this email or contact the supplier directly at {supplier.get('email', '')}</li>
                        <li>Your Agent can check status with <code>get_my_rfqs?supplier_id={supplier['id']}</code></li>
                    </ol>
                </div>

                <div style="background: #E2E3FF; border-radius: 8px; padding: 12px; margin: 16px 0;">
                    <strong>Supplier Contact:</strong><br>
                    {supplier.get('contact_person', '')} | {supplier.get('email', '')} | {supplier.get('phone', '')}<br>
                    WeChat: {supplier.get('wechat', 'N/A')}
                </div>
            </div>

            <div style="text-align:center; color:#999; font-size:12px; margin-top:16px;">
                LinkMoney — Link the Money, Link the World<br>
                <a href="https://linkmoney.online" style="color:#0066FF;">linkmoney.online</a>
            </div>
        </div>
        """
        self.send_async(to_email, subject, body)


# 全局单例
mailer = Mailer()