# UI-only extension, loaded by Gunicorn from the repository root.
def post_worker_init(worker):
    import app as dashboard
    html = dashboard.HTML
    def replace(old, new):
        nonlocal html
        if old not in html:
            raise RuntimeError('UI patch target not found: ' + old[:70])
        html = html.replace(old, new, 1)
    css = '''<style>
#marketTable{table-layout:fixed;width:max-content;min-width:0}
#marketTable th,#marketTable td{overflow:hidden;text-overflow:ellipsis;box-sizing:border-box}
#marketTable th{padding-right:20px}
.column-grip{position:absolute;right:0;top:0;bottom:0;width:10px;cursor:col-resize;touch-action:none;user-select:none;background:transparent;z-index:3}
.column-grip:hover,.column-grip:focus{background:rgba(255,255,255,.3);outline:1px solid #9bc9ff}
body.resizing-columns,body.resizing-columns *{cursor:col-resize!important;user-select:none!important}
</style>'''
    js = r'''
let columnWidths={};let resizingColumn=false;let deferredRender=false;
const widthStorage='sp500.columnWidths.v1';
const initialWidths={name:230,ticker:95,sector:190,industry:250,sub:290};
try{let saved=JSON.parse(localStorage.getItem(widthStorage));if(saved&&typeof saved==='object'&&!Array.isArray(saved)){for(let [k,v] of Object.entries(saved))if(Number.isFinite(v))columnWidths[k]=Math.max(55,Math.min(1200,v))}}catch(e){}
function persistWidths(){try{localStorage.setItem(widthStorage,JSON.stringify(columnWidths))}catch(e){}}
function widthFor(k){return columnWidths[k]||initialWidths[k]||95}
function resizeTable(){
 const active=cols.filter(c=>shown.has(c[0]));const table=document.getElementById('marketTable'),group=document.getElementById('columnSizes');
 group.replaceChildren();let total=0;
 for(let [k] of active){let col=document.createElement('col'),w=widthFor(k);col.style.width=w+'px';group.append(col);total+=w}
 table.style.width=Math.max(1,total)+'px';
 [...document.getElementById('head').children].forEach((th,index)=>{
  const k=active[index][0];let grip=document.createElement('span');grip.className='column-grip';grip.tabIndex=0;grip.setAttribute('role','separator');grip.setAttribute('aria-orientation','vertical');grip.setAttribute('aria-label','Ajustar ancho: '+active[index][1]);grip.setAttribute('aria-valuemin','55');grip.setAttribute('aria-valuemax','1200');grip.setAttribute('aria-valuenow',String(widthFor(k)));grip.title='Arrastra para cambiar el ancho. Flechas: ajustar. Doble clic: restablecer.';
  function setWidth(w){columnWidths[k]=Math.round(Math.max(55,Math.min(1200,w)));group.children[index].style.width=columnWidths[k]+'px';table.style.width=active.reduce((sum,[key])=>sum+widthFor(key),0)+'px';grip.setAttribute('aria-valuenow',String(columnWidths[k]))}
  grip.addEventListener('click',e=>{e.preventDefault();e.stopPropagation()});
  grip.addEventListener('dblclick',e=>{e.preventDefault();e.stopPropagation();delete columnWidths[k];persistWidths();render()});
  grip.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();e.stopPropagation();setWidth(widthFor(k)+(e.key==='ArrowRight'?10:-10));persistWidths()}});
  grip.addEventListener('pointerdown',e=>{
   if(e.button!==0)return;e.preventDefault();e.stopPropagation();const startX=e.clientX,startWidth=widthFor(k);resizingColumn=true;document.body.classList.add('resizing-columns');grip.setPointerCapture(e.pointerId);
   function move(ev){if(ev.pointerId===e.pointerId)setWidth(startWidth+ev.clientX-startX)}
   function finish(ev){if(ev.pointerId!==e.pointerId)return;grip.removeEventListener('pointermove',move);grip.removeEventListener('pointerup',finish);grip.removeEventListener('pointercancel',finish);grip.removeEventListener('lostpointercapture',finish);resizingColumn=false;document.body.classList.remove('resizing-columns');persistWidths();if(deferredRender){deferredRender=false;requestAnimationFrame(()=>{if(!resizingColumn)render();else deferredRender=true})}}
   grip.addEventListener('pointermove',move);grip.addEventListener('pointerup',finish);grip.addEventListener('pointercancel',finish);grip.addEventListener('lostpointercapture',finish);
  });th.append(grip)
 });
 const reset=document.getElementById('resetWidths');if(reset&&!reset.dataset.ready){reset.dataset.ready='yes';reset.onclick=()=>{columnWidths={};persistWidths();render()}}
}
function render(){if(resizingColumn){deferredRender=true;return}renderTable();resizeTable()}
function dateSummary(s){
 const dates=[...new Set(Object.values(s.prices||{}).map(p=>p.asof).filter(Boolean))].sort();
 if(!dates.length)return 'Fecha de cierre: pendiente. ';
 if(dates.length===1)return 'Datos al cierre: '+dates[0]+'. ';
 return 'Cierres entre '+dates[0]+' y '+dates[dates.length-1]+' (hay datos de fechas distintas). ';
}
'''
    replace('</style>', '</style>' + css)
    replace('<table>', '<table id="marketTable"><colgroup id="columnSizes"></colgroup>')
    replace('<button id="all">Mostrar todas</button>', '<button id="all">Mostrar todas</button> <button id="resetWidths">Restablecer anchos</button> <span class="note">Arrastra el borde derecho de los encabezados para ajustar el ancho.</span>')
    replace('function render(){', 'function renderTable(){')
    replace("else td.textContent=(v??'')+(k==='ticker'&&p?.asof?' · '+p.asof:'');", "else td.textContent=v??'';")
    replace("td.title=(p?.asof?'Cierre: '+p.asof:'Sin historico')+(p?.error?' · '+p.error:'');", "td.title=p?.error||String(v??'');")
    replace("+(s.updated?'Consulta: '+new Date(s.updated).toLocaleString():'');", "+dateSummary(s)+(s.updated?'Actualizado: '+new Date(s.updated).toLocaleString():'');")
    replace('Fecha de cierre junto al ticker y sobre cada celda.', 'Fecha de cierre y hora de actualizacion en el resumen superior; los tickers se muestran sin fechas.')
    replace('<script>', '<script>' + js)
    dashboard.HTML = html
