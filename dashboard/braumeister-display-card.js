/* Braumeister Display 0.3.0 — native HA telemetry card, no cloud credentials. */
(() => {
  // Entity IDs depend on the installation; configure them in the card YAML.
  const defaults = Object.fromEntries(['temperature', 'target', 'step', 'recipe', 'mode', 'connection', 'pump', 'heater', 'progress', 'time', 'alarm', 'plug', 'power', 'behavior'].map(key => [key, '']));
  const esc = v => String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  class BraumeisterDisplay extends HTMLElement {
    constructor() {
      super(); this.attachShadow({mode:'open'}); this.page='display'; this.pending=false;
      this.shadowRoot.addEventListener('click', e => {
        const b=e.target.closest('button'); if(!b || b.disabled) return;
        if(b.dataset.page) { this.page=b.dataset.page; this.render(); }
        if(b.dataset.info) this.dispatchEvent(new CustomEvent('hass-more-info', {detail:{entityId:this.ids[b.dataset.info]},bubbles:true,composed:true}));
        if(b.dataset.power) this.command('switch', b.dataset.power, {entity_id:this.ids.plug});
      });
      this.shadowRoot.addEventListener('change',e=>{
        if(e.target.id==='behavior') this.command('select','select_option',{entity_id:this.ids.behavior,option:e.target.value});
      });
    }
    setConfig(config) { this.config=config; this.ids={...defaults,...config.entities}; this.render(); }
    set hass(value) {
      const previous=this._hass; this._hass=value;
      if(!this.ids || !previous || Object.values(this.ids).some(id=>previous.states[id]!==value.states[id])) this.render();
    }
    getCardSize(){return 10;}
    getGridOptions(){return {columns:12,rows:'auto',min_columns:6};}
    state(key){return this._hass?.states[this.ids[key]]?.state;}
    text(key){const s=this.state(key);return s && !['unknown','unavailable'].includes(s)?s:'—';}
    number(key,unit){const s=this.text(key);return s!=='—' && Number.isFinite(Number(s))?Number(s).toLocaleString('de-DE',{maximumFractionDigits:1})+' '+unit:'—';}
    async command(domain,service,data){
      if(this.pending) return;
      this.pending=true; this.error=''; this.render();
      try{await this._hass.callService(domain,service,data);}
      catch(e){this.error=e.message || 'Aktion fehlgeschlagen';}
      finally{this.pending=false;this.render();}
    }
    render(){
      if(!this.config || !this._hass) return;
      const E=esc, off=this.state('plug')==='off', online=this.state('connection')==='online'&&!off;
      const reading=k=>online?this.number(k,'°C'):'—';
      const attrs=this._hass.states[this.ids.step]?.attributes||{};
      const live=online && !['unknown','unavailable',undefined].includes(this.state('step'));
      const flag=k=>live?attrs[k==='pump'?'display_pump_flag':'display_heater_flag']:null;
      const badgeClass=k=>!online?'':flag(k)?(['P','H'].includes(flag(k))?'active':['q','i'].includes(flag(k))?'inactive':''):['Ein','on'].includes(this.state(k))?'active':'';
      const duration=v=>Number.isInteger(v)&&v>=0?`${Math.floor(v/60)}:${String(v%60).padStart(2,'0')}`:'—';
      const targetTime=attrs.display_time_target_seconds;
      const targetLabel=Number.isInteger(targetTime)&&targetTime>=0?(targetTime%60?duration(targetTime):String(targetTime/60)):'—';
      const timed=live && Number.isInteger(attrs.display_state_code) && attrs.display_state_code>=2810 && attrs.display_state_code<2910;
      const timer=timed?`<div class="temp timer"><div>Zeit<small>Soll / Ist · verstrichen</small></div><strong>${targetLabel} / ${duration(attrs.display_time_elapsed_seconds)} min</strong></div>`:'';
      const heading=live&&attrs.display_phase?[this.text('recipe'),attrs.display_phase].filter(v=>v!=='—').join(' – '):this.text('step');
      const badge=(k,label)=>`<button data-info="${k}" class="badge ${badgeClass(k)}" title="${label}: ${E(['q','i'].includes(flag(k))?'Inaktiv (Zwischenzustand)':this.text(k))} (Integrationsmeldung)">${label}</button>`;
      const row=(label,key,unit)=>`<div class="row"><span>${label}</span><button class="value" data-info="${key}">${E(unit?this.number(key,unit):this.text(key))}</button></div>`;
      const title={display:heading,recipe:'Aktuelles Rezept',power:'Stromversorgung',details:'Gerätedaten'}[this.page];
      let body='';
      if(this.page==='display') body=`<h2>${E(this.config.title||'Speidels Braumeister')}</h2><div class="temp"><div>Temp<small>Soll / Ist</small></div><strong>${reading('target')} / ${reading('temperature')}</strong></div>${timer}<p class="phase">${E(online?this.text('step'):(off?'Zwischenstecker ausgeschaltet':'Keine Online-Verbindung'))}</p><div class="sub">${E(this.text('recipe'))}</div><div class="keys" aria-label="Braumeister-Steuerung noch nicht verfügbar">${[['✕','Abbruch'],['P','Pumpe'],['H','Heizung'],['↕','Temperatur']].map(([icon,label])=>`<div><button disabled title="Benötigt einen Steuerdienst der Integration">${icon}</button><small>${label}</small></div>`).join('')}</div><p class="hint">Live-Anzeige · Braumeister-Steuerung noch nicht verfügbar</p>`;
      if(this.page==='recipe') body=`<h2>${E(this.text('recipe'))}</h2>${row('Aktueller Schritt','step')}${row('Gemeldeter Fortschritt','progress','%')}${row('Gemeldete Zeit¹','time','min')}<p class="hint">¹ Zeitwert der Integration, noch nicht als Restzeit verifiziert. Rezeptliste und Rastplan werden von den vorhandenen Entitäten nicht bereitgestellt.</p>`;
      if(this.page==='details') body=`<h2>Braumeister 20L Plus</h2>${row('Verbindung','connection')}${row('Modus','mode')}${row('Pumpe · gemeldet','pump')}${row('Heizung · gemeldet','heater')}<p class="hint">P/H zeigen die Meldung der Integration. Die Anzeige übernimmt die Sensorwerte; für korrekte XHR-Zustände wird der Parser-Fix aus PR #8 benötigt.</p>`;
      if(this.page==='power') {
        const options=this._hass.states[this.ids.behavior]?.attributes.options||[];
        const available=['on','off'].includes(this.state('plug'));
        const disabled=this.pending||!available?'disabled':'';
        body=`<h2>Zwischenstecker</h2>${row('Schaltzustand','plug')}${row('Gesamtleistung','power','W')}<div class="power-buttons"><button data-power="turn_on" ${disabled}>Einschalten</button><button data-power="turn_off" ${disabled}>Ausschalten</button></div><label>Nach Stromausfall<select id="behavior" ${this.pending||!options.length?'disabled':''}><option disabled ${!options.includes(this.state('behavior'))?'selected':''}>Bitte wählen</option>${options.map(o=>`<option value="${E(o)}" ${this.state('behavior')===o?'selected':''}>${E(({on:'Ein',off:'Aus',previous:'Vorheriger Zustand',toggle:'Zustand umkehren'})[o]||o)}</option>`).join('')}</select></label><p class="hint">Schaltet die gesamte Stromversorgung des Braumeisters.</p>`;
      }
      this.shadowRoot.innerHTML=`<style>
      :host{display:block;color:#080808;font-family:Arial,sans-serif;container-type:inline-size}*{box-sizing:border-box}
      ha-card{display:block;background:linear-gradient(135deg,#505050,#060606);padding:clamp(14px,5cqw,34px);border-radius:16px;color:#080808;overflow:hidden}
      .screen{background:#f4f4f4;box-shadow:inset 0 0 15px #999;min-height:360px}
      header{display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:6px solid black;font-size:13px;min-height:49px}header .title{flex:1;overflow-wrap:anywhere}
      button,select{font:inherit}button{cursor:pointer;border:0}button:focus-visible,select:focus-visible{outline:3px solid #008bd2;outline-offset:3px}
      .badge{border:2px solid black;background:transparent;padding:2px 5px;color:black}.badge.active{background:#ffda16}.badge.inactive{background:linear-gradient(45deg,#f4f4f4 50%,#ffda16 50%)}.timer{margin-top:24px}
      main{padding:22px clamp(14px,4cqw,28px);min-height:290px}h2{font-size:clamp(20px,5cqw,34px);margin:4px 0 26px;overflow-wrap:anywhere}
      .temp{display:flex;justify-content:space-between;gap:12px;font-size:clamp(19px,4.6cqw,32px);font-weight:bold}.temp strong{text-align:right}.temp small{font-size:12px;display:block;font-weight:normal;margin-top:6px}
      .phase{font-size:clamp(19px,4cqw,28px);font-weight:bold;margin:24px 0 8px;overflow-wrap:anywhere}.sub{font-size:14px}
      .keys{display:flex;justify-content:space-between;gap:8px;margin-top:32px;text-align:center}.keys button{background:#ffda16;border-radius:10px;font-size:36px;font-weight:bold;width:56px;height:56px;color:black}.keys button:disabled{opacity:.4;cursor:not-allowed}small{display:block;font-size:11px;margin-top:7px}
      .hint{font-size:12px;line-height:1.5;color:#555;margin:20px 0 0}.row{display:flex;justify-content:space-between;gap:16px;padding:12px 0;border-bottom:1px solid #ddd;font-size:14px}.value{background:transparent;color:black;font-weight:bold;text-align:right;overflow-wrap:anywhere;max-width:65%}
      footer{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:24px}footer button{color:white;background:none;padding:0;font-size:11px}footer .ring{display:grid;place-items:center;margin:0 auto 10px;width:clamp(42px,11cqw,74px);height:clamp(42px,11cqw,74px);aspect-ratio:1;border:5px solid #f4f4f4;border-radius:50%;font-size:22px}footer button[aria-pressed=true] .ring{border-color:#ffda16;background:black;color:#ffda16}
      .power-buttons{display:flex;gap:12px;margin:20px 0}.power-buttons button{padding:14px;background:#ffda16;border-radius:8px;color:black;flex:1;font-weight:bold}.power-buttons button:disabled{opacity:.4;cursor:not-allowed}label{display:block;font-size:14px}select{display:block;width:100%;margin-top:8px;padding:12px;background:white;color:black;border:1px solid #888;border-radius:6px}.notice{padding:10px 16px;background:#ffda16;font-size:13px}.error{background:#ffd3d3;padding:12px;overflow-wrap:anywhere}
      </style><ha-card><div class="screen"><header><span class="title">${E(title)}</span>${live&&attrs.display_clock?`<time title="Vom Braumeister gemeldete Uhrzeit">${E(attrs.display_clock)}</time>`:''}${badge('pump','P')}${badge('heater','H')}</header>${this.state('alarm')==='on'?'<div class="notice">Alarm vom Braumeister gemeldet</div>':''}<main>${body}</main>${this.error?`<div class="error" role="alert">${E(this.error)}</div>`:''}</div><footer>${[['display','▣','Display'],['recipe','☷','Rezept'],['power','⏻','Strom'],['details','ⓘ','Status']].map(([p,i,t])=>`<button data-page="${p}" aria-pressed="${this.page===p}"><span class="ring">${i}</span>${t}</button>`).join('')}</footer></ha-card>`;
    }
  }
  if(!customElements.get('braumeister-display-card')) customElements.define('braumeister-display-card',BraumeisterDisplay);
  window.customCards=window.customCards||[];
  window.customCards.push({type:'braumeister-display-card',name:'Braumeister Display',description:'Live-Anzeige und Zwischenstecker, Version 0.3.0'});
})();
