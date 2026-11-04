"""One additive checkpoint table: inbox, outcomes and news share transactions."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import String, Text, inspect, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from news_similarity.database.models import News, UTCDateTime
from news_similarity.integrations.bot_probe import MAX_BYTES, ProbeError

SAFE = {"stored", "duplicate", "skipped_non_text"}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(",", ":")
    )


class BotBase(DeclarativeBase):
    pass


class BotCheckpoint(BotBase):
    __tablename__ = "bot_checkpoints"

    platform: Mapped[str] = mapped_column(String(32), primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(64))
    next_offset: Mapped[int | None] = mapped_column(nullable=True)
    state: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class BotStorage:
    def __init__(self, repository):
        self.repository = repository

    def initialize(self):
        self.repository.initialize()
        BotBase.metadata.create_all(self.repository.engine)

    @staticmethod
    def _scope(config):
        return hashlib.sha256(
            canonical(sorted(config.authorized_ids)).encode()
        ).hexdigest()

    def _row(self, session, collector, bot_id):
        identity = (collector.platform, str(bot_id))
        row = session.get(BotCheckpoint, identity)
        if row is None:
            row = BotCheckpoint(
                platform=identity[0],
                bot_id=identity[1],
                scope=self._scope(collector.config),
                next_offset=None,
                state=canonical({"inbox": [], "acknowledged_offset": None}),
                status="NEW",
                updated_at=datetime.now(UTC),
            )
            session.add(row)
        elif row.scope != self._scope(collector.config):
            raise ProbeError(
                "Checkpoint authorized scope changed; migration/review required."
            )
        return row

    def _save_item(self, session, item):
        source = self.repository._get_or_create_source(
            session, item.platform, item.channel_id, item.channel_name, None
        )
        existing = session.scalar(
            select(News).where(
                News.source_id == source.id, News.external_id == item.message_id
            )
        )
        if existing is not None:
            if existing.text != item.text or existing.published_at != item.published_at:
                return "blocked_message_identity_conflict"
            return "duplicate"
        session.execute(
            insert(News).values(
                source_id=source.id,
                external_id=item.message_id,
                text=item.text,
                published_at=item.published_at,
                url=item.url,
            )
        )
        return "stored"

    def ingest(
        self, collector, bot_id, updates, *, process=True, acknowledged_offset=None
    ):
        if not isinstance(updates, list) or len(updates) > 100:
            raise ProbeError("Invalid update batch; no acknowledgement permitted.")
        counts = {"inserted": 0, "duplicates": 0, "duplicate_updates": 0, "skipped": 0}
        with Session(self.repository.engine) as session, session.begin():
            row = self._row(session, collector, bot_id)
            state = json.loads(row.state)
            inbox = state["inbox"]
            if acknowledged_offset is not None:
                if any(
                    e["id"] is None or e["outcome"] not in SAFE
                    for e in inbox
                    if e["id"] is None or e["id"] < acknowledged_offset
                ):
                    raise ProbeError("Unsafe checkpoint acknowledgement boundary.")
                inbox = [e for e in inbox if e["id"] >= acknowledged_offset]
                state["acknowledged_offset"] = acknowledged_offset
                state.pop("ack_intent", None)
            previous = None
            for update in updates:
                identifier = (
                    update.get("update_id") if isinstance(update, dict) else None
                )
                if type(identifier) is not int or identifier < 0:
                    identifier = None
                    state["sequence_error"] = True
                elif previous is not None and identifier not in {
                    previous,
                    previous + 1,
                }:
                    state["sequence_error"] = True
                previous = identifier
                digest = hashlib.sha256(canonical(update).encode()).hexdigest()
                same = next((e for e in inbox if e["digest"] == digest), None)
                if same is not None:
                    counts["duplicate_updates"] += 1
                    if same["outcome"] in {"stored", "duplicate"}:
                        counts["duplicates"] += 1
                    continue
                conflict = [
                    e for e in inbox if identifier is not None and e["id"] == identifier
                ]
                for entry in conflict:
                    entry["outcome"] = "blocked_update_id_conflict"
                confirmed = state.get("acknowledged_offset")
                regressed = (
                    identifier is not None
                    and confirmed is not None
                    and identifier < confirmed
                )
                outcome = (
                    "blocked_update_id_conflict"
                    if conflict
                    else "blocked_cursor_regression"
                    if regressed
                    else "blocked_malformed"
                    if identifier is None
                    else "pending"
                )
                inbox.append(
                    {
                        "id": identifier,
                        "digest": digest,
                        "raw": update,
                        "outcome": outcome,
                    }
                )
            budget = collector.config.limit
            if process:
                for entry in inbox:
                    if entry["outcome"] != "pending" or budget <= 0:
                        continue
                    budget -= 1
                    outcome, item = collector.classify(entry["raw"])
                    if item is not None:
                        outcome = self._save_item(session, item)
                    entry["outcome"] = outcome
                    if outcome == "stored":
                        counts["inserted"] += 1
                    elif outcome == "duplicate":
                        counts["duplicates"] += 1
                    elif outcome == "skipped_non_text":
                        counts["skipped"] += 1
            state["inbox"] = inbox
            state["evidence_origin"] = (
                "live_http" if collector.real_transport else "mocked"
            )
            candidate = None
            ids = [entry["id"] for entry in inbox]
            if (
                not state.get("sequence_error")
                and None not in ids
                and len(set(ids)) == len(ids)
            ):
                for entry in sorted(inbox, key=lambda e: e["id"]):
                    if entry["outcome"] not in SAFE:
                        break
                    candidate = entry["id"] + 1
            state_text = canonical(state)
            if len(inbox) > 1000 or len(state_text.encode()) > 2 * MAX_BYTES:
                raise ProbeError(
                    "Durable inbox capacity reached; operator review required."
                )
            row.next_offset, row.state = candidate, state_text
            row.status = (
                "ACK_UNKNOWN"
                if state.get("ack_intent") is not None
                else "BLOCKED"
                if state.get("sequence_error")
                or any(e["outcome"].startswith("blocked_") for e in inbox)
                else "ACKNOWLEDGED"
                if acknowledged_offset is not None
                else "STORED"
            )
            row.updated_at = datetime.now(UTC)
            result = {
                **counts,
                "status": row.status,
                "next_offset": candidate,
                "pending_updates": len(inbox),
                "blocked_updates": sum(
                    e["outcome"].startswith("blocked_") for e in inbox
                ),
                "sequence_error": bool(state.get("sequence_error")),
            }
        return result

    def mark(self, platform, bot_id, status, *, intent=None):
        with Session(self.repository.engine) as session, session.begin():
            row = session.get(BotCheckpoint, (platform, str(bot_id)))
            if row is None:
                raise ProbeError("Checkpoint is missing.")
            state = json.loads(row.state)
            if intent is not None:
                if row.next_offset != intent:
                    raise ProbeError(
                        "Acknowledgement does not match committed checkpoint."
                    )
                state["ack_intent"] = intent
            row.status, row.state, row.updated_at = (
                status,
                canonical(state),
                datetime.now(UTC),
            )

    def status(self):
        if not inspect(self.repository.engine).has_table("bot_checkpoints"):
            return []
        with Session(self.repository.engine) as session:
            rows = session.scalars(
                select(BotCheckpoint).order_by(BotCheckpoint.platform)
            )
            result = []
            for row in rows:
                state = json.loads(row.state)
                result.append(
                    {
                        "platform": row.platform,
                        "collector_ref": hashlib.sha256(
                            f"{row.platform}:{row.bot_id}".encode()
                        ).hexdigest()[:12],
                        "status": row.status,
                        "next_offset": row.next_offset,
                        "acknowledged_offset": state.get("acknowledged_offset"),
                        "ack_intent": state.get("ack_intent"),
                        "sequence_error": bool(state.get("sequence_error")),
                        "evidence_origin": state.get("evidence_origin"),
                        "pending_updates": len(state["inbox"]),
                        "blocked_updates": sum(
                            e["outcome"].startswith("blocked_") for e in state["inbox"]
                        ),
                        "blocked": [
                            {"update_id": e["id"], "reason": e["outcome"]}
                            for e in state["inbox"]
                            if e["outcome"].startswith("blocked_")
                        ],
                        "updated_at": row.updated_at.isoformat(),
                    }
                )
            return result
