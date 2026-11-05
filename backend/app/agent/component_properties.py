"""Match the chat checker to the native editor's scalar property coercions.

The generated catalog sometimes labels Lit numeric/boolean defaults as strings.
Only those evidenced contradictions are adapted. Saved properties stay intact;
external compact MCP validation and undocumented attributes are unchanged.
"""
import copy
import math
import re
from app.mcp.compact import ProjectChecker

_RANGE = re.compile(r'(-?\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(-?\d+(?:\.\d+)?)')


def _range(attr, summary):
    if attr.get('type') not in ('number', 'integer') or 'min' in attr or 'max' in attr:
        return None
    name = attr.get('name', '').casefold()
    for text in (attr.get('description') or '', summary or ''):
        if name and name not in text.casefold():
            continue
        match = _RANGE.search(text)
        if match:
            low, high = float(match.group(1)), float(match.group(2))
            if low < high:
                return (int(low), int(high)) if low.is_integer() and high.is_integer() else (low, high)
    return None


def native_attrs(attrs,defaults,summary=''):
    result=[]
    for attr in attrs:
        default=defaults.get(attr['name']);kind=None
        if attr.get('type')=='string':
            if type(default) is bool:kind='boolean'
            elif type(default) in (int,float):kind='number'
        value={**attr,'type':kind} if kind else dict(attr)
        limits=_range(value,summary)
        if limits:value.update(min=limits[0],max=limits[1])
        result.append(value)
    return result


class EditorProjectChecker(ProjectChecker):
    def __init__(self,store,catalog,**kwargs):
        view=copy.copy(catalog);view._entries=dict(catalog._entries)
        self.coercions={}
        for key,entry in catalog._entries.items():
            attrs=native_attrs(entry.get('attrs',[]),entry.get('defaults',{}),entry.get('summary',''))
            changed={a['name']:a['type'] for a,b in zip(attrs,entry.get('attrs',[])) if a['type']!=b['type']}
            if attrs!=entry.get('attrs',[]):
                view._entries[key]={**entry,'attrs':attrs}
            if changed:
                self.coercions[key]=changed
        super().__init__(store,view,**kwargs)

    def _check(self,doc,pid,version):
        projected=copy.deepcopy(doc)
        for part in projected['components']:
            key='component:'+part['metadataId'].removeprefix('wokwi-').removeprefix('velxio-')
            for name,kind in self.coercions.get(key,{}).items():
                value=part['properties'].get(name)
                if kind=='number' and isinstance(value,str):
                    try:
                        numeric=float(value)
                        if math.isfinite(numeric):part['properties'][name]=numeric
                    except ValueError:pass
                elif kind=='boolean' and value in ('true','false'):
                    part['properties'][name]=value=='true'
        result=super()._check(projected,pid,version)
        result['checks_performed'].append('native_editor_scalar_types')
        return result
