from __future__ import annotations
from datetime import datetime, date, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
import re

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)

def utc(v):
    if not isinstance(v,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z',v): raise ValueError('canonical UTC timestamp required')
    d=datetime.strptime(v,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    if not 1970<=d.year<=2399: raise ValueError('timestamp outside supported calendar')
    return v

def day(v):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v): raise ValueError('ISO date required')
    d=date.fromisoformat(v)
    if not 1970<=d.year<=2399: raise ValueError('date outside supported calendar')
    return v

def now(): return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def csv_bytes(obj,fields):
    return (','.join(fields)+'\n'+','.join(str(getattr(obj,k)) for k in fields)+'\n').encode('ascii')

class Scenario(Strict):
    scenario_id:int=Field(1,ge=1,le=10**12)
    observed_at:str; ingested_at:str; decision_at:str
    arrival:str; departure:str
    adults:int=Field(ge=1,le=8); children:int=Field(0,ge=0,le=8)
    max_rooms:int=Field(1,ge=1,le=4); min_properties:int=Field(3,ge=3,le=32)
    target_bps:int=Field(5000,ge=0,le=10000); curve:Literal['linear','quadratic']='linear'
    currency:Literal['EUR']='EUR'; max_age_days:int=Field(7,ge=0,le=365)
    search_budget:int=Field(20000,ge=1,le=1_000_000)
    @field_validator('observed_at','ingested_at','decision_at')
    @classmethod
    def clocks(cls,v): return utc(v)
    @field_validator('arrival','departure')
    @classmethod
    def dates(cls,v): return day(v)
    @model_validator(mode='after')
    def chronology(self):
        if self.max_rooms>self.adults or not self.observed_at<=self.ingested_at<=self.decision_at or not self.decision_at[:10]<=self.arrival<self.departure: raise ValueError('invalid scenario chronology')
        return self
    def csv(self): return csv_bytes(self,type(self).model_fields)
class Valuation(Strict):
    valuation_id:int=Field(1,ge=1,le=10**12)
    observed_at:str; ingested_at:str; currency:Literal['EUR']='EUR'
    current_cents:int=Field(ge=0,le=10**12); floor_cents:int=Field(ge=0,le=10**12); cap_cents:int=Field(ge=0,le=10**12)
    max_move_cents:int=Field(ge=0,le=10**12); shortcut_cents:int=Field(0,ge=0,le=10**12)
    @field_validator('observed_at','ingested_at')
    @classmethod
    def clocks(cls,v): return utc(v)
    @model_validator(mode='after')
    def bounds(self):
        if self.observed_at>self.ingested_at or self.floor_cents>self.cap_cents: raise ValueError('invalid valuation')
        return self
    def csv(self): return csv_bytes(self,type(self).model_fields)
class Search(Strict):
    provider:Literal['google','bing']='google'
    keywords:list[str]=Field(min_length=1,max_length=8)
    extraction:Literal['basic','offer-csv-v1','gpt']='basic'
    max_results:int=Field(5,ge=1,le=10); interval_seconds:int=Field(300,ge=60,le=86400)
    as_of:str='now'
    @field_validator('keywords')
    @classmethod
    def keywords_check(cls,v):
        if any(not s.strip() or len(s.encode())>256 or any(ord(c)<32 or ord(c)==127 for c in s) for s in v): raise ValueError('invalid keyword')
        return v
    @field_validator('as_of')
    @classmethod
    def cutoff(cls,v): return v if v=='now' else utc(v)
    def config(self): return {'version':1,**self.model_dump(),'transport':'https'}
