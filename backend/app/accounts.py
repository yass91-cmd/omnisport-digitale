"""Trusted operator CLI. Elevated roles are never selected during public signup."""

import argparse
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .database import make_engine
from .models import Complex, StaffAssignment, User


def change_access(session: Session, command: str, email: str, *, complex_id=None, role=None):
    email = validate_email(email.strip().casefold(), check_deliverability=False).normalized
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.active:
        raise ValueError("An active, registered account is required.")
    if command == "set-client-role":
        if role not in {"player", "coach"}:
            raise ValueError("Invalid client role.")
        user.client_role = role
    else:
        complex_ = session.get(Complex, complex_id)
        if complex_ is None or not complex_.active:
            raise ValueError("An active complex is required.")
        assignment = session.scalar(
            select(StaffAssignment).where(
                StaffAssignment.user_id == user.id,
                StaffAssignment.complex_id == complex_id,
            )
        )
        if command == "revoke-staff":
            if assignment:
                assignment.active = False
        elif command == "grant-staff" and role in {"employee", "admin"}:
            if assignment is None:
                assignment = StaffAssignment(user_id=user.id, complex_id=complex_id, role=role)
                session.add(assignment)
            assignment.role = role
            assignment.active = True
        else:
            raise ValueError("Invalid staff command or role.")
    session.flush()


def main():
    parser = argparse.ArgumentParser(description="Assign access as a trusted application operator.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["grant-staff", "revoke-staff", "set-client-role"]:
        sub = commands.add_parser(name)
        sub.add_argument("--email", required=True)
        if name != "set-client-role":
            sub.add_argument("--complex-id", required=True, type=UUID)
        if name != "revoke-staff":
            sub.add_argument(
                "--role",
                required=True,
                choices=(
                    ["player", "coach"] if name == "set-client-role" else ["employee", "admin"]
                ),
            )
    args = parser.parse_args()
    engine = make_engine(Settings())
    try:
        with Session(engine) as session, session.begin():
            change_access(
                session,
                args.command,
                args.email,
                complex_id=getattr(args, "complex_id", None),
                role=getattr(args, "role", None),
            )
        print(
            "Access updated. Existing sessions will use the current permissions on their next request."
        )
    except (ValueError, EmailNotValidError) as error:
        raise SystemExit(str(error)) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
