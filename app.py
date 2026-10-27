import io, threading, time
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import yfinance as yf
from flask import Flask, jsonify, Response
app=Flask(__name__)
lock=threading.RLock()
state=dict(rows=[],prices={},busy=False,done=0,total=0,error=None,updated=None)
last=0

def calculate(series,cutoff):
    s=series.dropna().astype(float)
    idx=pd.to_datetime(s.index)
    if idx.tz is not None: idx=idx.tz_localize(None)
    s.index=idx.normalize()
    s=s[~s.index.duplicated(keep='last')].sort_index()
    s=s[s.index<=cutoff]
    if s.empty:return None
    end=s.index[-1];final=float(s.iloc[-1]);out=dict(asof=str(end.date()),error=None)
    def pct(base):return (final/base-1)*100 if base and base>0 else None
    for k,n in [('1D',1),('5D',5),('10D',10)]:out[k]=pct(float(s.iloc[-n-1]) if len(s)>n else None)
    targets={k:end-pd.DateOffset(months=n) for k,n in [('1M',1),('3M',3),('6M',6),('1A',12)]}
    targets['YTD']=pd.Timestamp(end.year,1,1)-pd.Timedelta(days=1)
    for k,d in targets.items():
        prev=s[s.index<=d];out[k]=pct(float(prev.iloc[-1]) if len(prev) else None)
    return out

def work():
    try:
        headers={'User-Agent':'Mozilla/5.0 SP500Dashboard/1.0'}
        r=requests.get('https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv',headers=headers,timeout=30);r.raise_for_status()
        df=pd.read_csv(io.StringIO(r.text),keep_default_na=False)
        if not 450<=len(df)<=600:raise ValueError('Listado de componentes inesperado')
        mapping={}
        try:
            g=requests.get('https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard',headers=headers,timeout=25);g.raise_for_status()
            for table in pd.read_html(io.StringIO(g.text)):
                if table.shape[1]==8:
                    for row in table.ffill().itertuples(index=False,name=None):mapping[str(row[7]).strip()]=str(row[5]).strip()
            if len(mapping)<100:raise ValueError('Mapa GICS no validado')
            mapping['Transaction & Payment Processing Services']='Financial Services'
        except Exception:
            mapping={}
        rows=[dict(ticker=r['Symbol'],name=r['Security'],sector=r['GICS Sector'],industry=mapping.get(r['GICS Sub-Industry'],'N/D - revisar GICS'),sub=r['GICS Sub-Industry']) for r in df.to_dict('records')]
        with lock:
            state['rows']=rows
            state['error']=None if mapping else 'No se pudo validar el mapa de industrias; sector y subindustria siguen disponibles.'
        ny=datetime.now(ZoneInfo('America/New_York'));cutoff=pd.Timestamp(ny.date())
        if (ny.hour,ny.minute)<(16,30):cutoff-=pd.Timedelta(days=1)
        with lock:todo=[r['ticker'] for r in rows if time.time()-state['prices'].get(r['ticker'],{}).get('fetched',0)>21600]
        with lock:state['total']=len(todo)
        failures=0
        for offset in range(0,len(todo),20):
            batch=todo[offset:offset+20]
            try:data=yf.download([t.replace('.','-') for t in batch],period='2y',interval='1d',auto_adjust=True,group_by='ticker',threads=False,progress=False,timeout=15)
            except Exception:data=None
            for t in batch:
                try:
                    if data is None:raise ValueError('Yahoo no disponible')
                    s=data[t.replace('.','-')]['Close'] if isinstance(data.columns,pd.MultiIndex) else data['Close']
                    item=calculate(s,cutoff)
                    if not item:raise ValueError('Sin cierres')
                    item['fetched']=time.time()
                    with lock:state['prices'][t]=item
                except Exception:
                    failures+=1
                    with lock:state['prices'][t]={**state['prices'].get(t,{}),'error':'Fallo al actualizar; cache anterior o N/D'}
            with lock:
                state['done']=offset+len(batch);state['updated']=datetime.now(ZoneInfo('UTC')).isoformat()
            if failures>=40 and failures==state['done']:break
            time.sleep(3)
        if failures:
            with lock:state['error']=(state['error'] or '')+f' {failures} consultas fallidas. Yahoo puede limitar o rechazar el acceso; revisa las fechas de cierre.'
    except Exception as e:
        with lock:state['error']=str(e)
    finally:
        with lock:state['busy']=False

@app.get('/health')
def health():return jsonify(ok=True)
@app.get('/api/state')
def api_state():
    with lock:return jsonify(state)
@app.post('/api/refresh')
def refresh():
    global last
    with lock:
        if state['busy']:return jsonify(status='busy')
        if time.time()-last<900:return jsonify(status='cooldown')
        last=time.time();state.update(busy=True,done=0,total=0,error=None)
    threading.Thread(target=work,daemon=True).start()
    return jsonify(status='started')
@app.get('/')
def home():return Response(HTML,mimetype='text/html')
HTML=r'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>S&P 500 Dashboard</title><style>body{font:14px system-ui;margin:20px;background:#f3f6fb;color:#18283f}h1{font-size:26px}.bar,.card{padding:15px;background:white;border:1px solid #d4dfed;border-radius:8px;margin:15px 0}.bar{display:flex;gap:10px;flex-wrap:wrap}input,select,button{padding:9px;border:1px solid #b8c8dd;border-radius:5px;max-width:95vw}button{background:#193e75;color:white;cursor:pointer}select{max-width:280px}#checks{display:flex;gap:14px;flex-wrap:wrap;margin:15px 0}.wrap{overflow:auto;max-height:68vh}table{border-collapse:collapse;background:white;width:100%;font-size:12px}td,th{padding:10px;white-space:nowrap;border-bottom:1px solid #dce5ef;text-align:left}th{position:sticky;top:0;background:#193e75;color:white;cursor:pointer}.num{text-align:right;font-variant-numeric:tabular-nums}.pos{color:#087438}.neg{color:#b52535}.stale{background:#fff0cc}.note{font-size:12px;line-height:1.6}#error{color:#9a4900}</style><h1>S&P 500 · Sectores y rendimientos</h1><p>Clasificacion GICS · Cierres ajustados, no intradia</p><div class="bar"><input id="q" placeholder="Compania o ticker"><select id="sector"></select><select id="industry"></select><select id="sub"></select><button id="clear">Limpiar filtros</button><button id="refresh">Actualizar datos</button><button id="csv">Exportar CSV</button></div><details class="card" open><summary>Columnas visibles</summary><div id="checks"></div><button id="all">Mostrar todas</button></details><div class="card"><div id="status" role="status" aria-live="polite">Conectando...</div><div id="error"></div><p id="count"></p></div><div class="wrap"><table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table></div><details class="card note"><summary>Metodologia, fuentes y limites</summary><p>1D/5D/10D: sesiones. 1M/3M/6M/1A: ultimo cierre en o antes de la fecha calendario correspondiente. YTD: ultimo cierre del ano anterior. Rendimiento = (cierre final/cierre de referencia - 1) x 100. Cierres ajustados por dividendos y splits de Yahoo Finance via yfinance. Se excluye hoy hasta las 16:30 de Nueva York; los cierres anticipados se incorporan conservadoramente a esa hora. Fecha de cierre junto al ticker y sobre cada celda. N/D no es cero. Filas amarillas indican error de actualizacion.</p><p>Cache en memoria de 6 horas, un intento cada 15 minutos. La primera carga puede tardar varios minutos. El servidor gratuito puede suspenderse o reiniciarse y perder la cache. Yahoo puede denegar consultas; no se garantizan datos ni disponibilidad. No es una API oficial de Yahoo. Uso personal e investigacion; revisa los <a href="https://ranaroussi.github.io/yfinance/">terminos de yfinance y Yahoo</a>.</p><p>Componentes: <a href="https://github.com/datasets/s-and-p-500-companies">datasets/s-and-p-500-companies</a>. Industria derivada de la <a href="https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard">jerarquia GICS</a>. Si no se valida, se indica N/D en lugar de adivinar. No es una composicion historica certificada. Un ticker por fila.</p></details><script>
const $=id=>document.getElementById(id),periods=['1D','5D','10D','1M','3M','6M','YTD','1A'],cols=[['name','Compania'],['ticker','Ticker'],['sector','Sector'],['industry','Industria'],['sub','Subindustria'],...periods.map(k=>[k,k])];let rows=[],prices={},filtered=[],shown=new Set(cols.map(c=>c[0])),key='sector',asc=true,first=true,loading=false;
try{let a=JSON.parse(localStorage.getItem('sp500.cols'));if(Array.isArray(a))shown=new Set(a.filter(k=>cols.some(c=>c[0]===k)))}catch(e){}
function checks(){$('checks').replaceChildren();for(let [k,n] of cols){let l=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.checked=shown.has(k);c.onchange=()=>{c.checked?shown.add(k):shown.delete(k);try{localStorage.setItem('sp500.cols',JSON.stringify([...shown]))}catch(e){}render()};l.append(c,document.createTextNode(n));$('checks').append(l)}}checks();
function options(id,list,k,text,keep=false){let old=keep?$(id).value:'',v=[...new Set(list.map(r=>r[k]))].sort();$(id).replaceChildren(new Option(text,''));v.forEach(x=>$(id).add(new Option(x,x)));$(id).value=v.includes(old)?old:''}
function sectorRows(){return rows.filter(r=>!$('sector').value||r.sector===$('sector').value)}
function industries(keep=false){options('industry',sectorRows(),'industry','Todas las industrias',keep)}
function subs(keep=false){options('sub',sectorRows().filter(r=>!$('industry').value||r.industry===$('industry').value),'sub','Todas las subindustrias',keep)}
function val(r,k){return periods.includes(k)?prices[r.ticker]?.[k]:r[k]}
function render(){let q=$('q').value.toLowerCase();filtered=sectorRows().filter(r=>(!$('industry').value||r.industry===$('industry').value)&&(!$('sub').value||r.sub===$('sub').value)&&Object.values(r).join(' ').toLowerCase().includes(q));filtered.sort((a,b)=>{let x=val(a,key),y=val(b,key);if(x==null||y==null)return x==null?(y==null?0:1):-1;return (asc?1:-1)*(periods.includes(key)?x-y:String(x).localeCompare(String(y)))||a.ticker.localeCompare(b.ticker)});let active=cols.filter(c=>shown.has(c[0]));$('head').replaceChildren();for(let [k,n] of active){let th=document.createElement('th');th.textContent=n+(key===k?(asc?' ▲':' ▼'):' ↕');th.onclick=()=>{asc=key===k?!asc:!periods.includes(k);key=k;render()};$('head').append(th)}let f=document.createDocumentFragment();for(let r of filtered){let tr=document.createElement('tr'),p=prices[r.ticker];if(p?.error)tr.className='stale';for(let [k] of active){let td=document.createElement('td'),v=val(r,k);if(periods.includes(k)){td.className='num '+(v>0?'pos':v<0?'neg':'');td.textContent=Number.isFinite(v)?(v>0?'+':'')+v.toFixed(2)+'%':'N/D'}else td.textContent=(v??'')+(k==='ticker'&&p?.asof?' · '+p.asof:'');td.title=(p?.asof?'Cierre: '+p.asof:'Sin historico')+(p?.error?' · '+p.error:'');tr.append(td)}f.append(tr)}if(!filtered.length||!active.length){let tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=Math.max(1,active.length);td.textContent=!active.length?'Activa una columna.':'Sin resultados o cargando listado...';tr.append(td);f.append(tr)}$('body').replaceChildren(f);$('count').textContent=`${filtered.length} de ${rows.length} tickers · ${active.length} de 13 columnas`}
$('sector').onchange=()=>{industries();subs();render()};$('industry').onchange=()=>{subs();render()};$('sub').onchange=render;$('q').oninput=render;$('clear').onclick=()=>{$('q').value='';$('sector').value='';industries();subs();render()};$('all').onclick=()=>{shown=new Set(cols.map(c=>c[0]));try{localStorage.setItem('sp500.cols',JSON.stringify([...shown]))}catch(e){}checks();render()};
$('csv').onclick=()=>{let active=cols.filter(c=>shown.has(c[0])),esc=v=>'"'+String(v??'').replaceAll('"','""')+'"',text=[[...active.map(c=>c[1]),'Fecha cierre','Estado'],...filtered.map(r=>[...active.map(([k])=>val(r,k)),prices[r.ticker]?.asof||'',prices[r.ticker]?.error||(!prices[r.ticker]?.asof?'Sin datos':'OK')])].map(r=>r.map(esc).join(',')).join('\r\n'),url=URL.createObjectURL(new Blob(['\ufeff'+text],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='SP500.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
async function update(){try{let r=await fetch('/api/refresh',{method:'POST'});if(!r.ok)throw Error(r.status);let s=await r.json();if(s.status==='cooldown')$('error').textContent='Espera 15 minutos entre intentos.';await poll()}catch(e){$('error').textContent='Fallo de conexion: '+e.message}}$('refresh').onclick=update;
async function poll(){if(loading)return;loading=true;try{let r=await fetch('/api/state');if(!r.ok)throw Error(r.status);let s=await r.json();rows=s.rows||[];prices=s.prices||{};options('sector',rows,'sector','Todos los sectores',true);industries(true);subs(true);$('refresh').disabled=s.busy;$('status').textContent=(s.busy?`Actualizando ${s.done}/${s.total} tickers pendientes. `:'Sin descarga en curso. ')+`Historicos: ${Object.values(prices).filter(p=>p.asof).length}. `+(s.updated?'Consulta: '+new Date(s.updated).toLocaleString():'');$('error').textContent=s.error||'';render();if(first){first=false;if(!s.busy){loading=false;await update();return}}}catch(e){$('error').textContent='Servidor no disponible: '+e.message}finally{loading=false}}
options('sector',[],'sector','Todos los sectores');industries();subs();render();poll();setInterval(poll,5000);
</script></html>'''
