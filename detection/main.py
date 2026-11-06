"""Translate the supported Sigma equality selection into parameterized SQLite queries."""
import json, sqlite3
from pathlib import Path
import yaml
ROOT=Path(__file__).parent
FIELDS={'event_type','user','source_ip','process','command_line','outcome'}
def compile_rule(rule):
    if not rule.get('id') or not rule.get('falsepositives') or not any(t.startswith('attack.t') for t in rule.get('tags',[])): raise ValueError('missing rule metadata')
    detection=rule['detection']; selection=detection['selection']
    if detection.get('condition') != 'selection' or not selection: raise ValueError('unsupported condition')
    clauses=[]; args=[]
    for field,value in selection.items():
        if field not in FIELDS or not isinstance(value,str): raise ValueError('unsupported selection')
        clauses.append('"'+field+'" = ?'); args.append(value)
    return 'SELECT id FROM events WHERE '+' AND '.join(clauses),args

def evaluate():
    samples=json.loads((ROOT/'samples.json').read_text()); db=sqlite3.connect(':memory:'); db.execute('CREATE TABLE events(id TEXT, event_type TEXT, user TEXT, source_ip TEXT, process TEXT, command_line TEXT, outcome TEXT)')
    for event in samples: db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?)',tuple(event.get(k,'') for k in ('id','event_type','user','source_ip','process','command_line','outcome')))
    coverage=[]
    for path in sorted((ROOT/'rules').glob('*.yml')):
        rule=yaml.safe_load(path.read_text()); sql,args=compile_rule(rule); hits={r[0] for r in db.execute(sql,args)}; expected={x['id'] for x in samples if rule['id'] in x['labels']}; tp=len(hits & expected); precision=tp/len(hits) if hits else 0; recall=tp/len(expected) if expected else 0
        if not expected or not (set(x['id'] for x in samples)-expected): raise ValueError('each rule needs positive and negative samples')
        coverage.append((rule['title'],rule['tags'][0],precision,recall)); assert hits==expected, (rule['id'],hits,expected)
    (ROOT/'coverage.md').write_text('# ATT&CK coverage\n\n| Rule | Technique | Precision | Recall |\n|---|---|---:|---:|\n'+''.join(f'| {title} | {tag} | {p:.2f} | {r:.2f} |\n' for title,tag,p,r in coverage))
    return coverage
if __name__=='__main__': print(evaluate())
