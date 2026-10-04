"""CLI: python -m u5g_sms {send,inbox,sim} ...

Connection comes from the environment: U5G_HOST, U5G_USER, U5G_JUMP, U5G_ICCID.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .client import U5GClient, U5GError, split_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="u5g_sms")
    sub = parser.add_subparsers(dest="cmd", required=True)
    send = sub.add_parser("send", help="send an SMS")
    send.add_argument("to", help="E.164 number, e.g. +48123456789")
    send.add_argument("text")
    send.add_argument("--dry-run", action="store_true", help="print the parts without sending")
    sub.add_parser("inbox", help="list messages uiwwand currently holds")
    sub.add_parser("sim", help="show the active SIM state")
    args = parser.parse_args(argv)

    if args.cmd == "send" and args.dry_run:
        for part in split_text(args.text):
            print(f"{len(part.encode()):>2} B | {part}")
        return 0

    host = os.environ.get("U5G_HOST")
    if not host:
        parser.error("U5G_HOST is not set")
    client = U5GClient(
        host=host,
        user=os.environ.get("U5G_USER", "root"),
        jump=os.environ.get("U5G_JUMP") or None,
        iccid=os.environ.get("U5G_ICCID") or None,
    )
    try:
        if args.cmd == "send":
            print(f"sent {client.send(args.to, args.text)} part(s)")
        elif args.cmd == "inbox":
            print(json.dumps(client.inbox(), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(client.sim_state(), indent=2, ensure_ascii=False))
    except U5GError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
