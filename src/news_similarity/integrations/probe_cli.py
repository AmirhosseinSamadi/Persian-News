"""CLI for isolated probes; defaults to a no-network configuration check."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import dotenv_values

from news_similarity.integrations.bot_probe import (
    MAX_BYTES,
    ProbeConfig,
    ProbeError,
    initial_report,
    live_probe,
    preview_updates,
)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(
            2,
            (
                "Invalid probe arguments. Use --help; credentials "
                "belong only in environment variables.\n"
            ),
        )


def sanitized_json(value, token=None):
    output = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    if token:
        output = output.replace(token, "[REDACTED]")
    return re.sub(r"[0-9]+:[A-Za-z0-9_-]{16,256}", "[REDACTED]", output)


def run_cli(platform: str, argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = SafeParser(
        description=(
            "Isolated experimental Bot API probe. Default: no "
            "network, no acknowledgement, no database writes."
        )
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--offline", type=Path)
    modes.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", default=".env.bot-probes")
    parser.add_argument("--chat-id", "--channel-id", dest="chat_ids", action="append")
    parser.add_argument("--exclusive-test-bot", action="store_true")
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Total request budget in seconds, not a continuous polling window.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=15,
        help="Timeout for one getUpdates request; queued updates can return early.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Inspect up to this many earliest unconfirmed updates (maximum 100).",
    )
    args = parser.parse_args(argv)
    token = None
    try:
        values = {**dotenv_values(args.env_file, interpolate=False), **os.environ}
        prefix = platform.upper()
        token = (values.get(prefix + "_BOT_TOKEN") or "").strip() or None
        key = prefix + (
            "_BOT_CHANNEL_IDS" if platform == "telegram" else "_BOT_CHAT_IDS"
        )
        identifiers = (
            args.chat_ids
            if args.chat_ids is not None
            else (values.get(key) or "").split(",")
        )
        ids = frozenset(
            str(int(value.strip())) for value in identifiers if value.strip()
        )
        config = ProbeConfig(
            platform, token, ids, args.duration, args.poll_seconds, args.limit
        )
        if args.offline:
            if args.offline.stat().st_size > MAX_BYTES:
                raise ProbeError("Offline fixture too large.")
            document = json.loads(args.offline.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("ok") is not True:
                raise ProbeError("Invalid offline API envelope.")
            report = preview_updates(config, document["result"])
            report["provenance"] = "Offline supplied payload; never live evidence."
            report["synthetic"] = document.get("synthetic") is True
        elif args.live:
            report = live_probe(config, exclusive_test_bot=args.exclusive_test_bot)
        else:
            report = initial_report(config, "dry-run")
            report.update(
                status="DOCUMENTED_ONLY" if token and ids else "BLOCKED",
                token_configured=bool(token),
                authorized_ids_configured=bool(ids),
                reason=(
                    "No network requests made. Live verification "
                    "requires dedicated bot credentials and "
                    "authorized chat IDs."
                ),
            )
    except (ProbeError, ValueError, OSError, KeyError, TypeError, OverflowError):
        report = {
            "platform": platform,
            "status": "BLOCKED",
            "live_verified": False,
            "reason": (
                "Invalid/missing configuration, unreadable offline "
                "fixture or unsupported payload. Tokens and raw "
                "errors are withheld."
            ),
            "network_requests": 0,
            "production_database_written": False,
        }
    print(sanitized_json(report, token))
    return 2 if report["status"] == "BLOCKED" else 0
