import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
app=FastAPI()
engine=create_engine(os.environ.get('DATABASE_URL','sqlite:///./telemetry.db'))
class Pass(BaseModel):
    satellite: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    elevation: float = Field(ge=0,le=90)
@app.on_event('startup')
def setup():
    with engine.begin() as c: c.execute(text('CREATE TABLE IF NOT EXISTS passes (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, satellite VARCHAR(100) NOT NULL, observed_at TIMESTAMP NOT NULL, elevation FLOAT NOT NULL)' if engine.dialect.name == 'postgresql' else 'CREATE TABLE IF NOT EXISTS passes (id INTEGER PRIMARY KEY, satellite VARCHAR(100) NOT NULL, observed_at TIMESTAMP NOT NULL, elevation FLOAT NOT NULL)'))
@app.get('/health')
def health(): return {'ok':True}
@app.post('/passes',status_code=201)
def ingest(record: Pass):
    with engine.begin() as c: c.execute(text('INSERT INTO passes (satellite,observed_at,elevation) VALUES (:satellite,:observed_at,:elevation)'),record.dict())
    return record
@app.get('/passes')
def query(satellite: str = ''):
    with engine.connect() as c: return [dict(r._mapping) for r in c.execute(text('SELECT * FROM passes WHERE (:satellite = \'\' OR satellite = :satellite) ORDER BY observed_at DESC LIMIT 100'),{'satellite':satellite})]
