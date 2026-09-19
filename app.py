from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    send_from_directory,
    make_response
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
import subprocess
import threading

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


# =========================================================
# FFMPEG OUTPUT
# =========================================================

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "outputs"
)

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


VIDEO_PROGRESS = {}
VIDEO_PROGRESS_LOCK = threading.Lock()


def set_video_progress(video_id, percent):
    try:
        percent = int(percent)
    except Exception:
        percent = 0

    percent = max(0, min(100, percent))

    with VIDEO_PROGRESS_LOCK:
        VIDEO_PROGRESS[video_id] = percent


def get_video_progress(video_id, status=None):
    if status == "Completed":
        return 100
    if status == "Error":
        return 0

    with VIDEO_PROGRESS_LOCK:
        return VIDEO_PROGRESS.get(video_id, 0)


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
# SMTP
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
# VIDEO MODEL
# =========================================================

class Video(db.Model):

    __tablename__ = "video"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    original_name = db.Column(
        db.String(500),
        nullable=False
    )

    stored_name = db.Column(
        db.String(500),
        nullable=False,
        unique=True
    )

    output_name = db.Column(
        db.String(500),
        nullable=True,
        unique=True
    )

    file_size = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="Completed"
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    user = db.relationship(
        "User",
        backref=db.backref(
            "videos",
            lazy=True,
            cascade="all, delete-orphan"
        )
    )


# =========================================================
# DATABASE SETUP / MIGRATION
# =========================================================

def setup_database():

    db.create_all()

    inspector = db.inspect(
        db.engine
    )

    table_names = inspector.get_table_names()

    if "user" not in table_names:
        return

    columns = {
        column["name"]
        for column in inspector.get_columns(
            "user"
        )
    }


    # -----------------------------------------------------
    # PLAN
    # -----------------------------------------------------

    if "plan" not in columns:

        with db.engine.connect() as connection:

            connection.exec_driver_sql(
                "ALTER TABLE user "
                "ADD COLUMN plan VARCHAR(20) "
                "DEFAULT 'Free'"
            )

            connection.commit()


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
    # CREATE VIDEO TABLE IF NEEDED
    # -----------------------------------------------------

    db.create_all()


    # -----------------------------------------------------
    # VIDEO MIGRATION - OUTPUT NAME
    # -----------------------------------------------------

    inspector = db.inspect(
        db.engine
    )

    table_names = inspector.get_table_names()

    if "video" in table_names:

        video_columns = {
            column["name"]
            for column in inspector.get_columns(
                "video"
            )
        }

        if "output_name" not in video_columns:

            with db.engine.connect() as connection:

                connection.exec_driver_sql(
                    "ALTER TABLE video "
                    "ADD COLUMN output_name VARCHAR(500)"
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
# AUTO ADMIN
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
                "[AUTO ADMIN] Chua co tai khoan:",
                admin_username
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
            "[AUTO ADMIN]",
            user.username,
            "=> Admin"
        )

    except Exception as e:

        db.session.rollback()

        print(
            "[AUTO ADMIN] LOI:",
            e
        )


# =========================================================
# START DATABASE
# =========================================================

with app.app_context():

    setup_database()

    auto_set_admin()


# =========================================================
# EMAIL
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

    sender = SMTP_FROM or SMTP_USER

    message = EmailMessage()

    message["Subject"] = (
        "REUP NVL VIP - Ma xac nhan"
    )

    message["From"] = sender

    message["To"] = receiver_email

    message.set_content(
        f"""
Xin chao,

Ma xac nhan REUP NVL VIP cua ban la:

{reset_code}

Ma nay co hieu luc trong 10 phut.

REUP NVL VIP
"""
    )

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
# ACTIVE USER CHECK
# =========================================================

def get_active_user():

    user = get_current_user()

    if user is None:
        return None

    if user.status != "Active":

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
# VIDEO SERIALIZER
# =========================================================

def serialize_video(video):

    return {

        "id": video.id,

        "user_id": video.user_id,

        "original_name": video.original_name,

        "stored_name": video.stored_name,

        "output_name": video.output_name,

        "file_size": video.file_size,

        "status": video.status,

        "progress": get_video_progress(
            video.id,
            video.status
        ),

        "created_at": (
            video.created_at.strftime(
                "%d/%m/%Y %H:%M:%S"
            )
            if video.created_at
            else ""
        ),

        "download_url": (
            url_for(
                "download_output",
                filename=video.output_name
            )
            if video.output_name
            and video.status == "Completed"
            else None
        )

    }


# =========================================================
# FFMPEG PROCESSOR
# =========================================================

def process_video_ffmpeg(video_id, process_mode="original"):

    with app.app_context():

        video = db.session.get(
            Video,
            video_id
        )

        if video is None:
            return

        input_path = os.path.join(
            UPLOAD_DIR,
            video.stored_name
        )

        output_name = (
            "processed_"
            + uuid.uuid4().hex
            + ".mp4"
        )

        output_path = os.path.join(
            OUTPUT_DIR,
            output_name
        )

        try:

            video.status = "Processing"
            video.output_name = None

            db.session.commit()
            set_video_progress(video_id, 1)

            if not os.path.isfile(input_path):
                raise RuntimeError(
                    "Không tìm thấy file video gốc."
                )

            if process_mode not in {
                "original",
                "fit",
                "crop"
            }:
                process_mode = "original"

            video_filter = None

            if process_mode == "fit":
                video_filter = (
                    "scale=720:1280:"
                    "force_original_aspect_ratio=decrease,"
                    "pad=720:1280:"
                    "(ow-iw)/2:(oh-ih)/2:black,"
                    "setsar=1"
                )

            elif process_mode == "crop":
                video_filter = (
                    "scale=720:1280:"
                    "force_original_aspect_ratio=increase,"
                    "crop=720:1280,"
                    "setsar=1"
                )

            command = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                input_path,
                "-map",
                "0:v:0",
                "-map",
                "0:a?"
            ]

            if video_filter:
                command.extend([
                    "-vf",
                    video_filter
                ])

            command.extend([
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
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
                "-progress",
                "pipe:1",
                "-nostats",
                output_path
            ])

            duration_result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    input_path
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False
            )

            try:
                duration_seconds = float(
                    duration_result.stdout.strip()
                )
            except Exception:
                duration_seconds = 0.0

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            if process.stdout is not None:
                for progress_line in process.stdout:
                    progress_line = progress_line.strip()

                    if progress_line.startswith(
                        "out_time_ms="
                    ):
                        try:
                            out_time_us = int(
                                progress_line.split(
                                    "=",
                                    1
                                )[1]
                            )

                            if duration_seconds > 0:
                                percent = int(
                                    (
                                        out_time_us / 1000000.0
                                    )
                                    / duration_seconds
                                    * 100
                                )

                                set_video_progress(
                                    video_id,
                                    min(99, max(1, percent))
                                )
                        except Exception:
                            pass

                    elif progress_line == "progress=end":
                        set_video_progress(video_id, 99)

            stderr_text = (
                process.stderr.read()
                if process.stderr is not None
                else ""
            )

            return_code = process.wait()

            if return_code != 0:
                raise RuntimeError(
                    (
                        stderr_text
                        or "FFmpeg xử lý thất bại."
                    )[-4000:]
                )

            if not os.path.isfile(output_path):

                raise RuntimeError(
                    "FFmpeg không tạo được file output."
                )

            if os.path.getsize(output_path) <= 0:

                raise RuntimeError(
                    "File output không hợp lệ."
                )

            video = db.session.get(
                Video,
                video_id
            )

            if video is None:

                try:
                    os.remove(output_path)
                except Exception:
                    pass

                return

            video.output_name = output_name
            video.status = "Completed"

            db.session.commit()
            set_video_progress(video_id, 100)

            print(
                "[FFMPEG] COMPLETED:",
                video.id,
                output_name
            )

        except subprocess.TimeoutExpired:

            db.session.rollback()

            try:
                if os.path.isfile(output_path):
                    os.remove(output_path)
            except Exception:
                pass

            video = db.session.get(
                Video,
                video_id
            )

            if video:

                video.output_name = None
                video.status = "Error"

                db.session.commit()
                set_video_progress(video_id, 0)

            print(
                "[FFMPEG] TIMEOUT:",
                video_id
            )

        except FileNotFoundError:

            db.session.rollback()

            video = db.session.get(
                Video,
                video_id
            )

            if video:

                video.output_name = None
                video.status = "Error"

                db.session.commit()
                set_video_progress(video_id, 0)

            print(
                "[FFMPEG] LOI: Không tìm thấy lệnh ffmpeg."
            )

        except Exception as e:

            db.session.rollback()

            try:
                if os.path.isfile(output_path):
                    os.remove(output_path)
            except Exception:
                pass

            video = db.session.get(
                Video,
                video_id
            )

            if video:

                video.output_name = None
                video.status = "Error"

                db.session.commit()
                set_video_progress(video_id, 0)

            print(
                "[FFMPEG] LOI:",
                e
            )


# =========================================================
# VIDEO STATS
# =========================================================

def get_video_stats(user_id):

    videos = Video.query.filter_by(
        user_id=user_id
    ).all()

    total = len(videos)

    processing = sum(
        1
        for video in videos
        if video.status == "Processing"
    )

    completed = sum(
        1
        for video in videos
        if video.status == "Completed"
    )

    error = sum(
        1
        for video in videos
        if video.status == "Error"
    )

    return {

        "total": total,

        "processing": processing,

        "success": completed,

        "completed": completed,

        "error": error

    }


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
            error="Thông tin đăng ký chưa hợp lệ.",
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
            error="Thông tin xác nhận không giống nhau.",
            success=None
        )

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

    new_user = User(

        username=username,

        email=email,

        password_hash=generate_password_hash(
            password
        ),

        plan="Free",

        role="User",

        status="Active",

        reset_code_hash=None,

        reset_code_expires=None
    )

    db.session.add(
        new_user
    )

    db.session.commit()

    # Nếu username trùng ADMIN_USERNAME
    # thì auto_set_admin sẽ cấp quyền.
    auto_set_admin()

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
            error="Tài khoản hoặc thông tin đăng nhập không đúng.",
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
            error="Tài khoản hoặc thông tin đăng nhập không đúng.",
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
# ACCOUNT SECURITY ROUTES
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
            "error": "Thông tin hiện tại chưa được nhập."
        }), 400

    if len(new_password) < 6:

        return jsonify({
            "success": False,
            "error": "Thông tin mới phải có ít nhất 6 ký tự."
        }), 400

    if new_password != new_password2:

        return jsonify({
            "success": False,
            "error": "Thông tin xác nhận không giống nhau."
        }), 400

    if not check_password_hash(
        current_user.password_hash,
        current_password
    ):

        return jsonify({
            "success": False,
            "error": "Thông tin hiện tại không đúng."
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
        "message": "Cập nhật tài khoản thành công."
    })


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

    if user is None:

        return jsonify({
            "success": True,
            "message": (
                "Nếu email tồn tại, mã xác nhận sẽ được gửi."
            )
        })

    reset_code = str(
        secrets.randbelow(900000) + 100000
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
            "[EMAIL] LOI:",
            e
        )

        user.reset_code_hash = None
        user.reset_code_expires = None

        db.session.commit()

        return jsonify({
            "success": False,
            "error": "Không gửi được email."
        }), 500

    return jsonify({
        "success": True,
        "message": "Mã xác nhận đã được gửi."
    })


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

    if not email or not code:

        return jsonify({
            "success": False,
            "error": "Thông tin xác nhận chưa đầy đủ."
        }), 400

    if len(code) != 6 or not code.isdigit():

        return jsonify({
            "success": False,
            "error": "Mã xác nhận không hợp lệ."
        }), 400

    if len(new_password) < 6:

        return jsonify({
            "success": False,
            "error": "Thông tin mới chưa hợp lệ."
        }), 400

    if new_password != new_password2:

        return jsonify({
            "success": False,
            "error": "Thông tin xác nhận không giống nhau."
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
            "error": "Mã không tồn tại hoặc đã hết hạn."
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
            "error": "Mã đã hết hạn."
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
        "message": "Cập nhật tài khoản thành công."
    })


# =========================================================
# ADMIN
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
# ADMIN PLAN
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

    # Không sửa tài khoản Admin khác
    if user.role == "Admin":

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
# ADMIN STATUS
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

    # Không khóa Admin khác
    if user.role == "Admin":

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
# ADMIN DELETE
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

    # Xóa file video của user trước
    user_videos = Video.query.filter_by(
        user_id=user.id
    ).all()

    for video in user_videos:

        file_path = os.path.join(
            UPLOAD_DIR,
            video.stored_name
        )

        try:

            if os.path.isfile(file_path):
                os.remove(file_path)

        except Exception as e:

            print(
                "[DELETE VIDEO FILE] LOI:",
                e
            )

        if video.output_name:

            output_path = os.path.join(
                OUTPUT_DIR,
                video.output_name
            )

            try:

                if os.path.isfile(output_path):
                    os.remove(output_path)

            except Exception as e:

                print(
                    "[DELETE OUTPUT FILE] LOI:",
                    e
                )

    db.session.delete(user)

    db.session.commit()

    return redirect(
        url_for("admin")
    )


# =========================================================
# DATABASE CHECK - ADMIN ONLY
# =========================================================

@app.route("/kiem-tra-db")
def check_db():

    current_user = get_current_user()

    if (
        current_user is None
        or current_user.status != "Active"
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

            "status": user.status,

            "video_count": Video.query.filter_by(
                user_id=user.id
            ).count()

        })

    return jsonify(result)


# =========================================================
# API - VIDEOS
# =========================================================

@app.route(
    "/api/videos",
    methods=["GET"]
)
def api_videos():

    current_user = get_active_user()

    if current_user is None:

        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    videos = (
        Video.query
        .filter_by(
            user_id=current_user.id
        )
        .order_by(
            Video.id.desc()
        )
        .all()
    )

    stats = get_video_stats(
        current_user.id
    )

    return jsonify({

        "success": True,

        "stats": stats,

        "videos": [
            serialize_video(video)
            for video in videos
        ]

    })


# =========================================================
# API - SINGLE VIDEO
# =========================================================

@app.route(
    "/api/videos/<int:video_id>",
    methods=["GET"]
)
def api_single_video(video_id):

    current_user = get_active_user()

    if current_user is None:

        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    video = Video.query.filter_by(
        id=video_id,
        user_id=current_user.id
    ).first()

    if video is None:

        return jsonify({
            "success": False,
            "error": "Không tìm thấy video."
        }), 404

    return jsonify({

        "success": True,

        "video": serialize_video(
            video
        )

    })


# =========================================================
# DELETE VIDEO
# =========================================================

@app.route(
    "/api/videos/<int:video_id>/delete",
    methods=["POST", "DELETE"]
)
def delete_video(video_id):

    current_user = get_active_user()

    if current_user is None:

        return jsonify({
            "success": False,
            "error": "Bạn chưa đăng nhập."
        }), 401

    video = Video.query.filter_by(
        id=video_id,
        user_id=current_user.id
    ).first()

    if video is None:

        return jsonify({
            "success": False,
            "error": "Không tìm thấy video."
        }), 404

    file_path = os.path.join(
        UPLOAD_DIR,
        video.stored_name
    )

    try:

        if os.path.isfile(file_path):
            os.remove(file_path)

    except Exception as e:

        print(
            "[DELETE VIDEO] LOI:",
            e
        )

    if video.output_name:

        output_path = os.path.join(
            OUTPUT_DIR,
            video.output_name
        )

        try:

            if os.path.isfile(output_path):
                os.remove(output_path)

        except Exception as e:

            print(
                "[DELETE OUTPUT] LOI:",
                e
            )

    db.session.delete(
        video
    )

    db.session.commit()

    return jsonify({

        "success": True,

        "message": "Đã xóa video."

    })


# =========================================================
# UPLOAD
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

    process_mode = request.form.get(
        "process_mode",
        "original"
    ).strip().lower()

    if process_mode not in {
        "original",
        "fit",
        "crop"
    }:
        process_mode = "original"

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

    original_name = file.filename

    safe_name = secure_filename(
        file.filename
    )

    if not safe_name:

        return jsonify({
            "success": False,
            "error": "Tên file không hợp lệ."
        }), 400

    extension = (
        safe_name.rsplit(
            ".",
            1
        )[1].lower()
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
            "[UPLOAD FILE] LOI:",
            e
        )

        return jsonify({
            "success": False,
            "error": "Không thể lưu video."
        }), 500

    try:

        file_size = os.path.getsize(
            save_path
        )

    except Exception:

        file_size = 0

    try:

        video = Video(

            user_id=current_user.id,

            original_name=original_name,

            stored_name=unique_name,

            file_size=file_size,

            status="Processing",

            created_at=datetime.utcnow()
        )

        db.session.add(
            video
        )

        db.session.commit()

    except Exception as e:

        db.session.rollback()

        print(
            "[VIDEO DATABASE] LOI:",
            e
        )

        try:

            if os.path.isfile(save_path):
                os.remove(save_path)

        except Exception:
            pass

        return jsonify({
            "success": False,
            "error": "Không thể lưu lịch sử video."
        }), 500

    set_video_progress(video.id, 0)

    worker = threading.Thread(
        target=process_video_ffmpeg,
        args=(
            video.id,
            process_mode
        ),
        daemon=True
    )

    worker.start()

    return jsonify({

        "success": True,

        "message": (
            "Upload thành công. "
            "Video đang được FFmpeg xử lý."
        ),

        "video": serialize_video(
            video
        ),

        "download_url": None

    })


# =========================================================
# DOWNLOAD OUTPUT - OWNER ONLY
# =========================================================

@app.route(
    "/download-output/<path:filename>"
)
def download_output(filename):

    current_user = get_active_user()

    if current_user is None:

        return redirect(
            url_for("index")
        )

    video = Video.query.filter_by(
        output_name=filename,
        user_id=current_user.id
    ).first()

    if video is None:

        return jsonify({
            "success": False,
            "error": (
                "Không tìm thấy video đã xử lý "
                "hoặc bạn không có quyền tải."
            )
        }), 404

    if video.status != "Completed":

        return jsonify({
            "success": False,
            "error": "Video chưa xử lý xong."
        }), 409

    file_path = os.path.join(
        OUTPUT_DIR,
        video.output_name
    )

    if not os.path.isfile(file_path):

        return jsonify({
            "success": False,
            "error": (
                "File video đã xử lý "
                "không còn trên máy chủ."
            )
        }), 404

    base_name = os.path.splitext(
        video.original_name
    )[0]

    download_name = (
        base_name
        + "_processed.mp4"
    )

    return send_from_directory(
        OUTPUT_DIR,
        video.output_name,
        as_attachment=True,
        download_name=download_name
    )


# =========================================================
# DOWNLOAD - OWNER ONLY
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

    # Chỉ cho phép tải video thuộc tài khoản hiện tại.
    video = Video.query.filter_by(
        stored_name=filename,
        user_id=current_user.id
    ).first()

    if video is None:

        return jsonify({
            "success": False,
            "error": "Không tìm thấy video hoặc bạn không có quyền tải."
        }), 404

    file_path = os.path.join(
        UPLOAD_DIR,
        video.stored_name
    )

    if not os.path.isfile(
        file_path
    ):

        return jsonify({
            "success": False,
            "error": "File video không còn trên máy chủ."
        }), 404

    return send_from_directory(
        UPLOAD_DIR,
        video.stored_name,
        as_attachment=True,
        download_name=video.original_name
    )


# =========================================================
# PWA MANIFEST
# =========================================================

@app.route("/manifest.json")
def manifest():

    response = make_response(
        send_from_directory(
            os.path.join(
                BASE_DIR,
                "static"
            ),
            "manifest.json"
        )
    )

    response.headers[
        "Cache-Control"
    ] = "no-cache"

    return response


# =========================================================
# SERVICE WORKER
# =========================================================

@app.route("/sw.js")
def service_worker():

    response = make_response(
        send_from_directory(
            os.path.join(
                BASE_DIR,
                "static"
            ),
            "sw.js"
        )
    )

    response.headers[
        "Content-Type"
    ] = "application/javascript"

    response.headers[
        "Cache-Control"
    ] = "no-cache"

    return response


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
# 404
# =========================================================

@app.errorhandler(404)
def not_found(error):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,
            "error": "Không tìm thấy."
        }), 404

    return redirect(
        url_for("index")
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

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
