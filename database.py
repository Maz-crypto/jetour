# database.py
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import asyncio
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL is not set!")

_conn = None

def get_connection():
    global _conn
    if _conn is None or _conn.closed:
        try:
            _conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            logger.info("✅ DB connection established.")
        except Exception as e:
            logger.critical(f"❌ Failed to connect to DB: {e}")
            raise
    return _conn

async def safe_db_execute(query: str, params: tuple = None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            conn.commit()
    except psycopg2.OperationalError:
        _conn.close()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            conn.commit()
    except Exception as e:
        logger.error(f"DB execute error: {query} | {e}")
        raise

async def safe_db_fetchone(query: str, params: tuple = None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            return cur.fetchone()
    except psycopg2.OperationalError:
        _conn.close()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            return cur.fetchone()
    except Exception as e:
        logger.error(f"DB fetchone error: {query} | {e}")
        raise

async def safe_db_fetchall(query: str, params: tuple = None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            return cur.fetchall()
    except psycopg2.OperationalError:
        _conn.close()
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            return cur.fetchall()
    except Exception as e:
        logger.error(f"DB fetchall error: {query} | {e}")
        raise

def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # users
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username TEXT,
                    referrer_id BIGINT,
                    referral_balance DECIMAL(10,2) DEFAULT 0,
                    subscription_active BOOLEAN DEFAULT FALSE,
                    subscription_end DATE,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            # settings
            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            defaults = [("subscription_price", "5"), ("referral_reward", "1"), ("min_withdraw", "2")]
            for k, v in defaults:
                cur.execute(
                    "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING;",
                    (k, v)
                )
            # payment_methods
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payment_methods (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    barcode TEXT NOT NULL
                );
            """)
            # payments
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount DECIMAL(10,2) NOT NULL,
                    proof TEXT,
                    status TEXT DEFAULT 'PENDING',
                    payment_method_id INTEGER,
                    transaction_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            # withdrawals
            cur.execute("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount DECIMAL(10,2) NOT NULL,
                    sham_cash_link TEXT,
                    method TEXT DEFAULT 'sham',
                    status TEXT DEFAULT 'PENDING',
                    transaction_id TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            # channel_links
            cur.execute("""
                CREATE TABLE IF NOT EXISTS channel_links (
                    id SERIAL PRIMARY KEY,
                    link TEXT UNIQUE NOT NULL
                );
            """)
            conn.commit()
            logger.info("✅ Database initialized.")
    except Exception as e:
        conn.rollback()
        logger.critical(f"❌ init_db failed: {e}")
        raise
