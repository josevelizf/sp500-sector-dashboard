import threading
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from flask import request, jsonify

DEFAULTS={'rsi':14,'fast':12,'slow':26,'signal':9,'volume':20}
LIMITS={'rsi':(2,100),'fast':(2,100),'slow':(3,200),'signal':(2,100),'volume':(2,200)}

def parameters(values):
    result={}
    for k,default in DEFAULTS.items():
        raw=values.get(k,default)
        number=int(raw)
        if str(number)!=str(raw) or not LIMITS[k][0]<=number<=LIMITS[k][1]:
            raise ValueError('Periodo no valido: '+k)
        result[k]=number
    if result['fast']>=result['slow']:raise ValueError('MACD rapido debe ser menor que lento')
    return result

def ema(series,period):
    valid=series.dropna();out=pd.Series(np.nan,index=series.index,dtype=float)
    if len(valid)<period:return out
    seeded=valid.iloc[period-1:].copy();seeded.iloc[0]=valid.iloc[:period].mean()
    out.loc[seeded.index]=seeded.ewm(span=period,adjust=False).mean()
    return out

def compute(frame,config):
    close=frame['Close'].dropna().astype(float)
    out={k:None for k in ['RSI','MACD','MACDSignal','MACDHist','RVOL']}
    out['asof']=str(close.index[-1].date()) if len(close) else None
    n=config['rsi']
    if len(close)>n:
        delta=close.diff().iloc[1:];gains=delta.clip(lower=0);losses=(-delta).clip(lower=0)
        gs=gains.iloc[n-1:].copy();ls=losses.iloc[n-1:].copy()
        gs.iloc[0]=gains.iloc[:n].mean();ls.iloc[0]=losses.iloc[:n].mean()
        up=float(gs.ewm(alpha=1/n,adjust=False).mean().iloc[-1]);down=float(ls.ewm(alpha=1/n,adjust=False).mean().iloc[-1])
        out['RSI']=50.0 if up==0 and down==0 else 100.0 if down==0 else 100-100/(1+up/down)
    macd=ema(close,config['fast'])-ema(close,config['slow'])
    signal=ema(macd,config['signal'])
    if len(close):
        for key,value in [('MACD',macd.iloc[-1]),('MACDSignal',signal.iloc[-1]),('MACDHist',macd.iloc[-1]-signal.iloc[-1])]:
            out[key]=float(value) if pd.notna(value) and np.isfinite(value) else None
        volume=frame['Volume'].reindex(close.index).astype(float);n=config['volume']
        if len(volume)>n:
            window=volume.iloc[-n-1:-1];last=volume.iloc[-1]
            if np.isfinite(window).all() and (window>=0).all() and np.isfinite(last) and last>=0 and window.mean()>0:
                out['RVOL']=float(last/window.mean())
    return out

def install(dashboard):
    mutex=threading.RLock();histories={};cache=OrderedDict();generation=[0]
    original=dashboard.yf.download
    def download(*args,**kwargs):
        data=original(*args,**kwargs)
        ny=datetime.now(ZoneInfo('America/New_York'));cutoff=pd.Timestamp(ny.date())
        if (ny.hour,ny.minute)<(16,30):cutoff-=pd.Timedelta(days=1)
        if isinstance(data.columns,pd.MultiIndex):
            groups={str(symbol):data[symbol] for symbol in data.columns.get_level_values(0).unique()}
        else:
            symbols=args[0] if args else kwargs.get('tickers',[])
            if isinstance(symbols,str):symbols=symbols.split()
            groups={symbols[0]:data} if len(symbols)==1 else {}
        for symbol,frame in groups.items():
            if not {'Close','Volume'}.issubset(frame.columns):continue
            frame=frame[['Close','Volume']].copy();idx=pd.to_datetime(frame.index)
            if idx.tz is not None:idx=idx.tz_localize(None)
            frame.index=idx.normalize();frame=frame[~frame.index.duplicated(keep='last')].sort_index()
            frame=frame.loc[frame.index<=cutoff].dropna(subset=['Close'])
            if frame.empty:continue
            with mutex:histories[symbol]=frame;generation[0]+=1;cache.clear()
        return data
    dashboard.yf.download=download
    @dashboard.app.get('/api/indicators')
    def indicators():
        try:config=parameters(request.args)
        except (TypeError,ValueError) as error:return jsonify(error=str(error)),400
        with mutex:
            version=generation[0];key=(version,tuple(config.values()))
            if key in cache:
                cache.move_to_end(key);return jsonify(cache[key])
            frames=dict(histories)
        with dashboard.lock:tickers=[r['ticker'] for r in dashboard.state['rows']]
        result={}
        for ticker in tickers:
            frame=frames.get(ticker.replace('.','-'))
            if frame is not None:
                try:result[ticker]=compute(frame,config)
                except (ValueError,IndexError,KeyError):pass
        payload={'parameters':config,'data':result,'available':len(frames)}
        with mutex:
            if generation[0]==version:
                cache[key]=payload
                while len(cache)>8:cache.popitem(last=False)
        return jsonify(payload)
    html=dashboard.HTML
    def replace(old,new):
        nonlocal html
        if old not in html:raise RuntimeError('Technical UI target missing: '+old[:60])
        html=html.replace(old,new,1)
    replace("periods=['1D','5D','10D','1M','3M','6M','YTD','1A']", "periods=['1D','5D','10D','1M','3M','6M','YTD','1A','RSI','MACD','MACDSignal','MACDHist','RVOL']")
    replace('de 13 columnas','de ${cols.length} columnas')
    replace("Number.isFinite(v)?(v>0?'+':'')+v.toFixed(2)+'%':'N/D'",'formatTechnical(k,v)')
    replace("td.className='num '+(v>0?'pos':v<0?'neg':'');", "td.className='num '+technicalColor(k,v);")
    replace('}}checks();','}}labelIndicators();checks();')
    replace('prices=s.prices||{};','prices=s.prices||{};await loadTechnical();')
    replace("options('sector',[],'sector','Todos los sectores');", "setupTechnical();options('sector',[],'sector','Todos los sectores');")
    form='''<details class="card" open><summary>Indicadores diarios: configuracion</summary><form id="technicalForm" class="bar"><label>RSI periodo <input name="rsi" type="number" min="2" max="100" required></label><label>RSI nivel bajo <input name="low" type="number" min="0" max="99" required></label><label>RSI nivel alto <input name="high" type="number" min="1" max="100" required></label><label>MACD rapido <input name="fast" type="number" min="2" max="100" required></label><label>MACD lento <input name="slow" type="number" min="3" max="200" required></label><label>MACD senal <input name="signal" type="number" min="2" max="100" required></label><label>Volumen promedio <input name="volume" type="number" min="2" max="200" required></label><button type="submit">Aplicar parametros</button><button id="resetTechnical" type="button">Valores por defecto</button></form><p id="technicalStatus" role="status"></p><p class="note">RSI: Wilder con semilla SMA; serie plana = 50. MACD: EMAs inicializadas con SMA; histograma = MACD - senal. RVOL: volumen de la ultima sesion completa / promedio de las N anteriores, excluyendo la sesion evaluada. MACD se expresa en unidades de precio, no en porcentaje. Los colores indican niveles, no recomendaciones. Se utilizan cierres ajustados e historicos en memoria; no datos intradia ni divergencias todavia.</p></details>'''
    replace('<div class="bar">',form+'<div class="bar">')
    replace('<script>','<script>'+JS)
    dashboard.HTML=html

JS=r'''
const technicalDefaults={rsi:14,low:30,high:70,fast:12,slow:26,signal:9,volume:20};
const technicalKeys=['RSI','MACD','MACDSignal','MACDHist','RVOL'];
let technicalConfig={...technicalDefaults};
function validTechnical(c){return ['rsi','low','high','fast','slow','signal','volume'].every(k=>Number.isInteger(c[k]))&&c.rsi>=2&&c.rsi<=100&&c.low>=0&&c.high<=100&&c.low<c.high&&c.fast>=2&&c.fast<=100&&c.slow>=3&&c.slow<=200&&c.fast<c.slow&&c.signal>=2&&c.signal<=100&&c.volume>=2&&c.volume<=200}
try{let saved=JSON.parse(localStorage.getItem('sp500.technical.v1'));if(saved&&validTechnical(saved))technicalConfig=saved}catch(e){}
function labelIndicators(){let labels={RSI:`RSI (${technicalConfig.rsi})`,MACD:`MACD (${technicalConfig.fast},${technicalConfig.slow})`,MACDSignal:`Senal MACD (${technicalConfig.signal})`,MACDHist:'Hist. MACD',RVOL:`RVOL (${technicalConfig.volume})`};for(let c of cols)if(labels[c[0]])c[1]=labels[c[0]]}
function formatTechnical(k,v){if(!Number.isFinite(v))return 'N/D';if(k==='RSI')return v.toFixed(2);if(k==='RVOL')return v.toFixed(2)+'x';if(technicalKeys.includes(k))return v.toFixed(4);return (v>0?'+':'')+v.toFixed(2)+'%'}
function technicalColor(k,v){if(!Number.isFinite(v))return '';if(k==='RSI')return v>=technicalConfig.high?'neg':v<=technicalConfig.low?'pos':'';if(k==='RVOL')return v>=1?'pos':'';return v>0?'pos':v<0?'neg':''}
async function loadTechnical(){
 const snapshot=JSON.stringify(technicalConfig),query=new URLSearchParams(Object.fromEntries(['rsi','fast','slow','signal','volume'].map(k=>[k,technicalConfig[k]])));
 try{let response=await fetch('/api/indicators?'+query);if(!response.ok)throw Error(await response.text());let result=await response.json();if(snapshot!==JSON.stringify(technicalConfig))return;let matched=0;for(let [ticker,p] of Object.entries(prices)){for(let k of technicalKeys)delete p[k];let item=result.data[ticker];if(item&&item.asof===p.asof){for(let k of technicalKeys)p[k]=item[k];matched++}}document.getElementById('technicalStatus').textContent=`Indicadores disponibles para ${matched} tickers; N/D si falta historia o datos. Parametros personales guardados en este navegador.`}
 catch(e){document.getElementById('technicalStatus').textContent='No se pudieron calcular los indicadores: '+e.message}
}
function setupTechnical(){
 const form=document.getElementById('technicalForm');
 function fill(){for(let k of Object.keys(technicalDefaults))form.elements.namedItem(k).value=technicalConfig[k]}
 async function apply(c){if(!validTechnical(c)){document.getElementById('technicalStatus').textContent='Revisa los rangos: RSI bajo < alto y MACD rapido < lento.';return}technicalConfig=c;try{localStorage.setItem('sp500.technical.v1',JSON.stringify(c))}catch(e){}for(let p of Object.values(prices))for(let k of technicalKeys)delete p[k];labelIndicators();checks();render();await loadTechnical();render()}
 fill();form.onsubmit=async e=>{e.preventDefault();let c=Object.fromEntries(Object.keys(technicalDefaults).map(k=>[k,Number(form.elements.namedItem(k).value)]));await apply(c)};
 document.getElementById('resetTechnical').onclick=async()=>{await apply({...technicalDefaults});fill()};
 try{if(!localStorage.getItem('sp500.technicalColumns.v1')){technicalKeys.forEach(k=>shown.add(k));localStorage.setItem('sp500.technicalColumns.v1','yes');localStorage.setItem('sp500.cols',JSON.stringify([...shown]));checks()}}catch(e){technicalKeys.forEach(k=>shown.add(k));checks()}
}
'''
