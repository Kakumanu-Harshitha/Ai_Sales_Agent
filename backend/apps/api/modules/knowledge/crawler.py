import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import logging
import re

logger = logging.getLogger(__name__)

class KnowledgeCrawler:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.domain = urlparse(base_url).netloc
        
    def _extract_text(self, html_content: str) -> str:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            script.decompose()
            
        text = soup.get_text(separator=' ', strip=True)
        # Collapse multiple spaces
        text = re.sub(r'\s+', ' ', text)
        return text

    def crawl_site(self, max_pages: int = 10) -> tuple[str, list[str]]:
        """
        Crawls the base_url and up to `max_pages` same-domain linked pages.
        Returns the combined extracted text and a list of URLs crawled.
        """
        visited = set()
        queue = [self.base_url]
        combined_text = []
        
        logger.info(f"Starting crawl of {self.base_url}")
        
        while queue and len(visited) < max_pages:
            current_url = queue.pop(0)
            if current_url in visited:
                continue
                
            visited.add(current_url)
            try:
                # Need a standard User-Agent so we don't get blocked
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                response = requests.get(current_url, headers=headers, timeout=10)
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch {current_url}, status {response.status_code}")
                    continue
                    
                content_type = response.headers.get('Content-Type', '')
                if 'text/html' not in content_type:
                    continue
                    
                text = self._extract_text(response.text)
                if text:
                    combined_text.append(f"--- CONTENT FROM {current_url} ---\n{text}\n")
                    
                # Find new links
                soup = BeautifulSoup(response.text, 'html.parser')
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    next_url = urljoin(current_url, href)
                    next_domain = urlparse(next_url).netloc
                    
                    # Remove fragments
                    next_url = next_url.split('#')[0]
                    
                    if next_domain == self.domain and next_url not in visited and next_url not in queue:
                        # Skip typical non-content extensions
                        if not any(next_url.lower().endswith(ext) for ext in ['.pdf', '.png', '.jpg', '.zip']):
                            queue.append(next_url)
                            
            except Exception as e:
                logger.error(f"Error crawling {current_url}: {e}")
                
        return "\n".join(combined_text), list(visited)
