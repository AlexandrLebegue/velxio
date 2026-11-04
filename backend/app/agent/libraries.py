"""Resolve sketch imports to real installed library identities, not guessed recipes."""
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re

from .settings import AgentError
from app.mcp.compact.sketches import lex


def normalized(value):return re.sub(r'[^a-z0-9]','',value.lower())


def split_spec(value):
    name,separator,version=value.rpartition('@')
    return (name,version) if separator and name and version else (value,None)


@dataclass
class Library:
    name: str
    version: str
    architectures: tuple
    headers: frozenset
    dependencies: tuple=()
    core: bool=False

    def supports(self,architecture):return '*' in self.architectures or architecture in self.architectures

    def aliases(self):
        return {normalized(self.name),*(normalized(PurePosixPath(h).stem) for h in self.headers)}


def imports(files):
    names={f['name'] for f in files};out=[]
    for file in files:
        if not file['name'].endswith(('.ino','.cpp','.c','.h','.hpp','.cc','.cxx')):continue
        clean,_,_=lex(file['content'])
        for original,masked in zip(file['content'].splitlines(),clean.splitlines()):
            if not re.match(r'^\s*#\s*include\b',masked):continue
            match=re.match(r'^\s*#\s*include\s*[<"]([^>"\r\n]+)[>"]',original)
            if not match:continue
            header=match[1]
            relative=posixpath.normpath(str(PurePosixPath(file['name']).parent/header))
            if header in names or relative in names:continue
            if header not in out:out.append(header)
    return out


def discover():
    # Existing app discovery knows both mutable Arduino sketchbooks and the
    # content-addressed library cache. This reads metadata/header names only.
    from app.api.routes.intellisense import _sources
    from app.services.symbol_extract import _read_props,_iter_headers
    roots=[(source.root,False) for source in _sources()]
    data=Path(os.environ.get('ARDUINO_DIRECTORIES_DATA',str(Path.home()/'.arduino15')))
    roots.extend((root,True) for root in data.glob('packages/*/hardware/*/*/libraries'))
    for variable,default in (('ARDUINO_ESP32_PATH','/opt/arduino-esp32'),('ARDUINO_ESP32_5_PATH','/opt/arduino-esp32-3')):
        root=Path(os.environ.get(variable,default))/'libraries'
        if root.is_dir():roots.append((root,True))
    libraries=[];seen=set()
    for root,core in roots:
        if not root.is_dir():continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or not (entry/'library.properties').is_file():continue
            resolved=entry.resolve()
            if resolved in seen:continue
            seen.add(resolved);props=_read_props(entry)
            if not props.get('name'):continue
            headers=set()
            for header in _iter_headers(entry):
                for parent in (entry/'src',entry):
                    if header.is_relative_to(parent):headers.add(header.relative_to(parent).as_posix())
                headers.add(header.name)
            dependencies=tuple(re.sub(r'\s*\([^)]*\)\s*$','',part).strip()
                for part in re.split(r',(?![^()]*\))',props.get('depends','')) if part.strip())
            libraries.append(Library(props['name'],props.get('version','unknown'),
                tuple(v.strip() for v in props.get('architectures','*').split(',')),frozenset(headers),dependencies,core))
    return libraries


def registry():
    # Cached official index only. Discovery never refreshes/downloads an index.
    data=Path(os.environ.get('ARDUINO_DIRECTORIES_DATA',str(Path.home()/'.arduino15')))
    path=data/'library_index.json'
    try:
        if path.stat().st_size>128*1024*1024:return []
        return json.loads(path.read_text()).get('libraries',[])
    except (OSError,ValueError):return []


async def install_managed(name,version,user):
    # Same installer, ownership and overlay policy as the existing Library UI.
    from app.api.routes.libraries import install_library,InstallLibraryRequest
    value=await install_library(InstallLibraryRequest(name=name,version=version),requester_id=user)
    if hasattr(value,'body'):value=json.loads(value.body)
    elif hasattr(value,'model_dump'):value=value.model_dump()
    return value


def dependency_error(code,message,received,expected,**details):
    error=AgentError(code,message)
    error.details={'path':'/libraries','received':received,'expected':expected,
                   'next_action':'Use the exact library names/candidates reported here with components(libraries=[...]), then call run(). Do not rewrite a driver to bypass a missing library.',**details}
    return error


async def resolve(files,declared,architecture,*,user=None,allow_install=False,hints=(),loader=discover,index_loader=registry,installer=install_managed):
    headers=imports(files)
    if not headers and not declared:return {'libraries':[],'resolved':[],'installed':[],'unknown_headers':[]}
    available=await asyncio.to_thread(loader);index=None;installed=[];resolved=[];manifest=[];attempted=set()
    def candidates(spec):
        name,version=split_spec(spec)
        return [v for v in available if normalized(name) in v.aliases() and (version is None or version==v.version)]
    async def select(spec):
        nonlocal available,index
        name,version=split_spec(spec);matching=candidates(spec)
        good=[v for v in matching if v.supports(architecture)]
        if good:
            identities={v.name for v in good}
            if len(identities)>1:
                raise dependency_error('library_ambiguous','Several installed libraries match '+name,spec,', '.join(sorted(identities)),candidates=sorted(identities))
            chosen=max(good,key=lambda v:tuple(int(n) for n in re.findall(r'\d+',v.version)))
            return chosen
        if index is None:index=await asyncio.to_thread(index_loader)
        entries=[v for v in index if normalized(v.get('name',''))==normalized(name) and (version is None or v.get('version')==version)]
        compatible=[v for v in entries if '*' in v.get('architectures',['*']) or architecture in v.get('architectures',[])]
        if matching and not good or entries and not compatible:
            alternatives=[{'name':v.name,'headers':sorted(v.headers)[:5]} for v in available if v.supports(architecture) and normalized(name) in normalized(v.name)]
            raise dependency_error('library_incompatible',name+' does not support board architecture '+architecture,spec,
                'A library for '+architecture,alternatives=alternatives[:5])
        if compatible:
            chosen=max(compatible,key=lambda v:tuple(int(n) for n in re.findall(r'\d+',v.get('version','0'))))
            identity=chosen['name'];pin=chosen.get('version')
            if not allow_install:
                raise dependency_error('library_missing',identity+' is not installed.',spec,'Installed '+identity,
                    library=identity,installable=True,next_action='Install '+identity+' through the application Library Manager, then call run() again. Keep the existing source.')
            token=(identity,pin)
            if token in attempted:raise dependency_error('library_install_failed','Installed library could not be found after installation.',identity,'Installed metadata and headers')
            attempted.add(token)
            outcome=await installer(identity,pin,user)
            if not outcome.get('success'):
                raise dependency_error('library_install_failed',str(outcome.get('error') or 'Application library installation failed.')[:400],identity,'A successful application-managed install',
                    next_action='Resolve the reported Library Manager error before retrying. Changing the sketch cannot repair an installation failure.')
            installed.append({'name':identity,'version':pin})
            available=await asyncio.to_thread(loader)
            return await select(identity+('@'+pin if pin else ''))
        # Preserve owner-scoped/private or manually uploaded declarations.
        # Their bytes and access rules are resolved by the real compiler.
        return None
    pending=list(declared)
    # Resolve explicit declarations first so aliases and version pins survive
    # header inference. A library is emitted once under its canonical name.
    chosen_specs={};unknown=[];visited=set()
    async def drain():
        while pending:
            spec=pending.pop(0)
            if spec in visited:continue
            visited.add(spec);library=await select(spec)
            if library is None:
                if spec not in manifest:manifest.append(spec)
                continue
            _,pin=split_spec(spec)
            previous=chosen_specs.get(library.name)
            if previous is not None:
                _,old_pin=split_spec(previous)
                if pin and old_pin and pin!=old_pin:
                    raise dependency_error('library_version_conflict','Two versions of one library were declared.',[previous,spec],'One version per library')
                continue
            chosen_specs[library.name]=library.name+('@'+pin if pin else '')
            if not library.core:manifest.append(chosen_specs[library.name])
            resolved.append({'name':library.name,'version':library.version,'core':library.core})
            pending.extend(library.dependencies)
    await drain()
    for header in headers:
        matching=[v for v in available if header in v.headers and v.supports(architecture)]
        explicit=[v for v in matching if v.name in chosen_specs]
        matching=explicit or matching
        names={v.name for v in matching}
        if not names and allow_install:
            if index is None:index=await asyncio.to_thread(index_loader)
            stem=normalized(PurePosixPath(header).stem)
            # Only cached registry identities are eligible. Prefer an exact
            # header/name identity; component metadata is a bounded fallback.
            exact={v.get('name') for v in index if normalized(v.get('name',''))==stem}
            hinted={name for name in hints if stem and stem in normalized(name)}
            names={v.get('name') for v in index if v.get('name') in (exact or hinted)
                   and ('*' in v.get('architectures',['*']) or architecture in v.get('architectures',[]))}
            if len(names)==1:
                selected=await select(next(iter(names)))
                names={v.name for v in available if header in v.headers and v.supports(architecture)}
                if not names:
                    exported=sorted(selected.headers) if selected else []
                    # Public top-level header names, not a workspace/cache path
                    # or implementation API. This is installation evidence.
                    exported=sorted({PurePosixPath(value).name for value in exported})[:12]
                    raise dependency_error('library_header_missing','Installed '+selected.name+' does not export '+header,header,
                        'One of the verified exported headers',library=selected.name,exported_headers=exported,
                        next_action='Correct the #include in your source using the exported_headers listed here, then call run() again. Keep the installed library; no server-directory read or driver rewrite is needed.')
        if len(names)==1:
            pending.append(next(iter(names)))
        elif len(names)>1:
            raise dependency_error('library_ambiguous','Several installed libraries provide '+header,header,
                                   'Declare one exact library name',candidates=sorted(names)[:8])
        else:unknown.append(header)
    await drain()
    return {'libraries':manifest,'resolved':resolved,'installed':installed,'unknown_headers':unknown[:8]}
