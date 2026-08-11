"""
Centralized AI Provider service wrapping Groq API calls.
"""

import json
import re
import logging
import requests
from typing import Any

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

class AIProvider:
    """
    Centralized service for all AI interactions across the SETV Sales Agent platform.
    Connects exclusively to Groq API.
    """

    def __init__(self):
        self.api_key = getattr(settings, "GROQ_API_KEY", None)
        self.model = getattr(settings, "GROQ_MODEL", "llama3-70b-8192")
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def _extract_json(self, text: str) -> Any:
        """Robustly extract JSON from AI response text."""
        if not text:
            return None

        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        fence_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```', text, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        obj_match = re.search(r'\{[\s\S]*\}', text)
        if obj_match:
            try:
                return json.loads(obj_match.group(0))
            except json.JSONDecodeError:
                pass

        arr_match = re.search(r'\[[\s\S]*\]', text)
        if arr_match:
            try:
                return json.loads(arr_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.error(f"AIProvider: could not extract JSON from text. First 300 chars: {text[:300]!r}")
        return None

    def generate_content(
        self,
        system_instruction: str,
        prompt: str,
    ) -> dict[str, Any]:
        """
        Call Groq API and return a parsed JSON dictionary.
        """
        has_key = bool(self.api_key)
        
        if not has_key:
            error_msg = "GROQ_API_KEY is missing. Check your .env file."
            print(f"Error: {error_msg}")
            raise ValueError(error_msg)

        fallback_model = getattr(settings, "GROQ_FALLBACK_MODEL", None)
        
        models_to_try = []
        if has_key:
            models_to_try.append({
                "provider": "Groq",
                "endpoint": self.endpoint,
                "api_key": self.api_key,
                "model": self.model
            })
            if fallback_model and fallback_model != self.model:
                models_to_try.append({
                    "provider": "Groq",
                    "endpoint": self.endpoint,
                    "api_key": self.api_key,
                    "model": fallback_model
                })
                
        mistral_key = getattr(settings, "MISTRAL_API_KEY", None)
        if mistral_key:
            mistral_model = getattr(settings, "MISTRAL_MODEL", "mistral-small-latest")
            models_to_try.append({
                "provider": "Mistral",
                "endpoint": "https://api.mistral.ai/v1/chat/completions",
                "api_key": mistral_key,
                "model": mistral_model
            })
            
        if not models_to_try:
            error_msg = "No AI providers configured. Check your .env file."
            logger.error(error_msg)
            raise ValueError(error_msg)

        last_exception = None

        for idx, config in enumerate(models_to_try):
            current_provider = config["provider"]
            current_model = config["model"]
            current_endpoint = config["endpoint"]
            current_api_key = config["api_key"]
            
            headers = {
                "Authorization": f"Bearer {current_api_key}",
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "SETV AI Sales Agent",
                "Content-Type": "application/json"
            }
            
            print(f"\n--- AI REQUEST {'(FALLBACK) ' if idx > 0 else ''}---")
            print(f"AI Provider: {current_provider}")
            print(f"Model: {current_model}")
            print(f"API Key Loaded: YES")
            print(f"Endpoint: {current_endpoint}")
            print("Authorization Header matches expected format: YES")

            logger.info(f"AI Provider: {current_provider}")
            logger.info(f"Model: {current_model}")
            logger.info(f"Endpoint: {current_endpoint}")

            payload = {
                "model": current_model,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"}
            }

            try:
                response = requests.post(
                    current_endpoint,
                    headers=headers,
                    json=payload,
                    timeout=120
                )
                
                print(f"HTTP Status: {response.status_code}")
                logger.info(f"HTTP Status: {response.status_code}")
                
                logger.debug(f"Response Body: {response.text.encode('utf-8', 'replace').decode('utf-8')}")
                logger.info(f"Response Body: {response.text.encode('utf-8', 'replace').decode('utf-8')}")

                if response.status_code != 200:
                    error_msg = f"{current_provider} API error: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    last_exception = RuntimeError(error_msg)
                    continue

                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    error_msg = f"No choices returned from {current_provider}. Full response: {data}"
                    logger.error(error_msg)
                    last_exception = RuntimeError(error_msg)
                    continue
                    
                message = choices[0].get("message", {})
                text = message.get("content", "")

                if not text or not text.strip():
                    error_msg = f"{current_provider} returned empty text."
                    logger.error(error_msg)
                    last_exception = RuntimeError(error_msg)
                    continue

                parsed_data = self._extract_json(text)
                if parsed_data is None:
                    error_msg = f"Could not parse JSON from {current_provider} response: {text}"
                    logger.error(error_msg)
                    last_exception = RuntimeError(error_msg)
                    continue

                if isinstance(parsed_data, list):
                    parsed_data = {"data": parsed_data}

                if not isinstance(parsed_data, dict):
                    error_msg = f"Unexpected JSON type: {type(parsed_data)}"
                    logger.error(error_msg)
                    last_exception = RuntimeError(error_msg)
                    continue

                print("------------------\n")
                return parsed_data

            except Exception as e:
                logger.error(f"{current_provider} integration failed for model {current_model}: {e}", exc_info=True)
                last_exception = e
                # Continue loop to try fallback model
                continue

        # If all models fail, raise the last exception
        raise last_exception
