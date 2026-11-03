"""PostgreSQL storage for the vendored PerfumAPI service."""
import os
from typing import Any
from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

def _connect():
    return connect(host=os.getenv('POSTGRES_HOST','postgres'), dbname=os.environ['POSTGRES_DB'],
        user=os.environ['POSTGRES_USER'], password=os.environ['POSTGRES_PASSWORD'], row_factory=dict_row)

async def run_migration():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS perfum_catalog (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name TEXT NOT NULL,
                brand TEXT, release_year INTEGER, gender TEXT,
                notes_top JSONB NOT NULL DEFAULT '[]', notes_middle JSONB NOT NULL DEFAULT '[]', notes_base JSONB NOT NULL DEFAULT '[]',
                rating REAL, votes INTEGER, description TEXT, longevity TEXT, sillage TEXT,
                image_url TEXT, perfume_url TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_perfum_catalog_name ON perfum_catalog (lower(name))")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_perfum_catalog_brand ON perfum_catalog (lower(brand))")

async def insert_perfume(perfume_data: dict[str, Any]):
    return (await insert_perfumes_batch([perfume_data]) and (await search_perfumes(perfume_data.get('name',''), limit=1) or [None])[0])

async def insert_perfumes_batch(perfumes: list[dict[str, Any]]) -> int:
    if not perfumes: return 0
    sql = """INSERT INTO perfum_catalog
        (name,brand,release_year,gender,notes_top,notes_middle,notes_base,rating,votes,description,longevity,sillage,image_url,perfume_url)
        VALUES (%(name)s,%(brand)s,%(release_year)s,%(gender)s,%(notes_top)s,%(notes_middle)s,%(notes_base)s,%(rating)s,%(votes)s,%(description)s,%(longevity)s,%(sillage)s,%(image_url)s,%(perfume_url)s)
        ON CONFLICT (perfume_url) DO UPDATE SET name=EXCLUDED.name, brand=EXCLUDED.brand, release_year=EXCLUDED.release_year,
        gender=EXCLUDED.gender, notes_top=EXCLUDED.notes_top, notes_middle=EXCLUDED.notes_middle, notes_base=EXCLUDED.notes_base,
        rating=EXCLUDED.rating, votes=EXCLUDED.votes, description=EXCLUDED.description, longevity=EXCLUDED.longevity,
        sillage=EXCLUDED.sillage, image_url=EXCLUDED.image_url RETURNING id"""
    count=0
    with _connect() as conn:
        for p in perfumes:
            values={k:p.get(k) for k in ('name','brand','release_year','gender','rating','votes','description','longevity','sillage','image_url','perfume_url')}
            for k in ('notes_top','notes_middle','notes_base'): values[k]=Jsonb(p.get(k) or [])
            conn.execute(sql,values); count+=1
    return count

async def get_all_perfumes(limit: int=100, offset: int=0):
    with _connect() as conn: return list(conn.execute('SELECT * FROM perfum_catalog ORDER BY created_at DESC LIMIT %s OFFSET %s',(limit,offset)).fetchall())

async def get_perfume_by_id(perfume_id: str):
    with _connect() as conn: return conn.execute('SELECT * FROM perfum_catalog WHERE id=%s',(perfume_id,)).fetchone()

async def search_perfumes(query: str, limit: int=50):
    term=f"%{query}%"
    with _connect() as conn:
        return list(conn.execute('SELECT * FROM perfum_catalog WHERE name ILIKE %s OR brand ILIKE %s ORDER BY CASE WHEN name ILIKE %s THEN 0 ELSE 1 END, name LIMIT %s',(term,term,f'{query}%',limit)).fetchall())

async def get_perfume_count() -> int:
    with _connect() as conn: return conn.execute('SELECT count(*) AS n FROM perfum_catalog').fetchone()['n']
