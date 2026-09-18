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
from werkzeug.security import generate_password_hash, check_password_hash

import os
import uuid
import subprocess
from werkzeug.utils import secure_filename


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

# Secret key dùng để bảo vệ session.
# Sau này khi đưa lên Render nên chuyển sang Environment Variable.
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

DB_PATH = os.path.join(DB_DIR, "reup_nvl_vip.db")

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + DB_PATH
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# =========================================================
# FILE UPLOAD / OUTPUT / FFMPEG
# =========================================================

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Giới hạn file upload: 500 MB
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

ALLOWED_VIDEO_EXTENSIONS = {
    "mp4",
    "mov",
    "avi",
    "mkv",
    "webm",
    "m4v"
}

# Có thể đặt FFMPEG_PATH bằng Environment Variable khi deploy.
# Ưu tiên theo thứ tự: Environment -> project -> Downloads (Windows).
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

FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "").strip()

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
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_VIDEO_EXTENSIONS
    )

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


# Initialize/migrate the database when running under Gunicorn/Render.
with app.app_context():
    setup_database()


# =========================================================
# CURRENT USER
# =========================================================

def get_current_user():

    user_id = session.get("user_id")

    if not user_id:
        return None

    user = db.session.get(User, user_id)

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

        return None, redirect(url_for("index"))

    # Kiểm tra trạng thái
    if user.status != "Active":

        session.clear()

        return None, redirect(url_for("index"))

    # Kiểm tra quyền Admin phía SERVER
    if user.role != "Admin":

        return None, redirect(url_for("index"))

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

@app.route("/register", methods=["POST"])
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

    new_user = User(

        username=username,

        email=email,

        password_hash=generate_password_hash(
            password
        ),

        # QUAN TRỌNG:
        # User đăng ký luôn bắt đầu là User
        plan="Free",

        role="User",

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

@app.route("/login", methods=["POST"])
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

    return redirect(url_for("index"))


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout", methods=["GET", "POST"])
def logout():

    session.clear()

    return redirect(url_for("index"))


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

        return redirect(url_for("admin"))

    user = db.session.get(
        User,
        user_id
    )

    if user is None:

        return redirect(url_for("admin"))

    new_plan = request.form.get(
        "plan",
        ""
    )

    # Chỉ cho phép 2 giá trị này
    if new_plan not in ["Free", "Pro"]:

        return redirect(url_for("admin"))

    user.plan = new_plan

    db.session.commit()

    return redirect(url_for("admin"))


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

        return redirect(url_for("admin"))

    user = db.session.get(
        User,
        user_id
    )

    if user is None:

        return redirect(url_for("admin"))

    new_status = request.form.get(
        "status",
        ""
    )

    # Chỉ Active hoặc Banned
    if new_status not in [
        "Active",
        "Banned"
    ]:

        return redirect(url_for("admin"))

    user.status = new_status

    db.session.commit()

    return redirect(url_for("admin"))


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

        return redirect(url_for("admin"))

    user = db.session.get(
        User,
        user_id
    )

    if user is None:

        return redirect(url_for("admin"))

    # Không cho xóa tài khoản Admin khác
    # Đây là lớp bảo vệ thêm.
    if user.role == "Admin":

        return redirect(url_for("admin"))

    db.session.delete(user)

    db.session.commit()

    return redirect(url_for("admin"))


# =========================================================
# VIDEO UPLOAD + FFMPEG REUP
# =========================================================

@app.route("/upload", methods=["POST"])
def upload_video():

    current_user = get_current_user()

    # -------------------------
    # LOGIN
    # -------------------------

    if current_user is None:
        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    # -------------------------
    # STATUS
    # -------------------------

    if current_user.status != "Active":
        session.clear()
        return jsonify({
            "success": False,
            "error": "Tài khoản của bạn đang bị khóa."
        }), 403

    # -------------------------
    # CHECK FFMPEG
    # -------------------------

    if FFMPEG_PATH != "ffmpeg" and not os.path.isfile(FFMPEG_PATH):
        return jsonify({
            "success": False,
            "error": "Không tìm thấy FFmpeg trên máy chủ."
        }), 500

    file = request.files.get("video")

    if file is None or not file.filename:
        return jsonify({
            "success": False,
            "error": "Vui lòng chọn video."
        }), 400

    if not allowed_video(file.filename):
        return jsonify({
            "success": False,
            "error": "Định dạng video không được hỗ trợ."
        }), 400

    # Tạo tên file ngẫu nhiên, không dùng trực tiếp tên file client gửi lên.
    original_name = secure_filename(file.filename)

    if not original_name or "." not in original_name:
        return jsonify({
            "success": False,
            "error": "Tên file video không hợp lệ."
        }), 400

    extension = original_name.rsplit(".", 1)[1].lower()
    file_id = uuid.uuid4().hex

    input_name = f"{file_id}_input.{extension}"
    output_name = f"{file_id}_output.mp4"

    input_path = os.path.join(UPLOAD_DIR, input_name)
    output_path = os.path.join(OUTPUT_DIR, output_name)

    try:
        # -------------------------
        # SAVE ORIGINAL
        # -------------------------

        file.save(input_path)

        # -------------------------
        # FFMPEG COMMAND
        # -------------------------
        # Re-encode video sang H.264 + AAC và xuất MP4.

        command = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path
        ]

        # -------------------------
        # RUN FFMPEG
        # -------------------------

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        # In lỗi FFmpeg ra terminal để dễ kiểm tra khi có sự cố.
        if result.returncode != 0:
            print()
            print("========== FFMPEG ERROR ==========")
            print(result.stderr)
            print("===================================")
            print()

            for path in (input_path, output_path):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

            return jsonify({
                "success": False,
                "error": "FFmpeg xử lý video thất bại."
            }), 500

        # -------------------------
        # CHECK OUTPUT
        # -------------------------

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            for path in (input_path, output_path):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

            return jsonify({
                "success": False,
                "error": "Không tạo được video đầu ra."
            }), 500

        # Xóa video gốc sau khi xử lý xong.
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
        except OSError:
            pass

        return jsonify({
            "success": True,
            "message": "Upload thành công. Video đã được FFmpeg xử lý.",
            "filename": output_name,
            "download_url": url_for(
                "download_video",
                filename=output_name
            )
        })

    except FileNotFoundError:
        for path in (input_path, output_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

        return jsonify({
            "success": False,
            "error": "Không tìm thấy chương trình FFmpeg."
        }), 500

    except Exception as e:
        print()
        print("========== UPLOAD ERROR ==========")
        print(str(e))
        print("==================================")
        print()

        for path in (input_path, output_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

        return jsonify({
            "success": False,
            "error": "Không thể xử lý video trên server."
        }), 500


# =========================================================
# VIDEO DOWNLOAD
# =========================================================

@app.route("/download/<path:filename>")
def download_video(filename):

    current_user = get_current_user()

    if current_user is None:
        return redirect(url_for("index"))

    if current_user.status != "Active":
        session.clear()
        return redirect(url_for("index"))

    # Chỉ cho tải file MP4 có hậu tố do server tạo.
    safe_name = secure_filename(filename)

    if safe_name != filename:
        return "File không hợp lệ.", 400

    if not safe_name.endswith("_output.mp4"):
        return "File không hợp lệ.", 400

    file_path = os.path.join(OUTPUT_DIR, safe_name)

    if not os.path.isfile(file_path):
        return "Không tìm thấy file.", 404

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

    with app.app_context():

        setup_database()

    print()
    print("======================================")
    print("       REUP NVL VIP SERVER")
    print("======================================")
    print("Database:")
    print(DB_PATH)
    print()
    port = int(os.environ.get("PORT", "5000"))

    print("Website:")
    print(f"http://127.0.0.1:{port}")
    print()
    print("Admin:")
    print(f"http://127.0.0.1:{port}/admin")
    print("======================================")
    print()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
