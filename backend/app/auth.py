from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import Complex, StaffAssignment, User
from .security import (
    CsrfIdentity,
    CurrentIdentity,
    Database,
    consume_attempts,
    create_session,
    csrf_token,
    current_identity,
    dummy_hash,
    password_matches,
    passwords,
    same_origin_write,
    utcnow,
)

router = APIRouter(
    prefix="/api/v1/auth", tags=["accounts"], dependencies=[Depends(same_origin_write)]
)
staff_router = APIRouter(
    prefix="/api/v1/staff", tags=["staff"], dependencies=[Depends(same_origin_write)]
)
Password = Annotated[SecretStr, Field(min_length=15, max_length=128)]


class NameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=100)]

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Annotated[EmailStr, Field(max_length=254)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, value):
        return value.strip().casefold() if isinstance(value, str) else value


class RegisterInput(LoginInput, NameInput):
    password: Password


class StaffRead(BaseModel):
    complex_id: UUID
    complex_name: str
    city: str
    role: Literal["employee", "admin"]


class AccountRead(BaseModel):
    id: UUID
    name: str
    email: str
    client_role: Literal["player", "coach"]
    staff_assignments: list[StaffRead]
    csrf_token: str


def account(session: Database, user: User, token: str) -> AccountRead:
    assignments = session.scalars(
        select(StaffAssignment)
        .join(Complex)
        .where(
            StaffAssignment.user_id == user.id,
            StaffAssignment.active.is_(True),
            Complex.active.is_(True),
        )
        .order_by(Complex.name)
    ).all()
    return AccountRead(
        id=user.id,
        name=user.name,
        email=user.email,
        client_role=user.client_role,
        staff_assignments=[
            StaffRead(
                complex_id=item.complex_id,
                complex_name=item.complex.name,
                city=item.complex.city,
                role=item.role,
            )
            for item in assignments
        ],
        csrf_token=token,
    )


@router.post("/register", response_model=AccountRead, status_code=201)
def register(data: RegisterInput, request: Request, response: Response, session: Database):
    consume_attempts(session, request, str(data.email), register=True)
    user = User(
        name=data.name,
        email=str(data.email),
        password_hash=passwords.hash(data.password.get_secret_value()),
        client_role="player",
        created_at=utcnow(),
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Unable to create an account with these details.") from None
    csrf = create_session(session, request, response, user)
    return account(session, user, csrf)


@router.post("/login", response_model=AccountRead)
def login(data: LoginInput, request: Request, response: Response, session: Database):
    consume_attempts(session, request, str(data.email))
    user = session.scalar(select(User).where(User.email == str(data.email)))
    valid = password_matches(
        user.password_hash if user else dummy_hash, data.password.get_secret_value()
    )
    if user is None or not valid or not user.active:
        raise HTTPException(401, "Email or password is incorrect.")
    if passwords.check_needs_rehash(user.password_hash):
        user.password_hash = passwords.hash(data.password.get_secret_value())
    csrf = create_session(session, request, response, user)
    return account(session, user, csrf)


@router.get("/me", response_model=AccountRead)
def me(identity: CurrentIdentity, session: Database):
    return account(session, identity.user, csrf_token(identity.token))


@router.get("/session", response_model=AccountRead | None)
def session_status(request: Request, session: Database):
    try:
        identity = current_identity(request, session)
    except HTTPException as error:
        if error.status_code == 401:
            return None
        raise
    return account(session, identity.user, csrf_token(identity.token))


@router.patch("/me", response_model=AccountRead)
def update_profile(data: NameInput, identity: CsrfIdentity, session: Database):
    identity.user.name = data.name
    session.commit()
    return account(session, identity.user, csrf_token(identity.token))


@router.post("/logout", status_code=204)
def logout(identity: CsrfIdentity, request: Request, session: Database):
    session.delete(identity.session)
    session.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        request.app.state.settings.session_cookie,
        path="/",
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
    )
    return response


def complex_assignment(
    complex_id: UUID, identity: CurrentIdentity, session: Database
) -> StaffAssignment:
    assignment = session.scalar(
        select(StaffAssignment)
        .join(Complex)
        .where(
            StaffAssignment.complex_id == complex_id,
            StaffAssignment.user_id == identity.user.id,
            StaffAssignment.active.is_(True),
            Complex.active.is_(True),
        )
    )
    if assignment is None:
        raise HTTPException(403, "You do not have staff access to this complex.")
    return assignment


ComplexAssignment = Annotated[StaffAssignment, Depends(complex_assignment)]


def complex_admin(assignment: ComplexAssignment) -> StaffAssignment:
    if assignment.role != "admin":
        raise HTTPException(403, "Complex administrator access is required.")
    return assignment


ComplexAdmin = Annotated[StaffAssignment, Depends(complex_admin)]


@staff_router.get("/complexes/{complex_id}")
def workspace(assignment: ComplexAssignment):
    complex_ = assignment.complex
    return {
        "id": complex_.id,
        "name": complex_.name,
        "city": complex_.city,
        "role": assignment.role,
        "facilities": [
            {"id": item.id, "name": item.name, "active": item.active}
            for item in sorted(complex_.facilities, key=lambda item: item.name)
        ],
    }


@staff_router.get("/complexes/{complex_id}/staff")
def staff_directory(assignment: ComplexAdmin, session: Database):
    rows = session.execute(
        select(StaffAssignment, User)
        .join(User)
        .where(
            StaffAssignment.complex_id == assignment.complex_id,
            StaffAssignment.active.is_(True),
            User.active.is_(True),
        )
        .order_by(User.name)
    ).all()
    return [{"name": user.name, "email": user.email, "role": item.role} for item, user in rows]
