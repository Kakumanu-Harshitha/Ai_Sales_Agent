import sys
import os

# Add the root directory to sys.path so we can import from apps
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from sqlalchemy import text
from apps.api.db.database import SessionLocal, engine

def fix_sequences():
    if engine.dialect.name != "postgresql":
        print("Not using PostgreSQL, sequences don't need fixing.")
        return

    db = SessionLocal()
    try:
        db.execute(text("SELECT setval('companies_id_seq', COALESCE((SELECT MAX(id) FROM companies), 1))"))
        db.execute(text("SELECT setval('contacts_id_seq', COALESCE((SELECT MAX(id) FROM contacts), 1))"))
        db.execute(text("SELECT setval('leads_id_seq', COALESCE((SELECT MAX(id) FROM leads), 1))"))
        db.commit()
        print("PostgreSQL sequences fixed successfully!")
    finally:
        db.close()

if __name__ == '__main__':
    fix_sequences()
