"""
services/email_resolver.py - EmailResolver (Lane B).

Responsibility: Given a selected CandidateContact and company domain,
resolve the best email address using a prioritised provider chain, with
a zero-quota permanent fallback that generates common corporate email
patterns and verifies them via SMTP MX-check.

Provider chain (in priority order):
  1. Hunter.io  - Email Finder + verification
  2. PDL        - Person enrichment
  3. Apollo     - people/match enrichment
  4. Pattern generator + SMTP/MX verification (permanent zero-quota fallback)

SMTP/MX verification is the primary verifier in practice:
  Hunter quota is currently exhausted.  The SMTP path must work standalone.

  SMTP verification process:
    a. DNS MX lookup for the domain (requires dnspython).
    b. SMTP EHLO + RCPT TO probe on port 25 (or 587 if 25 is blocked).
    c. 250 response -> address appears deliverable (UNVERIFIED - catch-alls exist).
    d. 550/551/553 -> address is invalid.
    e. All other errors (timeout, connection refused, etc.) -> UNVERIFIED.

  Catch-all detection: domains where every RCPT TO returns 250 regardless of
  address are detected by probing a random garbage address first.  If the probe
  succeeds, the domain is flagged as catch-all and patterns are returned as
  UNVERIFIED rather than claiming deliverability.

Generated patterns are always ranked below provider-returned emails in the
EnrichedContact.enrichment_status field (PARTIAL vs FULL).
"""

from __future__ import annotations

import asyncio
import logging
import random
import smtplib
import socket
import string
from typing import Any

from apps.api.modules.prospecting.engine.core.exceptions import (
    ProviderAuthError,
    ProviderQuotaExhaustedError,
)
from apps.api.modules.prospecting.engine.providers.base import EnrichmentProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    EnrichedContact,
    EnrichmentStatus,
    ProviderName,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

# Email patterns tried in order (highest deliverability probability first)
_EMAIL_PATTERNS = [
    "{first}.{last}@{domain}",
    "{first}{last}@{domain}",
    "{f}{last}@{domain}",
    "{first}@{domain}",
    "{f}.{last}@{domain}",
    "{last}@{domain}",
    "{first}_{last}@{domain}",
]

# SMTP connection timeout (seconds)
_SMTP_TIMEOUT = 8

# Ports to try for SMTP verification
_SMTP_PORTS = [25, 587]


class EmailResolver:
    """
    Lane B: resolves email for the selected best contact candidate.

    Provider chain -> SMTP pattern fallback.
    Always returns an EnrichedContact (never raises).
    """

    def __init__(self, enrichment_providers: list[EnrichmentProvider]) -> None:
        self._providers = enrichment_providers

    async def resolve(
        self,
        contact: CandidateContact,
        company: CandidateCompany,
    ) -> EnrichedContact:
        """
        Resolve email for a contact via the provider chain, then pattern fallback.

        Args:
            contact: Best candidate selected by ContactCandidatePool.
            company: Associated company (for domain-based resolution).

        Returns:
            EnrichedContact - always returns, never raises.
        """
        company_domain = company.domain
        providers_tried: list[ProviderName] = []

        # --- Fast Path: Literal email found on page -------------------------
        if contact.extracted_email:
            logger.info(
                "EmailResolver: fast path - using literal extracted email for '%s': %s",
                contact.display_name, contact.extracted_email,
            )
            return EnrichedContact(
                source_contact=contact,
                email=contact.extracted_email,
                email_verification_status=VerificationStatus.UNVERIFIED,
                phone=contact.phone or contact.extracted_phone,
                linkedin_url=contact.linkedin_url,
                enrichment_status=EnrichmentStatus.FULL,
                enrichment_providers_used=[contact.source_provider],
            )

        # --- Provider chain -------------------------------------------------
        for provider in self._providers:
            if not provider.is_enabled:
                continue

            providers_tried.append(provider.name)

            try:
                result = await provider.enrich_contact(contact, company_domain)

                if result.email and result.enrichment_status == EnrichmentStatus.FULL:
                    logger.debug(
                        "EmailResolver: '%s' fully resolved by provider '%s'",
                        contact.display_name, provider.name.value,
                    )
                    return result

                if result.email:
                    logger.debug(
                        "EmailResolver: partial result from '%s' for '%s' - continuing",
                        provider.name.value, contact.display_name,
                    )
                    # Carry email forward so next provider can improve on it
                    contact = contact.model_copy(update={"email": result.email})

            except ProviderQuotaExhaustedError as exc:
                logger.warning(
                    "EmailResolver: provider '%s' quota exhausted for '%s': %s",
                    provider.name.value, contact.display_name, exc,
                )
                continue
            except ProviderAuthError as exc:
                logger.error(
                    "EmailResolver: provider '%s' auth error for '%s': %s",
                    provider.name.value, contact.display_name, exc,
                )
                continue
            except Exception as exc:
                logger.warning(
                    "EmailResolver: provider '%s' failed for '%s': %s",
                    provider.name.value, contact.display_name, exc,
                )
                continue

        # Return existing email if any provider set one (even partially)
        if contact.email:
            return EnrichedContact(
                source_contact=contact,
                email=contact.email,
                phone=contact.phone,
                linkedin_url=contact.linkedin_url,
                enrichment_status=EnrichmentStatus.PARTIAL,
                enrichment_providers_used=providers_tried,
            )

        # --- Pattern generator fallback (zero-quota) ------------------------
        if company_domain and (contact.first_name or contact.full_name):
            pattern_result = await self._pattern_fallback(
                contact, company_domain, providers_tried
            )
            if pattern_result:
                return pattern_result

        # Nothing worked
        logger.debug(
            "EmailResolver: no email resolved for '%s' (providers tried: %s)",
            contact.display_name,
            [p.value for p in providers_tried],
        )
        return EnrichedContact(
            source_contact=contact,
            email=None,
            phone=contact.phone,
            linkedin_url=contact.linkedin_url,
            enrichment_status=EnrichmentStatus.PARTIAL,
            enrichment_providers_used=providers_tried,
        )

    # --- Pattern Fallback ---------------------------------------------------

    async def _pattern_fallback(
        self,
        contact: CandidateContact,
        domain: str,
        providers_tried: list[ProviderName],
    ) -> EnrichedContact | None:
        """
        Generate common email patterns and verify via SMTP MX-check.

        Returns the first deliverable pattern as an EnrichedContact,
        or None if no pattern verifies.

        Patterns ranked below provider-returned emails (status=PARTIAL).
        """
        # Extract name parts
        first = (contact.first_name or "").strip().lower()
        full = (contact.full_name or "").strip()
        if not first and full:
            parts = full.split()
            first = parts[0].lower() if parts else ""
            last_raw = parts[-1].lower() if len(parts) > 1 else ""
        else:
            last_raw = (contact.last_name or "").strip().lower()

        if not first or not last_raw:
            logger.debug(
                "EmailResolver: pattern fallback skipped for '%s' - insufficient name",
                contact.display_name,
            )
            return None

        f = first[0] if first else ""
        last = last_raw

        # Detect catch-all before trying real patterns
        is_catch_all = await asyncio.get_event_loop().run_in_executor(
            None, _smtp_check, _random_address(domain), domain
        )

        if is_catch_all:
            logger.debug(
                "EmailResolver: domain '%s' is a catch-all server - "
                "patterns returned as UNVERIFIED",
                domain,
            )

        candidates: list[tuple[str, VerificationStatus]] = []

        for pattern in _EMAIL_PATTERNS:
            try:
                email = pattern.format(
                    first=first, last=last, f=f, domain=domain
                )
            except KeyError:
                continue

            if is_catch_all:
                # Skip SMTP for catch-all - just queue as unverified
                candidates.append((email, VerificationStatus.UNVERIFIED))
            else:
                deliverable = await asyncio.get_event_loop().run_in_executor(
                    None, _smtp_check, email, domain
                )
                status = (
                    VerificationStatus.VERIFIED if deliverable
                    else VerificationStatus.INVALID
                )
                logger.debug(
                    "EmailResolver: SMTP MX-check -> %s for %s",
                    status.value, email,
                )
                if deliverable:
                    candidates.append((email, status))
                    break  # First verified pattern wins

        if not candidates:
            return None

        best_email, best_status = candidates[0]
        logger.info(
            "EmailResolver: resolved via pattern generator -> %s (status=%s) for '%s'",
            best_email, best_status.value, contact.display_name,
        )

        return EnrichedContact(
            source_contact=contact,
            email=best_email,
            email_verification_status=best_status,
            phone=contact.phone,
            linkedin_url=contact.linkedin_url,
            # PARTIAL because pattern generator is lower confidence than a provider
            enrichment_status=EnrichmentStatus.PARTIAL,
            enrichment_providers_used=providers_tried + [ProviderName.MANUAL],
        )


# --- SMTP / MX helpers (run in executor to avoid blocking the event loop) ----


def _get_mx_host(domain: str) -> str | None:
    """
    Resolve the primary MX record for a domain.
    Returns the hostname of the mail exchanger, or None on failure.

    Requires dnspython (pip install dnspython).
    Falls back to a direct connection attempt if dnspython is unavailable.
    """
    try:
        import dns.resolver  # noqa: PLC0415
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        # Sort by preference (lowest = highest priority)
        sorted_records = sorted(answers, key=lambda r: r.preference)
        return str(sorted_records[0].exchange).rstrip(".")
    except ImportError:
        # dnspython not installed - try the domain directly as a fallback
        logger.debug("dnspython not installed - using domain '%s' as MX host directly", domain)
        return domain
    except Exception as exc:
        logger.debug("MX lookup failed for '%s': %s", domain, exc)
        return None


def _smtp_check(email: str, domain: str) -> bool:
    """
    Perform an SMTP RCPT TO probe to check whether an email is deliverable.

    Returns True if the MX server accepts the address (250 response).
    Returns False on rejection (5xx) or any network/protocol error.

    NOTE: A True result on a catch-all domain does not confirm deliverability.
    Catch-all detection must be done separately (see _random_address()).
    """
    mx_host = _get_mx_host(domain)
    if not mx_host:
        return False

    sender = "probe@setvhealthcare.com"

    for port in _SMTP_PORTS:
        try:
            with smtplib.SMTP(timeout=_SMTP_TIMEOUT) as smtp:
                smtp.connect(mx_host, port)
                smtp.ehlo("setvhealthcare.com")
                smtp.mail(sender)
                code, _ = smtp.rcpt(email)
                if code == 250:
                    return True
                if code in (550, 551, 553, 554):
                    return False
                # Other codes (e.g. 452 = try again) - treat as unknown
                return False
        except smtplib.SMTPConnectError:
            continue  # Try next port
        except smtplib.SMTPRecipientsRefused:
            return False
        except (socket.timeout, ConnectionRefusedError, OSError):
            continue  # Try next port
        except Exception as exc:
            logger.debug("SMTP check error for %s: %s", email, exc)
            return False

    return False


def _random_address(domain: str) -> str:
    """Generate a random garbage address for catch-all detection."""
    rand = "".join(random.choices(string.ascii_lowercase, k=12))
    return f"{rand}@{domain}"
