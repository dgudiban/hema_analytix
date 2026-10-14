"""Family profile endpoints: manage the people under one patient account.

Every endpoint requires login and only ever touches the patient's own
family members — members are never visible across accounts.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.models.db import get_db
from app.models.entities import FamilyMember, User
from app.schemas.dto import (
    FamilyMemberCreate,
    FamilyMemberOut,
    FamilyMemberUpdate,
)

router = APIRouter()

VALID_RELATIONSHIPS = {"father", "mother", "spouse", "son", "daughter", "other"}
VALID_SEX = {"male", "female", "other"}


def _owned_member(db: Session, member_id: int, user: User) -> FamilyMember:
    member = db.get(FamilyMember, member_id)
    if member is None or member.user_id != user.id:
        raise HTTPException(status_code=404, detail="Family member not found.")
    return member


def _out(m: FamilyMember) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "relationship": m.relationship,
        "sex": m.sex,
        "date_of_birth": m.date_of_birth,
        "report_count": len(m.reports),
    }


@router.get("", response_model=list[FamilyMemberOut])
def list_members(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    members = (
        db.query(FamilyMember)
        .filter(FamilyMember.user_id == user.id)
        .order_by(FamilyMember.id)
        .all()
    )
    return [_out(m) for m in members]


@router.post("", response_model=FamilyMemberOut)
def create_member(
    body: FamilyMemberCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if body.relationship not in VALID_RELATIONSHIPS:
        raise HTTPException(status_code=400, detail="Invalid relationship.")
    if body.sex is not None and body.sex not in VALID_SEX:
        raise HTTPException(status_code=400, detail="Invalid value for sex.")
    member = FamilyMember(
        user_id=user.id,
        name=name[:120],
        relationship=body.relationship,
        sex=body.sex,
        date_of_birth=body.date_of_birth,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return _out(member)


@router.put("/{member_id}", response_model=FamilyMemberOut)
def update_member(
    member_id: int,
    body: FamilyMemberUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    member = _owned_member(db, member_id, user)
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty.")
        member.name = name[:120]
    if body.relationship is not None:
        if body.relationship not in VALID_RELATIONSHIPS:
            raise HTTPException(status_code=400, detail="Invalid relationship.")
        member.relationship = body.relationship
    if body.sex is not None:
        if body.sex not in VALID_SEX:
            raise HTTPException(status_code=400, detail="Invalid value for sex.")
        member.sex = body.sex
    if body.date_of_birth is not None:
        member.date_of_birth = body.date_of_birth
    db.commit()
    db.refresh(member)
    return _out(member)


@router.delete("/{member_id}")
def delete_member(
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    member = _owned_member(db, member_id, user)
    report_count = len(member.reports)
    db.delete(member)  # cascades to the member's reports + results
    db.commit()
    return {"deleted": member_id, "reports_removed": report_count}
