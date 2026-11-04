#!/usr/bin/env node
// Independent, headless ATmega328P I/O trace. No model calls or UI simulation.
// The stimulus specification stays outside the agent workspace.
import {createRequire} from 'node:module';
import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const avr = require('avr8js');
const sha = raw => createHash('sha256').update(raw).digest('hex');

export function flash(hex) {
  const bytes = new Uint8Array(32768);
  let base = 0, eof = false;
  for (const text of hex.trim().split(/\r?\n/)) {
    if (!/^:[\da-f]+$/i.test(text) || text.length % 2 !== 1) throw Error('Invalid HEX record');
    const row = Buffer.from(text.slice(1), 'hex');
    if (row.length !== row[0] + 5 || [...row].reduce((a,b)=>a+b,0) % 256) throw Error('HEX checksum/length mismatch');
    const address = row.readUInt16BE(1), type = row[3], data = row.subarray(4,-1);
    if (type === 0) {
      if (base + address + data.length > bytes.length) throw Error('Firmware exceeds ATmega328P flash');
      bytes.set(data, base + address);
    } else if (type === 1) { eof = true; break; }
    else if (type === 2) base = data.readUInt16BE(0) * 16;
    else if (type === 4) base = data.readUInt16BE(0) * 65536;
    else if (type !== 3 && type !== 5) throw Error('Unsupported HEX record');
  }
  if (!eof) throw Error('HEX has no EOF');
  const words = new Uint16Array(16384);
  for (let i=0;i<bytes.length;i+=2) words[i/2] = bytes[i] | bytes[i+1]<<8;
  return words;
}

function pin(ports, value) {
  const name = String(value).replace(/^D/, '');
  const number = /^A[0-5]$/.test(name) ? 14+Number(name.slice(1)) : /^\d+$/.test(name) ? Number(name) : -1;
  if (number < 0 || number > 19) throw Error('Unsupported ATmega328P digital pin: '+value);
  return number < 8 ? [ports.D,number] : number < 14 ? [ports.B,number-8] : [ports.C,number-14];
}

export function runProbe(hex, spec) {
  if (!(spec.duration_ms > 0 && spec.duration_ms <= 20000)) throw Error('duration_ms must be 0..20000');
  const frequency = 16000000;
  const cpu = new avr.CPU(flash(hex), 2048);
  const ports = {B:new avr.AVRIOPort(cpu,avr.portBConfig), C:new avr.AVRIOPort(cpu,avr.portCConfig), D:new avr.AVRIOPort(cpu,avr.portDConfig)};
  new avr.AVRTimer(cpu, avr.timer0Config);
  new avr.AVRTimer(cpu, avr.timer1Config);
  new avr.AVRTimer(cpu, avr.timer2Config);
  const adc = new avr.AVRADC(cpu, avr.adcConfig);
  adc.avcc = spec.avcc ?? 5;adc.aref = spec.aref ?? 5;
  const uart = new avr.AVRUSART(cpu, avr.usart0Config, frequency);
  const serial = [];
  uart.onLineTransmit = line => { if (serial.length<1000) serial.push({at_ms:cpu.cycles/16000,line}); };
  const outputs = Object.entries(spec.outputs ?? {}).map(([name, output]) => ({name,...output, binding: output.pin===undefined ? null : pin(ports, output.pin)}));
  const inputs = (spec.digital_inputs ?? []).map(input => ({...input,binding:pin(ports,input.pin)}));
  const state = output => output.binding ? output.binding[0].pinState(output.binding[1]) : output.constant ? avr.PinState.High : avr.PinState.Low;
  const level = output => {const value=state(output);return value===avr.PinState.High ? 1 : value===avr.PinState.Low ? 0 : null;};
  const edges = [], samples = [];
  let previous = {}, edgeTruncated = false;
  function observe() {
    const levels = Object.fromEntries(outputs.map(o=>[o.name,level(o)]));
    const modes = Object.fromEntries(outputs.map(o=>[o.name,state(o)]));
    if (outputs.some(o=>previous[o.name]!==modes[o.name])) {
      if (edges.length < (spec.edge_limit ?? 100000)) edges.push({at_ms:cpu.cycles/16000,levels,modes});
      else edgeTruncated = true;
      previous = modes;
    }
  }
  for (const port of Object.values(ports)) port.addListener(observe);
  const at = (ms,callback) => cpu.addClockEvent(callback, Math.max(1,Math.round(ms*16000)));
  for (const input of inputs) {
    // A hard-wired supply/ground net overrides requested fixture transitions.
    // This prevents an ideal input fixture from hiding an actual wiring fault.
    input.binding[0].setPin(input.binding[1], Boolean(input.fixed_level ?? input.initial));
    if (input.fixed_level === undefined)
      for (const change of input.changes ?? []) at(change.at_ms,()=>input.binding[0].setPin(input.binding[1],Boolean(change.level)));
  }
  for (const input of spec.analog_inputs ?? []) {
    if (!(Number.isInteger(input.channel) && input.channel>=0 && input.channel<8)) throw Error('Invalid ADC channel');
    adc.channelValues[input.channel] = input.initial;
    for (const change of input.changes ?? []) at(change.at_ms,()=>{adc.channelValues[input.channel]=change.voltage;});
  }
  let echoTriggers = 0;
  if (spec.ultrasonic) {
    const sensor = spec.ultrasonic, trigger = pin(ports,sensor.trigger), echo = pin(ports,sensor.echo);
    echo[0].setPin(echo[1],false);
    let wasHigh = false, rise = 0;
    trigger[0].addListener(()=>{
      const high = trigger[0].pinState(trigger[1])===avr.PinState.High;
      if (high && !wasHigh) rise=cpu.cycles;
      if (!high && wasHigh && cpu.cycles-rise>=8*16) {
        const time=cpu.cycles/16000;
        const distance=[...sensor.distances].reverse().find(d=>d.at_ms<=time)?.cm;
        if (distance!==undefined && distance!==null) {
          echoTriggers++;
          cpu.addClockEvent(()=>echo[0].setPin(echo[1],true),1600);
          cpu.addClockEvent(()=>echo[0].setPin(echo[1],false),1600+Math.round(distance*58*16));
        }
      }
      wasHigh=high;
    });
  }
  const period = spec.sample_ms ?? 10;
  if (!(period>=0.1)) throw Error('sample_ms must be at least 0.1');
  function sample() {
    samples.push({at_ms:cpu.cycles/16000,levels:Object.fromEntries(outputs.map(o=>[o.name,level(o)])),
                  input_modes:Object.fromEntries(inputs.map(i=>[i.name??String(i.pin),i.binding[0].pinState(i.binding[1])]))});
    cpu.addClockEvent(sample,Math.round(period*16000));
  }
  observe();sample();
  const end=Math.round(spec.duration_ms*16000),started=performance.now();
  while (cpu.cycles<end) {avr.avrInstruction(cpu);cpu.tick();}
  observe();
  return {method:'actual AVR firmware under avr8js with ideal deterministic external inputs; no browser/physical-device proof',
          avr8js_version:require('avr8js/package.json').version,firmware_sha256:sha(hex),spec_sha256:sha(JSON.stringify(spec)),
          cpu_hz:frequency,cycles:cpu.cycles,seconds:Number(((performance.now()-started)/1000).toFixed(3)),
          edge_truncated:edgeTruncated,echo_triggers:echoTriggers,edges,samples,serial};
}

if (process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  const args=Object.fromEntries(process.argv.slice(2).reduce((pairs,value,index,all)=>index%2===0?[...pairs,[value.replace(/^--/,''),all[index+1]]]:pairs,[]));
  if (!args.hex || !args.spec || !args.out) throw Error('Usage: --hex firmware.hex --spec inputs.json --out trace.json');
  const result=runProbe(readFileSync(args.hex,'utf8'),JSON.parse(readFileSync(args.spec,'utf8')));
  writeFileSync(args.out,JSON.stringify(result)+'\n');
  process.stdout.write(JSON.stringify({cycles:result.cycles,seconds:result.seconds,edges:result.edges.length,edge_truncated:result.edge_truncated})+'\n');
}
