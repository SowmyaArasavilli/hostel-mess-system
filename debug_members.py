#!/usr/bin/env python3
"""
Debug script to test the members route logic
"""

import pymysql
from pymysql.cursors import DictCursor

DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "1234",
    "database": "mess_management"
}

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
