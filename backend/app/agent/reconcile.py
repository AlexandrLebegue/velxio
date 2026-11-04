"""Merge independent editor/agent edits by stable entity IDs, never by index."""
import copy
from .settings import AgentError

MISSING=object()


def merge_documents(base, proposed, local, *, prefer_local=False):
    conflicts=[]
    def clone(value):return MISSING if value is MISSING else copy.deepcopy(value)
    def same(a,b):return a is b if a is MISSING or b is MISSING else a==b
    def volatile(path):
        return (path in (('name',),('exportedAt',)) or
                len(path)==3 and path[0]=='boards' and path[-1]=='serialBaudRate' or
                path and path[0]=='wires' and (path[-1]=='signalType' or len(path)==4 and path[-2] in ('start','end') and path[-1] in ('x','y')))
    def merge(old,wanted,current,path):
        if old is MISSING and path and path[-1]=='libraries' and isinstance(wanted,list) and isinstance(current,list):old=[]
        if same(wanted,old):return clone(current)
        if same(current,old) or same(wanted,current):return clone(wanted)
        if volatile(path):return clone(current)
        if all(isinstance(v,dict) for v in (old,wanted,current)):
            out={}
            for key in sorted(set(old)|set(wanted)|set(current)):
                item=merge(old.get(key,MISSING),wanted.get(key,MISSING),current.get(key,MISSING),(*path,key))
                if item is not MISSING:out[key]=item
            return out
        if all(isinstance(v,list) for v in (old,wanted,current)):
            entries=old+wanted+current
            field=next((key for key in ('id','name') if entries and all(isinstance(v,dict) and isinstance(v.get(key),str) for v in entries)),None)
            if field and all(len({v[field] for v in values})==len(values) for values in (old,wanted,current)):
                maps=[{v[field]:v for v in values} for values in (old,wanted,current)]
                order=list(dict.fromkeys([v[field] for v in current+wanted+old]));out=[]
                for key in order:
                    item=merge(*(values.get(key,MISSING) for values in maps),(*path,key))
                    if item is not MISSING:out.append(item)
                return out
            if path and path[-1]=='libraries' and all(isinstance(v,str) for v in entries):
                removed=(set(old)-set(wanted))|(set(old)-set(current))
                return list(dict.fromkeys(v for v in current+wanted if v not in removed))
        conflicts.append('/'+'/'.join(str(v).replace('~','~0').replace('/','~1') for v in path))
        return clone(current)
    value=merge(base,proposed,local,())
    if conflicts and not prefer_local:
        error=AgentError('edit_conflict','The same fields changed in the editor and agent: '+', '.join(conflicts[:4])+'. Manual edits were preserved.')
        error.details={'path':conflicts[0],'conflicting_paths':conflicts[:16],
                       'next_action':'Read the latest state with components() and change only the requested fields. Do not repeat a stale full snapshot.'}
        raise error
    return value,conflicts
