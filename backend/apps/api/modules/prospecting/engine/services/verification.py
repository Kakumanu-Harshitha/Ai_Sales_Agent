"""
services/verification.py â€” VerificationService.

Responsibility: Validate the quality of enriched contact information
using deterministic, rule-based checks. No AI, no external APIs.

Checks performed:
  1. Email format validation (RFC 5322 regex)
  2. Email MX record lookup (DNS) â€” confirms the domain can receive email
  3. Phone number format validation (E.164 via phonenumbers library)

All checks are non-blocking best-effort:
  - DNS lookup timeout â†’ treated as "unverified" (not "invalid")
  - phonenumbers parse failure â†’ treated as "unverified"

The service updates the verification_status fields on the EnrichedContact
and returns the updated contact.
"""

from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache

from apps.api.modules.prospecting.engine.schemas.internal import EnrichedContact, EnrichmentStatus, VerificationStatus

logger = logging.getLogger(__name__)

# â”€â”€â”€ Email validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# RFC 5322-ish regex (simple but sufficient for pre-send validation)
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

_DNS_TIMEOUT = 5  # seconds for MX record lookup


class VerificationService:
    """
    Validates email format, email domain MX records, and phone number format.

    All operations are deterministic and require no external API calls
    (DNS lookup uses the system resolver â€” entirely free).
    """

    async def verify(self, contact: EnrichedContact) -> EnrichedContact:
        """
        Run all applicable verification checks on a contact.

        Returns an updated EnrichedContact with corrected verification_status
        fields. The enrichment_status may be downgraded to FAILED if
        verification reveals the contact information is definitively invalid.
        """
        email_status = contact.email_verification_status
        phone_status = contact.phone_verification_status

        # â”€â”€ Email verification â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if contact.email:
            email_status = await self._verify_email(contact.email)
        else:
            email_status = VerificationStatus.UNVERIFIED

        # â”€â”€ Phone verification â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if contact.phone:
            phone_status = self._verify_phone(contact.phone)

        # â”€â”€ Determine final enrichment status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # FULL: we have a verified (or at least syntactically valid) email
        # PARTIAL: email present but unverified, or no email at all
        # FAILED: email confirmed invalid
        if email_status == VerificationStatus.INVALID:
            enrichment_status = EnrichmentStatus.PARTIAL  # Invalid email â†’ partial, not failed
            logger.warning(
                "Contact '%s' has invalid email '%s' â€” marking as unverified",
                contact.source_contact.display_name, contact.email,
            )
            # Clear the invalid email to prevent it being used
            return contact.model_copy(
                update={
                    "email": None,
                    "email_verification_status": VerificationStatus.INVALID,
                    "phone_verification_status": phone_status,
                    "enrichment_status": enrichment_status,
                }
            )

        enrichment_status = (
            EnrichmentStatus.FULL
            if (contact.email and email_status == VerificationStatus.VERIFIED)
            else contact.enrichment_status
        )

        return contact.model_copy(
            update={
                "email_verification_status": email_status,
                "phone_verification_status": phone_status,
                "enrichment_status": enrichment_status,
            }
        )

    async def _verify_email(self, email: str) -> VerificationStatus:
        """
        Two-stage email verification:
          1. Regex format check (synchronous)
          2. DNS MX record lookup (async with timeout)
        """
        # Stage 1: format check
        if not _EMAIL_RE.match(email):
            logger.debug("Email '%s' failed regex validation", email)
            return VerificationStatus.INVALID

        # Stage 2: MX record lookup
        domain = email.split("@")[1]
        has_mx = await self._check_mx_async(domain)

        if has_mx is False:
            logger.debug("Domain '%s' has no MX records â€” email invalid", domain)
            return VerificationStatus.INVALID

        if has_mx is None:
            # DNS lookup failed/timed out â€” treat as unverified, not invalid
            return VerificationStatus.UNVERIFIED

        return VerificationStatus.VERIFIED

    @staticmethod
    async def _check_mx_async(domain: str) -> bool | None:
        """
        Check if the domain has MX records via async DNS query.

        Returns:
          True  â€” domain has MX records (email can be received)
          False â€” domain has no MX records (email is invalid)
          None  â€” DNS lookup failed or timed out (unknown)
        """
        try:
            import dns.resolver  # noqa: PLC0415

            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: _dns_mx_lookup(domain),
                ),
                timeout=_DNS_TIMEOUT,
            )
            return result

        except asyncio.TimeoutError:
            logger.debug("MX lookup timed out for domain '%s'", domain)
            return None
        except ImportError:
            logger.debug("dnspython not available â€” skipping MX check")
            return None  # Treat as unverified
        except Exception as exc:
            logger.debug("MX lookup failed for '%s': %s", domain, exc)
            return None

    @staticmethod
    def _verify_phone(phone: str) -> VerificationStatus:
        """Validate phone number format using the phonenumbers library."""
        try:
            import phonenumbers  # noqa: PLC0415

            # Default to US region if no country code prefix
            parsed = phonenumbers.parse(phone, "US")
            if phonenumbers.is_valid_number(parsed):
                return VerificationStatus.VERIFIED
            return VerificationStatus.INVALID

        except ImportError:
            return VerificationStatus.UNVERIFIED
        except Exception:
            return VerificationStatus.UNVERIFIED


def _dns_mx_lookup(domain: str) -> bool:
    """Synchronous DNS MX lookup â€” runs in executor."""
    import dns.resolver  # noqa: PLC0415

    try:
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        return False
    except Exception:
        return False

