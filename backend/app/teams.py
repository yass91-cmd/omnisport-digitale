"""Coach-owned teams and consent-based player memberships."""

import hashlib
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from .contact import name_key, normalize_phone
from .models import (
    RosterIdentityLock,
    Sport,
    Team,
    TeamContactMember,
    TeamMembership,
    TeamRequest,
    User,
)
from .security import CsrfIdentity, Database, PassiveIdentity, same_origin_write, utcnow

router = APIRouter(
    prefix="/api/v1/teams", tags=["teams"], dependencies=[Depends(same_origin_write)]
)


class TeamInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=100)]
    sport_id: UUID
    open_to_requests: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value


class TeamSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    open_to_requests: bool


def require_role(identity, role):
    if identity.user.client_role != role:
        raise HTTPException(403, f"This action requires a {role} account.")


def owned_team(session, team_id, coach_id):
    team = session.scalar(select(Team).where(Team.id == team_id).with_for_update())
    if team is None or team.coach_id != coach_id:
        raise HTTPException(404, "Team not found.")
    return team


def team_read(team):
    return {
        "id": team.id,
        "name": team.name,
        "sport_id": team.sport_id,
        "sport": team.sport.name,
        "sport_slug": team.sport.slug,
        "coach_name": team.coach.name,
        "open_to_requests": team.open_to_requests,
    }


@router.get("")
def list_teams(
    identity: PassiveIdentity,
    session: Database,
    mine: bool = False,
    sport_id: UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    query = select(Team).join(Team.coach).where(Team.coach.has(active=True))
    if mine:
        query = query.where(Team.coach_id == identity.user.id)
    if sport_id:
        query = query.where(Team.sport_id == sport_id)
    rows = session.scalars(query.order_by(Team.name, Team.id).offset(offset).limit(51)).all()
    return {"items": [team_read(row) for row in rows[:50]], "has_more": len(rows) > 50}


@router.post("", status_code=201)
def create_team(data: TeamInput, identity: CsrfIdentity, session: Database):
    require_role(identity, "coach")
    if session.get(Sport, data.sport_id) is None:
        raise HTTPException(422, "Choose a supported sport.")
    team = Team(**data.model_dump(), coach_id=identity.user.id, created_at=utcnow())
    session.add(team)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "You already have a team with this name in this sport.") from None
    return team_read(team)


@router.patch("/{team_id}")
def update_team(team_id: UUID, data: TeamSettings, identity: CsrfIdentity, session: Database):
    require_role(identity, "coach")
    team = owned_team(session, team_id, identity.user.id)
    team.open_to_requests = data.open_to_requests
    session.commit()
    return team_read(team)


class InviteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "decline", "withdraw"]


class AddPlayerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=100)]
    phone: str
    email: Annotated[EmailStr | None, Field(max_length=254)] = None
    _name = field_validator("name", mode="before")(TeamInput.clean_name.__func__)
    _phone = field_validator("phone", mode="before")(normalize_phone)

    @field_validator("email", mode="before")
    @classmethod
    def optional_email(cls, value):
        return value.strip().casefold() or None if isinstance(value, str) else value


def roster_key(name, phone):
    return hashlib.sha256(f"{name_key(name)}\n{phone}".encode()).hexdigest()


def lock_roster(session, key):
    table = RosterIdentityLock.__table__
    if session.get_bind().dialect.name == "mysql":
        statement = mysql_insert(table).values(key=key)
        statement = statement.on_duplicate_key_update(key=key)
    else:
        statement = sqlite_insert(table).values(key=key).on_conflict_do_nothing()
    session.execute(statement)
    session.scalar(
        select(RosterIdentityLock).where(RosterIdentityLock.key == key).with_for_update()
    )


def contact_membership(session, key, sport_id):
    return session.scalar(
        select(TeamContactMember)
        .where(
            TeamContactMember.identity_key == key,
            TeamContactMember.sport_id == sport_id,
            TeamContactMember.active_slot == 1,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def contact_read(row):
    return {
        "id": row.id,
        "team_id": row.team_id,
        "team_name": row.team.name,
        "sport": row.team.sport.name,
        "player_name": row.name,
        "phone": row.phone,
        "email": row.email,
        "contact_member": True,
    }


@router.post("/{team_id}/players", status_code=201)
def add_player(team_id: UUID, data: AddPlayerInput, identity: CsrfIdentity, session: Database):
    require_role(identity, "coach")
    team = session.get(Team, team_id)
    if team is None or team.coach_id != identity.user.id:
        raise HTTPException(404, "Team not found.")
    key = roster_key(data.name, data.phone)
    lock_roster(session, key)
    team = owned_team(session, team_id, identity.user.id)
    current = contact_membership(session, key, team.sport_id)
    if current:
        raise HTTPException(
            409,
            "This player already belongs to a team in this sport. Remove the existing membership first.",
        )
    # Contact details never create a login or overwrite an existing user's identity.
    players = session.scalars(
        select(User).where(User.phone == data.phone, User.client_role == "player")
    ).all()
    for player in players:
        if name_key(player.name) == name_key(data.name) and active_membership(
            session, player.id, team.sport_id
        ):
            raise HTTPException(409, "This player already belongs to a team in this sport.")
    row = TeamContactMember(
        team_id=team.id,
        sport_id=team.sport_id,
        identity_key=key,
        name=data.name,
        phone=data.phone,
        email=str(data.email) if data.email else None,
        active_slot=1,
        started_at=utcnow(),
    )
    session.add(row)
    session.commit()
    return contact_read(row)


@router.post("/players/{member_id}/remove")
def remove_player(member_id: UUID, identity: CsrfIdentity, session: Database):
    require_role(identity, "coach")
    row = session.get(TeamContactMember, member_id)
    if row is None or row.team.coach_id != identity.user.id:
        raise HTTPException(404, "Player not found.")
    lock_roster(session, row.identity_key)
    row = session.scalar(
        select(TeamContactMember)
        .where(TeamContactMember.id == member_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.active_slot:
        row.active_slot = None
        row.ended_at = utcnow()
    session.commit()
    return {"status": "ended"}


def lock_player(session, player_id):
    # All membership writers serialize on the player, including when no membership exists.
    # A write also provides the equivalent serialization on SQLite.
    session.execute(update(User).where(User.id == player_id).values(active=User.active))
    player = session.scalar(select(User).where(User.id == player_id).with_for_update())
    if player is None or not player.active or player.client_role != "player":
        raise HTTPException(404, "Player account not available.")
    if player.phone:
        lock_roster(session, roster_key(player.name, player.phone))
    return player


def active_membership(session, player_id, sport_id):
    return session.scalar(
        select(TeamMembership)
        .where(
            TeamMembership.player_id == player_id,
            TeamMembership.sport_id == sport_id,
            TeamMembership.active_slot == 1,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def request_read(row):
    return {
        "id": row.id,
        "team_id": row.team_id,
        "team_name": row.team.name,
        "sport": row.team.sport.name,
        "player_name": row.player.name,
        "kind": row.kind,
        "status": row.status,
    }


def add_request(session, team, player_id, kind):
    current = active_membership(session, player_id, team.sport_id)
    if current and current.team_id == team.id:
        raise HTTPException(409, "This player already belongs to this team.")
    existing = session.scalar(
        select(TeamRequest)
        .where(
            TeamRequest.team_id == team.id,
            TeamRequest.player_id == player_id,
            TeamRequest.pending_slot == 1,
        )
        .with_for_update()
    )
    if existing:
        raise HTTPException(409, "A request or invitation is already waiting for a response.")
    row = TeamRequest(
        team_id=team.id,
        player_id=player_id,
        kind=kind,
        previous_membership_id=current.id if current else None,
        created_at=utcnow(),
    )
    session.add(row)
    session.commit()
    return request_read(row)


@router.post("/{team_id}/join", status_code=201)
def join_team(team_id: UUID, identity: CsrfIdentity, session: Database):
    require_role(identity, "player")
    lock_player(session, identity.user.id)
    team = session.scalar(select(Team).where(Team.id == team_id).with_for_update())
    if team is None or not team.coach.active:
        raise HTTPException(404, "Team not found.")
    return add_request(session, team, identity.user.id, "join")


@router.post("/{team_id}/invite", status_code=201)
def invite_player(team_id: UUID, data: InviteInput, identity: CsrfIdentity, session: Database):
    require_role(identity, "coach")
    # Check ownership before looking up a private account.
    team = session.get(Team, team_id)
    if team is None or team.coach_id != identity.user.id:
        raise HTTPException(404, "Team not found.")
    player = session.scalar(select(User).where(User.email == str(data.email).casefold()))
    if player is None:
        raise HTTPException(404, "Player account not available. Ask the player to register first.")
    lock_player(session, player.id)
    team = owned_team(session, team_id, identity.user.id)
    return add_request(session, team, player.id, "invite")


@router.get("/activity")
def activity(identity: PassiveIdentity, session: Database, offset: Annotated[int, Query(ge=0)] = 0):
    coach = identity.user.client_role == "coach"
    scope = (
        Team.coach_id == identity.user.id if coach else TeamRequest.player_id == identity.user.id
    )
    requests = session.scalars(
        select(TeamRequest)
        .join(Team)
        .where(scope)
        .order_by(TeamRequest.created_at.desc(), TeamRequest.id)
        .offset(offset)
        .limit(51)
    ).all()
    member_scope = (
        Team.coach_id == identity.user.id if coach else TeamMembership.player_id == identity.user.id
    )
    members = session.scalars(
        select(TeamMembership)
        .join(Team)
        .where(member_scope, TeamMembership.active_slot == 1)
        .order_by(Team.name, TeamMembership.id)
    ).all()
    contacts = (
        session.scalars(
            select(TeamContactMember)
            .join(Team)
            .where(Team.coach_id == identity.user.id, TeamContactMember.active_slot == 1)
            .order_by(TeamContactMember.name, TeamContactMember.id)
        ).all()
        if coach
        else []
    )
    return {
        "requests": [request_read(row) for row in requests[:50]],
        "has_more": len(requests) > 50,
        "members": [
            {
                "id": row.id,
                "team_id": row.team_id,
                "team_name": row.team.name,
                "sport": row.team.sport.name,
                "player_name": row.player.name,
            }
            for row in members
        ]
        + [contact_read(row) for row in contacts],
    }


@router.post("/requests/{request_id}/decide")
def decide_request(
    request_id: UUID, data: DecisionInput, identity: CsrfIdentity, session: Database
):
    row = session.get(TeamRequest, request_id)
    if row is None or identity.user.id not in {row.player_id, row.team.coach_id}:
        raise HTTPException(404, "Request not found.")
    responder = row.team.coach_id if row.kind == "join" else row.player_id
    initiator = row.player_id if row.kind == "join" else row.team.coach_id
    if identity.user.id != (initiator if data.action == "withdraw" else responder):
        raise HTTPException(403, "Only the recipient can accept or decline this request.")
    lock_player(session, row.player_id)
    row = session.scalar(
        select(TeamRequest)
        .where(TeamRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    wanted = {"accept": "accepted", "decline": "declined", "withdraw": "withdrawn"}[data.action]
    if row.status != "pending":
        if row.status == wanted:
            return request_read(row)
        raise HTTPException(409, "This request has already been answered.")
    if data.action == "accept":
        if not row.team.coach.active:
            raise HTTPException(409, "This team's coach is unavailable.")
        current = active_membership(session, row.player_id, row.team.sport_id)
        if row.kind == "join" and (current.id if current else None) != row.previous_membership_id:
            raise HTTPException(
                409, "The player's team has changed. Withdraw this request and send a new one."
            )
        if current and current.team_id == row.team_id:
            raise HTTPException(409, "Already a member of this team.")
        if row.player.phone:
            contact = contact_membership(
                session, roster_key(row.player.name, row.player.phone), row.team.sport_id
            )
            if contact:
                if contact.team_id != row.team_id:
                    raise HTTPException(
                        409,
                        "This player is already listed in another team. Ask that coach to remove the existing membership first.",
                    )
                contact.active_slot = None
                contact.ended_at = utcnow()
        if current:
            current.active_slot = None
            current.ended_at = utcnow()
            session.flush()
        session.add(
            TeamMembership(
                team_id=row.team_id,
                player_id=row.player_id,
                sport_id=row.team.sport_id,
                active_slot=1,
                started_at=utcnow(),
            )
        )
    row.status = wanted
    row.pending_slot = None
    row.decided_at = utcnow()
    session.commit()
    return request_read(row)


@router.post("/memberships/{membership_id}/leave")
def leave_team(membership_id: UUID, identity: CsrfIdentity, session: Database):
    row = session.get(TeamMembership, membership_id)
    if row is None or identity.user.id not in {row.player_id, row.team.coach_id}:
        raise HTTPException(404, "Membership not found.")
    lock_player(session, row.player_id)
    row = session.scalar(
        select(TeamMembership)
        .where(TeamMembership.id == membership_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.active_slot:
        row.active_slot = None
        row.ended_at = utcnow()
        session.commit()
    return {"status": "ended"}
