import json
import numpy as np

SETTINGS=[('ema8','EMA8','EMA',8),('ema21','EMA21','EMA',21),('sma50','SMA50','SMA',50),('sma100','SMA100','SMA',100),('sma200','SMA200','SMA',200)]
KEYS=[key+suffix for _,key,_,_ in SETTINGS for suffix in ['', '_pts', '_pct']]

def moving_metrics(series,config,ema):
    close=series.replace([np.inf,-np.inf],np.nan).dropna().astype(float)
    out={key:None for key in KEYS}
    if close.empty:return out
    price=float(close.iloc[-1])
    for parameter,key,kind,default in SETTINGS:
        period=config.get(parameter,default)
        if len(close)<period:continue
        average=float(ema(close,period).iloc[-1]) if kind=='EMA' else float(close.iloc[-period:].mean())
        if not np.isfinite(average):continue
        out[key]=average;out[key+'_pts']=price-average
        out[key+'_pct']=(price/average-1)*100 if average!=0 else None
    return out

def install(dashboard):
    import technical as core
    for parameter,_,_,default in SETTINGS:
        core.DEFAULTS[parameter]=default;core.LIMITS[parameter]=(2,400)
    original_compute=core.compute
    def compute(frame,config):
        out=original_compute(frame,config)
        out.update(moving_metrics(frame['Close'],config,core.ema))
        return out
    core.compute=compute
    script=core.JS
    def change(old,new):
        nonlocal script
        if old not in script:raise RuntimeError('Moving average JS target missing: '+old[:60])
        script=script.replace(old,new,1)
    change('volume:20};','volume:20,ema8:8,ema21:21,sma50:50,sma100:100,sma200:200};')
    change("const technicalKeys=['RSI','MACD','MACDSignal','MACDHist','RVOL'];", "const technicalKeys="+json.dumps(['RSI','MACD','MACDSignal','MACDHist','RVOL']+KEYS)+';')
    change("['rsi','low','high','fast','slow','signal','volume'].every", "['rsi','low','high','fast','slow','signal','volume','ema8','ema21','sma50','sma100','sma200'].every")
    change('c.volume>=2&&c.volume<=200}',"c.volume>=2&&c.volume<=200&&['ema8','ema21','sma50','sma100','sma200'].every(k=>c[k]>=2&&c[k]<=400)}")
    change('if(saved&&validTechnical(saved))','if(saved)saved={...technicalDefaults,...saved};if(saved&&validTechnical(saved))')
    change("['rsi','fast','slow','signal','volume'].map", "['rsi','fast','slow','signal','volume','ema8','ema21','sma50','sma100','sma200'].map")
    for old,new in [('function labelIndicators(){','function labelCoreIndicators(){'),('function formatTechnical(k,v){','function formatCoreTechnical(k,v){'),('function technicalColor(k,v){','function coreTechnicalColor(k,v){'),('function setupTechnical(){','function setupCoreTechnical(){')]:change(old,new)
    change('Revisa los rangos: RSI bajo < alto y MACD rapido < lento.','Revisa los rangos: RSI bajo < alto, MACD rapido < lento y periodos de medias entre 2 y 400.')
    script+='\nconst maSettings='+json.dumps(SETTINGS)+';\nconst movingKeys='+json.dumps(KEYS)+';\n'+EXTRA_JS
    core.JS=script
    core.install(dashboard)
    html=dashboard.HTML
    old="periods=['1D','5D','10D','1M','3M','6M','YTD','1A','RSI','MACD','MACDSignal','MACDHist','RVOL']"
    if old not in html:raise RuntimeError('Moving average column target missing')
    html=html.replace(old, 'periods='+json.dumps(['1D','5D','10D','1M','3M','6M','YTD','1A','RSI','MACD','MACDSignal','MACDHist','RVOL']+KEYS),1)
    controls=''.join('<label>'+kind+' '+str(default)+' periodo <input name="'+parameter+'" type="number" min="2" max="400" required></label>' for parameter,_,kind,default in SETTINGS)
    old='<button type="submit">Aplicar parametros</button>'
    if old not in html:raise RuntimeError('Moving average form target missing')
    html=html.replace(old,controls+old,1)
    note='<p class="note">Medias sobre cierres diarios ajustados. EMA con semilla SMA; SMA usa N cierres. Distancia en puntos = cierre - media; distancia % = (cierre / media - 1) x 100. Positivo: por encima; negativo: por debajo. Puntos expresados en unidades de precio ajustado por accion, no puntos porcentuales ni ticks. Se utiliza el mismo cierre que para los rendimientos y los demas indicadores. N/D si no hay N sesiones. Los nombres de columna reflejan el periodo elegido.</p>'
    html=html.replace('<p id="technicalStatus" role="status"></p>','<p id="technicalStatus" role="status"></p>'+note,1)
    dashboard.HTML=html

EXTRA_JS=r'''
function labelIndicators(){labelCoreIndicators();for(let [parameter,key,kind] of maSettings){const name=kind+' '+technicalConfig[parameter];for(let c of cols){if(c[0]===key)c[1]=name;if(c[0]===key+'_pts')c[1]='Dist. '+name+' pts';if(c[0]===key+'_pct')c[1]='Dist. '+name+' %'}}}
function formatTechnical(k,v){if(!movingKeys.includes(k))return formatCoreTechnical(k,v);if(!Number.isFinite(v))return 'N/D';if(k.endsWith('_pct'))return (v>0?'+':'')+v.toFixed(2)+'%';if(k.endsWith('_pts'))return (v>0?'+':'')+v.toFixed(2);return v.toFixed(2)}
function technicalColor(k,v){if(!movingKeys.includes(k))return coreTechnicalColor(k,v);if(!Number.isFinite(v))return '';if(k.endsWith('_pts')||k.endsWith('_pct'))return v>0?'pos':v<0?'neg':'';return ''}
function setupTechnical(){setupCoreTechnical();try{if(!localStorage.getItem('sp500.movingColumns.v1')){movingKeys.forEach(k=>shown.add(k));localStorage.setItem('sp500.movingColumns.v1','yes');localStorage.setItem('sp500.cols',JSON.stringify([...shown]));checks()}}catch(e){movingKeys.forEach(k=>shown.add(k));checks()}}
'''
