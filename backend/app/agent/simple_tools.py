"""Small chat-only tool surface; the external compact MCP is unchanged."""
import asyncio
import copy
import json
import secrets

from .settings import AgentError
from .workspace import checked_document, project_revision


def obj(properties, required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}


TEXT = {'type':'string','minLength':1,'maxLength':200}
ENDPOINT = obj({'componentId':TEXT,'pinName':TEXT}, ('componentId','pinName'))
PART = obj({'component':TEXT,'id':TEXT,'properties':{'type':'object'},'x':{'type':'number'},'y':{'type':'number'}}, ('component',))
EDIT = obj({'id':TEXT,'properties':{'type':'object'},'x':{'type':'number'},'y':{'type':'number'}}, ('id',))
def array(items, maximum=64):
    return {'type':'array','items':items,'maxItems':maximum}


CHAT_TOOLS = {
    'search_component': ('Find components or boards by a short query. Results include exact IDs, real pins, defaults and possible libraries; no reference read needed. Use next_offset for more results.',
        obj({'query':TEXT,'kind':{'enum':['all','component','board'],'default':'all'},
             'limit':{'type':'integer','minimum':1,'maximum':5,'default':3},
             'offset':{'type':'integer','minimum':0,'maximum':100000,'default':0}}, ('query',))),
    'components': ('Edit the current circuit in one batch; no arguments reads its current state. board creates or replaces the active board while preserving source. add uses component IDs and optional instance id/properties; update/remove use existing instance IDs. libraries optionally selects exact sketch dependencies; run resolves imports automatically with the application compiler. Returns mounted pins and source paths. All edits are atomic.',
        obj({'board':TEXT,'language_mode':{'enum':['arduino','micropython','espidf']},
             'pin_map':{'type':'object','additionalProperties':{'type':'string'}},
             'add':array(PART),'update':array(EDIT),'remove':array(TEXT),'libraries':array(TEXT)})),
    'connect': ('Connect all planned wires in one call using wires:[{start:{componentId,pinName},end:{componentId,pinName}}]. Use the exact returned pins. remove accepts wire IDs. Existing wires are preserved; duplicates are skipped; the whole edit is validated atomically.',
        obj({'wires':array(obj({'start':ENDPOINT,'end':ENDPOINT}, ('start','end')),128),'remove':array(TEXT,128)})),
    'run': ('Save current files, resolve library imports through the application Library Manager, check the circuit, compile and start the editor simulation. No project/build IDs or separate check/build calls. simulate=false compiles only (also used for ESP32, whose simulation is unsupported). If pending, call run again to get progress without restarting. action=status observes; stop stops simulation; restart explicitly starts over. Compilation and startup never prove functional behavior.',
        obj({'action':{'enum':['start','status','stop','restart'],'default':'start'},
             'simulate':{'type':'boolean','default':True},
             'wait_seconds':{'type':'number','minimum':0,'maximum':60,'default':20},
             'duration_ms':{'type':'integer','minimum':0,'maximum':15000,'default':500}})),
}


def normalize_chat(name, arguments):
    """Only lossless transport coercions; never guess missing/truncated data."""
    if not isinstance(arguments, dict):
        return arguments
    def coerce(value, schema):
        if isinstance(value,str) and schema.get('type') in ('array','object'):
            try:
                parsed=json.loads(value)
                if isinstance(parsed,list if schema['type']=='array' else dict):
                    value=parsed
            except (ValueError,RecursionError):
                pass
        if isinstance(value,str) and schema.get('type')=='boolean' and value in ('true','false'):
            return value=='true'
        if isinstance(value,str) and schema.get('type') in ('integer','number'):
            try:
                parsed=json.loads(value)
                if type(parsed) in (int,float) and (schema['type']=='number' or type(parsed)==int):
                    return parsed
            except ValueError:
                pass
        if isinstance(value,dict):
            return {k:coerce(v,schema.get('properties',{}).get(k,{})) for k,v in value.items()}
        if isinstance(value,list):
            return [coerce(v,schema.get('items',{})) for v in value]
        return value
    return coerce(copy.deepcopy(arguments), CHAT_TOOLS[name][1])


def reference_card(result):
    data=result['data']
    card={'id':result['id'], **{k:data[k] for k in ('name','summary','metadataId','boardKind','pins','attrs','defaults','protocol','languages','capabilities') if k in data}}
    usage=data.get('usage')
    if isinstance(usage,dict):
        card['usage']=usage
        libraries=usage.get('libraries')
        card['library_candidates']=[{'name':name} for name in libraries[:8]] if isinstance(libraries,list) else 'unknown'
    elif 'metadataId' in data:
        card['library_candidates']=[{'name':v['name']} for v in data.get('libraries',[])][:8] if isinstance(data.get('libraries'),list) else 'unknown'
    return card


class SimpleChatTools:
    def __init__(self, runtime, session):
        self.runtime,self.session=runtime,session
        self.last_run=None

    async def call(self, name, args):
        if name=='search_component':
            catalog=self.runtime.get_catalog()
            kind=args.get('kind','all')
            # Search boards/components only: examples and code recipes are not
            # the chat's default construction workflow.
            kinds=('board','component') if kind=='all' else (kind,)
            matches=[];used=[]
            for part_kind in kinds:
                page=catalog.search_catalog(query=args['query'],kind=part_kind,limit=50)
                if not page.get('ok'):
                    return page
                matches.extend(page['items']);used.extend(page['query_used'])
                offset=page['next_offset']
                while offset is not None:
                    page=catalog.search_catalog(query=args['query'],kind=part_kind,limit=50,offset=offset)
                    if not page.get('ok'):return page
                    matches.extend(page['items']);offset=page['next_offset']
            offset,limit=args.get('offset',0),args.get('limit',3)
            cards=[]
            for item in matches[offset:offset+limit]:
                reference=await self.runtime._call_tool(self.session,'get_reference',{'id':item['id']})
                if not reference.get('ok'):return reference
                card=reference_card(reference)
                if cards and len(json.dumps(cards+[card],ensure_ascii=False).encode())>20*1024:break
                cards.append(card)
            return {'ok':True,'items':cards,'total':len(matches),'query_used':list(dict.fromkeys(used)),
                    'next_offset':offset+len(cards) if offset+len(cards)<len(matches) else None,
                    'has_more':offset+len(cards)<len(matches)}
        if name=='components':return await self.components(args)
        if name=='connect':return await self.connect(args)
        if name=='run':return await self.run(args)
        raise AgentError('unknown_tool','Unknown chat tool')

    async def publish(self, value, materialize=False):
        new_groups=set(value['fileGroups'])!=set(self.session.workspace.groups)
        result=await self.runtime.apply_candidate(self.session,checked_document(value))
        if result.get('ok'):
            # Circuit-only changes must not overwrite native file edits that
            # OpenCode completed while the editor was validating the circuit.
            if materialize and new_groups:
                self.session.workspace.sync(self.session.workspace.document,self.session.workspace.revision)
            result['workspace']=self.runtime.source_context(self.session)
        return result

    async def components(self, args):
        if not args:
            return await self.runtime.project_context(self.session)
        if not any(key in args for key in ('board','add','update','remove','libraries')):
            raise AgentError('invalid_argument','Supply board, add, update, remove or libraries.')
        if 'pin_map' in args and 'board' not in args:
            raise AgentError('invalid_argument','Supply board when using pin_map.')
        value=self.session.workspace.capture()
        board=next((b for b in value['boards'] if b['id']==value['activeBoardId']),None)
        references={}
        if 'board' in args:
            key=args['board'].removeprefix('board:')
            reference=await self.runtime._call_tool(self.session,'get_reference',{'id':'board:'+key})
            if not reference.get('ok'):return reference
            definition=reference['data'];references['board']=reference_card(reference)
            languages=definition.get('languages',[])
            mode=args.get('language_mode',board.get('languageMode','arduino') if board else 'arduino')
            if mode not in languages and languages:
                if 'language_mode' in args:raise AgentError('unsupported_language','Supported languages: '+', '.join(languages))
                mode=languages[0]
            if board is None:
                group='sketch'
                while group in value['fileGroups']:group+='-new'
                board={'id':'board','boardKind':key,'x':0,'y':0,'activeFileGroupId':group,'languageMode':mode,'libraries':[]}
                occupied={p['id'] for p in value['boards']+value['components']}
                while board['id'] in occupied:board['id']+='-new'
                value['boards'].append(board);value['activeBoardId']=board['id']
                value['fileGroups'][group]=[{'name':'main.py' if mode=='micropython' else 'main.c' if mode=='espidf' else 'sketch.ino',
                    'content':'# Write your program here.\n' if mode=='micropython' else 'void app_main(void) {}\n' if mode=='espidf' else 'void setup() {}\n\nvoid loop() {}\n'}]
            else:
                if board['boardKind']!=key:board.pop('boardOptions',None)
                board.update(boardKind=key,languageMode=mode)
                for wire in value['wires']:
                    for side in ('start','end'):
                        endpoint=wire[side]
                        if endpoint['componentId']==board['id']:
                            endpoint['pinName']=args.get('pin_map',{}).get(endpoint['pinName'],endpoint['pinName'])
        if board is None:
            raise AgentError('board_unknown','Add a board first with components(board=<boardKind>,add=[...]).')
        if 'language_mode' in args and 'board' not in args:
            raise AgentError('invalid_argument','Supply board when changing language_mode.')
        if 'libraries' in args:board['libraries']=args['libraries']
        removed=set(args.get('remove',[]));ids={p['id'] for p in value['components']}
        if removed-ids:raise AgentError('component_unknown','Unknown component IDs: '+', '.join(sorted(removed-ids)))
        value['components']=[p for p in value['components'] if p['id'] not in removed]
        value['wires']=[w for w in value['wires'] if not any(w[side]['componentId'] in removed for side in ('start','end'))]
        for edit in args.get('update',[]):
            part=next((p for p in value['components'] if p['id']==edit['id']),None)
            if part is None:raise AgentError('component_unknown','Unknown component ID: '+edit['id'])
            part['properties'].update(edit.get('properties',{}))
            part.update({k:edit[k] for k in ('x','y') if k in edit})
        existing={p['id'] for p in value['boards']+value['components']}
        added=[]
        for spec in args.get('add',[]):
            key=spec['component'].removeprefix('component:')
            reference=await self.runtime._call_tool(self.session,'get_reference',{'id':'component:'+key})
            if not reference.get('ok'):return reference
            card=reference_card(reference);key=card['metadataId']
            suffix=1
            while f'{key}-{suffix}' in existing:suffix+=1
            identity=spec.get('id',f'{key}-{suffix}')
            if identity in existing:raise AgentError('duplicate_id','Instance '+identity+' already exists; use update for an existing component.')
            index=len(value['components'])
            part={'id':identity,'metadataId':key,'x':spec.get('x',board.get('x',0)+440+index%3*300),
                  'y':spec.get('y',board.get('y',0)+index//3*320),
                  'properties':{**reference['data']['instance_template']['properties'],**spec.get('properties',{})}}
            value['components'].append(part);existing.add(identity);added.append(identity);references[identity]=card
        result=await self.publish(value,materialize=True)
        if result.get('ok'):
            result.update(board=next(b for b in self.session.workspace.document['boards'] if b['id']==value['activeBoardId']),
                          components=self.session.workspace.document['components'],references=references,
                          added=added,removed=sorted(removed))
        return result

    async def connect(self, args):
        if not args.get('wires') and not args.get('remove'):
            raise AgentError('invalid_argument','Supply wires:[{start:{componentId,pinName},end:{componentId,pinName}}] or remove:[wire_id].')
        value=self.session.workspace.capture();removed=set(args.get('remove',[]))
        known={w['id'] for w in value['wires']}
        if removed-known:raise AgentError('wire_unknown','Unknown wire IDs: '+', '.join(sorted(removed-known)))
        value['wires']=[w for w in value['wires'] if w['id'] not in removed]
        def signature(wire):
            return frozenset((wire[s]['componentId'],wire[s]['pinName']) for s in ('start','end'))
        existing={signature(w) for w in value['wires']};added=[];skipped=0
        for wire in args.get('wires',[]):
            if signature(wire) in existing:skipped+=1;continue
            if wire['start']==wire['end']:raise AgentError('invalid_argument','A wire must connect two different pins.')
            item={'id':'wire-'+secrets.token_hex(6),**copy.deepcopy(wire)}
            value['wires'].append(item);existing.add(signature(wire));added.append(item['id'])
        result=await self.publish(value)
        if result.get('ok'):result.update(added_connections=len(added),connection_ids=added,duplicates_skipped=skipped)
        return result

    async def run(self, args):
        action=args.get('action','start')
        if action=='stop':
            result=await self.runtime.browser_command(self.session,'stop')
            if self.last_run and self.last_run['mode']=='compile' and (self.last_run.get('result') or {}).get('state')=='compiling':
                result['compilation_continues']=True
            else:self.last_run=None
            return result
        current=project_revision(self.session.workspace.capture())
        if self.session.workspace.document['activeBoardId'] is None:
            raise AgentError('board_unknown','Add a board with components(board=<boardKind>) before calling run().')
        previous=self.last_run
        if action=='status' and (not previous or previous['revision']!=current):
            return {'ok':False,'state':'not_run','confirmed':False,'error':{'code':'not_run','message':'Current files have not been run. Call run() to check and run them.'}}
        # A pending compile must be resumed even if simulate was omitted on
        # the following call. Explicit restart must not duplicate a live build.
        if previous and previous['revision']==current and previous['mode']=='compile' and (previous.get('result') or {}).get('state')=='compiling':
            return await self.compile(args,previous)
        if previous and previous['mode']=='editor_compile' and previous['revision']==current and action!='restart' and (action=='status' or previous.get('result',{}).get('state')=='compiling' or args.get('simulate',True) is False or self.runtime.execution_refusal(self.session)):
            return await self.editor_compile(args,previous)
        same_mode=previous and (action=='status' or previous['mode']==('compile' if args.get('simulate',True) is False or self.runtime.execution_refusal(self.session) else 'simulation'))
        if action!='restart' and same_mode and previous['revision']==current:
            if previous['mode']=='compile':
                return await self.compile(args,previous)
            if previous['result'].get('state') in ('running','starting','booting','compiling') or action=='status':
                delay=500 if previous['result'].get('state')=='running' else min(15000,int(args.get('wait_seconds',20)*1000))
                result=await self.runtime.browser_command(self.session,'observe',duration_ms=args.get('duration_ms',delay))
                return self.simulation_result(result,current)
        dependency_resolution=None
        if self.session.editor_capabilities.get('compile'):
            from .libraries import resolve
            value=self.session.workspace.capture()
            board=next(b for b in value['boards'] if b['id']==value['activeBoardId'])
            if board.get('languageMode','arduino')=='arduino':
                definition=self.runtime.get_catalog()._entries.get('board:'+board['boardKind'],{})
                architecture=definition.get('architecture')
                if not architecture:
                    fqbn=definition.get('fqbn','')
                    architecture=fqbn.split(':')[1] if ':' in fqbn else None
                if architecture:
                    hints=[]
                    for part in value['components']:
                        reference=self.runtime.get_catalog().get_reference(id='component:'+part['metadataId'])
                        hints.extend(v['name'] for v in reference.get('data',{}).get('libraries',[]) if isinstance(v,dict))
                    dependency_resolution=await resolve(value['fileGroups'][board['activeFileGroupId']],board.get('libraries',[]),architecture,
                        user=self.session.compile_user,allow_install=True,hints=hints)
                    if dependency_resolution['libraries']!=board.get('libraries',[]):
                        board['libraries']=dependency_resolution['libraries']
                        applied=await self.publish(value)
                        if not applied.get('ok'):return applied
        checked=await self.runtime._call_tool(self.session,'check_project',{})
        if not checked.get('ok'):return checked
        if checked.get('structure_status')=='invalid':
            issue=next((i for i in checked.get('issues',[]) if i.get('severity')=='error'),{})
            return {'ok':False,'state':'invalid','confirmed':False,'checks':{'structure_status':'invalid'},'issues':checked['issues'],
                    'error':{'code':issue.get('code','invalid_project'),'path':issue.get('path',''),
                             'message':issue.get('message','Project check failed.'),
                             'next_action':'Fix the reported source or circuit error, then call run() again.'}}
        # Editor validation sees current native files before compilation; it
        # also enforces manual-edit revision conflicts. No source rewriting.
        applied=await self.publish(self.session.workspace.capture())
        if not applied.get('ok'):return applied
        current=self.session.workspace.revision
        if args.get('simulate',True) is False or self.runtime.execution_refusal(self.session):
            if self.session.editor_capabilities.get('compile'):
                self.last_run={'mode':'editor_compile','revision':current,'checks':{'structure_status':checked['structure_status']},
                    'dependency_resolution':dependency_resolution}
                return await self.editor_compile(args,self.last_run)
            self.last_run={'mode':'compile','revision':current,'build_id':None,'result':None,
                           'checks':{'structure_status':checked['structure_status']}}
            return await self.compile(args,self.last_run)
        result=await self.runtime.browser_command(self.session,'run',document=self.session.workspace.document,revision=current)
        executed=result.get('applied_revision',current)
        self.last_run={'mode':'simulation','revision':executed,'result':result,
                       'checks':{'structure_status':checked['structure_status']}}
        return self.simulation_result(result,executed)

    async def editor_compile(self,args,record):
        result=await self.runtime.browser_command(self.session,'compile',document=self.session.workspace.document,
            revision=record['revision'],wait_seconds=args.get('wait_seconds',20),restart=args.get('action')=='restart')
        executed=result.get('applied_revision',record['revision'])
        record['revision']=executed
        value=self.simulation_result(result,executed)
        value['simulation']={'state':'unsupported' if self.runtime.execution_refusal(self.session) else 'not_requested','confirmed':False}
        if record.get('dependency_resolution'):value['dependencies']=record['dependency_resolution']
        if result.get('state')=='compiled':
            value['next_action']='Compilation succeeded for current files. Simulation and behavior have not been verified.'
        return value

    def simulation_result(self, result, revision):
        matches=revision==project_revision(self.session.workspace.capture())
        if self.last_run:self.last_run['result']=result
        if not matches:
            return {'ok':False,'state':'stale','confirmed':False,'error':{'code':'revision_conflict','message':'Files changed during execution. Call run() for the current files; this result covers an older revision.'}}
        exposed={k:v for k,v in result.items() if k not in ('document','editor_document','editor_revision','applied_revision')}
        value={**exposed,'workspace_revision':revision,'matches_current_workspace':True,
               'behavior_verified':False,'checks':self.last_run.get('checks',{}) if self.last_run else {}}
        if result.get('error',{}).get('code')=='compilation_failed':
            value['compilation']={'success':False,'source':'editor run pipeline'}
        elif result.get('compiled') is True:value['compilation']={'success':True,'source':'editor run pipeline'}
        if result.get('state') in ('starting','booting','compiling'):
            value['next_action']='Call run() again to get progress. Do not restart.'
        return value

    async def compile(self, args, record):
        if record.get('result') and record['result'].get('state') not in ('running','compiling'):
            return record['result']
        query={'action':'status','build_id':record['build_id']} if record['build_id'] else {'action':'start','wait_seconds':args.get('wait_seconds',20)}
        build=await self.runtime._call_tool(self.session,'build_project',query)
        if query['action']=='status':
            deadline=asyncio.get_running_loop().time()+args.get('wait_seconds',20)
            while build.get('ok') and build.get('state')=='running' and asyncio.get_running_loop().time()<deadline:
                await asyncio.sleep(min(0.5,deadline-asyncio.get_running_loop().time()))
                build=await self.runtime._call_tool(self.session,'build_project',query)
        if build.get('build_id'):record['build_id']=build['build_id']
        value={k:v for k,v in build.items() if k not in ('build_id','artifacts','next_action')}
        value['checks']=record['checks']
        value.update(confirmed=False,behavior_verified=False,simulation={'state':'unsupported' if self.runtime.execution_refusal(self.session) else 'not_requested','confirmed':False})
        if build.get('state')=='running':
            value.update(state='compiling',next_action='Call run() again to get the result of this build. Do not restart.')
        elif build.get('success') is True and build.get('matches_current_workspace') is True:
            value.update(state='compiled',compilation={'success':True},next_action='Compilation succeeded for current files. Simulation and behavior have not been verified.')
        elif not build.get('ok') or build.get('success') is False:
            if build.get('success') is False:value['compilation']={'success':False}
            value['next_action']='Fix the reported diagnostic or prerequisite, then call run() again.'
        else:
            value.update(ok=False,state='stale',next_action='Files changed since this build. Call run() for the current files.')
        record['result']=value
        if value.get('ok') is False or value.get('success') is False:self.last_run=None
        return value
