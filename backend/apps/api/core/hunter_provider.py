import logging
import requests
from typing import Optional, Dict, Any

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

class HunterProvider:
    """
    Centralized service for Hunter.io API interactions.
    Used for email finding and verification to enrich existing contacts.
    """

    def __init__(self):
        self.api_key = getattr(settings, "HUNTER_API_KEY", None)
        self.base_url = "https://api.hunter.io/v2"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def find_email(self, first_name: str, last_name: str, domain: str) -> Optional[Dict[str, Any]]:
        """
        Finds a public business email for a contact using Hunter.io.
        Does not guess emails; only returns verified/found results.
        Returns dict with 'email' and 'confidence' (score) if found, else None.
        """
        if not self.is_configured():
            return None

        try:
            response = requests.get(
                f"{self.base_url}/email-finder",
                params={
                    "domain": domain,
                    "first_name": first_name,
                    "last_name": last_name,
                    "api_key": self.api_key
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                email = data.get("email")
                if email:
                    return {
                        "email": email,
                        "confidence": data.get("score", 0),
                        "status": "found"
                    }
            elif response.status_code == 429:
                logger.warning("Hunter API rate limit exceeded.")
            elif response.status_code != 404:  # 404 just means not found
                logger.error(f"Hunter API find error: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Hunter API request failed: {e}")

        return None

    def verify_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Verifies an existing business email address.
        """
        if not self.is_configured():
            return None

        try:
            response = requests.get(
                f"{self.base_url}/email-verifier",
                params={
                    "email": email,
                    "api_key": self.api_key
                },
                timeout=10
            )

            if response.status_code == 200:
                data = response.json().get("data", {})
                return {
                    "status": data.get("status"),
                    "score": data.get("score", 0),
                    "sources": len(data.get("sources", []))
                }
            elif response.status_code == 429:
                logger.warning("Hunter API rate limit exceeded.")
            else:
                logger.error(f"Hunter API verify error: {response.status_code} - {response.text}")

        except Exception as e:
            logger.error(f"Hunter API request failed: {e}")

        return None
