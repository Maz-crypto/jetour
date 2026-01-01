# database.py — PostgreSQL version for Render
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL is not set in environment variables!")

try:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    cursor = conn.cursor()
    logger.info("✅ Connected to PostgreSQL.")
except Exception as e:
    logger.critical(f"❌ Failed to connect to database: {e}")
    raise

def init_db():
    """Initialize tables if not exist — compatible with PostgreSQL"""
    try:
        # 1. Users table
        cursor.execute("""
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

        # 2. Settings (key-value store)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        # Insert default settings if not exist
        defaults = {
            "subscription_price": "5",
            "referral_reward": "1",
            "min_withdraw": "2"
        }
        for k, v in defaults.items():
            cursor.execute("""
                INSERT INTO settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO NOTHING;
            """, (k, str(v)))

        # 3. Payment methods
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_methods (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                barcode TEXT NOT NULL
            );
        """)

        # 4. Payments
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                proof TEXT,
                status TEXT DEFAULT 'PENDING', -- PENDING, APPROVED, REJECTED
                payment_method_id INTEGER,
                transaction_id TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        # 5. Withdrawals
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                sham_cash_link TEXT,  -- will store SC code or USDT address
                method TEXT DEFAULT 'sham',  -- 'sham' or 'usdt'
                status TEXT DEFAULT 'PENDING', -- PENDING, PAID, CANCELLED
                transaction_id TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        # 6. Channel links
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS channel_links (
                id SERIAL PRIMARY KEY,
                link TEXT UNIQUE NOT NULL
            );
        """)

        conn.commit()
        logger.info("✅ Database tables initialized.")
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ init_db failed: {e}")
        raise

def get_setting(key):
    try:
        cursor.execute("SELECT value FROM settings WHERE key = %s;", (key,))
        row = cursor.fetchone()
        return row["value"] if row else None
    except Exception as e:
        logger.error(f"get_setting('{key}') error: {e}")
        return None

def set_setting(key, value):
    try:
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, (key, str(value)))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"set_setting('{key}', '{value}') error: {e}")
        raise
