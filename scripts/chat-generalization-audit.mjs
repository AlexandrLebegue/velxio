#!/usr/bin/env node
// Held-out test assertions, never supplied to the model or product catalog.
// Bindings are independently reviewed GPIO assignments from the SAVED circuit.
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {runProbe} from './avr-firmware-probe.mjs';

const near = (actual, expected, tolerance) => Math.abs(actual-expected)<=tolerance;
export function pulses(trace, name) {
  const result=[];let previous=null, rise=null;
  for (const event of trace.edges) {
    const value=event.levels[name];
    if (value===1 && previous!==1) rise=event.at_ms;
    if (value===0 && previous===1 && rise!==null) result.push({start:rise,end:event.at_ms,width:event.at_ms-rise});
    previous=value;
  }
  return result;
}
export function highFraction(trace, name, start, end) {
  let level=null, previous=0, high=0, known=0;
  for (const event of [...trace.edges,{at_ms:end,levels:{[name]:null}}]) {
    const a=Math.max(previous,start),b=Math.min(event.at_ms,end);
    if (b>a && level!==null) {known+=b-a;if(level===1)high+=b-a;}
    if(event.at_ms>=end)break;
    level=event.levels[name];previous=event.at_ms;
  }
  return known>0 ? high/known : null;
}
function fixed(trace,name,start,end,level) {
  const fraction=highFraction(trace,name,start,end);
  return fraction!==null && near(fraction,level,0.001);
}
function press(changes, start, release, bounce=false) {
  changes.push({at_ms:start,level:0});
  if(bounce)for(const [delta,level]of[[2,1],[4,0],[6,1],[10,0]])changes.push({at_ms:start+delta,level});
  changes.push({at_ms:release,level:1});
}
export function stimulus(id, bindings) {
  const spec={duration_ms:5200,outputs:bindings.outputs,sample_ms:5};
  const digital=(name,changes,initial=1)=>({name,pin:bindings.inputs[name],initial,changes,
    ...(bindings.fixed_inputs?.[name]===undefined?{}:{fixed_level:bindings.fixed_inputs[name]})});
  if(id==='G2') {
    const up=[],down=[];press(up,500,1500,true);
    for(let i=0;i<8;i++)press(up,1800+i*200,1880+i*200);
    for(let i=0;i<17;i++)press(down,3700+i*220,3780+i*220);
    spec.duration_ms=8000;spec.digital_inputs=[digital('up',up),digital('down',down)];
  } else if(id==='G3') {
    const changes=[];press(changes,2500,3300,true);press(changes,3800,4000,true);
    spec.duration_ms=5000;spec.digital_inputs=[digital('button',changes)];
    spec.analog_inputs=[{channel:bindings.analog_channel,initial:0,changes:[{at_ms:1000,voltage:2.5},{at_ms:2000,voltage:5}]}];
  } else if(id==='G4') {
    spec.duration_ms=5500;spec.ultrasonic={...bindings.ultrasonic,distances:[{at_ms:0,cm:80},{at_ms:700,cm:35},
      {at_ms:1400,cm:10},{at_ms:3500,cm:80},{at_ms:4300,cm:10},{at_ms:4700,cm:35}]};
  } else if(id==='G5') {
    const changes=[];press(changes,1000,2700,true);press(changes,3300,3500,true);
    spec.duration_ms=5200;spec.digital_inputs=[digital('button',changes),digital('pir',[
      {at_ms:500,level:1},{at_ms:2000,level:0},{at_ms:4200,level:1},{at_ms:4700,level:0}],0)];
  } else if(id==='G6') {
    const changes=[];press(changes,2500,4700,true);
    spec.duration_ms=12000;spec.digital_inputs=[digital('button',changes)];
  } else if(id!=='G1')throw Error('Unknown frozen case');
  return spec;
}

export function assess(id, trace) {
  const checks=[];const check=(requirement,ok,evidence)=>checks.push({requirement,ok:Boolean(ok),evidence});
  check('complete firmware trace',!trace.edge_truncated,{cycles:trace.cycles});
  if(id==='G1') {
    const red=pulses(trace,'red'),green=pulses(trace,'green');
    check('150 ms pulses',red.length>=2&&green.length>=2&&[...red,...green].every(p=>near(p.width,150,2)),{red,green});
    check('2000 ms cycle and alternating phase',red.slice(1).every((p,i)=>near(p.start-red[i].start,2000,2))&&
      green.every((p,i)=>near(p.start-red[i]?.start,1000,2)),null);
    check('never simultaneously on',trace.edges.every(e=>!(e.levels.red===1&&e.levels.green===1)),null);
  } else if(id==='G2') {
    const servo=pulses(trace,'servo');
    const angleAt=(start,end)=>{
      const widths=servo.filter(p=>p.start>=start&&p.end<=end).map(p=>p.width*1000).sort((a,b)=>a-b);
      return widths.length? (widths[Math.floor(widths.length/2)]-542)*180/1856:null;
    };
    const windows=[[100,400,90],[800,1400,100]];
    for(let i=0;i<8;i++)windows.push([1880+i*200,1970+i*200,Math.min(160,110+i*10)]);
    for(let i=0;i<17;i++)windows.push([3780+i*220,3870+i*220,Math.max(20,150-i*10)]);
    const observed=windows.map(([start,end,expected])=>({start,end,expected,angle:angleAt(start,end)}));
    check('initial angle, one debounced step per hold, saturation and direction',
      observed.every(w=>w.angle!==null&&near(w.angle,w.expected,3)),observed);
    check('servo frames approximately 20 ms',servo.length>100&&servo.slice(5).every((p,i)=>near(p.start-servo[i+4].start,20,0.3)),null);
  } else if(id==='G3') {
    const windows=[[200,800,'blue'],[1200,1800,'purple'],[2200,2450,'red'],[2800,3200,'off'],[4200,4800,'red']];
    const observed=windows.map(([start,end,expected])=>({start,end,expected,
      red:1-highFraction(trace,'red',start,end),green:1-highFraction(trace,'green',start,end),blue:1-highFraction(trace,'blue',start,end)}));
    check('common-anode endpoints, midpoint, toggle and hold',observed.every(w=>w.green<0.02&&(
      w.expected==='off'?w.red<0.02&&w.blue<0.02:w.expected==='blue'?w.blue>0.95&&w.red<0.02:
      w.expected==='red'?w.red>0.95&&w.blue<0.02:w.red>0.3&&w.blue>0.3)),observed);
  } else if(id==='G4') {
    const zones=[[350,'green'],[1050,'yellow'],[1750,'red'],[3800,'green'],[4550,'red'],[5050,'yellow']];
    check('three exclusive zones',zones.every(([at,color])=>['red','yellow','green'].every(n=>fixed(trace,n,at,at+50,n===color?1:0))),zones);
    const changed=trace.edges.find(e=>e.at_ms>=3500&&e.levels.green===1&&e.levels.red===0);
    check('LED responds within 250 ms while beeping',changed&&changed.at_ms-3500<=250,changed?.at_ms);
    const tone=pulses(trace,'buzzer').filter(p=>p.width<5);const groups=[];
    for(const p of tone){const last=groups.at(-1);if(!last||p.start-last.end>10)groups.push({start:p.start,end:p.end});else last.end=p.end;}
    const full=groups.filter(p=>p.start>1300&&p.end<3400);
    check('200 ms tone, 800 ms silence',full.length>=2&&full.every(p=>near(p.end-p.start,200,25))&&
      full.slice(1).every((p,i)=>near(p.start-full[i].end,800,25)),groups);
    check('buzzer silent outside red zone',[...tone].filter(p=>p.start>100&&p.start<1300).length===0,null);
  } else if(id==='G5') {
    const states=[[100,400,false],[800,1800,true],[2200,2600,true],[2900,3200,true],[3700,4000,false],[4500,5000,true]];
    check('alarm latches; press during motion remains ignored after motion stops; new press resets',
      states.every(([a,b,on])=>fixed(trace,'red',a,b,on?1:0)&&fixed(trace,'green',a,b,on?0:1)),states);
    const tone=pulses(trace,'buzzer');
    check('passive buzzer gets continuous tone only during alarm',[[800,1800],[2200,2600],[4500,5000]].every(([a,b])=>tone.filter(p=>p.start>a&&p.end<b).length>50)&&
      tone.filter(p=>p.start>3700&&p.end<4000).length===0,null);
  } else if(id==='G6') {
    const value=e=>e.levels.red+2*e.levels.yellow+4*e.levels.green;
    const at=time=>trace.samples.find(e=>e.at_ms>=time);
    const before=[150,1150,2150].map(t=>value(at(t)));
    check('binary starts 0,1,2 at one-second intervals',JSON.stringify(before)==='[0,1,2]',before);
    const reset=trace.samples.find(e=>e.at_ms>=2500&&value(e)===0);
    check('new press resets within 100 ms',reset&&reset.at_ms<=2600,reset?.at_ms);
    const held=trace.samples.filter(e=>e.at_ms>=2700&&e.at_ms<4600).map(value);
    check('count continues while button held',new Set(held).size>=2,[...new Set(held)]);
    const settled=trace.samples.filter(e=>e.at_ms>100&&!near(e.at_ms%1000,0,20));
    let changes=[];for(const e of settled)if(!changes.length||changes.at(-1).value!==value(e))changes.push({at_ms:e.at_ms,value:value(e)});
    const after=changes.filter(e=>e.at_ms>2600);
    check('binary advances and wraps every second',after.length>=6&&after.slice(1).every((e,i)=>e.value===(after[i].value+1)%8&&near(e.at_ms-after[i].at_ms,1000,30)),changes);
    check('preserved user callback executes',trace.serial.some(e=>e.line.replace(/\r$/,'')==='USER_CODE_KEEP'),trace.serial);
  }
  if(['G2','G3','G5','G6'].includes(id)) {
    const names=id==='G2'?['up','down']:['button'];
    check('button idle has internal pull-up',names.every(n=>trace.samples.some(e=>e.at_ms>100&&e.at_ms<400&&e.input_modes[n]===3)),null);
  }
  return {case:id,behavior_ok:checks.every(c=>c.ok),checks};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) {
  const [root,bindingFile]=process.argv.slice(2);
  if(!root||!bindingFile)throw Error('Usage: evidence-directory reviewed-bindings.json');
  const bindings=JSON.parse(readFileSync(bindingFile,'utf8')),out=join(root,'audit');mkdirSync(out,{recursive:true});
  const results=[];
  for(const [id,binding]of Object.entries(bindings)) {
    const spec=stimulus(id,binding),hex=readFileSync(join(root,id,'independent/build/sketch.ino.hex'),'utf8');
    const trace=runProbe(hex,spec),result=assess(id,trace);
    Object.assign(result,{firmware_sha256:trace.firmware_sha256,spec_sha256:trace.spec_sha256,method:trace.method});
    writeFileSync(join(out,id+'-spec.json'),JSON.stringify(spec));writeFileSync(join(out,id+'-trace.json'),JSON.stringify(trace));
    writeFileSync(join(out,id+'-audit.json'),JSON.stringify(result,null,2));results.push(result);
    console.log(id,result.behavior_ok?'PASS':'FAIL',result.checks.filter(c=>!c.ok).map(c=>c.requirement));
  }
  writeFileSync(join(out,'summary.json'),JSON.stringify(results,null,2));
}
