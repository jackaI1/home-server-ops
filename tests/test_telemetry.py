import os
os.environ['DATABASE_URL']='sqlite://'
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from telemetry import main

def test_ingest_and_query():
    main.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    with TestClient(main.app) as c:
        assert c.post('/passes',json={'satellite':'demo','observed_at':'2025-01-01T00:00:00','elevation':91}).status_code==422
        assert c.post('/passes',json={'satellite':'demo','observed_at':'2025-01-01T00:00:00','elevation':45}).status_code==201
        assert len(c.get('/passes?satellite=demo').json())==1
        assert c.get('/passes?satellite=other').json()==[]
