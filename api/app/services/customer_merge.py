from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import (
    Appointment,
    Customer,
    CustomerTag,
    Deal,
    FacebookLeadEvent,
    Interaction,
    OutboundMessage,
    OutcomeEvent,
    User,
)
from app.services.appointment_rules import lock_event_for_booking
from app.services.audit import record_audit
from app.services.tags import add_tag_to_customer

# Fields filled on the survivor from the loser only when the survivor's value is blank.
# Never applied when the survivor already has a non-blank value -- such cases are reported
# as conflicts instead (survivor always wins, loser's alternate value is preserved in the
# audit log, never silently discarded).
MERGEABLE_FIELDS = [
    "email",
    "phone",
    "company",
    "language",
    "lead_source",
    "form_id",
    "form_name",
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
]


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _customer_snapshot(c: Customer) -> dict:
    return {f: getattr(c, f) for f in ["name", *MERGEABLE_FIELDS, "stage"]}


@dataclass
class FieldConflict:
    field: str
    survivor_value: str | None
    loser_value: str | None


@dataclass
class BookingPair:
    event_id: str
    event_name: str | None
    survivor_appointment_id: str
    loser_appointment_id: str
    starts_at: str
    kind: str  # "identical" | "same_time_different_detail"
    detail: dict
    both_active: bool  # True when NEITHER side is cancelled -- the pair would otherwise double-book the slot


class MergeBlockedError(Exception):
    """Raised by merge_customers when the merge cannot safely proceed without manual review --
    currently: two different ACTIVE bookings for the same event/slot (same_time_different_detail,
    both_active). Carries the analysis so the caller can surface it to the user."""

    def __init__(self, analysis: "MergeAnalysis"):
        self.analysis = analysis
        super().__init__("Merge blocked: conflicting active bookings at the same event and slot")


@dataclass
class MergeAnalysis:
    survivor_id: str
    loser_id: str
    conflicts: list[FieldConflict] = field(default_factory=list)
    identical_bookings: list[BookingPair] = field(default_factory=list)
    divergent_bookings: list[BookingPair] = field(default_factory=list)

    @property
    def capacity_conflicts(self) -> list[BookingPair]:
        """Divergent (different status/notes/staff) pairs where BOTH sides are still active.
        These would leave the merged customer double-booked in the same slot -- not safe to
        auto-resolve (unlike an identical pair, which is unambiguously a duplicate), so the
        merge must be blocked until a human cancels one of the two bookings."""
        return [b for b in self.divergent_bookings if b.both_active]

    @property
    def fingerprint(self) -> str:
        payload = {
            "survivor_id": self.survivor_id,
            "loser_id": self.loser_id,
            "conflicts": [asdict(c) for c in self.conflicts],
            "identical_bookings": [asdict(b) for b in self.identical_bookings],
            "divergent_bookings": [asdict(b) for b in self.divergent_bookings],
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        return {
            "survivor_id": self.survivor_id,
            "loser_id": self.loser_id,
            "conflicts": [asdict(c) for c in self.conflicts],
            "identical_bookings": [asdict(b) for b in self.identical_bookings],
            "divergent_bookings": [asdict(b) for b in self.divergent_bookings],
            "capacity_conflicts": [asdict(b) for b in self.capacity_conflicts],
            "fingerprint": self.fingerprint,
        }


def analyse_merge(db: Session, *, survivor: Customer, loser: Customer) -> MergeAnalysis:
    """Read-only comparison of two customers -- never mutates anything."""
    conflicts: list[FieldConflict] = []
    for f in ["name", *MERGEABLE_FIELDS]:
        sv, lv = getattr(survivor, f), getattr(loser, f)
        if _blank(sv) or _blank(lv):
            continue
        if sv != lv:
            conflicts.append(FieldConflict(field=f, survivor_value=sv, loser_value=lv))

    survivor_appts = (
        db.query(Appointment).filter(Appointment.customer_id == survivor.id).all()
    )
    loser_appts = db.query(Appointment).filter(Appointment.customer_id == loser.id).all()

    identical: list[BookingPair] = []
    divergent: list[BookingPair] = []
    for sa_appt in survivor_appts:
        for la_appt in loser_appts:
            if sa_appt.event_id != la_appt.event_id or sa_appt.starts_at != la_appt.starts_at:
                continue
            same_detail = (
                sa_appt.status == la_appt.status
                and (sa_appt.notes or "") == (la_appt.notes or "")
                and sa_appt.assigned_user_id == la_appt.assigned_user_id
            )
            both_active = sa_appt.status != "cancelled" and la_appt.status != "cancelled"
            pair = BookingPair(
                event_id=str(sa_appt.event_id),
                event_name=sa_appt.event.name if sa_appt.event is not None else None,
                survivor_appointment_id=str(sa_appt.id),
                loser_appointment_id=str(la_appt.id),
                starts_at=sa_appt.starts_at.isoformat() if sa_appt.starts_at else "",
                kind="identical" if same_detail else "same_time_different_detail",
                detail={
                    "survivor_status": sa_appt.status,
                    "loser_status": la_appt.status,
                    "survivor_notes": sa_appt.notes,
                    "loser_notes": la_appt.notes,
                },
                both_active=both_active,
            )
            (identical if same_detail else divergent).append(pair)

    return MergeAnalysis(
        survivor_id=str(survivor.id),
        loser_id=str(loser.id),
        conflicts=conflicts,
        identical_bookings=identical,
        divergent_bookings=divergent,
    )


@dataclass
class MergeResult:
    filled_fields: list[str]
    analysis: MergeAnalysis
    cancelled_duplicate_appointment_ids: list[str] = field(default_factory=list)


def merge_customers(
    db: Session, *, survivor: Customer, loser: Customer, actor: User | None, analysis: MergeAnalysis
) -> MergeResult:
    """Mutating merge. Caller is responsible for: rejecting a self-merge, acquiring the ordered
    customer row locks and the affected event locks, and recomputing `analysis` fresh under
    those locks immediately before calling this (never a stale client-held analysis).

    Raises MergeBlockedError (nothing is mutated) if the two customers have different ACTIVE
    bookings at the same event and exact slot -- consolidating those automatically could silently
    discard whichever one turns out to be wrong, so a human must cancel one first. An identical
    active/active pair (same status/notes/staff -- an unambiguous duplicate) is instead
    auto-consolidated below: both appointments are preserved (never deleted, so history and any
    linked deal/notes survive), but the now-redundant one is cancelled so the merged customer
    never ends up occupying the same slot's capacity twice.
    """
    if analysis.capacity_conflicts:
        raise MergeBlockedError(analysis)

    before = {"survivor": _customer_snapshot(survivor), "loser": _customer_snapshot(loser)}

    db.query(Deal).filter(Deal.customer_id == loser.id).update(
        {Deal.customer_id: survivor.id}, synchronize_session=False
    )
    db.query(Interaction).filter(Interaction.customer_id == loser.id).update(
        {Interaction.customer_id: survivor.id}, synchronize_session=False
    )
    db.query(OutboundMessage).filter(OutboundMessage.customer_id == loser.id).update(
        {OutboundMessage.customer_id: survivor.id}, synchronize_session=False
    )
    db.query(OutcomeEvent).filter(OutcomeEvent.customer_id == loser.id).update(
        {OutcomeEvent.customer_id: survivor.id}, synchronize_session=False
    )
    db.query(FacebookLeadEvent).filter(FacebookLeadEvent.customer_id == loser.id).update(
        {FacebookLeadEvent.customer_id: survivor.id}, synchronize_session=False
    )
    # FacebookLeadEvent.deal_id references Deal.id directly; those Deal rows already had their
    # customer_id repointed to survivor above, so no separate deal_id reassignment is needed here.

    # Appointments are never deleted by a merge -- always reassigned first, regardless of whether
    # the analysis found an "identical" pairing. Preserves status/notes/assigned-staff/linked-deal
    # history.
    db.query(Appointment).filter(Appointment.customer_id == loser.id).update(
        {Appointment.customer_id: survivor.id}, synchronize_session=False
    )

    # Consolidate unambiguous active duplicates (same event, same exact slot, same status/notes/
    # staff on both sides) so the merge never leaves the customer double-booked -- occupying the
    # same slot's capacity twice -- while still preserving both rows: the redundant one (loser's,
    # now reassigned to survivor above) is cancelled rather than deleted, with a note recording
    # why. MergeBlockedError already guaranteed above that no *divergent* active/active pair
    # exists, so every remaining active/active pair here is a true, safe-to-collapse duplicate.
    cancelled_duplicate_appointment_ids: list[str] = []
    for pair in analysis.identical_bookings:
        if not pair.both_active:
            continue
        dup = db.get(Appointment, UUID(pair.loser_appointment_id))
        if dup is not None and dup.status != "cancelled":
            dup.status = "cancelled"
            dup.notes = ((dup.notes or "") + " [auto-cancelled: duplicate of another active booking in the same slot during customer merge]").strip()
            db.add(dup)
            cancelled_duplicate_appointment_ids.append(pair.loser_appointment_id)

    for ct in db.query(CustomerTag).filter(CustomerTag.customer_id == loser.id).all():
        if ct.tag is not None:
            add_tag_to_customer(db, customer=survivor, tag_name=ct.tag.name, color=ct.tag.color)
    db.query(CustomerTag).filter(CustomerTag.customer_id == loser.id).delete(synchronize_session=False)

    filled: list[str] = []
    if _blank(survivor.name) and not _blank(loser.name):
        survivor.name = loser.name
        filled.append("name")
    for f in MERGEABLE_FIELDS:
        if _blank(getattr(survivor, f)) and not _blank(getattr(loser, f)):
            setattr(survivor, f, getattr(loser, f))
            filled.append(f)
    db.add(survivor)

    record_audit(
        db,
        actor=actor,
        action="customer.merged",
        entity_type="customer",
        entity_id=survivor.id,
        before=before,
        after=_customer_snapshot(survivor),
        metadata={
            "loser_id": str(loser.id),
            "filled_fields": filled,
            "cancelled_duplicate_appointment_ids": cancelled_duplicate_appointment_ids,
            **analysis.as_dict(),
        },
    )

    db.delete(loser)
    return MergeResult(filled_fields=filled, analysis=analysis, cancelled_duplicate_appointment_ids=cancelled_duplicate_appointment_ids)


def lock_customers_ordered(db: Session, id_a: UUID, id_b: UUID) -> None:
    """Row-lock both customers in a fixed order (by string id) to avoid deadlocking against a
    concurrent reverse-direction merge of the same pair."""
    for cid in sorted([id_a, id_b], key=str):
        db.query(Customer).filter(Customer.id == cid).with_for_update().first()


def lock_affected_events(db: Session, *customer_ids: UUID) -> None:
    event_ids = {
        row[0]
        for row in db.query(Appointment.event_id)
        .filter(Appointment.customer_id.in_(customer_ids))
        .distinct()
        .all()
    }
    for event_id in sorted(event_ids, key=str):
        lock_event_for_booking(db, event_id)
