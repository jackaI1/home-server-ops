import sqlite3
from datetime import datetime, timezone, timedelta
from inventory.main import matches, rank, snapshots, findings
from helpdesk.main import connect, add, report, flags
from soar.main import triage, deduplicate, sweep, HttpIntelClient
from detection.main import evaluate

def test_matching_ranking():
    assert matches('cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*','cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*')
    assert not matches('cpe:2.3:a:other:log4j:2.14.1:*:*:*:*:*:*:*','cpe:2.3:a:apache:log4j:*:*:*:*:*:*:*:*')
    assert rank(9.8,True,'high') > rank(9.8,False,'low')
    nvd, kev = snapshots()
    assets=[{'id':'ok','owner':'x','environment':'home','criticality':'high'}, {'id':'missing','owner':'','environment':'home','criticality':'high'}]
    scans=[{'asset_id':x['id'],'cpe':'cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*'} for x in assets]
    rows, missing=findings(assets,scans,nvd,kev,{})
    assert any(x['asset']=='ok' and x['cve']=='CVE-2021-44228' for x in rows)
    assert missing==['missing'] and all(x['asset']!='missing' for x in rows)
    rows, _=findings(assets,scans,nvd,kev,{'ok:CVE-2021-44228':{'status':'closed','date':'2026-11-06'}})
    assert any(x['status']=='closed' and x['date']=='2026-11-06' for x in rows)

def test_tickets(tmp_path):
    db=connect(str(tmp_path/'db')); now=datetime.now(timezone.utc)-timedelta(hours=10)
    assert add(db,'','','')['missing']; a=add(db,'Outage','Cannot login','a',now.isoformat()); b=add(db,'Printer','broken','b',now.isoformat()); assert a['queue'] != b['queue']; assert add(db,'Outage','again','a')['duplicate']==a['id']
    rows=report(db); urgent=next(r for r in rows if r['queue']==a['queue']); assert urgent['sla_met']==0 and urgent['backlog']==1
    assert 'aging' in flags(db.execute('SELECT * FROM tickets WHERE id=?',(a['id'],)).fetchone())

def test_soar():
    class Client:
        def lookup(self,kind,value): return {'verdict':'malicious' if value=='bad' else 'unknown','confidence':.95 if value=='bad' else 0,'source':'test'}
    a={'id':'1','severity':5,'iocs':[{'type':'ip','value':'bad'}]}; b={'id':'2','severity':1,'iocs':[{'type':'domain','value':'unknown'}]}
    assert triage(a,Client())['route']=='escalate'; assert triage(b,Client())['route']=='ask-a-human'; assert len(deduplicate([a,a]))==1; assert sweep(['bad connection'],['bad'])

def test_detection():
    assert len(evaluate())==2

def test_http_enrichment():
    import io
    def open_mock(url, timeout):
        assert 'type=hash' in url and timeout == 5
        return io.BytesIO(b'{"verdict":"benign","confidence":0.99,"source":"fixture"}')
    client=HttpIntelClient('https://example.test/lookup', open_mock)
    result=triage({'id':'x','severity':1,'iocs':[{'type':'hash','value':'abc'}]}, client)
    assert result['route']=='close' and result['evidence'][0]['source']=='fixture'
    def failed(url, timeout): raise OSError('offline')
    assert triage({'id':'x','iocs':[{'type':'ip','value':'192.0.2.1'}]}, HttpIntelClient('https://example.test',failed))['route']=='ask-a-human'
