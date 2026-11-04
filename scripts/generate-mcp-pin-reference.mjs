// Extract real package pinInfo and the editor's native endpoint alias resolver.
// No browser, network, guessed pin counts, or named connection DSL.
import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const require=createRequire(process.cwd()+'/frontend/package.json');
const {JSDOM}=require('jsdom');const window=new JSDOM('<html></html>',{pretendToBeVisual:true}).window;
for(const key of ['window','document','customElements','HTMLElement','Element','Node','Document','DocumentFragment','ShadowRoot','CSSStyleSheet','CustomEvent','MutationObserver','navigator']) Object.defineProperty(globalThis,key,{value:key==='window'?window:window[key],configurable:true});
globalThis.ImageData=class ImageData {constructor(width,height){this.width=width;this.height=height;this.data=new Uint8ClampedArray(width*height*4);}};
require('@wokwi/elements');
const metadata=JSON.parse(readFileSync('frontend/public/components-metadata.json'));
const snapshot=JSON.parse(readFileSync('backend/app/mcp/compact/catalog.snapshot.json'));
const source=readFileSync('frontend/src/utils/pinPositionCalculator.ts','utf8');
const match=source.match(/export function resolvePinDescriptor\([\s\S]*?\n\}/);
// Use the already installed TypeScript compiler, not a hand-maintained alias list.
const {transformSync}=require('esbuild');
const customSource='frontend/src/components/velxio-components/Ssd1306I2cElement.ts';
new Function(transformSync(readFileSync(customSource,'utf8'),{loader:'ts'}).code)();
const transformed=transformSync(match[0].replace('export function','function'),{loader:'ts'}).code;
const resolve=new Function(transformed+'; return resolvePinDescriptor;')();
const records={};
for(const entry of snapshot.entries.filter(e=>e.kind==='component'||e.kind==='board')) {
 const m=metadata.components.find(x=>x.id===entry.key);
 const tag=m?.tagName || 'wokwi-'+entry.key;
 if(!customElements.get(tag))continue;
 const el=document.createElement(tag);
 for(const [key,value] of Object.entries(m?.defaultValues||{})) {try{el[key]=value;}catch{}}
 // pinInfo is a synchronous getter; do not render or connect the element.
 const pins=el.pinInfo?.map(p=>({name:p.name,...(Number.isFinite(p.x)&&Number.isFinite(p.y)?{x:p.x,y:p.y}:{})}));
 if(!pins?.length)continue;
 const candidates=new Set([...pins.map(p=>p.name),...pins.map(p=>p.name.split('.')[0]),'GND','GND2','3V3','3.3V','5V']);
 for(let n=0;n<64;n++)for(const prefix of ['','D','GP'])candidates.add(prefix+n);
 const aliases={};for(const name of candidates){const pin=resolve(el.pinInfo,name);if(pin)aliases[name]=pin.name;}
 const variants={};
 for(const property of m?.properties||[]) {
  if(!Array.isArray(property.options)||property.options.length>32)continue;
  const options={};const original=el[property.name];
  for(const candidate of property.options) {
   const value=typeof candidate==='object'?candidate.value:candidate;
   try{el[property.name]=value;}catch{continue;}
   const other=el.pinInfo?.map(p=>({name:p.name,...(Number.isFinite(p.x)&&Number.isFinite(p.y)?{x:p.x,y:p.y}:{})}));
   if(other?.length && JSON.stringify(other)!==JSON.stringify(pins))options[String(value)]={pins:other};
  }
  try{el[property.name]=original;}catch{}
  if(Object.keys(options).length)variants[property.name]=options;
 }
 records[entry.id]={pins,aliases,...(Object.keys(variants).length?{variants}:{})};el.remove();
}
const sha=p=>createHash('sha256').update(readFileSync(p)).digest('hex');
const sources=[customSource,'frontend/public/components-metadata.json','frontend/src/utils/pinPositionCalculator.ts','frontend/node_modules/@wokwi/elements/package.json'];
const result={schema_version:1,package_version:require('@wokwi/elements/package.json').version,sources:sources.map(path=>({path,sha256:sha(path)})),entries:records};
const output='backend/app/mcp/compact/pins.snapshot.json';const raw=JSON.stringify(result,null,2)+'\n';writeFileSync(output,raw);writeFileSync(output+'.sha256',createHash('sha256').update(raw).digest('hex')+'\n');
console.log('Extracted real pins for '+Object.keys(records).length+' catalog entries.');window.close();
