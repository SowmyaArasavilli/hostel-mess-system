#!/usr/bin/env python3
"""
Debug script to test the members route logic
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

def debug_members_logic():
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cur = conn.cursor(DictCursor)
        
        print("=== Debugging Members Route Logic ===")
        
        # Check which columns exist
        cur.execute("SHOW COLUMNS FROM users")
        columns_result = cur.fetchall()
        columns = [col['Field'] for col in columns_result]
        print(f"Columns in users table: {columns}")
        
        # Build safe SELECT query (same logic as in app.py)
        select_columns = ["id", "name", "email", "role", "created_at"]
        if "mess_start_date" in columns:
            select_columns.append("mess_start_date")
            print("✓ mess_start_date column found")
        else:
            print("✗ mess_start_date column NOT found")
            
        if "is_active" in columns:
            select_columns.append("is_active")
            print("✓ is_active column found")
        else:
            print("✗ is_active column NOT found")
            
        select_query = f"SELECT {', '.join(select_columns)} FROM users ORDER BY created_at DESC"
        print(f"Final SELECT query: {select_query}")
        
        # Execute the query
        cur.execute(select_query)
        users = cur.fetchall()
        print(f"Number of users fetched: {len(users)}")
        
        if users:
            print("First user data:")
            print(f"  {users[0]}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_members_logic()