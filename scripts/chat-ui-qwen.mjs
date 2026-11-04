#!/usr/bin/env node
// Actual editor + chat + OpenCode + configured Qwen. One prompt per fresh context.
// Invoke under the shared flock; no credentials or raw evidence belong in Git.
import {readFileSync,writeFileSync,mkdirSync,chmodSync} from 'node:fs';
import {join} from 'node:path';
import {homedir} from 'node:os';
import {pathToFileURL} from 'node:url';

const options=Object.fromEntries(process.argv.slice(2).reduce((a,v,i,x)=>i%2===0?[...a,[v.replace(/^--/,''),x[i+1]]]:a,[]));
if(!options.url||!options.evidence||!options.suite)throw Error('Required: --url --evidence --suite; optional --cases --playwright --chromium');
const {chromium}=await import(options.playwright?pathToFileURL(options.playwright).href:'playwright');
const configured=JSON.parse(readFileSync(join(homedir(),'.config/opencode/opencode.json'),'utf8')).provider.hyperqwen;
let key=configured.options.apiKey;
if(key?.startsWith('{env:')&&key.endsWith('}'))key=process.env[key.slice(5,-1)];
if(!key)throw Error('Existing provider credential unavailable');
const suite=JSON.parse(readFileSync(options.suite,'utf8')).cases;
const cases=(options.cases||Object.keys(suite).join(',')).split(',');
const settings={base_url:configured.options.baseURL,api_key:key,model:'qwen3.8-27b',max_steps:20,timeout_seconds:300,max_output_tokens:8192,context_window:65536};
mkdirSync(options.evidence,{recursive:true,mode:0o700});chmodSync(options.evidence,0o700);
const browser=await chromium.launch({headless:true,...(options.chromium?{executablePath:options.chromium}:{}),args:['--no-sandbox']});
const rows=[];
try{
  for(const id of cases){
    const folder=join(options.evidence,id);mkdirSync(folder,{recursive:true,mode:0o700});
    const context=await browser.newContext({locale:'en-US',viewport:{width:1540,height:1000}});
    const page=await context.newPage();let sid=null;const browserResults=[],compileResults=[],pageErrors=[],prompts=[];
    page.on('request',r=>{
      if(r.url().includes('/api/agent/sessions/')&&r.url().endsWith('/messages')){
        sid=r.url().match(/sessions\/([^/]+)\/messages/)?.[1];prompts.push(r.postDataJSON().message);
      }
      if(r.url().endsWith('/browser-result'))browserResults.push(r.postDataJSON().result);
    });
    page.on('pageerror',e=>pageErrors.push(e.message));
    page.on('response',r=>{
      if(/\/api\/compile\/(start|status\/[^/?]+)(\?|$)/.test(r.url()))
        void r.json().then(d=>compileResults.push(d)).catch(()=>{});
    });
    const started=Date.now();let error=null,session=null,workspace=null;
    try{
      await page.goto(options.url+'/editor?agent-preview=1',{waitUntil:'domcontentloaded',timeout:60000});
      const current=await page.request.get(options.url+'/api/agent/settings');if(!current.ok())throw Error('Cannot access chat settings');
      const saved=await page.request.put(options.url+'/api/agent/settings',{data:settings});if(!saved.ok())throw Error('Cannot configure isolated test owner');
      await page.locator('.monaco-editor').first().waitFor({timeout:60000});
      const news=page.locator('.velxio-news-overlay');
      if(await news.isVisible()){
        const close=news.getByRole('button',{name:/close|got it|continue|fermer/i}).first();
        if(await close.count())await close.click();else await page.keyboard.press('Escape');
      }
      await page.getByRole('button',{name:'AI agent',exact:true}).click();
      const panel=page.locator('.agent-panel');await panel.getByLabel('Message to the agent').fill(suite[id].prompt);
      await panel.getByRole('button',{name:'Send',exact:true}).click();
      await panel.locator('.agent-turn').first().waitFor({timeout:30000});
      await page.waitForFunction(()=>{const box=document.querySelector('.agent-panel textarea');return box&&!box.disabled;},{},{timeout:360000});
      if(!sid)throw Error('No chat session captured');
      for(let i=0;i<30;i++){
        const reply=await page.request.get(options.url+'/api/agent/sessions/'+sid);session=await reply.json();
        if(!session.busy)break;await page.waitForTimeout(200);
      }
      const reply=await page.request.get(options.url+'/api/agent/sessions/'+sid+'/workspace');workspace=await reply.json();
    }catch(e){error=String(e);}
    finally{
      if(sid&&(!session||session.busy))await page.request.post(options.url+'/api/agent/sessions/'+sid+'/stop').catch(()=>{});
      await page.screenshot({path:join(folder,'chat.png'),fullPage:true}).catch(()=>{});
      const steps=session?.turns?.flatMap(t=>t.steps)||[];
      const alerts=await page.locator('.agent-error').allTextContents().catch(()=>[]);
      const turnStatus=session?.turns?.at(-1)?.status;
      if(!error&&turnStatus==='error')error=alerts.join('\n')||'Chat turn failed before completion';
      const row={case:id,seconds:Number(((Date.now()-started)/1000).toFixed(2)),error,
        single_exact_prompt:prompts.length===1&&prompts[0]===suite[id].prompt,
        steps:steps.length,mcp_calls:steps.filter(s=>!['read','write','edit','glob','grep','list','apply_patch'].includes(s.name)).length,
        failed_steps:steps.filter(s=>s.status==='error').map(s=>({name:s.name,summary:s.summary})),
        browser_results:browserResults,page_errors:pageErrors,compile_requests:compileResults.length,
        conclusion:session?.messages?.at(-1),session_id:sid,turn_status:turnStatus,alerts};
      for(const [file,value]of [['result.json',row],['session.json',session],['workspace.json',workspace],['compile-results.json',compileResults]])
        writeFileSync(join(folder,file),JSON.stringify(value,null,2));
      rows.push(row);writeFileSync(join(options.evidence,'summary.json'),JSON.stringify(rows,null,2));
      console.log(JSON.stringify({case:id,seconds:row.seconds,error:row.error,mcp_calls:row.mcp_calls,failed_steps:row.failed_steps.length,compile_requests:row.compile_requests,single_exact_prompt:row.single_exact_prompt}));
      await context.close();
    }
  }
}finally{await browser.close();}
