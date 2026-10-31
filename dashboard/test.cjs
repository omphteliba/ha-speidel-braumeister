const assert=require('node:assert/strict');
global.HTMLElement=class{attachShadow(){this.shadowRoot={innerHTML:'',addEventListener(){}};} dispatchEvent(){}};
global.window={};const registry={};global.customElements={get:k=>registry[k],define:(k,v)=>registry[k]=v};
require('./braumeister-display-card.js');
const Card=registry['braumeister-display-card'];const card=new Card();card.setConfig({entities:Object.fromEntries(['temperature','target','step','recipe','mode','connection','pump','heater','progress','time','alarm','plug','power','behavior'].map(key=>[key, 'test.'+key]))});
const states={};for(const id of Object.values(card.ids))states[id]={state:'unknown',attributes:{}};
const set=(k,v,attrs={})=>states[card.ids[k]]={state:v,attributes:attrs};
const calls=[];card.hass={states,callService:async(...args)=>calls.push(args)};
assert(!card.shadowRoot.innerHTML.includes('NaN'));
set('connection','online');set('plug','on');set('temperature','20.5');set('target','38');set('recipe','<img src=x onerror=alert(1)>');card.render();
assert(card.shadowRoot.innerHTML.includes('20,5 °C'));assert(card.shadowRoot.innerHTML.includes('&lt;img'));assert(!card.shadowRoot.innerHTML.includes('<img'));
assert(card.shadowRoot.innerHTML.includes('button disabled title="Benötigt'));
set('plug','off');card.render();assert(!card.shadowRoot.innerHTML.includes('20,5 °C'));
set('plug','on');set('recipe','LBZ 2026');set('step','1. Rast',{
 display_phase:'1. Rast',display_state_code:2820,display_clock:'15:17',
 display_pump_flag:'P',display_heater_flag:'i',display_time_target_seconds:1200,display_time_elapsed_seconds:27});card.render();
assert(card.shadowRoot.innerHTML.includes('LBZ 2026 – 1. Rast'));
assert(card.shadowRoot.innerHTML.includes('20 / 0:27 min'));
assert(card.shadowRoot.innerHTML.includes('class="badge inactive"'));
assert(card.shadowRoot.innerHTML.includes('>15:17</time>'));
set('plug','off');card.render();assert(!card.shadowRoot.innerHTML.includes('20 / 0:27 min'));assert(!card.shadowRoot.innerHTML.includes('>15:17</time>'));
set('plug','on');set('step','1. Rast',{display_state_code:2820,display_time_target_seconds:null,display_time_elapsed_seconds:null});card.render();assert(card.shadowRoot.innerHTML.includes('— / — min'));
set('behavior','on',{options:['off','on','previous','toggle']});card.page='power';card.render();assert(card.shadowRoot.innerHTML.includes('Vorheriger Zustand'));
(async()=>{
 await card.command('switch','turn_off',{entity_id:card.ids.plug});
 assert.deepEqual(calls[0],['switch','turn_off',{entity_id:'test.plug'}]);
 await card.command('select','select_option',{entity_id:card.ids.behavior,option:'previous'});
 assert.equal(calls[1][2].option,'previous');
 card._hass.callService=async()=>{throw Error('Testfehler')};await card.command('switch','turn_on',{});
 assert(card.shadowRoot.innerHTML.includes('Testfehler'));assert.equal(card.pending,false);
 console.log('PASS: unknown states, offline masking, HTML escaping, disabled device controls, switch/select routing, error feedback');
})().catch(e=>{console.error(e);process.exitCode=1});
