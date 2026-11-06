"""SQLite-backed triage and queue-level SLA reporting."""
import argparse, csv, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

RULES = json.loads((Path(__file__).parent / 'rules.json').read_text())
def connect(path):
    db = sqlite3.connect(path); db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY, subject TEXT, description TEXT, requester TEXT, category TEXT, priority TEXT, queue TEXT, created TEXT, updated TEXT, status TEXT)'); return db

def classify(subject, description):
    text = (subject + ' ' + description).lower()
    for rule in RULES['rules']:
        if any(word in text for word in rule['keywords']): return rule['category'], rule['priority']
    return 'general', 'normal'

def route(db):
    counts = {name: db.execute("SELECT count(*) FROM tickets WHERE queue=? AND status != 'closed'", (name,)).fetchone()[0] for name in RULES['queues']}
    return min(counts, key=lambda name: (counts[name], name))

def duplicate(db, subject, requester):
    return db.execute("SELECT id FROM tickets WHERE lower(trim(subject))=lower(trim(?)) AND lower(trim(requester))=lower(trim(?)) AND status != 'closed'", (subject, requester)).fetchone()

def add(db, subject, description, requester, now=None):
    missing = [key for key, val in [('subject', subject), ('description', description), ('requester', requester)] if not val.strip()]
    if missing: return {'missing': missing, 'follow_up': 'Please provide: ' + ', '.join(missing) + '.'}
    dup = duplicate(db, subject, requester)
    if dup: return {'duplicate': dup['id']}
    category, priority = classify(subject, description); queue = route(db); now = now or datetime.now(timezone.utc).isoformat()
    cur = db.execute('INSERT INTO tickets(subject,description,requester,category,priority,queue,created,updated,status) VALUES(?,?,?,?,?,?,?,?,?)', (subject,description,requester,category,priority,queue,now,now,'open')); db.commit(); return {'id': cur.lastrowid, 'queue': queue}

def report(db, now=None):
    now = now or datetime.now(timezone.utc); result = []
    for queue in RULES['queues']:
        rows = db.execute('SELECT * FROM tickets WHERE queue=?', (queue,)).fetchall(); met = 0; backlog = 0
        for row in rows:
            end = datetime.fromisoformat(row['updated']) if row['status'] == 'closed' else now
            hours = (end - datetime.fromisoformat(row['created'])).total_seconds()/3600
            met += hours <= RULES['sla_hours'][row['priority']]; backlog += row['status'] != 'closed'
        result.append({'queue': queue, 'volume': len(rows), 'backlog': backlog, 'sla_met': met, 'sla_percent': round(100*met/len(rows), 1) if rows else 0})
    return result

def flags(row, now=None):
    now = now or datetime.now(timezone.utc); age = (now - datetime.fromisoformat(row['created'])).total_seconds()/3600; idle = (now - datetime.fromisoformat(row['updated'])).total_seconds()/3600
    return [name for name, condition in [('unassigned', not row['queue']), ('aging', age > RULES['sla_hours'][row['priority']]), ('stalled', idle > 24)] if condition and row['status'] != 'closed']

def main():
    p=argparse.ArgumentParser(); p.add_argument('--db', default='tickets.db'); sub=p.add_subparsers(dest='cmd', required=True); a=sub.add_parser('add'); a.add_argument('--subject', default=''); a.add_argument('--description', default=''); a.add_argument('--requester', default=''); sub.add_parser('report'); sub.add_parser('serve'); u=sub.add_parser('update'); u.add_argument('id',type=int); u.add_argument('--status',choices=['open','closed'],required=True); x=p.parse_args(); db=connect(x.db)
    if x.cmd=='add': print(json.dumps(add(db,x.subject,x.description,x.requester)))
    elif x.cmd=='update':
        cur=db.execute('UPDATE tickets SET status=?, updated=? WHERE id=?', (x.status, datetime.now(timezone.utc).isoformat(), x.id)); db.commit()
        if not cur.rowcount: p.error('ticket not found')
        print(json.dumps({'id': x.id, 'status': x.status}))
    elif x.cmd=='serve':
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from html import escape
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                rows=db.execute('SELECT * FROM tickets ORDER BY created').fetchall(); body='<h1>Ticket queue</h1>'+''.join('<p>'+escape(f"{r['id']}: {r['subject']} ({r['queue']}) {', '.join(flags(r))}")+'</p>' for r in rows); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(body.encode())
        HTTPServer(('127.0.0.1',8000),Handler).serve_forever()
    else:
        rows=report(db)
        with open('sla.csv','w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
        from openpyxl import Workbook
        wb=Workbook(); ws=wb.active; ws.append(list(rows[0])); [ws.append(list(r.values())) for r in rows]; wb.save('sla.xlsx'); print(json.dumps(rows))
if __name__=='__main__': main()
