import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

try:
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    tables = [r[0] for r in cur.fetchall()]
    print('Tables:', tables)
    
    for t in tables:
        if t != 'alembic_version':
            cur.execute(f'SELECT COUNT(*) FROM {t}')
            print(f'{t}: {cur.fetchone()[0]} rows')
except Exception as e:
    print("Error:", e)
