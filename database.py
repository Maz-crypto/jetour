import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ["DATABASE_URL"]

conn = psycopg.connect(
    DATABASE_URL,
    row_factory=dict_row,
    autocommit=False
)

cursor = conn.cursor()


# ---------------- INIT DB ----------------
def init_db():
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE,
        username TEXT,
        referrer_id BIGINT,
        referral_balance FLOAT DEFAULT 0,
        subscription_active INTEGER DEFAULT 0,
        subscription_end DATE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        amount FLOAT,
        proof TEXT,
        status TEXT,
        transaction_id TEXT,
        payment_method_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS withdrawals (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        amount FLOAT,
        sham_cash_link TEXT,
        method TEXT,
        status TEXT,
        transaction_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payment_methods (
        id SERIAL PRIMARY KEY,
        name TEXT,
        barcode TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS channel_links (
        id SERIAL PRIMARY KEY,
        link TEXT UNIQUE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # قيم افتراضية
    defaults = {
        "subscription_price": "10",
        "referral_reward": "2",
        "min_withdraw": "5"
    }

    for k, v in defaults.items():
        cursor.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (k, v)
        )

    conn.commit()


# ---------------- SETTINGS ----------------
def get_setting(key):
    cursor.execute("SELECT value FROM settings WHERE key=%s", (key,))
    row = cursor.fetchone()
    return float(row["value"]) if row else 0


def set_setting(key, value):
    cursor.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
        """,
        (key, str(value))
    )
    conn.commit()
