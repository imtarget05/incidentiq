#!/usr/bin/env python3
"""Local-only warehouse commands unless explicit source credentials are supplied."""
import argparse
from datetime import datetime,timezone
import os
import sys
from pipeline import Warehouse,window_start
from sources import enterprise_documents,d1_events


def timestamp(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError('Timestamp must include timezone')
    return parsed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','export','secure'])
    parser.add_argument('--source',choices=['enterprise','incidentiq'])
    parser.add_argument('--start',type=timestamp)
    parser.add_argument('--until',type=timestamp)
    parser.add_argument('--source-timezone',help='Required for Enterprise naive operational timestamps')
    args=parser.parse_args()
    if bool(args.start) != bool(args.until):
        parser.error('Backfill requires both --start and --until')
    try:
        wh=Warehouse(os.environ['ANALYTICS_DSN'])
        if args.action=='init':
            wh.initialize();return 0
        if args.action=='secure':
            wh.secure_reads();return 0
        if not args.source:
            parser.error('--source is required for export')
        until=args.until or datetime.now(timezone.utc)
        start=args.start or window_start(wh.checkpoint(args.source))
        if start>=until:
            parser.error('--start must precede --until')
        if args.source=='enterprise':
            if not args.source_timezone:
                parser.error('--source-timezone is required; use actual deployment timezone')
            records=enterprise_documents(os.environ['ENTERPRISE_SOURCE_DSN'],start,until,args.source_timezone)
        else:
            records=d1_events(os.environ['CLOUDFLARE_ACCOUNT_ID'],os.environ['CLOUDFLARE_D1_DATABASE_ID'],
                              os.environ['CLOUDFLARE_ANALYTICS_READ_TOKEN'],start,until)
        count=wh.load(args.source,records,until,backfill=args.start is not None)
        print(f'Committed {count} normalized source rows; backfill={args.start is not None}')
        return 0
    except Exception as exc:
        # DB/HTTP exceptions can contain credentials, SQL or request payload.
        print(f'Analytics command failed ({type(exc).__name__}); checkpoint unchanged on rollback. Check configuration privately.',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
