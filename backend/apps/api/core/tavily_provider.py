import logging
import requests
from typing import List, Dict, Any, Optional

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

class TavilyProvider:
    """
    Centralized service for Tavily Search API interactions.
    Provides real-time search context for AI models (grounding).
    """

    def __init__(self):
        self.api_key = getattr(settings, "TAVILY_API_KEY", None)
        self.base_url = "https://api.tavily.com/search"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search(self, query: str, max_results: int = 5, search_depth: str = "basic") -> str:
        """
        Executes a search query and formats the results as a string
        ready to be injected into an LLM prompt.
        """
        if not self.is_configured():
            logger.warning("TAVILY_API_KEY is not configured. Returning empty search context.")
            return ""

        try:
            payload = {
                "api_key": self.api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": search_depth,
                "include_answer": False,
                "include_images": False,
                "include_raw_content": False
            }

            response = requests.post(self.base_url, json=payload, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                
                if not results:
                    return "No search results found."

                # Format results cleanly for the LLM
                context_parts = []
                for idx, r in enumerate(results):
                    title = r.get("title", "Untitled")
                    url = r.get("url", "")
                    content = r.get("content", "").strip()
                    context_parts.append(f"Result {idx+1}:\nTitle: {title}\nURL: {url}\nSummary: {content}\n")
                
                return "\n".join(context_parts)

            else:
                logger.error(f"Tavily API error: {response.status_code} - {response.text}")
                return f"[Search failed with status {response.status_code}]"

        except Exception as e:
            logger.error(f"Tavily search request failed: {e}", exc_info=True)
            return "[Search request failed]"
