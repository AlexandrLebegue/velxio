import {test} from 'node:test';
import assert from 'node:assert/strict';
import {flash, runProbe} from '../../scripts/avr-firmware-probe.mjs';
import {assess, highFraction, pulses, stimulus} from '../../scripts/chat-generalization-audit.mjs';

function firmware(bytes) {
  const row=[bytes.length,0,0,0,...bytes];
  row.push((-row.reduce((a,b)=>a+b,0))&255);
  return ':'+Buffer.from(row).toString('hex')+'\n:00000001FF\n';
}

test('executes actual machine code and distinguishes a floating pin from driven output',()=>{
  // LDI r16,32; OUT DDRB,r16; OUT PORTB,r16; RJMP -1.
  const trace=runProbe(firmware([0,0xe2,4,0xb9,5,0xb9,0xff,0xcf]),
    {duration_ms:2,sample_ms:0.1,outputs:{led:{pin:13},floating:{pin:12}}});
  assert.equal(trace.samples.at(-1).levels.led,1);
  assert.equal(trace.samples.at(-1).levels.floating,null);
  assert.equal(highFraction(trace,'led',1,2),1);
  assert.equal(highFraction(trace,'floating',1,2),null);
  assert.equal(trace.edge_truncated,false);
  assert.match(trace.firmware_sha256,/^[a-f0-9]{64}$/);
});

test('rejects corrupted/truncated firmware and unsupported GPIO',()=>{
  const valid=firmware([0xff,0xcf]);
  assert.throws(()=>flash(valid.replace('ffcf','ffce')),/checksum/);
  assert.throws(()=>flash(valid.split('\n')[0]),/EOF/);
  assert.throws(()=>runProbe(valid,{duration_ms:1,outputs:{bad:{pin:'A6'}}}),/Unsupported/);
});

test('hard-wired nets override ideal button stimulus rather than masking a short',()=>{
  // Read PIND into PORTB repeatedly, observing copied input bit 2 at GPIO10.
  const hex=firmware([4,0xe0,4,0xb9,9,0xb1,5,0xb9,0xfd,0xcf]);
  const input={name:'button',pin:2,initial:1,changes:[{at_ms:1,level:0}]};
  const spec={duration_ms:2,sample_ms:0.1,outputs:{copied:{pin:10}},digital_inputs:[input]};
  assert.equal(runProbe(hex,spec).samples.at(-1).levels.copied,0);
  const fixed=runProbe(hex,{...spec,digital_inputs:[{...input,fixed_level:1}]});
  assert.equal(fixed.samples.at(-1).levels.copied,1);
});

test('behavior audit rejects wrong pulse duration even with correct phase and period',()=>{
  const events=[{at_ms:0,levels:{red:0,green:0}}];
  for(let i=0;i<3;i++)events.push(
    {at_ms:i*2000+1,levels:{red:1,green:0}},
    {at_ms:i*2000+501,levels:{red:0,green:0}},
    {at_ms:i*2000+1001,levels:{red:0,green:1}},
    {at_ms:i*2000+1501,levels:{red:0,green:0}});
  const trace={edges:events,edge_truncated:false,cycles:1};
  assert.equal(pulses(trace,'red').length,3);
  const result=assess('G1',trace);
  assert.equal(result.behavior_ok,false);
  assert.equal(result.checks.find(c=>c.requirement==='150 ms pulses').ok,false);
});

test('counter stimulus includes a held reset and enough time to observe wrap',()=>{
  const spec=stimulus('G6',{outputs:{},inputs:{button:2}});
  assert.ok(spec.duration_ms>=11000);
  assert.equal(spec.digital_inputs[0].changes.at(-1).at_ms,4700);
});
