from app import app, db, User

with app.app_context():

    users = User.query.order_by(User.id).all()

    print("================================")
    print("      REUP NVL VIP - USERS")
    print("================================")
    print("So tai khoan:", len(users))
    print()

    for user in users:
        print(
            f"ID: {user.id} | "
            f"Username: {user.username} | "
            f"Email: {user.email} | "
            f"Plan: {user.plan} | "
            f"Role: {user.role} | "
            f"Status: {user.status}"
        )

    print()
    username = input("Nhap username muon lam Admin: ").strip()

    user = User.query.filter_by(
        username=username
    ).first()

    if user is None:
        print("KHONG TIM THAY TAI KHOAN!")
    else:
        user.role = "Admin"
        user.status = "Active"

        db.session.commit()

        print()
        print("================================")
        print("TAO ADMIN THANH CONG!")
        print("Username:", user.username)
        print("Plan:", user.plan)
        print("Role:", user.role)
        print("Status:", user.status)
        print("================================")