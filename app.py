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
import subprocess
from datetime import datetime, timedelta

import resend


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
# RESEND
# =========================================================

RESEND_API_KEY = os.environ.get(
    "RESEND_API_KEY",
    ""
).strip()

RESEND_FROM = os.environ.get(
    "RESEND_FROM",
    "onboarding@resend.dev"
).strip()

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


# =========================================================
# FILE UPLOAD / OUTPUT / FFMPEG
# =========================================================

UPLOAD_DIR = os.path.join(
    BASE_DIR,
    "uploads"
)

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "outputs"
)

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)

app.config["MAX_CONTENT_LENGTH"] = (
    500 * 1024 * 1024
)

ALLOWED_VIDEO_EXTENSIONS = {
    "mp4",
    "mov",
    "avi",
    "mkv",
    "webm",
    "m4v"
}

PROJECT_FFMPEG = os.path.join(
    BASE_DIR,
    "ffmpeg",
    "bin",
    "ffmpeg.exe"
)

DOWNLOADS_FFMPEG = os.path.join(
    os.path.expanduser("~"),
    "Downloads",
    "ffmpeg",
    "bin",
    "ffmpeg.exe"
)

FFMPEG_PATH = os.environ.get(
    "FFMPEG_PATH",
    ""
).strip()

if not FFMPEG_PATH:

    if os.path.isfile(PROJECT_FFMPEG):

        FFMPEG_PATH = PROJECT_FFMPEG

    elif os.path.isfile(DOWNLOADS_FFMPEG):

        FFMPEG_PATH = DOWNLOADS_FFMPEG

    else:

        FFMPEG_PATH = "ffmpeg"


def allowed_video(filename):

    return (
        "." in filename
        and filename.rsplit(
            ".",
            1
        )[1].lower()
        in ALLOWED_VIDEO_EXTENSIONS
    )


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

    columns = [
        column["name"]
        for column in inspector.get_columns(
            "user"
        )
    ]

    if "role" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                'ALTER TABLE "user" '
                "ADD COLUMN role "
                "VARCHAR(20) "
                "DEFAULT 'User'"
            )

            connection.commit()

    if "status" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                'ALTER TABLE "user" '
                "ADD COLUMN status "
                "VARCHAR(20) "
                "DEFAULT 'Active'"
            )

            connection.commit()

    if "reset_code_hash" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                'ALTER TABLE "user" '
                "ADD COLUMN reset_code_hash "
                "VARCHAR(255)"
            )

            connection.commit()

    if "reset_code_expires" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                'ALTER TABLE "user" '
                "ADD COLUMN reset_code_expires "
                "DATETIME"
            )

            connection.commit()

    users = User.query.all()

    changed = False

    for user in users:

        if not user.plan:

            user.plan = "Free"
            changed = True

        if user.plan not in [
            "Free",
            "Pro"
        ]:

            user.plan = "Free"
            changed = True

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

    admin_username = os.environ.get(
        "ADMIN_USERNAME",
        "admin"
    ).strip()

    if admin_username:

        admin_user = User.query.filter(
            db.func.lower(
                User.username
            )
            == admin_username.lower()
        ).first()

        if admin_user:

            if admin_user.role != "Admin":

                admin_user.role = "Admin"
                changed = True

    if changed:

        db.session.commit()


with app.app_context():

    setup_database()


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
# HOME RENDER
# =========================================================

def render_home(
    error=None,
    success=None
):

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

        error=error,

        success=success

    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    return render_home()


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

    if not username:

        return render_home(
            error="Vui lòng nhập username."
        )

    if not email:

        return render_home(
            error="Vui lòng nhập email."
        )

    if len(password) < 6:

        return render_home(
            error=(
                "Mật khẩu phải có ít nhất 6 ký tự."
            )
        )

    if password != password2:

        return render_home(
            error=(
                "Mật khẩu nhập lại không giống nhau."
            )
        )

    existing_username = User.query.filter(
        db.func.lower(
            User.username
        )
        == username.lower()
    ).first()

    if existing_username:

        return render_home(
            error="Username đã tồn tại."
        )

    existing_email = User.query.filter(
        db.func.lower(
            User.email
        )
        == email.lower()
    ).first()

    if existing_email:

        return render_home(
            error="Email đã được sử dụng."
        )

    admin_username = os.environ.get(
        "ADMIN_USERNAME",
        "admin"
    ).strip()

    role = "User"

    if (
        admin_username
        and username.lower()
        == admin_username.lower()
    ):

        role = "Admin"

    new_user = User(

        username=username,

        email=email,

        password_hash=(
            generate_password_hash(
                password
            )
        ),

        plan="Free",

        role=role,

        status="Active"

    )

    db.session.add(
        new_user
    )

    db.session.commit()

    return render_home(
        success=(
            "Đăng ký thành công! Hãy đăng nhập."
        )
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

    if not login_value:

        login_value = request.form.get(
            "login_user",
            ""
        ).strip()

    password = request.form.get(
        "password",
        ""
    )

    if (
        not login_value
        or not password
    ):

        return render_home(
            error=(
                "Vui lòng nhập đầy đủ thông tin."
            )
        )

    user = User.query.filter(
        db.or_(
            db.func.lower(
                User.username
            )
            == login_value.lower(),

            db.func.lower(
                User.email
            )
            == login_value.lower()
        )
    ).first()

    if user is None:

        return render_home(
            error=(
                "Tài khoản hoặc mật khẩu không đúng."
            )
        )

    if not check_password_hash(
        user.password_hash,
        password
    ):

        return render_home(
            error=(
                "Tài khoản hoặc mật khẩu không đúng."
            )
        )

    if user.status != "Active":

        return render_home(
            error=(
                "Tài khoản của bạn đang bị khóa."
            )
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
# RESEND - SEND RESET EMAIL
# =========================================================

def send_reset_email(
    receiver_email,
    reset_code
):

    if not RESEND_API_KEY:

        message = (
            "RESEND_API_KEY chưa được cấu hình trên Render."
        )

        print(
            "[RESEND] ERROR:",
            message
        )

        return False, message

    if not RESEND_FROM:

        message = (
            "RESEND_FROM chưa được cấu hình trên Render."
        )

        print(
            "[RESEND] ERROR:",
            message
        )

        return False, message

    try:

        resend.api_key = RESEND_API_KEY

        params = {

            "from": RESEND_FROM,

            "to": [
                receiver_email
            ],

            "subject": (
                "Mã xác nhận - REUP NVL VIP"
            ),

            "text": (
                "REUP NVL VIP\n\n"
                "Mã xác nhận đặt lại mật khẩu của bạn là:\n\n"
                f"{reset_code}\n\n"
                "Mã có hiệu lực trong 10 phút.\n\n"
                "Nếu bạn không yêu cầu thao tác này, "
                "hãy bỏ qua email."
            ),

            "html": f"""
<!DOCTYPE html>

<html lang="vi">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>REUP NVL VIP</title>

</head>

<body
style="
    margin:0;
    padding:0;
    background:#f3f4f6;
    font-family:Arial,Helvetica,sans-serif;
"
>

<table
width="100%"
cellpadding="0"
cellspacing="0"
border="0"
style="
    background:#f3f4f6;
    padding:30px 10px;
"
>

<tr>

<td align="center">

<table
width="100%"
cellpadding="0"
cellspacing="0"
border="0"
style="
    max-width:520px;
    background:#ffffff;
    border-radius:16px;
    overflow:hidden;
"
>

<tr>

<td
style="
    padding:28px;
    background:#111827;
    text-align:center;
"
>

<div
style="
    color:#a78bfa;
    font-size:24px;
    font-weight:800;
"
>
REUP NVL VIP
</div>

</td>

</tr>

<tr>

<td
style="
    padding:30px;
    color:#111827;
"
>

<h2
style="
    margin:0 0 18px 0;
"
>
Mã xác nhận đặt lại mật khẩu
</h2>

<p
style="
    margin:0 0 16px 0;
    font-size:15px;
    line-height:1.6;
"
>
Bạn vừa yêu cầu đặt lại mật khẩu.
</p>

<p
style="
    margin:0 0 12px 0;
    font-size:15px;
    line-height:1.6;
"
>
Mã xác nhận của bạn là:
</p>

<div
style="
    display:block;
    padding:20px 10px;
    margin:10px 0 22px 0;
    background:#f3f4f6;
    border:2px solid #8b5cf6;
    border-radius:12px;
    text-align:center;
    color:#111827;
    font-size:38px;
    line-height:1.2;
    font-weight:900;
    letter-spacing:10px;
"
>
{reset_code}
</div>

<p
style="
    margin:0 0 10px 0;
    font-size:14px;
    line-height:1.6;
"
>
Mã có hiệu lực trong <strong>10 phút</strong>.
</p>

<p
style="
    margin:0;
    color:#6b7280;
    font-size:13px;
    line-height:1.6;
"
>
Nếu bạn không yêu cầu thao tác này,
hãy bỏ qua email.
</p>

</td>

</tr>

</table>

</td>

</tr>

</table>

</body>

</html>
""".strip()

        }

        email_result = resend.Emails.send(
            params
        )

        print(
            "[RESEND] OK:",
            email_result
        )

        return True, email_result

    except Exception as exc:

        error_text = str(exc)

        print(
            "[RESEND] ERROR:",
            error_text
        )

        return False, error_text


# =========================================================
# FORGOT PASSWORD
# =========================================================

@app.route(
    "/forgot-password",
    methods=["POST"]
)
def forgot_password():

    data = (
        request.get_json(
            silent=True
        )
        or request.form
    )

    email = str(
        data.get(
            "email",
            ""
        )
    ).strip().lower()

    if not email:

        return jsonify({

            "success": False,

            "error": "Vui lòng nhập email."

        }), 400

    user = User.query.filter(

        db.func.lower(
            User.email
        )
        == email

    ).first()

    if user is None:

        return jsonify({

            "success": True,

            "message": (
                "Nếu email tồn tại, "
                "mã xác nhận đã được gửi."
            )

        })

    if user.status != "Active":

        return jsonify({

            "success": False,

            "error": (
                "Tài khoản của bạn đang bị khóa."
            )

        }), 403

    reset_code = (
        f"{secrets.randbelow(1000000):06d}"
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

    print(
        "[RESET EMAIL] "
        "ĐANG GỬI MÃ 6 SỐ TỚI:",
        user.email
    )

    ok, result = send_reset_email(

        user.email,

        reset_code

    )

    if not ok:

        user.reset_code_hash = None

        user.reset_code_expires = None

        db.session.commit()

        print(
            "[RESET EMAIL] LOI:",
            result
        )

        return jsonify({

            "success": False,

            "error": (
                "Không gửi được email. "
                "Kiểm tra Resend trên Render."
            )

        }), 500

    print(
        "[RESET EMAIL] DA GUI:",
        user.email
    )

    return jsonify({

        "success": True,

        "message": (
            "Mã xác nhận đã được gửi "
            "về email."
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

    data = (
        request.get_json(
            silent=True
        )
        or request.form
    )

    email = str(
        data.get(
            "email",
            ""
        )
    ).strip().lower()

    code = str(
        data.get(
            "code",
            ""
        )
    ).strip()

    new_password = str(

        data.get(
            "new_password",
            ""
        )

        or data.get(
            "newPassword",
            ""
        )

        or data.get(
            "password",
            ""
        )

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

    if not new_password:

        return jsonify({

            "success": False,

            "error": "Vui lòng nhập mật khẩu mới."

        }), 400

    if len(new_password) < 6:

        return jsonify({

            "success": False,

            "error": (
                "Mật khẩu mới phải có ít nhất 6 ký tự."
            )

        }), 400

    user = User.query.filter(

        db.func.lower(
            User.email
        )
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

            "error": "Mã xác nhận không hợp lệ."

        }), 400

    if not user.reset_code_expires:

        return jsonify({

            "success": False,

            "error": "Mã xác nhận không hợp lệ."

        }), 400

    if (
        datetime.utcnow()
        > user.reset_code_expires
    ):

        user.reset_code_hash = None

        user.reset_code_expires = None

        db.session.commit()

        return jsonify({

            "success": False,

            "error": "Mã xác nhận đã hết hạn."

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

    user.reset_code_hash = None

    user.reset_code_expires = None

    db.session.commit()

    return jsonify({

        "success": True,

        "message": (
            "Đổi mật khẩu thành công. "
            "Bạn có thể đăng nhập."
        )

    })


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

    if current_user.status != "Active":

        session.clear()

        return jsonify({

            "success": False,

            "error": (
                "Tài khoản của bạn đang bị khóa."
            )

        }), 403

    data = (
        request.get_json(
            silent=True
        )
        or request.form
    )

    current_password = str(

        data.get(
            "current_password",
            ""
        )

        or data.get(
            "old_password",
            ""
        )

        or data.get(
            "currentPassword",
            ""
        )

    )

    new_password = str(

        data.get(
            "new_password",
            ""
        )

        or data.get(
            "newPassword",
            ""
        )

        or data.get(
            "password",
            ""
        )

    )

    if not current_password:

        return jsonify({

            "success": False,

            "error": (
                "Vui lòng nhập mật khẩu hiện tại."
            )

        }), 400

    if not new_password:

        return jsonify({

            "success": False,

            "error": (
                "Vui lòng nhập mật khẩu mới."
            )

        }), 400

    if len(new_password) < 6:

        return jsonify({

            "success": False,

            "error": (
                "Mật khẩu mới phải có ít nhất 6 ký tự."
            )

        }), 400

    if not check_password_hash(
        current_user.password_hash,
        current_password
    ):

        return jsonify({

            "success": False,

            "error": (
                "Mật khẩu hiện tại không đúng."
            )

        }), 400

    current_user.password_hash = (
        generate_password_hash(
            new_password
        )
    )

    db.session.commit()

    return jsonify({

        "success": True,

        "message": "Đổi mật khẩu thành công."

    })


# =========================================================
# ADMIN PAGE
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
# VIDEO UPLOAD
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

            "error": (
                "Tài khoản của bạn đang bị khóa."
            )

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

            "error": (
                "Định dạng video không được hỗ trợ."
            )

        }), 400

    original_name = secure_filename(
        file.filename
    )

    if (
        not original_name
        or "." not in original_name
    ):

        return jsonify({

            "success": False,

            "error": (
                "Tên file video không hợp lệ."
            )

        }), 400

    extension = (
        original_name
        .rsplit(
            ".",
            1
        )[1]
        .lower()
    )

    file_id = uuid.uuid4().hex

    input_name = (
        f"{file_id}_input.{extension}"
    )

    output_name = (
        f"{file_id}_output.mp4"
    )

    input_path = os.path.join(
        UPLOAD_DIR,
        input_name
    )

    output_path = os.path.join(
        OUTPUT_DIR,
        output_name
    )

    try:

        file.save(
            input_path
        )

        command = [

            FFMPEG_PATH,

            "-y",

            "-i",
            input_path,

            "-c:v",
            "libx264",

            "-preset",
            "medium",

            "-crf",
            "23",

            "-pix_fmt",
            "yuv420p",

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-movflags",
            "+faststart",

            output_path
        ]

        result = subprocess.run(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE,

            text=True,

            encoding="utf-8",

            errors="replace"

        )

        if result.returncode != 0:

            print(
                "========== FFMPEG ERROR =========="
            )

            print(
                result.stderr
            )

            print(
                "=================================="
            )

            for path in [
                input_path,
                output_path
            ]:

                try:

                    if os.path.exists(path):

                        os.remove(path)

                except OSError:

                    pass

            return jsonify({

                "success": False,

                "error": (
                    "FFmpeg xử lý video thất bại."
                )

            }), 500

        if (
            not os.path.isfile(
                output_path
            )
            or os.path.getsize(
                output_path
            ) == 0
        ):

            for path in [
                input_path,
                output_path
            ]:

                try:

                    if os.path.exists(path):

                        os.remove(path)

                except OSError:

                    pass

            return jsonify({

                "success": False,

                "error": (
                    "Không tạo được video đầu ra."
                )

            }), 500

        try:

            if os.path.exists(
                input_path
            ):

                os.remove(
                    input_path
                )

        except OSError:

            pass

        return jsonify({

            "success": True,

            "message": (
                "Upload thành công. "
                "Video đã được xử lý."
            ),

            "filename": output_name,

            "download_url": url_for(
                "download_video",
                filename=output_name
            )

        })

    except FileNotFoundError:

        for path in [
            input_path,
            output_path
        ]:

            try:

                if os.path.exists(path):

                    os.remove(path)

            except OSError:

                pass

        return jsonify({

            "success": False,

            "error": (
                "Không tìm thấy chương trình FFmpeg."
            )

        }), 500

    except Exception as exc:

        print(
            "========== UPLOAD ERROR =========="
        )

        print(
            str(exc)
        )

        print(
            "=================================="
        )

        for path in [
            input_path,
            output_path
        ]:

            try:

                if os.path.exists(path):

                    os.remove(path)

            except OSError:

                pass

        return jsonify({

            "success": False,

            "error": (
                "Không thể xử lý video trên server."
            )

        }), 500


# =========================================================
# VIDEO DOWNLOAD
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

    safe_name = secure_filename(
        filename
    )

    if safe_name != filename:

        return (
            "File không hợp lệ.",
            400
        )

    if not safe_name.endswith(
        "_output.mp4"
    ):

        return (
            "File không hợp lệ.",
            400
        )

    file_path = os.path.join(
        OUTPUT_DIR,
        safe_name
    )

    if not os.path.isfile(
        file_path
    ):

        return (
            "Không tìm thấy file.",
            404
        )

    return send_from_directory(

        OUTPUT_DIR,

        safe_name,

        as_attachment=True,

        download_name=safe_name,

        mimetype="video/mp4"

    )


# =========================================================
# DATABASE CHECK
# =========================================================

@app.route(
    "/kiem-tra-db"
)
def check_db():

    current_user = get_current_user()

    if (
        current_user is None
        or current_user.role != "Admin"
    ):

        return jsonify({

            "error": "Unauthorized"

        }), 403

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

    return jsonify(
        result
    )


# =========================================================
# PWA MANIFEST
# =========================================================

@app.route(
    "/manifest.json"
)
def manifest():

    return send_from_directory(

        os.path.join(
            BASE_DIR,
            "static"
        ),

        "manifest.json",

        mimetype=(
            "application/manifest+json"
        )

    )


# =========================================================
# SERVICE WORKER
# =========================================================

@app.route(
    "/sw.js"
)
def service_worker():

    return send_from_directory(

        os.path.join(
            BASE_DIR,
            "static"
        ),

        "sw.js",

        mimetype=(
            "application/javascript"
        )

    )


# =========================================================
# ERROR 413
# =========================================================

@app.errorhandler(413)
def request_entity_too_large(error):

    if request.path == "/upload":

        return jsonify({

            "success": False,

            "error": (
                "Video vượt quá giới hạn 500MB."
            )

        }), 413

    return (
        "File quá lớn.",
        413
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    with app.app_context():

        setup_database()

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(

        host="0.0.0.0",

        port=port,

        debug=False

    )
