from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify
)

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

import os


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

# Secret key dùng để bảo vệ session.
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "REUP_NVL_VIP_CHANGE_THIS_SECRET_KEY_2026"
)

# Cookie bảo mật
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Khi chạy HTTPS trên Render có thể bật True bằng biến môi trường.
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("COOKIE_SECURE", "0") == "1"
)


# =========================================================
# DATABASE
# =========================================================

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DB_DIR = os.path.join(BASE_DIR, "instance")

os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(
    DB_DIR,
    "reup_nvl_vip.db"
)

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + DB_PATH
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =========================================================
# USER MODEL
# =========================================================

class User(db.Model):

    __tablename__ = "user"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    plan = db.Column(
        db.String(20),
        nullable=False,
        default="Free"
    )

    role = db.Column(
        db.String(20),
        nullable=False,
        default="User"
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="Active"
    )


# =========================================================
# DATABASE SETUP / MIGRATION
# =========================================================

def setup_database():

    db.create_all()

    # Kiểm tra các cột hiện có
    inspector = db.inspect(db.engine)

    columns = [
        column["name"]
        for column in inspector.get_columns("user")
    ]

    # Thêm role nếu database cũ chưa có
    if "role" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                "ALTER TABLE user "
                "ADD COLUMN role VARCHAR(20) "
                "DEFAULT 'User'"
            )

            connection.commit()

    # Thêm status nếu database cũ chưa có
    if "status" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                "ALTER TABLE user "
                "ADD COLUMN status VARCHAR(20) "
                "DEFAULT 'Active'"
            )

            connection.commit()

    # Đảm bảo dữ liệu cũ có giá trị hợp lệ
    users = User.query.all()

    changed = False

    for user in users:

        if not user.role:
            user.role = "User"
            changed = True

        if not user.status:
            user.status = "Active"
            changed = True

        if user.plan not in ["Free", "Pro"]:
            user.plan = "Free"
            changed = True

        if user.role not in ["User", "Admin"]:
            user.role = "User"
            changed = True

        if user.status not in ["Active", "Banned"]:
            user.status = "Active"
            changed = True

    if changed:
        db.session.commit()


# =========================================================
# AUTO SET ADMIN
# =========================================================

def auto_set_admin():

    admin_username = os.environ.get(
        "ADMIN_USERNAME",
        ""
    ).strip()

    if not admin_username:
        return

    try:

        user = User.query.filter(
            db.func.lower(User.username)
            == admin_username.lower()
        ).first()

        if user is None:

            print(
                "======================================"
            )

            print(
                "AUTO ADMIN:"
            )

            print(
                f"KHONG TIM THAY USER: {admin_username}"
            )

            print(
                "======================================"
            )

            return

        changed = False

        if user.role != "Admin":

            user.role = "Admin"
            changed = True

        if user.status != "Active":

            user.status = "Active"
            changed = True

        if changed:

            db.session.commit()

        print(
            "======================================"
        )

        print(
            "AUTO ADMIN:"
        )

        print(
            f"USERNAME: {user.username}"
        )

        print(
            "ROLE: Admin"
        )

        print(
            "STATUS: Active"
        )

        print(
            "======================================"
        )

    except Exception as e:

        db.session.rollback()

        print(
            "LOI AUTO ADMIN:",
            e
        )


# =========================================================
# INITIALIZE DATABASE
# =========================================================

with app.app_context():

    setup_database()

    auto_set_admin()


# =========================================================
# CURRENT USER
# =========================================================

def get_current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    user = db.session.get(
        User,
        user_id
    )

    if user is None:

        session.clear()

        return None

    return user


# =========================================================
# ADMIN CHECK
# =========================================================

def require_admin():

    user = get_current_user()

    if user is None:

        return None, redirect(
            url_for("index")
        )

    # Kiểm tra trạng thái
    if user.status != "Active":

        session.clear()

        return None, redirect(
            url_for("index")
        )

    # Kiểm tra quyền Admin phía SERVER
    if user.role != "Admin":

        return None, redirect(
            url_for("index")
        )

    return user, None


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    current_user = get_current_user()

    # Nếu session tồn tại nhưng tài khoản bị khóa
    if current_user and current_user.status != "Active":

        session.clear()

        current_user = None

    return render_template(

        "index.html",

        logged_in=current_user is not None,

        username=(
            current_user.username
            if current_user
            else None
        ),

        plan=(
            current_user.plan
            if current_user
            else None
        ),

        role=(
            current_user.role
            if current_user
            else None
        ),

        current_user=current_user,

        admin_page=False,

        users=[],

        error=None,

        success=None
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["POST"]
)
def register():

    username = request.form.get(
        "username",
        ""
    ).strip()

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    password = request.form.get(
        "password",
        ""
    )

    password2 = request.form.get(
        "password2",
        ""
    )

    # -------------------------
    # VALIDATION
    # -------------------------

    if not username:

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Vui lòng nhập username.",
            success=None
        )

    if not email:

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Vui lòng nhập email.",
            success=None
        )

    if len(password) < 6:

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Mật khẩu phải có ít nhất 6 ký tự.",
            success=None
        )

    if password != password2:

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Mật khẩu nhập lại không giống nhau.",
            success=None
        )

    # -------------------------
    # CHECK USERNAME
    # -------------------------

    existing_username = User.query.filter(
        db.func.lower(User.username)
        == username.lower()
    ).first()

    if existing_username:

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Username đã tồn tại.",
            success=None
        )

    # -------------------------
    # CHECK EMAIL
    # -------------------------

    existing_email = User.query.filter(
        db.func.lower(User.email)
        == email.lower()
    ).first()

    if existing_email:

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Email đã được sử dụng.",
            success=None
        )

    # -------------------------
    # CREATE USER
    # -------------------------

    admin_username = os.environ.get(
    "ADMIN_USERNAME",
    ""
).strip().lower()

new_role = "User"

if (
    admin_username
    and username.lower() == admin_username
):
    new_role = "Admin"

new_user = User(

    username=username,

    email=email,

    password_hash=generate_password_hash(
        password
    ),

    plan="Free",

    role=new_role,

    status="Active"
)

    db.session.add(new_user)

    db.session.commit()

    return render_template(
        "index.html",
        logged_in=False,
        username=None,
        plan=None,
        role=None,
        current_user=None,
        admin_page=False,
        users=[],
        error=None,
        success="Đăng ký thành công! Hãy đăng nhập."
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["POST"]
)
def login():

    login_value = request.form.get(
        "login",
        ""
    ).strip()

    password = request.form.get(
        "password",
        ""
    )

    if not login_value or not password:

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Vui lòng nhập đầy đủ thông tin.",
            success=None
        )

    # Tìm bằng username hoặc email
    user = User.query.filter(
        db.or_(
            db.func.lower(User.username)
            == login_value.lower(),

            db.func.lower(User.email)
            == login_value.lower()
        )
    ).first()

    # Không tiết lộ username/email nào tồn tại
    if user is None:

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Tài khoản hoặc mật khẩu không đúng.",
            success=None
        )

    # Kiểm tra password
    if not check_password_hash(
        user.password_hash,
        password
    ):

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Tài khoản hoặc mật khẩu không đúng.",
            success=None
        )

    # -------------------------
    # CHECK BANNED
    # -------------------------

    if user.status != "Active":

        return render_template(
            "index.html",
            logged_in=False,
            username=None,
            plan=None,
            role=None,
            current_user=None,
            admin_page=False,
            users=[],
            error="Tài khoản của bạn đang bị khóa.",
            success=None
        )

    # -------------------------
    # LOGIN SESSION
    # -------------------------

    session.clear()

    session["user_id"] = user.id

    return redirect(
        url_for("index")
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route(
    "/logout",
    methods=["GET", "POST"]
)
def logout():

    session.clear()

    return redirect(
        url_for("index")
    )


# =========================================================
# ADMIN PANEL
# =========================================================

@app.route("/admin")
def admin():

    current_user, error_response = require_admin()

    if error_response:
        return error_response

    users = User.query.order_by(
        User.id.asc()
    ).all()

    return render_template(
        "index.html",

        logged_in=True,

        username=current_user.username,

        plan=current_user.plan,

        role=current_user.role,

        current_user=current_user,

        admin_page=True,

        users=users,

        error=None,

        success=None
    )


# =========================================================
# ADMIN - CHANGE PLAN
# =========================================================

@app.route(
    "/admin/user/<int:user_id>/plan",
    methods=["POST"]
)
def admin_change_plan(user_id):

    current_user, error_response = require_admin()

    if error_response:
        return error_response

    # Không cho thao tác lên chính mình
    if user_id == current_user.id:

        return redirect(
            url_for("admin")
        )

    user = db.session.get(
        User,
        user_id
    )

    if user is None:

        return redirect(
            url_for("admin")
        )

    new_plan = request.form.get(
        "plan",
        ""
    )

    # Chỉ cho phép 2 giá trị này
    if new_plan not in [
        "Free",
        "Pro"
    ]:

        return redirect(
            url_for("admin")
        )

    user.plan = new_plan

    db.session.commit()

    return redirect(
        url_for("admin")
    )


# =========================================================
# ADMIN - CHANGE STATUS
# =========================================================

@app.route(
    "/admin/user/<int:user_id>/status",
    methods=["POST"]
)
def admin_change_status(user_id):

    current_user, error_response = require_admin()

    if error_response:
        return error_response

    # Không cho Admin tự khóa mình
    if user_id == current_user.id:

        return redirect(
            url_for("admin")
        )

    user = db.session.get(
        User,
        user_id
    )

    if user is None:

        return redirect(
            url_for("admin")
        )

    new_status = request.form.get(
        "status",
        ""
    )

    # Chỉ Active hoặc Banned
    if new_status not in [
        "Active",
        "Banned"
    ]:

        return redirect(
            url_for("admin")
        )

    user.status = new_status

    db.session.commit()

    return redirect(
        url_for("admin")
    )


# =========================================================
# ADMIN - DELETE USER
# =========================================================

@app.route(
    "/admin/user/<int:user_id>/delete",
    methods=["POST"]
)
def admin_delete_user(user_id):

    current_user, error_response = require_admin()

    if error_response:
        return error_response

    # Không cho Admin tự xóa mình
    if user_id == current_user.id:

        return redirect(
            url_for("admin")
        )

    user = db.session.get(
        User,
        user_id
    )

    if user is None:

        return redirect(
            url_for("admin")
        )

    # Không cho xóa tài khoản Admin khác
    if user.role == "Admin":

        return redirect(
            url_for("admin")
        )

    db.session.delete(user)

    db.session.commit()

    return redirect(
        url_for("admin")
    )


# =========================================================
# DATABASE CHECK
# =========================================================

@app.route("/kiem-tra-db")
def check_db():

    users = User.query.order_by(
        User.id.asc()
    ).all()

    result = []

    for user in users:

        result.append({

            "id": user.id,

            "username": user.username,

            "email": user.email,

            "plan": user.plan,

            "role": user.role,

            "status": user.status

        })

    return jsonify(result)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    print()
    print(
        "======================================"
    )
    print(
        "       REUP NVL VIP SERVER"
    )
    print(
        "======================================"
    )
    print(
        "Database:"
    )
    print(
        DB_PATH
    )
    print()

    print(
        "Website:"
    )
    print(
        "http://127.0.0.1:5000"
    )
    print()

    print(
        "Admin:"
    )
    print(
        "http://127.0.0.1:5000/admin"
    )

    print(
        "======================================"
    )
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
