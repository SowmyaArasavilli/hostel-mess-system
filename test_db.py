#!/usr/bin/env python3
"""
Test script to verify database connection and schema
"""

import os
from urllib.parse import unquote, urlparse

import pymysql
from pymysql.cursors import DictCursor


def build_db_config():
    url = os.getenv("DATABASE_URL")
    if url:
        parsed = urlparse(url)
        database = parsed.path.lstrip("/") or None
        config = {
            "host": parsed.hostname,
            "port": parsed.port or 3306,
            "user": unquote(parsed.username) if parsed.username else None,
            "password": unquote(parsed.password) if parsed.password else None,
            "database": database or os.getenv("DB_NAME", "mess_management"),
        }
    else:
        config = {
            "host": os.getenv("DB_HOST", "127.0.0.1"),
            "port": int(os.getenv("DB_PORT", "3306")),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", "1234"),
            "database": os.getenv("DB_NAME", "mess_management"),
        }

    ssl_ca = os.getenv("DB_SSL_CA")
    if ssl_ca:
        config["ssl"] = {"ca": ssl_ca}

    return {k: v for k, v in config.items() if v is not None}


DB_CONFIG = build_db_config()

def test_db():
    try:
        # Test connection
        conn = pymysql.connect(**DB_CONFIG)
        cur = conn.cursor(DictCursor)
        
        print("✓ Database connection successful")
        
        # Check users table structure
        cur.execute("DESCRIBE users")
        columns = cur.fetchall()
        print(f"✓ Users table has {len(columns)} columns:")
        for col in columns:
            print(f"  - {col['Field']}: {col['Type']}")
        
        # Check if required columns exist
        required_columns = ['id', 'name', 'email', 'password_hash', 'role', 'mess_start_date', 'is_active', 'created_at']
        existing_columns = [col['Field'] for col in columns]
        
        missing_columns = [col for col in required_columns if col not in existing_columns]
        if missing_columns:
            print(f"✗ Missing columns: {missing_columns}")
        else:
            print("✓ All required columns exist")
        
        # Check payments table structure
        cur.execute("DESCRIBE payments")
        payment_columns = cur.fetchall()
        print(f"✓ Payments table has {len(payment_columns)} columns:")
        for col in payment_columns:
            print(f"  - {col['Field']}: {col['Type']}")
        
        # Check monthly_bills table
        cur.execute("SHOW TABLES LIKE 'monthly_bills'")
        if cur.fetchone():
            print("✓ Monthly bills table exists")
            cur.execute("DESCRIBE monthly_bills")
            bill_columns = cur.fetchall()
            print(f"  Monthly bills table has {len(bill_columns)} columns:")
            for col in bill_columns:
                print(f"    - {col['Field']}: {col['Type']}")
        else:
            print("✗ Monthly bills table does not exist")
        
        # Check users data
        cur.execute("SELECT COUNT(*) as count FROM users")
        user_count = cur.fetchone()['count']
        print(f"✓ Users table has {user_count} records")
        
        if user_count > 0:
            cur.execute("SELECT id, name, email, role, mess_start_date, is_active FROM users LIMIT 3")
            users = cur.fetchall()
            print("Sample users:")
            for user in users:
                print(f"  - {user['name']} ({user['email']}) - Role: {user['role']}, Active: {user['is_active']}, Start: {user['mess_start_date']}")
        
        cur.close()
        conn.close()
        print("✓ Database test completed successfully")
        
    except Exception as e:
        print(f"✗ Database test failed: {e}")

if __name__ == "__main__":
    test_db()