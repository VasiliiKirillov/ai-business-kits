"""sqlite: лиды, сообщения, брони (брони нужны локальному источнику данных)."""
import json
import os
import sqlite3
from pathlib import Path

DB = Path(os.getenv("DB_PATH") or "intake.db")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("""create table if not exists leads(
        id integer primary key, created text default (datetime('now')),
        channel text, client_id text, client_name text, text text, model text, data text, status text)""")
    c.execute("""create table if not exists messages(
        id integer primary key, created text default (datetime('now')),
        client_id text, role text, text text)""")
    c.execute("""create table if not exists bookings(
        id text primary key, item text, start text, end text, client text, contact text, phone text,
        total real, status text, document text, created text default (datetime('now')), data text)""")
    return c


def add(channel, client_id, client_name, text, model, data, status) -> int:
    with conn() as c:
        return c.execute("insert into leads(channel,client_id,client_name,text,model,data,status) values(?,?,?,?,?,?,?)",
                         (channel, client_id, client_name, text, model, json.dumps(data, ensure_ascii=False), status)).lastrowid


def get(lead_id):
    with conn() as c:
        return c.execute("select * from leads where id=?", (lead_id,)).fetchone()


def set_status(lead_id, status):
    with conn() as c:
        c.execute("update leads set status=? where id=?", (status, lead_id))


def update_data(lead_id, data):
    with conn() as c:
        c.execute("update leads set data=? where id=?", (json.dumps(data, ensure_ascii=False), lead_id))


def log_msg(client_id, role, text):
    with conn() as c:
        c.execute("insert into messages(client_id,role,text) values(?,?,?)", (client_id, role, text))


# --- брони
def next_booking_id() -> str:
    with conn() as c:
        n = c.execute("select count(*) from bookings").fetchone()[0]
        ids = {r[0] for r in c.execute("select id from bookings")}
    while f"BK-{n + 1:04d}" in ids:
        n += 1
    return f"BK-{n + 1:04d}"


def add_booking(b: dict) -> str:
    with conn() as c:
        c.execute("insert into bookings(id,item,start,end,client,contact,phone,total,status,document,data) values(?,?,?,?,?,?,?,?,?,?,?)",
                  (b["id"], b.get("item"), b.get("start"), b.get("end"), b.get("client_name"), b.get("contact"),
                   b.get("phone"), b.get("total"), b.get("status", "подтверждена"), b.get("document", ""),
                   json.dumps({**(b.get("fields") or {}), "doc": b.get("doc") or {}}, ensure_ascii=False)))
    return b["id"]


def bookings() -> list[dict]:
    with conn() as c:
        rows = c.execute("select * from bookings order by created, id").fetchall()
    return [{**dict(r), "data": json.loads(r["data"] or "{}")} for r in rows]


def set_booking_status(booking_id, status):
    with conn() as c:
        c.execute("update bookings set status=? where id=?", (status, booking_id))
