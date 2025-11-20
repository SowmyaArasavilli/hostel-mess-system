from flask import Flask, render_template, redirect, url_for, flash, session, request
import pymysql
from pymysql.cursors import DictCursor
from werkzeug.security import generate_password_hash, check_password_hash
from forms import RegisterForm, LoginForm

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev"  # change to a strong secret in production

DB_CONFIG = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "1234",
}


def get_connection(database=None):
    config = DB_CONFIG.copy()
    if database:
        config["database"] = database
    return pymysql.connect(**config)


def init_db():
    # Create database and users table if they don't exist
    try:
        # Ensure database exists
        conn = get_connection()
        conn.autocommit(True)
        cur = conn.cursor()
        cur.execute(
            "CREATE DATABASE IF NOT EXISTS mess_management CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cur.close()
        conn.close()

        # Ensure users table exists
        conn = get_connection("mess_management")
        conn.autocommit(True)
        cur = conn.cursor()
        
        # First check if users table exists
        cur.execute("SHOW TABLES LIKE 'users'")
        if not cur.fetchone():
            # Create new table with all columns
            cur.execute(
                """
                CREATE TABLE users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role ENUM('admin','member') NOT NULL DEFAULT 'member',
                    mess_start_date DATE DEFAULT CURRENT_DATE,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
                """
            )
        else:
            # Table exists, add missing columns
            try:
                cur.execute("SHOW COLUMNS FROM users LIKE 'role'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE users ADD COLUMN role ENUM('admin','member') NOT NULL DEFAULT 'member' AFTER password_hash")
                    print("Added role column")
            except Exception as e:
                print(f"Role column check: {e}")
                
            try:
                cur.execute("SHOW COLUMNS FROM users LIKE 'mess_start_date'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE users ADD COLUMN mess_start_date DATE DEFAULT CURRENT_DATE AFTER role")
                    print("Added mess_start_date column")
            except Exception as e:
                print(f"Mess start date column check: {e}")
                
            try:
                cur.execute("SHOW COLUMNS FROM users LIKE 'is_active'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE AFTER mess_start_date")
                    print("Added is_active column")
            except Exception as e:
                print(f"Is active column check: {e}")
        
        # Other core tables
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                date DATE NOT NULL,
                breakfast TINYINT(1) DEFAULT 0,
                lunch TINYINT(1) DEFAULT 0,
                dinner TINYINT(1) DEFAULT 0,
                UNIQUE KEY uniq_user_date (user_id, date),
                CONSTRAINT fk_meals_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INT AUTO_INCREMENT PRIMARY KEY,
                date DATE NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                category VARCHAR(100),
                notes VARCHAR(255),
                created_by INT,
                CONSTRAINT fk_expenses_user FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                date DATE NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                method VARCHAR(50),
                reference VARCHAR(100),
                status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
                approved_by INT NULL,
                approved_at TIMESTAMP NULL,
                CONSTRAINT fk_payments_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_payments_approver FOREIGN KEY (approved_by) REFERENCES users(id) ON DELETE SET NULL
            ) ENGINE=InnoDB
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS menu (
                id INT AUTO_INCREMENT PRIMARY KEY,
                date DATE NOT NULL UNIQUE,
                breakfast_menu VARCHAR(255),
                lunch_menu VARCHAR(255),
                dinner_menu VARCHAR(255)
            ) ENGINE=InnoDB
            """
        )
        # Weekly fixed fees for meals
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_fees (
                weekday ENUM('Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday') PRIMARY KEY,
                breakfast_fee DECIMAL(10,2) DEFAULT 0,
                lunch_fee DECIMAL(10,2) DEFAULT 0,
                dinner_fee DECIMAL(10,2) DEFAULT 0
            ) ENGINE=InnoDB
            """
        )
        # Monthly billing table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_bills (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                month VARCHAR(7) NOT NULL,
                total_meals INT DEFAULT 0,
                cancelled_meals INT DEFAULT 0,
                billable_meals INT DEFAULT 0,
                meal_rate DECIMAL(10,2) DEFAULT 0,
                total_amount DECIMAL(10,2) DEFAULT 0,
                paid_amount DECIMAL(10,2) DEFAULT 0,
                due_amount DECIMAL(10,2) DEFAULT 0,
                status ENUM('pending','paid','overdue') DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_user_month (user_id, month),
                CONSTRAINT fk_bills_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            ) ENGINE=InnoDB
            """
        )
        # Seed weekly fees if empty
        cur.execute("SELECT COUNT(*) FROM weekly_fees")
        if (cur.fetchone() or [0])[0] == 0:
            fee_values = [
                ("Sunday", 15.00, 45.00, 40.00),
                ("Monday", 20.00, 45.00, 40.00),
                ("Tuesday", 25.00, 45.00, 40.00),
                ("Wednesday", 20.00, 50.00, 40.00),
                ("Thursday", 20.00, 45.00, 45.00),
                ("Friday", 20.00, 50.00, 40.00),
                ("Saturday", 25.00, 45.00, 40.00),
            ]
            cur.executemany(
                "INSERT INTO weekly_fees (weekday, breakfast_fee, lunch_fee, dinner_fee) VALUES (%s,%s,%s,%s)",
                fee_values,
            )
        
        # Seed admin if no admin exists
        cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
        has_admin = cur.fetchone()
        if not has_admin:
            admin_email = "admin@mess.com"
            admin_name = "Admin"
            admin_password_hash = generate_password_hash("admin123")
            try:
                cur.execute(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'admin')",
                    (admin_name, admin_email, admin_password_hash),
                )
            except Exception:
                pass
        cur.close()
        conn.close()
        print("Database initialization completed successfully!")
    except pymysql.MySQLError as err:
        # Simple stdout log; keep minimal
        print(f"Database init error: {err}")


init_db()


def force_update_db():
    """Force update database schema for existing installations"""
    try:
        conn = get_connection("mess_management")
        conn.autocommit(True)
        cur = conn.cursor()
        
        print("Checking and updating database schema...")
        
        # Update users table - add columns one by one with proper syntax
        try:
            cur.execute("SHOW COLUMNS FROM users LIKE 'role'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE users ADD COLUMN role ENUM('admin','member') NOT NULL DEFAULT 'member' AFTER password_hash")
                print("✓ Added role column")
            else:
                print("✓ Role column already exists")
        except Exception as e:
            print(f"✗ Role column error: {e}")
            
        try:
            cur.execute("SHOW COLUMNS FROM users LIKE 'mess_start_date'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE users ADD COLUMN mess_start_date DATE DEFAULT (CURDATE()) AFTER role")
                print("✓ Added mess_start_date column")
            else:
                print("✓ Mess start date column already exists")
        except Exception as e:
            print(f"✗ Mess start date column error: {e}")
            
        try:
            cur.execute("SHOW COLUMNS FROM users LIKE 'is_active'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE AFTER mess_start_date")
                print("✓ Added is_active column")
            else:
                print("✓ Is active column already exists")
        except Exception as e:
            print(f"✗ Is active column error: {e}")
        
        # Update payments table
        try:
            cur.execute("SHOW COLUMNS FROM payments LIKE 'status'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE payments ADD COLUMN status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending' AFTER reference")
                print("✓ Added status column to payments")
            else:
                print("✓ Payments status column already exists")
        except Exception as e:
            print(f"✗ Payments status column error: {e}")
            
        try:
            cur.execute("SHOW COLUMNS FROM payments LIKE 'approved_by'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE payments ADD COLUMN approved_by INT NULL AFTER status")
                print("✓ Added approved_by column to payments")
            else:
                print("✓ Payments approved_by column already exists")
        except Exception as e:
            print(f"✗ Payments approved_by column error: {e}")
            
        try:
            cur.execute("SHOW COLUMNS FROM payments LIKE 'approved_at'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE payments ADD COLUMN approved_at TIMESTAMP NULL AFTER approved_by")
                print("✓ Added approved_at column to payments")
            else:
                print("✓ Payments approved_at column already exists")
        except Exception as e:
            print(f"✗ Payments approved_at column error: {e}")
        
        # Create monthly_bills table if not exists
        try:
            cur.execute("SHOW TABLES LIKE 'monthly_bills'")
            if not cur.fetchone():
                cur.execute(
                    """
                    CREATE TABLE monthly_bills (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        month VARCHAR(7) NOT NULL,
                        total_meals INT DEFAULT 0,
                        cancelled_meals INT DEFAULT 0,
                        billable_meals INT DEFAULT 0,
                        meal_rate DECIMAL(10,2) DEFAULT 0,
                        total_amount DECIMAL(10,2) DEFAULT 0,
                        paid_amount DECIMAL(10,2) DEFAULT 0,
                        due_amount DECIMAL(10,2) DEFAULT 0,
                        status ENUM('pending','paid','overdue') DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uniq_user_month (user_id, month),
                        CONSTRAINT fk_bills_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB
                    """
                )
                print("✓ Created monthly_bills table")
            else:
                print("✓ Monthly bills table already exists")
        except Exception as e:
            print(f"✗ Monthly bills table error: {e}")
        
        # Update existing users to have default values - only if columns exist
        try:
            cur.execute("SHOW COLUMNS FROM users LIKE 'role'")
            if cur.fetchone():
                cur.execute("UPDATE users SET role='member' WHERE role IS NULL")
                print("✓ Updated existing users with default role")
        except Exception as e:
            print(f"✗ Role update error: {e}")
            
        try:
            cur.execute("SHOW COLUMNS FROM users LIKE 'mess_start_date'")
            if cur.fetchone():
                cur.execute("UPDATE users SET mess_start_date=CURDATE() WHERE mess_start_date IS NULL")
                print("✓ Updated existing users with default mess start date")
        except Exception as e:
            print(f"✗ Mess start date update error: {e}")
            
        try:
            cur.execute("SHOW COLUMNS FROM users LIKE 'is_active'")
            if cur.fetchone():
                cur.execute("UPDATE users SET is_active=TRUE WHERE is_active IS NULL")
                print("✓ Updated existing users with default active status")
        except Exception as e:
            print(f"✗ Active status update error: {e}")
        
        cur.close()
        conn.close()
        print("Database schema update completed!")
        
    except Exception as e:
        print(f"Database update error: {e}")


# Force update database schema
force_update_db()


# --------- Debug/Admin Routes ---------
@app.route("/update_db")
def update_db():
    """Manual database update route for debugging"""
    if not require_login() or not require_admin():
        return redirect(url_for("login"))
    
    try:
        force_update_db()
        flash("Database updated successfully", "success")
    except Exception as e:
        flash(f"Database update failed: {e}", "error")
    
    return redirect(url_for("dashboard"))


@app.route("/register", methods=["GET", "POST"])
def register():
    # Public self-registration disabled; only admin can create accounts in Members page
    flash("Registration is managed by admin. Please contact your admin.", "error")
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        password = form.password.data
        try:
            conn = get_connection("mess_management")
            cur = conn.cursor(DictCursor)
            cur.execute(
                "SELECT id, name, password_hash, role FROM users WHERE email=%s",
                (email,),
            )
            user = cur.fetchone()
            if not user or not check_password_hash(user["password_hash"], password):
                flash("Invalid email or password", "error")
            else:
                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                session["user_role"] = user["role"]
                flash("Logged in successfully", "success")
                cur.close()
                conn.close()
                return redirect(url_for("dashboard"))
            cur.close()
            conn.close()
        except pymysql.MySQLError as err:
            flash(f"Database error: {err}", "error")

    return render_template("login.html", form=form)

@app.route("/")
def home():
    user_name = session.get("user_name")
    if user_name:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if not session.get("user_id"):
        flash("Please log in to access the dashboard", "error")
        return redirect(url_for("login"))
    return render_template(
        "dashboard.html",
        title="Dashboard",
        user_name=session.get("user_name"),
        user_role=session.get("user_role"),
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "success")
    return redirect(url_for("login"))


# --------- Helpers ---------
def require_login():
    if not session.get("user_id"):
        flash("Please log in", "error")
        return False
    return True


def require_admin():
    if session.get("user_role") != "admin":
        flash("Admin access required", "error")
        return False
    return True


# --------- Members (Admin) ---------
@app.route("/members", methods=["GET", "POST"])
def members():
    if not require_login() or not require_admin():
        return redirect(url_for("login"))

    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)

    # Create user or update role
    if request.method == "POST":
        form_type = request.form.get("form_type")
        if form_type == "create":
            name = (request.form.get("name") or "").strip()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            mess_start_date = date.today().strftime("%Y-%m-%d")
            if not name or not email or not password:
                flash("Name, email and password are required", "error")
            else:
                try:
                    cur.execute("SELECT id FROM users WHERE email=%s", (email,))
                    if cur.fetchone():
                        flash("Email already exists", "error")
                    else:
                        # Check if mess_start_date column exists
                        cur.execute("SHOW COLUMNS FROM users LIKE 'mess_start_date'")
                        if cur.fetchone():
                            cur.execute(
                                "INSERT INTO users (name, email, password_hash, role, mess_start_date) VALUES (%s, %s, %s, 'member', %s)",
                                (name, email, generate_password_hash(password), mess_start_date),
                            )
                        else:
                            # Fallback to basic insert if column doesn't exist
                            cur.execute(
                                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, 'member')",
                                (name, email, generate_password_hash(password)),
                            )
                        conn.commit()
                        flash("Member created successfully", "success")
                except Exception as err:
                    flash(f"Error creating member: {err}", "error")
        elif form_type == "update":
            user_id = request.form.get("user_id")
            role = request.form.get("role")
            if user_id and role in ("admin", "member"):
                cur.execute("UPDATE users SET role=%s WHERE id=%s", (role, user_id))
                conn.commit()
                flash("Member updated", "success")
        elif form_type == "remove":
            user_id = request.form.get("user_id")
            if user_id:
                try:
                    # Check if is_active column exists
                    cur.execute("SHOW COLUMNS FROM users LIKE 'is_active'")
                    if cur.fetchone():
                        # Soft delete - mark as inactive
                        cur.execute("UPDATE users SET is_active=FALSE WHERE id=%s AND role='member'", (user_id,))
                    else:
                        # Hard delete if column doesn't exist
                        cur.execute("DELETE FROM users WHERE id=%s AND role='member'", (user_id,))
                    
                    if cur.rowcount > 0:
                        conn.commit()
                        flash("Member removed successfully", "success")
                    else:
                        flash("Cannot remove admin users", "error")
                except Exception as err:
                    flash(f"Error removing member: {err}", "error")
        elif form_type == "update_mess_date":
            user_id = request.form.get("user_id")
            mess_start_date = request.form.get("mess_start_date")
            if user_id and mess_start_date:
                try:
                    # Check if mess_start_date column exists
                    cur.execute("SHOW COLUMNS FROM users LIKE 'mess_start_date'")
                    if cur.fetchone():
                        cur.execute("UPDATE users SET mess_start_date=%s WHERE id=%s", (mess_start_date, user_id))
                        conn.commit()
                        flash("Mess start date updated", "success")
                    else:
                        flash("Mess start date column not available", "error")
                except Exception as err:
                    flash(f"Error updating mess start date: {err}", "error")

    # Get users with safe column selection
    try:
        # Check which columns exist
        cur.execute("SHOW COLUMNS FROM users")
        columns_result = cur.fetchall()
        columns = [col['Field'] for col in columns_result]
        
        # Build safe SELECT query
        select_columns = ["id", "name", "email", "role", "created_at"]
        if "mess_start_date" in columns:
            select_columns.append("mess_start_date")
        if "is_active" in columns:
            select_columns.append("is_active")
            
        select_query = f"SELECT {', '.join(select_columns)} FROM users ORDER BY created_at DESC"
        cur.execute(select_query)
        users = cur.fetchall()
        
    except Exception as e:
        flash(f"Error fetching users: {e}", "error")
        users = []
    
    cur.close()
    conn.close()
    
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    
    return render_template("members.html", users=users, user_name=session.get("user_name"), user_role=session.get("user_role"), today=today)


# --------- Meals ---------
@app.route("/meals", methods=["GET", "POST"])
def meals():
    if not require_login():
        return redirect(url_for("login"))

    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)

    if request.method == "POST":
        # Admin is view-only for meals; members can only cancel for tomorrow
        if session.get("user_role") == "admin":
            flash("Admins cannot add or modify meals. View-only.", "error")
        else:
            from datetime import date as _d, timedelta
            tomorrow = (_d.today() + timedelta(days=1)).strftime("%Y-%m-%d")
            user_id = session.get("user_id")
            date = request.form.get("date")
            if date != tomorrow:
                flash("You can only cancel for tomorrow.", "error")
            else:
                # Default: all meals are included (1), user can cancel (0)
                b = 0 if request.form.get("breakfast") == "on" else 1
                l = 0 if request.form.get("lunch") == "on" else 1
                d = 0 if request.form.get("dinner") == "on" else 1
                try:
                    cur.execute(
                        """
                        INSERT INTO meals (user_id, date, breakfast, lunch, dinner)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE breakfast=VALUES(breakfast), lunch=VALUES(lunch), dinner=VALUES(dinner)
                        """,
                        (user_id, date, b, l, d),
                    )
                    conn.commit()
                    flash("Tomorrow's meal cancellations updated", "success")
                except Exception as err:
                    flash(f"Error saving meal cancellations: {err}", "error")

    # List meals for month
    month = request.args.get("month")
    if not month:
        from datetime import date as _d

        month = _d.today().strftime("%Y-%m")

    # Admin sees all; member sees own
    if session.get("user_role") == "admin":
        cur.execute(
            """
            SELECT m.*, u.name as user_name
            FROM meals m
            JOIN users u ON u.id = m.user_id
            WHERE DATE_FORMAT(m.date, '%%Y-%%m')=%s
            ORDER BY m.date DESC, u.name ASC
            """,
            (month,),
        )
        all_users = None
        cur.execute("SELECT id, name FROM users ORDER BY name")
        all_users = cur.fetchall()
    else:
        cur.execute(
            """
            SELECT m.*, %s as user_name
            FROM meals m
            WHERE m.user_id=%s AND DATE_FORMAT(m.date, '%%Y-%%m')=%s
            ORDER BY m.date DESC
            """,
            (session.get("user_name"), session.get("user_id"), month),
        )
        all_users = None

    meals_rows = cur.fetchall()
    # Tomorrow string for template
    from datetime import date as _d, timedelta
    tomorrow = (_d.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    cur.close()
    conn.close()
    return render_template(
        "meals.html",
        meals=meals_rows,
        month=month,
        all_users=all_users,
        user_name=session.get("user_name"),
        user_role=session.get("user_role"),
        tomorrow=tomorrow,
    )


# --------- Expenses (Admin) ---------
@app.route("/expenses", methods=["GET", "POST"])
def expenses():
    if not require_login() or not require_admin():
        return redirect(url_for("login"))

    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)

    if request.method == "POST":
        date = request.form.get("date")
        amount = request.form.get("amount")
        category = request.form.get("category")
        notes = request.form.get("notes")
        try:
            cur.execute(
                "INSERT INTO expenses (date, amount, category, notes, created_by) VALUES (%s, %s, %s, %s, %s)",
                (date, amount, category, notes, session.get("user_id")),
            )
            conn.commit()
            flash("Expense added", "success")
        except Exception as err:
            flash(f"Error adding expense: {err}", "error")

    month = request.args.get("month")
    if not month:
        from datetime import date as _d

        month = _d.today().strftime("%Y-%m")

    cur.execute(
        "SELECT * FROM expenses WHERE DATE_FORMAT(date, '%%Y-%%m')=%s ORDER BY date DESC",
        (month,),
    )
    rows = cur.fetchall()
    cur.execute(
        "SELECT IFNULL(SUM(amount),0) as total FROM expenses WHERE DATE_FORMAT(date, '%%Y-%%m')=%s",
        (month,),
    )
    total = cur.fetchone()["total"]
    cur.close()
    conn.close()
    return render_template("expenses.html", expenses=rows, month=month, total=total, user_name=session.get("user_name"), user_role=session.get("user_role"))


# --------- Payments ---------
@app.route("/payments", methods=["GET", "POST"])
def payments():
    if not require_login():
        return redirect(url_for("login"))

    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)

    if request.method == "POST":
        form_type = request.form.get("form_type")
        if form_type == "create":
            # Members submit payments; status is pending by default
            user_id = session.get("user_id")
            date = request.form.get("date")
            amount = request.form.get("amount")
            method = request.form.get("method")
            reference = request.form.get("reference")
            try:
                cur.execute(
                    "INSERT INTO payments (user_id, date, amount, method, reference, status) VALUES (%s, %s, %s, %s, %s, 'pending')",
                    (user_id, date, amount, method, reference),
                )
                conn.commit()
                flash("Payment submitted successfully. Waiting for admin approval.", "success")
            except Exception as err:
                flash(f"Error submitting payment: {err}", "error")
        elif form_type == "approve" and session.get("user_role") == "admin":
            payment_id = request.form.get("payment_id")
            action = request.form.get("action")  # approve or reject
            if payment_id and action in ("approve", "reject"):
                try:
                    status = "approved" if action == "approve" else "rejected"
                    cur.execute(
                        "UPDATE payments SET status=%s, approved_by=%s, approved_at=CURRENT_TIMESTAMP WHERE id=%s",
                        (status, session.get("user_id"), payment_id)
                    )
                    conn.commit()
                    flash(f"Payment {action}d successfully", "success")
                except Exception as err:
                    flash(f"Error updating payment: {err}", "error")

    month = request.args.get("month")
    if not month:
        from datetime import date as _d
        month = _d.today().strftime("%Y-%m")

    if session.get("user_role") == "admin":
        cur.execute(
            """
            SELECT p.*, u.name as user_name
            FROM payments p
            JOIN users u ON u.id = p.user_id
            WHERE DATE_FORMAT(p.date, '%%Y-%%m')=%s
            ORDER BY p.date DESC
            """,
            (month,),
        )
        payments_rows = cur.fetchall()
        all_users = None
    else:
        cur.execute(
            """
            SELECT p.*, %s as user_name
            FROM payments p
            WHERE p.user_id=%s AND DATE_FORMAT(p.date, '%%Y-%%m')=%s
            ORDER BY p.date DESC
            """,
            (session.get("user_name"), session.get("user_id"), month),
        )
        payments_rows = cur.fetchall()
        all_users = None

    cur.close()
    conn.close()
    return render_template(
        "payments.html",
        payments=payments_rows,
        month=month,
        all_users=all_users,
        user_name=session.get("user_name"),
        user_role=session.get("user_role"),
    )


# --------- Monthly Billing ---------
@app.route("/monthly_bill")
def monthly_bill():
    if not require_login():
        return redirect(url_for("login"))

    month = request.args.get("month")
    user_id = request.args.get("user_id") or session.get("user_id")

    # Members can only see their own bill
    if session.get("user_role") != "admin" and str(user_id) != str(session.get("user_id")):
        flash("Not allowed", "error")
        return redirect(url_for("dashboard"))

    if not month:
        from datetime import date as _d
        month = _d.today().strftime("%Y-%m")

    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)

    # Get user details including mess start date
    cur.execute("SELECT name FROM users WHERE id=%s", (user_id,))
    user_row = cur.fetchone()
    if not user_row:
        flash("User not found", "error")
        return redirect(url_for("dashboard"))
    
    user_name = user_row["name"]
    
    # Check if mess_start_date column exists
    cur.execute("SHOW COLUMNS FROM users LIKE 'mess_start_date'")
    if cur.fetchone():
        cur.execute("SELECT mess_start_date FROM users WHERE id=%s", (user_id,))
        mess_start_date = cur.fetchone()["mess_start_date"] or month_start
    else:
        mess_start_date = month_start  # Default to month start if column doesn't exist

    # Calculate month start and end dates
    from datetime import datetime, timedelta
    month_start = datetime.strptime(month, "%Y-%m").date()
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    
    # Adjust start date if mess started mid-month
    actual_start = max(month_start, mess_start_date)
    
    # Get total expenses for the month
    cur.execute(
        "SELECT IFNULL(SUM(amount),0) as total_expenses FROM expenses WHERE DATE_FORMAT(date, '%%Y-%%m')=%s",
        (month,),
    )
    total_expenses = float(cur.fetchone()["total_expenses"] or 0)

    # Get total meals for the month (excluding cancelled meals)
    cur.execute(
        """
        SELECT IFNULL(SUM(breakfast + lunch + dinner),0) as total_meals 
        FROM meals 
        WHERE DATE_FORMAT(date, '%%Y-%%m')=%s
        """,
        (month,),
    )
    total_meals = int(cur.fetchone()["total_meals"] or 0)
    
    # Calculate meal rate
    meal_rate = (total_expenses / total_meals) if total_meals > 0 else 0.0

    # Get user's meals for the month (including cancelled meals)
    cur.execute(
        """
        SELECT 
            IFNULL(SUM(breakfast + lunch + dinner),0) as total_meals,
            IFNULL(SUM(CASE WHEN breakfast=0 THEN 1 ELSE 0 END + 
                       CASE WHEN lunch=0 THEN 1 ELSE 0 END + 
                       CASE WHEN dinner=0 THEN 1 ELSE 0 END), 0) as cancelled_meals
        FROM meals
        WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m')=%s
        """,
        (user_id, month),
    )
    user_meals = cur.fetchone()
    total_user_meals = int(user_meals["total_meals"] or 0)
    cancelled_meals = int(user_meals["cancelled_meals"] or 0)
    
    # Calculate billable meals - if no meals recorded, assume all days in month are billable
    if total_user_meals == 0 and cancelled_meals == 0:
        # Calculate days from mess start date to end of month
        days_in_month = (month_end - actual_start).days + 1
        billable_meals = days_in_month * 3  # 3 meals per day
    else:
        billable_meals = total_user_meals + cancelled_meals

    # Calculate bill amount
    bill_amount = billable_meals * meal_rate

    # Get approved payments for the month
    cur.execute(
        "SELECT IFNULL(SUM(amount),0) as payments_sum FROM payments WHERE user_id=%s AND status='approved' AND DATE_FORMAT(date, '%%Y-%%m')=%s",
        (user_id, month),
    )
    payments_sum = float(cur.fetchone()["payments_sum"] or 0)

    # Calculate due amount
    due_amount = bill_amount - payments_sum

    # Update or create monthly bill record
    cur.execute(
        """
        INSERT INTO monthly_bills (user_id, month, total_meals, cancelled_meals, billable_meals, 
                                 meal_rate, total_amount, paid_amount, due_amount, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
            total_meals=VALUES(total_meals), cancelled_meals=VALUES(cancelled_meals),
            billable_meals=VALUES(billable_meals), meal_rate=VALUES(meal_rate),
            total_amount=VALUES(total_amount), paid_amount=VALUES(paid_amount),
            due_amount=VALUES(due_amount), status=VALUES(status)
        """,
        (user_id, month, total_user_meals, cancelled_meals, billable_meals, 
         meal_rate, bill_amount, payments_sum, due_amount, 
         "paid" if due_amount <= 0 else "pending")
    )
    conn.commit()

    # Itemized payments
    cur.execute(
        "SELECT date, amount, method, reference, status FROM payments WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m')=%s ORDER BY date",
        (user_id, month),
    )
    payments_rows = cur.fetchall()

    # Itemized meals by day
    cur.execute(
        "SELECT date, breakfast, lunch, dinner FROM meals WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m')=%s ORDER BY date",
        (user_id, month),
    )
    meals_rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "monthly_bill.html",
        month=month,
        user_name=user_name,
        mess_start_date=mess_start_date,
        total_meals=total_user_meals,
        cancelled_meals=cancelled_meals,
        billable_meals=billable_meals,
        payments_sum=payments_sum,
        meal_rate=meal_rate,
        bill_amount=bill_amount,
        due_amount=due_amount,
        payments_rows=payments_rows,
        meals_rows=meals_rows,
        user_role=session.get("user_role"),
    )

# --------- Bill (per user, printable) ---------
@app.route("/bill")
def bill():
    if not require_login():
        return redirect(url_for("login"))

    month = request.args.get("month")
    user_id = request.args.get("user_id") or session.get("user_id")

    # Members can only see their own bill
    if session.get("user_role") != "admin" and str(user_id) != str(session.get("user_id")):
        flash("Not allowed", "error")
        return redirect(url_for("reports"))

    if not month:
        from datetime import date as _d

        month = _d.today().strftime("%Y-%m")

    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)

    cur.execute("SELECT name FROM users WHERE id=%s", (user_id,))
    user_row = cur.fetchone()
    user_name = user_row["name"] if user_row else "Member"

    cur.execute(
        "SELECT IFNULL(SUM(amount),0) as total_expenses FROM expenses WHERE DATE_FORMAT(date, '%%Y-%%m')=%s",
        (month,),
    )
    total_expenses = float(cur.fetchone()["total_expenses"] or 0)

    cur.execute(
        "SELECT IFNULL(SUM(breakfast + lunch + dinner),0) as total_meals FROM meals WHERE DATE_FORMAT(date, '%%Y-%%m')=%s",
        (month,),
    )
    total_meals = int(cur.fetchone()["total_meals"] or 0)
    meal_rate = (total_expenses / total_meals) if total_meals > 0 else 0.0

    cur.execute(
        """
        SELECT IFNULL(SUM(breakfast + lunch + dinner),0) as meals_count
        FROM meals
        WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m')=%s
        """,
        (user_id, month),
    )
    meals_count = int(cur.fetchone()["meals_count"] or 0)

    cur.execute(
        "SELECT IFNULL(SUM(amount),0) as payments_sum FROM payments WHERE user_id=%s AND status='approved' AND DATE_FORMAT(date, '%%Y-%%m')=%s",
        (user_id, month),
    )
    payments_sum = float(cur.fetchone()["payments_sum"] or 0)

    # Itemized payments
    cur.execute(
        "SELECT date, amount, method, reference, status FROM payments WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m')=%s ORDER BY date",
        (user_id, month),
    )
    payments_rows = cur.fetchall()

    # Itemized meals by day
    cur.execute(
        "SELECT date, breakfast, lunch, dinner FROM meals WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m')=%s ORDER BY date",
        (user_id, month),
    )
    meals_rows = cur.fetchall()

    cur.close()
    conn.close()

    cost = meals_count * meal_rate
    due = cost - payments_sum

    return render_template(
        "bill.html",
        month=month,
        user_name=user_name,
        meals_count=meals_count,
        payments_sum=payments_sum,
        meal_rate=meal_rate,
        cost=cost,
        due=due,
        payments_rows=payments_rows,
        meals_rows=meals_rows,
    )

# --------- Menu Management (Admin) ---------
@app.route("/menu", methods=["GET", "POST"])
def menu():
    # Menu should be visible to all logged-in users
    if not require_login():
        return redirect(url_for("login"))

    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)

    if request.method == "POST":
        form_type = request.form.get("form_type")
        if form_type == "weekly":
            from datetime import datetime, timedelta
            week_start = request.form.get("week_start")
            bm = request.form.get("breakfast_menu")
            lm = request.form.get("lunch_menu")
            sm = request.form.get("snacks_menu")
            dm = request.form.get("dinner_menu")
            try:
                start_dt = datetime.strptime(week_start, "%Y-%m-%d")
                for i in range(7):
                    day = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
                    cur.execute(
                        """
                        INSERT INTO menu (date, breakfast_menu, lunch_menu, dinner_menu)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE breakfast_menu=VALUES(breakfast_menu), lunch_menu=VALUES(lunch_menu), dinner_menu=VALUES(dinner_menu)
                        """,
                        (day, bm, lm, dm),
                    )
                conn.commit()
                flash("Weekly menu saved", "success")
            except Exception as err:
                flash(f"Error saving weekly menu: {err}", "error")
        else:
            date = request.form.get("date")
            bm = request.form.get("breakfast_menu")
            lm = request.form.get("lunch_menu")
            dm = request.form.get("dinner_menu")
            cur.execute(
                """
                INSERT INTO menu (date, breakfast_menu, lunch_menu, dinner_menu)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE breakfast_menu=VALUES(breakfast_menu), lunch_menu=VALUES(lunch_menu), dinner_menu=VALUES(dinner_menu)
                """,
                (date, bm, lm, dm),
            )
            conn.commit()
            flash("Menu saved", "success")

    month = request.args.get("month")
    if not month:
        from datetime import date as _d
        month = _d.today().strftime("%Y-%m")

    cur.execute(
        "SELECT * FROM menu WHERE DATE_FORMAT(date, '%%Y-%%m')=%s ORDER BY date DESC",
        (month,),
    )
    rows = cur.fetchall()
    
    # Get weekly fees for display
    cur.execute("SELECT * FROM weekly_fees ORDER BY FIELD(weekday, 'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')")
    weekly_fees = cur.fetchall()
    
    # Create weekly menu structure with actual food items from the image
    weekly_menu = {
        'Sunday': {
            'breakfast_menu': 'Puri, Upma, Alu-curry',
            'lunch_menu': 'Rice, Roti, Dal, Fish Fry / Kabuli Paneer, Mustard Gravy, Dahi Salad',
            'snacks_menu': 'Coffee & Biscuits',
            'dinner_menu': 'Rice, Roti, Dal, Egg Tadka / Veg Tadka, Vegetable Fry'
        },
        'Monday': {
            'breakfast_menu': 'Vegetable chow mien',
            'lunch_menu': 'Rice, Roti, Dal, Sambar, Veg Curry, Vegetable Chips',
            'snacks_menu': 'Tea & Biscuits',
            'dinner_menu': 'Rice, Roti, Dal, Manchurian Chilli, Kheer'
        },
        'Tuesday': {
            'breakfast_menu': 'Bara (4 pc), Upma, Alu-Matar-Curry',
            'lunch_menu': 'Rice, Roti, Dal, Rasam, Chingudi Ghanta / Veg Ghanta, Guji Chana Bhaja',
            'snacks_menu': 'Tea & Biscuits',
            'dinner_menu': 'Rice, Jeera Rice, Roti, Dal, Cauliflower / Parwal Alu Curry, Soyabean Chilli'
        },
        'Wednesday': {
            'breakfast_menu': 'Aloo Chop / Gulgula, Aloo Matar Curry',
            'lunch_menu': 'Rice, Roti, Dal, Chicken Curry / Mushroom Alu Masala, Dahi Raita',
            'snacks_menu': 'Coffee & Biscuits',
            'dinner_menu': 'Lemon Rice, Rice, Roti, Dalma, Mix veg Fry, Achar'
        },
        'Thursday': {
            'breakfast_menu': 'Idli, Sambar, Chutney',
            'lunch_menu': 'Rice, Roti, Dal, Rasam, Egg Masala / Veg Masala, Alu Choka',
            'snacks_menu': 'Tea & Biscuits',
            'dinner_menu': 'Roti, Dal Fry, Veg Biriyani, Paneer & Green Motor Curry, Sweet Pickle'
        },
        'Friday': {
            'breakfast_menu': 'Poha / Halwa, Alu-Matar-Curry',
            'lunch_menu': 'Rice, Roti, Dal, Chicken Kasa / Paneer & Green Peas Curry, Pampad',
            'snacks_menu': 'Tea & Biscuits',
            'dinner_menu': 'Roti, Fried Rice, Dal, Chhole Masala, Sweet'
        },
        'Saturday': {
            'breakfast_menu': 'Pesarattu / Chakuli, Alu-Curry, Chutney',
            'lunch_menu': 'Rice, Roti, Dal, Sambar, Egg Curry / Veg Curry, Dahi Bundi',
            'snacks_menu': 'Tea & Biscuits',
            'dinner_menu': 'Roti, Rice, Dal, Mushroom Alu Masala, Jeera Aloo'
        }
    }
    
    # Update weekly menu with pricing information
    for fee in weekly_fees:
        weekday = fee['weekday']
        if weekday in weekly_menu:
            weekly_menu[weekday]['breakfast_price'] = f"₹{fee['breakfast_fee']:.2f}"
            weekly_menu[weekday]['lunch_price'] = f"₹{fee['lunch_fee']:.2f}"
            weekly_menu[weekday]['dinner_price'] = f"₹{fee['dinner_fee']:.2f}"
    
    # Default timings from the image
    timings = {
        'breakfast': '6:30 AM to 8:30 AM',
        'lunch': '12:30 PM to 2:30 PM',
        'tea': '6:00 PM to 7:00 PM',
        'dinner': '8:00 PM to 9:45 PM',
        'sunday_breakfast': '8:00 AM to 9:30 AM',
        'sunday_lunch': '12:30 PM to 2:30 PM'
    }
    
    # Get today's date for default values
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    
    cur.close()
    conn.close()
    return render_template("menu.html", month=month, menu_rows=rows, weekly_menu=weekly_menu, timings=timings, today=today, user_name=session.get("user_name"), user_role=session.get("user_role"))


# --------- Admin View: All Monthly Bills ---------
@app.route("/all_bills")
def all_bills():
    if not require_login() or not require_admin():
        return redirect(url_for("login"))
    
    month = request.args.get("month")
    if not month:
        from datetime import date as _d
        month = _d.today().strftime("%Y-%m")
    
    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)
    
    # First, ensure all active users have monthly bills generated for this month
    cur.execute("SELECT id, name FROM users WHERE role = 'member'")
    active_users = cur.fetchall()
    
    # Check if mess_start_date column exists
    cur.execute("SHOW COLUMNS FROM users LIKE 'mess_start_date'")
    has_mess_start_date = cur.fetchone() is not None
    
    for user in active_users:
        # Generate bill for each user if not exists
        user_id = user["id"]
        mess_start_date = None
        
        if has_mess_start_date:
            cur.execute("SELECT mess_start_date FROM users WHERE id=%s", (user_id,))
            mess_start_date = cur.fetchone()["mess_start_date"]
        
        # Get total expenses for the month
        cur.execute(
            "SELECT IFNULL(SUM(amount),0) as total_expenses FROM expenses WHERE DATE_FORMAT(date, '%%Y-%%m')=%s",
            (month,),
        )
        total_expenses = float(cur.fetchone()["total_expenses"] or 0)

        # Get total meals for the month (excluding cancelled meals)
        cur.execute(
            """
            SELECT IFNULL(SUM(breakfast + lunch + dinner),0) as total_meals 
            FROM meals 
            WHERE DATE_FORMAT(date, '%%Y-%%m')=%s
            """,
            (month,),
        )
        total_meals = int(cur.fetchone()["total_meals"] or 0)
        
        # Calculate meal rate
        meal_rate = (total_expenses / total_meals) if total_meals > 0 else 0.0

        # Get user's meals for the month
        cur.execute(
            """
            SELECT 
                IFNULL(SUM(breakfast + lunch + dinner),0) as total_meals,
                IFNULL(SUM(CASE WHEN breakfast=0 THEN 1 ELSE 0 END + 
                           CASE WHEN lunch=0 THEN 1 ELSE 0 END + 
                           CASE WHEN dinner=0 THEN 1 ELSE 0 END), 0) as cancelled_meals
            FROM meals
            WHERE user_id=%s AND DATE_FORMAT(date, '%%Y-%%m')=%s
            """,
            (user_id, month),
        )
        user_meals = cur.fetchone()
        total_user_meals = int(user_meals["total_meals"] or 0)
        cancelled_meals = int(user_meals["cancelled_meals"] or 0)
        
        # Calculate billable meals
        if total_user_meals == 0 and cancelled_meals == 0:
            from datetime import datetime, timedelta
            month_start = datetime.strptime(month, "%Y-%m").date()
            month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            actual_start = max(month_start, mess_start_date or month_start)
            days_in_month = (month_end - actual_start).days + 1
            billable_meals = days_in_month * 3
        else:
            billable_meals = total_user_meals + cancelled_meals

        # Calculate bill amount
        bill_amount = billable_meals * meal_rate

        # Get approved payments for the month
        cur.execute(
            "SELECT IFNULL(SUM(amount),0) as payments_sum FROM payments WHERE user_id=%s AND status='approved' AND DATE_FORMAT(date, '%%Y-%%m')=%s",
            (user_id, month),
        )
        payments_sum = float(cur.fetchone()["payments_sum"] or 0)

        # Calculate due amount
        due_amount = bill_amount - payments_sum

        # Insert or update monthly bill
        cur.execute(
            """
            INSERT INTO monthly_bills (user_id, month, total_meals, cancelled_meals, billable_meals, 
                                     meal_rate, total_amount, paid_amount, due_amount, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                total_meals=VALUES(total_meals), cancelled_meals=VALUES(cancelled_meals),
                billable_meals=VALUES(billable_meals), meal_rate=VALUES(meal_rate),
                total_amount=VALUES(total_amount), paid_amount=VALUES(paid_amount),
                due_amount=VALUES(due_amount), status=VALUES(status)
            """,
            (user_id, month, total_user_meals, cancelled_meals, billable_meals, 
             meal_rate, bill_amount, payments_sum, due_amount, 
             "paid" if due_amount <= 0 else "pending")
        )
    
    conn.commit()
    
    # Get all monthly bills for the month
    cur.execute(
        """
        SELECT mb.*, u.name as user_name, u.email
        FROM monthly_bills mb
        JOIN users u ON u.id = mb.user_id
        WHERE mb.month = %s
        ORDER BY u.name ASC
        """,
        (month,)
    )
    bills = cur.fetchall()
    
    # Add mess_start_date to bills if column exists
    if has_mess_start_date:
        for bill in bills:
            cur.execute("SELECT mess_start_date FROM users WHERE id=%s", (bill["user_id"],))
            bill["mess_start_date"] = cur.fetchone()["mess_start_date"]
    
    # Get summary statistics
    cur.execute(
        """
        SELECT 
            COUNT(*) as total_members,
            SUM(mb.total_amount) as total_billed,
            SUM(mb.paid_amount) as total_paid,
            SUM(mb.due_amount) as total_due
        FROM monthly_bills mb
        JOIN users u ON u.id = mb.user_id
        WHERE mb.month = %s
        """,
        (month,)
    )
    summary = cur.fetchone()
    
    cur.close()
    conn.close()
    
    return render_template(
        "all_bills.html", 
        bills=bills, 
        month=month, 
        summary=summary,
        user_name=session.get("user_name"), 
        user_role=session.get("user_role")
    )

# --------- Admin View: Student Meal Cancellations ---------
@app.route("/cancellations")
def cancellations():
    if not require_login() or not require_admin():
        return redirect(url_for("login"))
    
    month = request.args.get("month")
    if not month:
        from datetime import date as _d
        month = _d.today().strftime("%Y-%m")
    
    conn = get_connection("mess_management")
    cur = conn.cursor(DictCursor)
    
    # Get cancellations (meals = 0) for the month
    cur.execute(
        """
        SELECT m.*, u.name as user_name, 
               DATE_FORMAT(m.date, '%%W') as weekday
        FROM meals m
        JOIN users u ON u.id = m.user_id
        WHERE DATE_FORMAT(m.date, '%%Y-%%m')=%s 
        AND (m.breakfast=0 OR m.lunch=0 OR m.dinner=0)
        ORDER BY m.date DESC, u.name ASC
        """,
        (month,),
    )
    cancellations = cur.fetchall()
    
    # Get weekly fees for billing calculation
    cur.execute("SELECT * FROM weekly_fees")
    weekly_fees = {r["weekday"]: r for r in cur.fetchall()}
    
    cur.close()
    conn.close()
    
    return render_template(
        "cancellations.html", 
        cancellations=cancellations, 
        month=month, 
        weekly_fees=weekly_fees,
        user_name=session.get("user_name"), 
        user_role=session.get("user_role")
    )


if __name__ == "__main__":
    app.run(debug=True)


