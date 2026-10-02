"""Command line: python -m app.cli <command>"""
import argparse
import json
from pathlib import Path

from app.db import SessionLocal, init_db
from app.settings_store import get_status_map


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="створити таблиці")
    sub.add_parser("seed", help="завантажити стартові дані з data/seed.json")
    m = sub.add_parser("sync-meta", help="завантажити статистику з Meta Ads")
    m.add_argument("--days", type=int, default=90)
    c = sub.add_parser("import-crm", help="імпорт замовлень LP-CRM з CSV")
    c.add_argument("file")
    s = sub.add_parser("sync-crm", help="завантажити замовлення через API LP-CRM (неперевірений метод)")
    s.add_argument("--days", type=int, default=90)
    s.add_argument("--method", default="getOrdersByTime")
    p = sub.add_parser("lpcrm-probe", help="перевірити API LP-CRM і показати сиру відповідь")
    p.add_argument("--method", default="getOrdersByTime")
    p.add_argument("--days", type=int, default=1)
    args = ap.parse_args(argv)

    init_db()
    db = SessionLocal()
    try:
        out: dict
        if args.cmd == "init-db":
            out = {"ok": True}
        elif args.cmd == "seed":
            from app.seed import load_seed
            out = load_seed(db)
        elif args.cmd == "sync-meta":
            from app.collectors.meta_ads import sync
            out = sync(db, days=args.days)
        elif args.cmd == "import-crm":
            from app.collectors.lpcrm import import_csv
            out = import_csv(db, Path(args.file).read_bytes(), get_status_map(db))
        elif args.cmd == "sync-crm":
            from app.collectors.lpcrm import LpCrmClient, sync_api
            out = sync_api(db, get_status_map(db), days=args.days, client=LpCrmClient(orders_method=args.method))
        elif args.cmd == "lpcrm-probe":
            from datetime import datetime, timedelta

            from app.collectors.lpcrm import LpCrmClient
            cl = LpCrmClient(orders_method=args.method)
            now = datetime.now()
            body = cl.call(args.method, created_from=(now - timedelta(days=args.days)).strftime("%Y-%m-%d %H:%M:%S"),
                           created_to=now.strftime("%Y-%m-%d %H:%M:%S"))
            out = {"raw_response_preview": json.dumps(body, ensure_ascii=False)[:3000]}
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    except Exception as e:  # readable errors for operators
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        raise SystemExit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
