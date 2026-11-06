"""Evidence-based alert triage with a pluggable intelligence client."""
import hashlib, json
from urllib.parse import urlencode
from urllib.request import urlopen
from pathlib import Path
class IntelClient:
    def lookup(self, kind, value):
        return {'verdict':'unknown','confidence':0,'source':'no provider configured'}

class HttpIntelClient:
    """A JSON intelligence endpoint returning verdict, confidence and source."""
    def __init__(self, endpoint, opener=urlopen):
        self.endpoint, self.opener = endpoint, opener
    def lookup(self, kind, value):
        try:
            with self.opener(self.endpoint + '?' + urlencode({'type': kind, 'value': value}), timeout=5) as response:
                data = json.load(response)
            confidence = float(data['confidence'])
            if data['verdict'] not in ('malicious', 'benign', 'unknown') or not 0 <= confidence <= 1: raise ValueError('invalid response')
            return {'verdict': data['verdict'], 'confidence': confidence, 'source': data['source']}
        except (OSError, ValueError, KeyError, TypeError):
            return {'verdict': 'unknown', 'confidence': 0, 'source': 'provider unavailable or invalid'}

def triage(alert, client, summarizer=None):
    evidence = [dict(ioc=ioc, **client.lookup(ioc['type'], ioc['value'])) for ioc in alert['iocs']]
    bad = [e for e in evidence if e['verdict']=='malicious' and e['confidence'] >= .8]
    uncertain = any(e['verdict']=='unknown' or e['confidence'] < .8 for e in evidence)
    score = min(100, int(alert.get('severity', 0)*10 + 40*bool(bad)))
    route = 'escalate' if bad else ('ask-a-human' if uncertain or not evidence else 'close')
    result = {'id':alert['id'], 'score':score, 'route':route, 'evidence':evidence}
    if summarizer: result['summary'] = summarizer(alert, evidence)
    return result

def deduplicate(alerts):
    seen=set(); result=[]
    for a in alerts:
        key=hashlib.sha256(json.dumps(sorted((i['type'],i['value']) for i in a['iocs'])).encode()).hexdigest()
        if key not in seen: result.append(a); seen.add(key)
    return result

def sweep(logs, iocs):
    return [{'line': n, 'ioc': i} for n,line in enumerate(logs,1) for i in iocs if i in line]
if __name__=='__main__':
    for alert in deduplicate(json.loads((Path(__file__).parent/'alerts.json').read_text())): print(json.dumps(triage(alert,IntelClient())))
