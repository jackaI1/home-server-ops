"""Upload rule documents by stable ID; repeated PUTs replace the same documents."""
import json, sys
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
import yaml
from main import compile_rule

endpoint=sys.argv[1].rstrip('/')
for path in sorted((Path(__file__).parent/'rules').glob('*.yml')):
    rule=yaml.safe_load(path.read_text()); compile_rule(rule)
    request=Request(endpoint+'/home-detection-rules/_doc/'+quote(rule['id'],safe=''),data=json.dumps(rule).encode(),headers={'Content-Type':'application/json'},method='PUT')
    with urlopen(request,timeout=10) as response:
        if response.status not in (200,201): raise RuntimeError('rule upload failed')
