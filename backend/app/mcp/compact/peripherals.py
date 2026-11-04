"""Reviewed, composable readout and digital-control variants of catalog examples.

Options express peripheral behavior, not user prompt matching. Native endpoints
are generated from fixed driver roles; there is no named-wiring input language.
"""
import copy
import hashlib
import json

BOARDS={'type':'string','enum':['arduino-uno','arduino-nano'],'default':'arduino-uno'}
PIN=lambda default:{'type':'integer','minimum':2,'maximum':13,'default':default}
SCHEMAS={
 'example:button-led':{'board':BOARDS,'mode':{'type':'string','enum':['momentary','toggle'],'default':'momentary'},
    'button_pin':PIN(2),'led_pin':PIN(13),'debounce_ms':{'type':'integer','minimum':5,'maximum':500,'default':30},
    'resistance_ohms':{'type':'integer','minimum':10,'maximum':1000000,'default':1000},
    'led_color':{'type':'string','enum':['red','green','blue','yellow','white'],'default':'red'}},
}
for reference in ('example:uno-hcsr04','example:uno-dht22'):
    fields={'board':BOARDS,'display':{'type':'string','enum':['serial','lcd1602-i2c','ssd1306'],'default':'serial','description':'Optional LCD or OLED readout of the sensor values'},
            'alarm':{'type':'string','enum':['none','led','buzzer'],'default':'none'},
            'threshold':{'type':'number','minimum':-1000,'maximum':10000,'default':0},
            'alarm_when':{'type':'string','enum':['below','above'],'default':'below' if 'hcsr04' in reference else 'above'},
            'alarm_pin':PIN(8),'display_address':{'type':'integer','minimum':8,'maximum':119},
            'resistance_ohms':{'type':'integer','minimum':10,'maximum':1000000,'default':1000},
            'led_color':{'type':'string','enum':['red','green','blue','yellow','white'],'default':'red'}}
    if 'hcsr04' in reference:fields.update(trigger_pin=PIN(9),echo_pin=PIN(10))
    else:fields.update(sensor_pin=PIN(2),alarm_metric={'type':'string','enum':['temperature','humidity'],'default':'temperature'})
    SCHEMAS[reference]=fields


def instantiate(catalog, reference, parameters):
    from .examples import _checked
    from .projects import invalid
    from .catalog import CatalogError
    fields=SCHEMAS[reference];_checked(parameters,fields)
    values={k:copy.deepcopy(v['default']) for k,v in fields.items() if 'default' in v};values.update(parameters)
    original=catalog._entries.get(reference,{}).get('project',{}).get('code','')
    marker='digitalRead' if reference=='example:button-led' else 'pulseIn' if 'hcsr04' in reference else 'DHT'
    if marker not in original:
        raise CatalogError('unsupported','Catalog source no longer matches the reviewed peripheral driver')
    board_kind=values['board'];doc=catalog._native_fragment(catalog._entries['board:'+board_kind]);doc['boards'][0]['id']='board';doc['activeBoardId']='board'
    libraries=[]
    def part(kind,instance):
        native=catalog._native_fragment(catalog._entries['component:'+kind])['instance_template']
        native.update(id=instance,x=300+len(doc['components'])*80,y=50)
        doc['components'].append(native);return native
    def wire(left,pin,right,target):
        doc['wires'].append({'id':'w'+str(len(doc['wires'])+1),'start':{'componentId':left,'pinName':str(pin)},'end':{'componentId':right,'pinName':str(target)}})
    def led(pin):
        element=part('led','led');element['properties']['color']=values['led_color']
        resistor=part('resistor','resistor');resistor['properties']['value']=str(values['resistance_ohms'])
        wire('board',pin,'resistor','1');wire('resistor','2','led','A');wire('led','C','board','GND.1')
    if reference=='example:button-led':
        bp,lp=values['button_pin'],values['led_pin']
        if bp==lp:invalid('/parameters/led_pin',lp,'a GPIO distinct from button_pin')
        part('pushbutton','button');wire('board',bp,'button','1.l');wire('button','2.l','board','GND.1');led(lp)
        action='ledOn = !ledOn;' if values['mode']=='toggle' else 'ledOn = (stable == LOW);'
        gate='if (stable == LOW)' if values['mode']=='toggle' else ''
        code=f'''// Debounced digital input and LED output
const byte INPUT_PIN = {bp}, LED_PIN = {lp};
const unsigned long DEBOUNCE_MS = {values['debounce_ms']};
int lastRaw = HIGH, stable = HIGH;
unsigned long changedAt = 0;
bool ledOn = false;
void setup() {{ pinMode(INPUT_PIN, INPUT_PULLUP); pinMode(LED_PIN, OUTPUT); digitalWrite(LED_PIN, LOW); }}
void loop() {{
  int raw = digitalRead(INPUT_PIN);
  if (raw != lastRaw) changedAt = millis();
  if (millis() - changedAt >= DEBOUNCE_MS && raw != stable) {{
    stable = raw;
    {gate} {{ {action} digitalWrite(LED_PIN, ledOn ? HIGH : LOW); }}
  }}
  lastRaw = raw;
}}
'''
    else:
        distance='hcsr04' in reference
        pins=[values['trigger_pin'],values['echo_pin']] if distance else [values['sensor_pin']]
        if values['alarm']!='none':pins.append(values['alarm_pin'])
        if len(pins)!=len(set(pins)):invalid('/parameters',parameters,'distinct sensor and alarm GPIOs')
        sensor=part('hc-sr04' if distance else 'dht22','sensor')
        wire('board','5V','sensor','VCC');wire('board','GND.1','sensor','GND')
        includes=[];declarations=[];setup=['Serial.begin(9600);']
        if distance:
            t,e=values['trigger_pin'],values['echo_pin'];wire('board',t,'sensor','TRIG');wire('board',e,'sensor','ECHO')
            declarations += [f'const byte TRIG_PIN={t}, ECHO_PIN={e};']
            setup += ['pinMode(TRIG_PIN, OUTPUT);','pinMode(ECHO_PIN, INPUT);']
            readings=['digitalWrite(TRIG_PIN, LOW); delayMicroseconds(2);','digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10); digitalWrite(TRIG_PIN, LOW);',
                      'unsigned long echoUs = pulseIn(ECHO_PIN, HIGH, 30000UL);','float distanceCm = echoUs / 58.0f;']
            displays=[('Dist: ','distanceCm',' cm')];metric='distanceCm'
        else:
            pin=values['sensor_pin'];wire('board',pin,'sensor','SDA');libraries += ['DHT sensor library','Adafruit Unified Sensor']
            includes += ['#include <DHT.h>'];declarations += [f'DHT dht({pin}, DHT22);'];setup += ['dht.begin();']
            readings=['float temperature = dht.readTemperature();','float humidity = dht.readHumidity();','if (isnan(temperature) || isnan(humidity)) { delay(2000); return; }']
            displays=[('Temp: ','temperature',' C'),('RH: ','humidity',' %')];metric=values['alarm_metric']
        display=values['display']
        if display!='serial':
            includes += ['#include <Wire.h>'];libraries += ['Wire']
            screen=part('ssd1306-i2c-4pin' if display=='ssd1306' else display,'display');wire('board','A4','display','SDA');wire('board','A5','display','SCL')
            wire('board','5V','display','VCC');wire('board','GND.1','display','GND')
            address=values.get('display_address',0x27 if display=='lcd1602-i2c' else 0x3c)
            screen['properties']['i2cAddress']=hex(address)
            if display=='lcd1602-i2c':
                includes += ['#include <LiquidCrystal_I2C.h>'];libraries += ['LiquidCrystal I2C'];declarations += [f'LiquidCrystal_I2C screen({address}, 16, 2);'];setup += ['screen.init(); screen.backlight();']
                show=['screen.clear();']+[f'screen.setCursor(0,{i}); screen.print("{label}"); screen.print({value},1); screen.print("{unit}");' for i,(label,value,unit) in enumerate(displays)]
            else:
                includes += ['#include <Adafruit_GFX.h>','#include <Adafruit_SSD1306.h>'];libraries += ['Adafruit SSD1306','Adafruit GFX Library','Adafruit BusIO']
                declarations += ['Adafruit_SSD1306 screen(128, 64, &Wire, -1);'];setup += [f'if (!screen.begin(SSD1306_SWITCHCAPVCC, {address})) while(true) delay(10);','screen.setTextColor(SSD1306_WHITE); screen.setTextSize(1);']
                show=['screen.clearDisplay(); screen.setCursor(0,0);']+[f'screen.print("{label}"); screen.print({value},1); screen.println("{unit}");' for label,value,unit in displays]+['screen.display();']
        else:show=[f'Serial.print("{label}"); Serial.print({value}); Serial.println("{unit}");' for label,value,unit in displays]
        alarm=[]
        if values['alarm']!='none':
            pin=values['alarm_pin'];setup += [f'pinMode({pin}, OUTPUT);']
            if values['alarm']=='led':led(pin)
            else:part('buzzer','alarm');wire('board',pin,'alarm','1');wire('board','GND.1','alarm','2')
            comparison='<' if values['alarm_when']=='below' else '>'
            condition=f'{metric} {comparison} {values["threshold"]}'
            if distance:condition='echoUs > 0 && '+condition
            alarm=([f'digitalWrite({pin}, ({condition}) ? HIGH : LOW);'] if values['alarm']=='led' else [f'if ({condition}) tone({pin}, 1000); else noTone({pin});'])
        code='\n'.join([*includes,*declarations,'void setup() {',*['  '+s for s in setup],'}','void loop() {',*['  '+s for s in [*readings,*show,*alarm,'delay('+('200' if distance else '2000')+');']],'}',''])
    doc['boards'][0]['libraries']=list(dict.fromkeys(libraries));doc['fileGroups']['sketch']=[{'name':'sketch.ino','content':code}]
    doc['name']=catalog._entries[reference]['name']
    return doc,{'example_id':reference,'catalog_revision':catalog.revision,'recipe_version':2,'source_sha256':hashlib.sha256(original.encode()).hexdigest(),'parameters':values}
