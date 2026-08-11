import logging
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .models import KnowledgeBase, KnowledgeSyncLog
from .crawler import KnowledgeCrawler
from apps.api.core.ai_provider import AIProvider

logger = logging.getLogger(__name__)

KNOWLEDGE_EXTRACTION_PROMPT = """You are a highly capable business intelligence extraction agent.
You have been provided with the raw scraped text from the official SETV website.
Your job is to read this text and extract structured information about SETV.

Extract the following categories and present them as a clean JSON object:
- "products": [list of strings]
- "services": [list of strings]
- "features": [list of strings]
- "healthcare_specialties": [list of strings]
- "company_messaging": [list of strings]
- "case_studies": [list of strings]
- "capabilities": [list of strings]

Only include information explicitly found in the text. Ignore boilerplate, navigation menus, and cosmetic text.
The output MUST be a valid JSON object matching the exact keys above.

RAW WEBSITE TEXT:
=================
{raw_text}
=================

Return ONLY valid JSON.
"""

CHANGE_DETECTION_PROMPT = """You are a change detection analyst.
You have been given two versions of the SETV Knowledge Base (JSON format).

OLD KNOWLEDGE:
{old_knowledge}

NEW KNOWLEDGE:
{new_knowledge}

Compare the two and generate a structured markdown summary of the changes.
Highlight any New Products, New Services, Updated Company Messaging, New Specialties, etc.
If there are no changes, just say "No significant changes detected."

Return only the markdown summary.
"""

class KnowledgeSyncService:
    def __init__(self, db: Session, base_url: str = "https://www.setvglobal.com/"):
        self.db = db
        self.base_url = base_url
        self.ai_provider = AIProvider()
        
    def sync(self):
        """
        Executes the sync operation.
        1. Crawls the website.
        2. Extracts knowledge via LLM.
        3. Diffs against previous version.
        4. Saves to DB.
        """
        logger.info(f"Starting Knowledge Sync for {self.base_url}")
        crawler = KnowledgeCrawler(self.base_url)
        
        sync_log = KnowledgeSyncLog(
            status="running"
        )
        self.db.add(sync_log)
        self.db.commit()
        
        try:
            # 1. Crawl
            raw_text, crawled_pages = crawler.crawl_site(max_pages=15)
            sync_log.pages_crawled = crawled_pages
            
            if not raw_text.strip():
                raise Exception("Failed to extract any text from the website.")
            
            # 2. Extract Knowledge
            llm_response = self.ai_provider.generate_content(
                system_instruction="You are a highly capable business intelligence extraction agent.",
                prompt=KNOWLEDGE_EXTRACTION_PROMPT.format(raw_text=raw_text)
            )
            
            # Parse JSON
            try:
                # generate_content automatically attempts to parse JSON, 
                # so llm_response should already be a dict if successful.
                # Let's handle if it returns a string by mistake, but AIProvider usually returns a dict.
                if isinstance(llm_response, dict):
                    new_knowledge_data = llm_response
                else:
                    clean_json_str = str(llm_response).replace("```json", "").replace("```", "").strip()
                    new_knowledge_data = json.loads(clean_json_str)
            except Exception as e:
                logger.error(f"Failed to parse LLM JSON response: {llm_response}")
                raise Exception(f"Failed to parse LLM response into JSON: {str(e)}")
            
            # 3. Get previous knowledge for change detection
            old_kb = self.db.query(KnowledgeBase).order_by(KnowledgeBase.version.desc()).first()
            
            changes_summary = "First synchronization. No previous version to compare."
            new_version = 1
            
            if old_kb:
                new_version = old_kb.version + 1
                diff_prompt = CHANGE_DETECTION_PROMPT.format(
                    old_knowledge=json.dumps(old_kb.data, indent=2),
                    new_knowledge=json.dumps(new_knowledge_data, indent=2)
                )
                diff_response = self.ai_provider.generate_content(
                    system_instruction="You are a change detection analyst.",
                    prompt=diff_prompt
                )
                # If diff returns a dict with 'summary' or similar, stringify it.
                if isinstance(diff_response, dict):
                    changes_summary = json.dumps(diff_response, indent=2)
                else:
                    changes_summary = str(diff_response)
            
            # 4. Save New KnowledgeBase
            new_kb = KnowledgeBase(
                version=new_version,
                data=new_knowledge_data
            )
            self.db.add(new_kb)
            
            # Update Sync Log
            sync_log.changes_detected = {"summary": changes_summary}
            sync_log.knowledge_version = new_version
            sync_log.status = "success"
            
            self.db.commit()
            logger.info("Knowledge Sync completed successfully.")
            return True, changes_summary
            
        except Exception as e:
            logger.error(f"Knowledge Sync failed: {e}")
            sync_log.status = "failed"
            sync_log.errors = str(e)
            self.db.commit()
            return False, str(e)
