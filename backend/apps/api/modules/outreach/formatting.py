"""
Unified email formatting pipeline.

This module is the SINGLE source of truth for rendering outreach emails.
It is used for BOTH:
  - Preview (in-browser via dangerouslySetInnerHTML)
  - Gmail Send (with cid: inline attachments)

Rendering order:
  1. Header Banner
  2. Subject (as heading)
  3. Body (Markdown → HTML)
  4. Divider
  5. Best Regards
  6. Sender Name + Designation + Company + Email + Phone + Website + LinkedIn + Address
  7. Company Logo
  8. Digital Signature Image
  9. Footer Banner
"""

import os
import re
import markdown
from typing import Any, Optional, Tuple


def _sanitize_url_for_preview(url: str) -> str:
    """
    Ensure image URLs are browser-accessible for preview.
    Relative /static/... paths are resolved to the backend base URL.
    """
    if not url:
        return ""
    url = url.strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"http://localhost:8000{url}"
    return url


def _sanitize_url_for_send(url: str, cid_prefix: str, inline_images: dict) -> str:
    """
    Convert a static file URL to a cid: attachment for Gmail sending.
    Stores the file path in inline_images dict keyed by the cid.
    """
    if not url:
        return ""
    url = url.strip()
    if "/static/uploads/" in url:
        filename = url.split("/static/uploads/")[-1].split("?")[0]
        local_path = os.path.join("static", "uploads", filename)
        cid = f"{cid_prefix}_{filename}"
        inline_images[cid] = local_path
        return f"cid:{cid}"
    # External URL — use as-is
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"http://localhost:8000{url}"
    return url


def _markdown_to_html(text: str) -> str:
    """Convert markdown body text to clean HTML."""
    if not text:
        return ""
    text = text.strip()

    # Strip any trailing sign-off that the LLM may have added despite instructions
    sign_off_patterns = [
        r"\n+Best Regards,?\s*$",
        r"\n+Warm Regards,?\s*$",
        r"\n+Sincerely,?\s*$",
        r"\n+Kind Regards,?\s*$",
        r"\n+Regards,?\s*$",
        r"\n+Thanks,?\s*$",
        r"\n+Thank you,?\s*$",
    ]
    for pat in sign_off_patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE).strip()

    return markdown.markdown(text, extensions=["extra", "nl2br"])


def generate_professional_html(
    body_text: str,
    subject: Optional[str],
    header_url: Optional[str],
    signature: Optional[Any],
    for_preview: bool = False,
) -> Tuple[str, dict]:
    """
    Centralized formatting pipeline.
    Returns (html_string, inline_images_dict).

    for_preview=True  → resolves images as browser-accessible HTTP URLs
    for_preview=False → converts images to cid: attachments for Gmail
    """
    inline_images: dict = {}

    def resolve_img(url: Optional[str], prefix: str) -> str:
        if not url:
            return ""
        if for_preview:
            return _sanitize_url_for_preview(url)
        return _sanitize_url_for_send(url, prefix, inline_images)

    parts = []

    # ── Outer container ──────────────────────────────────────────────────────
    parts.append(
        '<div style="font-family: Arial, Helvetica, sans-serif; color: #333333; '
        'max-width: 620px; margin: 0 auto; line-height: 1.65; background: #ffffff;">'
    )

    # ── 1. Header Banner ────────────────────────────────────────────────────
    # Priority: email.header_image_url → signature.header_banner_url
    header_img_url = resolve_img(header_url, "header")
    if not header_img_url and signature:
        fallback_header = getattr(signature, "header_banner_url", None) or getattr(signature, "header_image_url", None)
        header_img_url = resolve_img(fallback_header, "header")

    if header_img_url:
        parts.append(
            f'<div style="width: 100%; margin-bottom: 0;">'
            f'<img src="{header_img_url}" style="width: 100%; max-width: 620px; height: auto; display: block;" alt="Header Banner">'
            f'</div>'
        )

    # ── Email body wrapper ──────────────────────────────────────────────────
    parts.append('<div style="padding: 28px 32px;">')

    # ── 2. Subject heading ───────────────────────────────────────────────────
    if subject:
        parts.append(
            f'<h2 style="margin: 0 0 22px 0; font-size: 18px; font-weight: 700; '
            f'color: #111111; line-height: 1.3;">{subject}</h2>'
        )

    # ── 3. Body (Markdown → HTML) ────────────────────────────────────────────
    if body_text:
        body_html = _markdown_to_html(body_text)
        parts.append(
            f'<div style="font-size: 15px; line-height: 1.7; color: #2c2c2c; margin-bottom: 28px;">'
            f'{body_html}'
            f'</div>'
        )

    # ── 4-9. Footer (signature block) ───────────────────────────────────────
    # Always render at least "Best Regards," even without a signature template
    parts.append('<div style="margin-top: 8px;">')
    parts.append(
        '<p style="margin: 0 0 16px 0; font-size: 15px; color: #333333;">Best Regards,</p>'
    )

    if signature:
        # ── Divider ──────────────────────────────────────────────────────────
        parts.append(
            '<hr style="border: none; border-top: 1px solid #e8e8e8; margin: 0 0 18px 0;">'
        )

        # ── Company Logo + Sender details side by side ────────────────────
        logo_url = resolve_img(getattr(signature, "logo_url", None), "logo")
        parts.append('<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>')

        if logo_url:
            parts.append(
                f'<td style="width: 80px; padding-right: 16px; vertical-align: top;">'
                f'<img src="{logo_url}" style="max-width: 75px; height: auto; display: block;" alt="Logo">'
                f'</td>'
            )

        parts.append(
            '<td style="vertical-align: top; border-left: 3px solid #0056b3; padding-left: 14px;">'
        )

        # Sender name
        full_name = getattr(signature, "full_name", None)
        if full_name:
            parts.append(
                f'<div style="font-size: 16px; font-weight: 700; color: #0056b3; margin-bottom: 2px;">{full_name}</div>'
            )

        # Designation
        designation = getattr(signature, "designation", None)
        if designation:
            parts.append(
                f'<div style="font-size: 13px; color: #555555; margin-bottom: 1px;">{designation}</div>'
            )

        # Department
        department = getattr(signature, "department", None)
        if department:
            parts.append(
                f'<div style="font-size: 12px; color: #777777; margin-bottom: 4px;">{department}</div>'
            )

        # Company
        company = getattr(signature, "company", None)
        if company:
            parts.append(
                f'<div style="font-size: 13px; font-weight: 600; color: #222222; margin-bottom: 6px;">{company}</div>'
            )

        # Contact info rows
        sender_email = getattr(signature, "sender_email", None) or getattr(signature, "email", None)
        if sender_email:
            parts.append(
                f'<div style="font-size: 13px; color: #333333; margin-bottom: 2px;">'
                f'<a href="mailto:{sender_email}" style="color: #0056b3; text-decoration: none;">{sender_email}</a>'
                f'</div>'
            )

        phone = getattr(signature, "phone", None)
        if phone:
            parts.append(f'<div style="font-size: 13px; color: #333333; margin-bottom: 2px;">{phone}</div>')

        website = getattr(signature, "website", None)
        if website:
            display_site = website.replace("https://", "").replace("http://", "").rstrip("/")
            parts.append(
                f'<div style="font-size: 13px; margin-bottom: 2px;">'
                f'<a href="{website}" style="color: #0056b3; text-decoration: none;">{display_site}</a>'
                f'</div>'
            )

        linkedin = getattr(signature, "linkedin", None)
        if linkedin:
            parts.append(
                f'<div style="font-size: 13px; margin-bottom: 2px;">'
                f'<a href="{linkedin}" style="color: #0056b3; text-decoration: none;">LinkedIn</a>'
                f'</div>'
            )

        address = getattr(signature, "address", None)
        if address:
            parts.append(
                f'<div style="font-size: 12px; color: #888888; margin-top: 4px;">{address}</div>'
            )

        parts.append("</td></tr></table>")

        # ── Digital Signature Image ──────────────────────────────────────────
        dig_sig_url = resolve_img(getattr(signature, "digital_signature_url", None), "sig")
        if dig_sig_url:
            parts.append(
                f'<div style="margin-top: 16px;">'
                f'<img src="{dig_sig_url}" style="max-width: 200px; height: auto; display: block;" alt="Signature">'
                f'</div>'
            )

        # ── Footer Banner ────────────────────────────────────────────────────
        footer_banner = resolve_img(getattr(signature, "footer_banner_url", None), "footer")
        if footer_banner:
            parts.append(
                f'<div style="margin-top: 20px; text-align: center;">'
                f'<img src="{footer_banner}" style="width: 100%; max-width: 620px; height: auto; display: block;" alt="Footer Banner">'
                f'</div>'
            )

    parts.append("</div>")  # close footer block
    parts.append("</div>")  # close padding wrapper
    parts.append("</div>")  # close outer container

    return "".join(parts), inline_images


def format_and_save_email_html(db, email) -> None:
    """
    Populate html_body on an Email instance using the shared rendering pipeline.

    Uses email fields as primary source of truth.
    Falls back to the linked SignatureTemplate for any missing fields.
    Always uses for_preview=True (browser-safe image URLs).
    """
    from apps.api.modules.crm.models import AgentSettings, SignatureTemplate

    settings = db.query(AgentSettings).first()
    default_sig_id = settings.default_template_id if settings else None

    sig_id = getattr(email, "signature_template_id", None) or default_sig_id
    sig_template = None
    if sig_id:
        sig_template = db.query(SignatureTemplate).filter(SignatureTemplate.id == sig_id).first()

    # Build a merged signature object:
    # Email fields take priority; fall back to sig_template if email field is empty/None
    class MergedSig:
        """Merges email-level branding fields with a SignatureTemplate fallback."""

        FIELD_ALIASES = {
            "sender_email": ["sender_email", "email"],
            "header_image_url": ["header_image_url", "header_banner_url"],
        }

        def __getattr__(self, name):
            # 1. Check the email record first
            email_val = getattr(email, name, None)
            if email_val:
                return email_val

            # 2. Handle field aliases (email stores sender_email, sig stores email)
            if name == "sender_email":
                return getattr(email, "sender_email", None) or (
                    getattr(sig_template, "email", None) if sig_template else None
                )
            if name == "header_image_url":
                return getattr(email, "header_image_url", None) or (
                    getattr(sig_template, "header_banner_url", None) if sig_template else None
                )

            # 3. Fall back to sig_template
            if sig_template:
                return getattr(sig_template, name, None)

            return None

    merged = MergedSig()

    html_body, _ = generate_professional_html(
        body_text=getattr(email, "body", None),
        subject=getattr(email, "subject", None),
        header_url=getattr(email, "header_image_url", None),
        signature=merged,
        for_preview=True,
    )
    email.html_body = html_body
