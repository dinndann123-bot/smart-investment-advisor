"""Final runtime UI patch for the actually served static/index.html."""
from pathlib import Path

try:
    import fastapi.responses as _responses
    from fastapi.responses import HTMLResponse

    _PreviousFileResponse = _responses.FileResponse

    _PATCH = r'''
<style id="mobile-header-r20-css">
.brand-r20{display:flex;align-items:center;gap:12px}
.brand-r20 img{width:48px;height:48px;border-radius:12px;object-fit:contain;background:rgba(255,255,255,.12)}
.back-r20{display:none;border:1px solid rgba(255,255,255,.28);background:rgba(255,255,255,.12);color:#fff;border-radius:12px;width:44px;height:44px;font-size:28px;line-height:1;cursor:pointer}
@media(max-width:760px){
  .hero-actions{display:none!important}
  .hero-inner{align-items:flex-start!important}
  .brand-r20 img{width:42px;height:42px}
  .back-r20{display:grid;place-items:center;position:absolute;left:14px;top:16px;z-index:5}
  .hero{position:relative;padding-top:20px!important}
  .hero h1{padding-left:48px}
}
</style>
<script id="mobile-header-r20-js">
(()=>{
 const run=()=>{
   const hero=document.querySelector('.hero');
   const h1=hero?.querySelector('h1');
   if(!hero||!h1)return;
   if(!h1.parentElement.classList.contains('brand-r20')){
     const wrap=document.createElement('div'); wrap.className='brand-r20';
     const img=document.createElement('img'); img.src='/static/icons/icons/icon-192.png'; img.alt='לוגו';
     h1.parentNode.insertBefore(wrap,h1); wrap.appendChild(img); wrap.appendChild(h1);
   }
   if(!document.getElementById('backR20')){
     const b=document.createElement('button'); b.id='backR20'; b.className='back-r20'; b.type='button'; b.setAttribute('aria-label','חזרה'); b.textContent='‹';
     b.onclick=()=>{ if(history.length>1) history.back(); else if(typeof go==='function') go('home'); };
     hero.appendChild(b);
   }
   const status=document.getElementById('apiStatus');
   if(status){
     const clean=()=>{
       const t=status.textContent||'';
       if(/Alpaca\s+מחובר/i.test(t) && !/(Alpaca\s+(?:מנותק|לא מחובר)|שגיאה)/i.test(t)) status.textContent='● נתוני שוק מחוברים • Alpaca פעיל';
       else if(/Alpha\s*Vantage/i.test(t)) status.textContent=t.replace(/\s*[•·-]?\s*Alpha\s*Vantage\s+לא\s+מוגדר/ig,'').replace(/\s*[•·]\s*$/,'').trim();
     };
     clean(); new MutationObserver(clean).observe(status,{childList:true,subtree:true,characterData:true});
   }
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',run);else run();
})();
</script>
'''

    def _r20_file_response(path, *args, **kwargs):
        try:
            p = Path(path)
            if p.suffix.lower() in {'.html', '.htm'} and p.exists():
                html = p.read_text(encoding='utf-8')
                if 'mobile-header-r20-js' not in html:
                    html = html.replace('</body>', _PATCH + '\n</body>', 1)
                return HTMLResponse(content=html, status_code=kwargs.get('status_code', 200), headers=kwargs.get('headers'), media_type='text/html')
        except Exception:
            pass
        return _PreviousFileResponse(path, *args, **kwargs)

    _responses.FileResponse = _r20_file_response
except Exception:
    pass
