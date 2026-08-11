import sys
import os

# Add the root directory to sys.path so we can import from apps
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from apps.api.db.database import Base, engine
# Import all modules containing models so they are registered with Base
from apps.api.modules.crm.models import *
from apps.api.modules.prospecting.models import *
from apps.api.modules.meetings.models import *
from apps.api.core.idempotency import IdempotencyRecord

def init_db():
    print("Creating all database tables from SQLAlchemy models...")
    Base.metadata.create_all(bind=engine)
    print("Done!")

if __name__ == '__main__':
    init_db()
