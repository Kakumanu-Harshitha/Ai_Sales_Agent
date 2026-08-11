"""
Migration: Add Company Intelligence tables.

Safely creates new intelligence tables without touching existing data.
Run once after deploying the Company Intelligence Engine.
"""

import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from apps.api.db.database import engine, Base

# Import all models to register them
from apps.api.modules.crm import models as crm_models           # noqa
from apps.api.modules.meetings import models as meetings_models  # noqa
from apps.api.modules.prospecting import models as prospecting_models  # noqa
from apps.api.modules.intelligence import models as intelligence_models  # noqa
from apps.api.core.idempotency import IdempotencyRecord  # noqa

if __name__ == "__main__":
    print("Creating Company Intelligence tables...")
    Base.metadata.create_all(bind=engine)
    print("Done. Tables created:")
    for table in ["company_intelligence", "website_insights", "linkedin_insights", "news_insights", "ai_company_summaries"]:
        print(f"  ✓ {table}")
