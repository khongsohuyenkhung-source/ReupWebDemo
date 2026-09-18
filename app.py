from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory
)

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
from werkzeug.utils import secure_filename

import os
import uuid
import secrets
import smtplib

from datetime import datetime, timedelta
from email.message import EmailMessage


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "REUP_NVL_VIP_CHANGE_THIS_SECRET_KEY_2026"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("COOKIE_SECURE", "0") == "1"
)


# =========================================================
# DATABASE
# =========================================================

BASE_DIR = os.path.abspath(
    os.path.dirname(__file__)
)

DB_DIR = os.path.join(
    BASE_DIR,
    "instance"
)

os.makedirs(
    DB_DIR,
    exist_ok=True
)

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
# UPLOAD
# =========================================================

UPLOAD_DIR = os.path.join(
    BASE_DIR,
    "uploads"
)

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)

ALLOWED_VIDEO_EXTENSIONS = {
    "mp4",
    "mov",
    "avi",
    "mkv",
    "webm",
    "m4v"
}

MAX_UPLOAD_SIZE = 500 * 1024 * 1024

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE


def allowed_video(filename):

    if not filename:
        return False

    if "." not in filename:
        return False

    extension = (
        filename
        .rsplit(".", 1)[1]
        .lower()
    )

    return extension in ALLOWED_VIDEO_EXTENSIONS


# =========================================================
# EMAIL CONFIG
# =========================================================

SMTP_HOST = os.environ.get(
    "SMTP_HOST",
    ""
).strip()

SMTP_PORT = int(
    os.environ.get(
        "SMTP_PORT",
        "587"
    )
)

SMTP_USER = os.environ.get(
    "SMTP_USER",
    ""
).strip()

SMTP_PASSWORD = os.environ.get(
    "SMTP_PASSWORD",
    ""
).strip()

SMTP_FROM = os.environ.get(
    "SMTP_FROM",
    SMTP_USER
).strip()


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

    reset_code_hash = db.Column(
        db.String(255),
        nullable=True
    )

    reset_code_expires = db.Column(
        db.DateTime,
        nullable=True
    )


# =========================================================
# DATABASE SETUP / MIGRATION
# =========================================================

def setup_database():

    db.create_all()

    inspector = db.inspect(
        db.engine
    )

    columns = {
        column["name"]
        for column in inspector.get_columns(
            "user"
        )
    }

    # -----------------------------------------------------
    # ROLE
    # -----------------------------------------------------

    if "role" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                "ALTER TABLE user "
                "ADD COLUMN role VARCHAR(20) "
                "DEFAULT 'User'"
            )

            connection.commit()

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if "status" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                "ALTER TABLE user "
                "ADD COLUMN status VARCHAR(20) "
                "DEFAULT 'Active'"
            )

            connection.commit()

    # -----------------------------------------------------
    # RESET CODE HASH
    # -----------------------------------------------------

    if "reset_code_hash" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                "ALTER TABLE user "
                "ADD COLUMN reset_code_hash VARCHAR(255)"
            )

            connection.commit()

    # -----------------------------------------------------
    # RESET CODE EXPIRES
    # -----------------------------------------------------

    if "reset_code_expires" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                "ALTER TABLE user "
                "ADD COLUMN reset_code_expires DATETIME"
            )

            connection.commit()

    # -----------------------------------------------------
    # CHUẨN HÓA USER CŨ
    # -----------------------------------------------------

    users = User.query.all()

    changed = False

    for user in users:

        if not user.role:

            user.role = "User"
            changed = True

        if user.role not in [
            "User",
            "Admin"
        ]:

            user.role = "User"
            changed = True

        if not user.status:

            user.status = "Active"
            changed = True

        if user.status not in [
            "Active",
            "Banned"
        ]:

            user.status = "Active"
            changed = True

        if user.plan not in [
            "Free",
            "Pro"
        ]:

            user.plan = "Free"
            changed = True

    if changed:

        db.session.commit()


# =========================================================
# EMAIL SENDER
# =========================================================

def send_reset_email(
    receiver_email,
    reset_code
):

    if not SMTP_HOST:

        raise RuntimeError(
            "SMTP_HOST chưa được cấu hình."
        )

    if not SMTP_USER:

        raise RuntimeError(
            "SMTP_USER chưa được cấu hình."
        )

    if not SMTP_PASSWORD:

        raise RuntimeError(
            "SMTP_PASSWORD chưa được cấu hình."
        )

    sender_email = (
        SMTP_FROM
        or SMTP_USER
    )

    message = EmailMessage()

    message["Subject"] = (
        "REUP NVL VIP - Ma dat lai mat khau"
    )

    message["From"] = sender_email

    message["To"] = receiver_email

    message.set_content(
        f"""
Xin chao,

Ban vua yeu cau dat lai mat khau cho tai khoan REUP NVL VIP.

Ma xac nhan cua ban la:

{reset_code}

Ma co hieu luc trong 10 phut.

Neu ban khong yeu cau dat lai mat khau,
hay bo qua email nay.

REUP NVL VIP
"""
    )

    # -----------------------------------------------------
    # SMTP SSL - thường dùng port 465
    # -----------------------------------------------------

    if SMTP_PORT == 465:

        with smtplib.SMTP_SSL(
            SMTP_HOST,
            SMTP_PORT,
            timeout=20
        ) as server:

            server.login(
                SMTP_USER,
                SMTP_PASSWORD
            )

            server.send_message(
                message
            )

        return

    # -----------------------------------------------------
    # SMTP STARTTLS - thường dùng port 587
    # -----------------------------------------------------

    with smtplib.SMTP(
        SMTP_HOST,
        SMTP_PORT,
        timeout=20
    ) as server:

        server.ehlo()

        server.starttls()

        server.ehlo()

        server.login(
            SMTP_USER,
            SMTP_PASSWORD
        )

        server.send_message(
            message
        )


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
                "[AUTO ADMIN] "
                f"Chua co user: {admin_username}"
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
            "[AUTO ADMIN] "
            f"{user.username} = Admin"
        )

    except Exception as e:

        db.session.rollback()

        print(
            "[AUTO ADMIN] LOI:",
            e
        )


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

with app.app_context():

    setup_database()

    auto_set_admin()


# =========================================================
# CURRENT USER
# =========================================================

def get_current_user():

    user_id = session.get(
        "user_id"
    )

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

    if user.status != "Active":

        session.clear()

        return None, redirect(
            url_for("index")
        )

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

    if (
        current_user
        and current_user.status != "Active"
    ):

        session.clear()

        current_user = None

    return render_template(

        "index.html",

        logged_in=(
            current_user is not None
        ),

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

    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # CHECK USERNAME
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # CHECK EMAIL
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # AUTO ADMIN FOR USERNAME
    # -----------------------------------------------------

    admin_username = os.environ.get(
        "ADMIN_USERNAME",
        ""
    ).strip().lower()

    if (
        admin_username
        and username.lower() == admin_username
    ):

        role = "Admin"

    else:

        role = "User"

    # -----------------------------------------------------
    # CREATE USER
    # -----------------------------------------------------

    new_user = User(

        username=username,

        email=email,

        password_hash=generate_password_hash(
            password
        ),

        plan="Free",

        role=role,

        status="Active",

        reset_code_hash=None,

        reset_code_expires=None
    )

    db.session.add(
        new_user
    )

    db.session.commit()

    if role == "Admin":

        success_message = (
            "Đăng ký thành công! "
            "Tài khoản đã được cấp quyền Admin."
        )

    else:

        success_message = (
            "Đăng ký thành công! "
            "Hãy đăng nhập."
        )

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

        success=success_message
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

    # Tìm username hoặc email
    user = User.query.filter(
        db.or_(
            db.func.lower(User.username)
            == login_value.lower(),

            db.func.lower(User.email)
            == login_value.lower()
        )
    ).first()

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
# CHANGE PASSWORD
# =========================================================

@app.route(
    "/change-password",
    methods=["POST"]
)
def change_password():

    current_user = get_current_user()

    if current_user is None:

        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    current_password = request.form.get(
        "current_password",
        ""
    )

    new_password = request.form.get(
        "new_password",
        ""
    )

    new_password2 = request.form.get(
        "new_password2",
        ""
    )

    if not current_password:

        return jsonify({
            "success": False,
            "error": "Vui lòng nhập mật khẩu hiện tại."
        }), 400

    if not new_password:

        return jsonify({
            "success": False,
            "error": "Vui lòng nhập mật khẩu mới."
        }), 400

    if len(new_password) < 6:

        return jsonify({
            "success": False,
            "error": "Mật khẩu mới phải có ít nhất 6 ký tự."
        }), 400

    if new_password != new_password2:

        return jsonify({
            "success": False,
            "error": "Mật khẩu mới nhập lại không giống nhau."
        }), 400

    if not check_password_hash(
        current_user.password_hash,
        current_password
    ):

        return jsonify({
            "success": False,
            "error": "Mật khẩu hiện tại không đúng."
        }), 400

    if check_password_hash(
        current_user.password_hash,
        new_password
    ):

        return jsonify({
            "success": False,
            "error": "Mật khẩu mới phải khác mật khẩu cũ."
        }), 400

    current_user.password_hash = (
        generate_password_hash(
            new_password
        )
    )

    current_user.reset_code_hash = None
    current_user.reset_code_expires = None

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Đổi mật khẩu thành công."
    })


# =========================================================
# FORGOT PASSWORD - SEND CODE
# =========================================================

@app.route(
    "/forgot-password",
    methods=["POST"]
)
def forgot_password():

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    if not email:

        return jsonify({
            "success": False,
            "error": "Vui lòng nhập email."
        }), 400

    user = User.query.filter(
        db.func.lower(User.email)
        == email
    ).first()

    # Không tiết lộ email có tồn tại
    if user is None:

        return jsonify({
            "success": True,
            "message": (
                "Nếu email tồn tại trong hệ thống, "
                "mã xác nhận sẽ được gửi về email đó."
            )
        })

    # Tạo mã 6 số
    reset_code = str(
        secrets.randbelow(
            900000
        ) + 100000
    )

    user.reset_code_hash = (
        generate_password_hash(
            reset_code
        )
    )

    user.reset_code_expires = (
        datetime.utcnow()
        + timedelta(minutes=10)
    )

    db.session.commit()

    try:

        send_reset_email(
            user.email,
            reset_code
        )

    except Exception as e:

        print(
            "[RESET EMAIL] LOI:",
            e
        )

        user.reset_code_hash = None
        user.reset_code_expires = None

        db.session.commit()

        return jsonify({
            "success": False,
            "error": (
                "Không thể gửi email. "
                "Hãy kiểm tra SMTP trên Render."
            )
        }), 500

    return jsonify({
        "success": True,
        "message": (
            "Mã xác nhận đã được gửi về email."
        )
    })


# =========================================================
# RESET PASSWORD
# =========================================================

@app.route(
    "/reset-password",
    methods=["POST"]
)
def reset_password():

    email = request.form.get(
        "email",
        ""
    ).strip().lower()

    code = request.form.get(
        "code",
        ""
    ).strip()

    new_password = request.form.get(
        "new_password",
        ""
    )

    new_password2 = request.form.get(
        "new_password2",
        ""
    )

    if not email:

        return jsonify({
            "success": False,
            "error": "Vui lòng nhập email."
        }), 400

    if not code:

        return jsonify({
            "success": False,
            "error": "Vui lòng nhập mã xác nhận."
        }), 400

    if len(new_password) < 6:

        return jsonify({
            "success": False,
            "error": "Mật khẩu mới phải có ít nhất 6 ký tự."
        }), 400

    if new_password != new_password2:

        return jsonify({
            "success": False,
            "error": (
                "Mật khẩu mới nhập lại "
                "không giống nhau."
            )
        }), 400

    user = User.query.filter(
        db.func.lower(User.email)
        == email
    ).first()

    if user is None:

        return jsonify({
            "success": False,
            "error": "Mã xác nhận không hợp lệ."
        }), 400

    if not user.reset_code_hash:

        return jsonify({
            "success": False,
            "error": (
                "Mã xác nhận không tồn tại "
                "hoặc đã hết hạn."
            )
        }), 400

    if not user.reset_code_expires:

        return jsonify({
            "success": False,
            "error": "Mã xác nhận đã hết hạn."
        }), 400

    if datetime.utcnow() > user.reset_code_expires:

        user.reset_code_hash = None
        user.reset_code_expires = None

        db.session.commit()

        return jsonify({
            "success": False,
            "error": (
                "Mã xác nhận đã hết hạn. "
                "Vui lòng lấy mã mới."
            )
        }), 400

    if not check_password_hash(
        user.reset_code_hash,
        code
    ):

        return jsonify({
            "success": False,
            "error": "Mã xác nhận không đúng."
        }), 400

    user.password_hash = (
        generate_password_hash(
            new_password
        )
    )

    # Mã chỉ dùng một lần
    user.reset_code_hash = None
    user.reset_code_expires = None

    db.session.commit()

    return jsonify({
        "success": True,
        "message": (
            "Đặt lại mật khẩu thành công."
        )
    })


# =========================================================
# ADMIN PANEL
# =========================================================

@app.route("/admin")
def admin():

    current_user, error_response = (
        require_admin()
    )

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

    current_user, error_response = (
        require_admin()
    )

    if error_response:

        return error_response

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

    current_user, error_response = (
        require_admin()
    )

    if error_response:

        return error_response

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

    current_user, error_response = (
        require_admin()
    )

    if error_response:

        return error_response

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

    # Không cho xóa Admin khác
    if user.role == "Admin":

        return redirect(
            url_for("admin")
        )

    db.session.delete(
        user
    )

    db.session.commit()

    return redirect(
        url_for("admin")
    )


# =========================================================
# DATABASE CHECK
# =========================================================

@app.route(
    "/kiem-tra-db"
)
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
# UPLOAD VIDEO
# =========================================================

@app.route(
    "/upload",
    methods=["POST"]
)
def upload_video():

    current_user = get_current_user()

    if current_user is None:

        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    if current_user.status != "Active":

        session.clear()

        return jsonify({
            "success": False,
            "error": "Tài khoản của bạn đang bị khóa."
        }), 403

    file = request.files.get(
        "video"
    )

    if file is None or not file.filename:

        return jsonify({
            "success": False,
            "error": "Vui lòng chọn video."
        }), 400

    if not allowed_video(
        file.filename
    ):

        return jsonify({
            "success": False,
            "error": "Định dạng video không được hỗ trợ."
        }), 400

    safe_name = secure_filename(
        file.filename
    )

    if not safe_name:

        return jsonify({
            "success": False,
            "error": "Tên file không hợp lệ."
        }), 400

    extension = ""

    if "." in safe_name:

        extension = (
            safe_name
            .rsplit(".", 1)[1]
            .lower()
        )

    unique_name = (
        str(uuid.uuid4())
        + "."
        + extension
    )

    save_path = os.path.join(
        UPLOAD_DIR,
        unique_name
    )

    try:

        file.save(
            save_path
        )

    except Exception as e:

        print(
            "[UPLOAD] LOI:",
            e
        )

        return jsonify({
            "success": False,
            "error": "Không thể lưu video."
        }), 500

    download_url = url_for(
        "download_video",
        filename=unique_name
    )

    return jsonify({

        "success": True,

        "message": "Upload thành công.",

        "download_url": download_url

    })


# =========================================================
# DOWNLOAD VIDEO
# =========================================================

@app.route(
    "/download/<path:filename>"
)
def download_video(filename):

    current_user = get_current_user()

    if current_user is None:

        return redirect(
            url_for("index")
        )

    if current_user.status != "Active":

        session.clear()

        return redirect(
            url_for("index")
        )

    return send_from_directory(
        UPLOAD_DIR,
        filename,
        as_attachment=True
    )


# =========================================================
# 413 - FILE TOO LARGE
# =========================================================

@app.errorhandler(413)
def request_entity_too_large(error):

    return jsonify({

        "success": False,

        "error": (
            "Video vượt quá giới hạn 500 MB."
        )

    }), 413


# =========================================================
# 500 - INTERNAL ERROR
# =========================================================

@app.errorhandler(500)
def internal_server_error(error):

    db.session.rollback()

    return jsonify({

        "success": False,

        "error": (
            "Máy chủ gặp lỗi. "
            "Vui lòng thử lại."
        )

    }), 500


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

    print()

    print(
        "ADMIN_USERNAME:"
    )

    print(
        os.environ.get(
            "ADMIN_USERNAME",
            "(chua cai)"
        )
    )

    print()

    print(
        "SMTP:"
    )

    print(
        SMTP_HOST
        if SMTP_HOST
        else "(chua cai)"
    )

    print(
        "======================================"
    )

    print()

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=(
            os.environ.get(
                "FLASK_DEBUG",
                "0"
            ) == "1"
        )
    )
