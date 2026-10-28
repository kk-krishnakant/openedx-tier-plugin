"""The learner-facing panel.

PANEL_HTML    the panel itself (HTML, CSS, JavaScript). Reads /api/tier/v1/me/progress/ with the learner's own login.
PAGE_HTML     a full page around it, served at /api/tier/progress/ (add ?course_id=...&embed=1 to show it inside another page).
LOADER_HTML   tiny snippet for a course HTML unit: it only shows the page above in an iframe, so the panel can change later
              without importing the course again. The Progress tab slot (tutor-plugins/tier_mfe.py) does the same.

The panel shows only what Open edX does not already show (it has its own quiz scores, grades and completion ring):
CPF score, level, video and reading completion, study consistency, points to the next level, what helps and what
holds the score back, and alerts. Text from the server is inserted with textContent, never as HTML.
"""

PANEL_HTML = """<div id="tp-root" class="tp">
<style>
.tp{--bg:#fff;--fg:#1c2330;--mut:#5b6678;--line:#dde2ea;--card:#f6f8fb;--ok:#1a7f4b;--warn:#b45309;--info:#2563eb;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--fg);background:var(--bg);padding:4px}
@media (prefers-color-scheme:dark){.tp{--bg:#10151d;--fg:#e8ecf3;--mut:#9aa6b8;--line:#2a3342;--card:#171e29;--ok:#4ade80;--warn:#fbbf24;--info:#7aa7ff}}
.tp h4{margin:18px 0 8px;font-size:15px}.tp .mut{color:var(--mut)}.tp .small{font-size:13px}
.tp .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tp .stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tp .stat b{display:block;font-size:24px;line-height:1.2}.tp .stat span{font-size:12px;color:var(--mut)}
.tp .note{border-left:4px solid var(--info);background:var(--card);padding:8px 12px;margin:8px 0;border-radius:0 8px 8px 0}
.tp .note.warn{border-color:var(--warn)}.tp .note.good{border-color:var(--ok)}.tp .note b{display:block}
.tp .cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:0 16px}
.tp .next{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:14px}
.tp .pick{display:block;margin:6px 0;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit;cursor:pointer;text-align:left}
</style>
<div id="tp-body" aria-live="polite"><p class="mut">Loading your progress...</p></div>
<script>
(function(){
  var body=document.getElementById('tp-body');
  function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;if(txt!==undefined)e.textContent=txt;return e;}
  function tellParent(){ // lets a page that shows this one in an iframe fit its height
    if(window.parent!==window){try{window.parent.postMessage({tierPanelHeight:document.documentElement.scrollHeight},'*');}catch(e){}}
  }
  if(window.ResizeObserver){new ResizeObserver(tellParent).observe(document.body);}
  function courseId(){
    var q=new URLSearchParams(location.search).get('course_id'); if(q) return q;
    var href=location.href; try{href=decodeURIComponent(href);}catch(e){}
    var m=href.match(/block-v1:([^+\\/]+\\+[^+\\/]+\\+[^+\\/]+)\\+type@/); if(m) return 'course-v1:'+m[1];
    m=href.match(/course-v1:[^\\/?#]+/); return m?m[0]:'';
  }
  function show(msg){body.textContent='';body.appendChild(el('p','mut',msg));tellParent();}
  function stat(value,label,sub){var s=el('div','stat');s.appendChild(el('b','',value));s.appendChild(el('span','',label));if(sub){s.appendChild(el('br'));s.appendChild(el('span','',sub));}return s;}
  function render(d){
    body.textContent='';
    body.appendChild(el('div','mut small',d.exam_label));
    var st=el('div','stats');
    if(d.cpf){st.appendChild(stat(Math.round(d.cpf.score)+' / 100','CPF score',d.cpf.kind==='readiness'?'readiness index':'model estimate'));}
    if(d.tier){st.appendChild(stat(d.tier.name,'Your level',d.tier.meaning));}
    st.appendChild(stat(d.content.content_pct+'%','Videos and reading done','videos: '+d.content.video_pct+'%'));
    st.appendChild(stat(d.consistency.active_weeks_pct+'%','Study consistency',d.consistency.days_since_active===null?'no activity yet':(d.consistency.days_since_active===0?'studied today':'last studied '+d.consistency.days_since_active+' days ago')));
    if(d.cpf){var nl=d.cpf.next_level;st.appendChild(nl?stat(nl.gap+' pts','To reach '+nl.name,'needs '+nl.at):stat('Top','Level reached','keep it up'));}
    body.appendChild(st);
    if(d.cpf){
      body.appendChild(el('p','mut small',d.cpf.note));
      var dr=d.drivers, cols=el('div','cols');
      [['What is helping you',dr.helping,'good'],['What is holding you back',dr.holding_back,'warn']].forEach(function(g){
        var box=el('div',''); box.appendChild(el('h4','',g[0]));
        if(!g[1].length) box.appendChild(el('p','mut','Nothing significant yet.'));
        g[1].forEach(function(x){var n=el('div','note '+g[2]); n.appendChild(el('b','',x.label+'  '+(x.points>0?'+':'')+x.points+' pts')); if(x.text) n.appendChild(el('span','',x.text)); box.appendChild(n);});
        cols.appendChild(box);});
      body.appendChild(cols);
      if(dr.cap_note){body.appendChild(el('div','note warn',dr.cap_note));}
      if(dr.benchmark_note){body.appendChild(el('p','mut small',dr.benchmark_note));}
    }
    body.appendChild(el('h4','','Alerts'));
    if(!d.alerts.length) body.appendChild(el('p','mut','No alerts right now.'));
    d.alerts.forEach(function(n){var b=el('div','note '+n.level);b.appendChild(el('b','',n.title));b.appendChild(el('span','',n.text));body.appendChild(b);});
    var nx=el('div','next'); nx.appendChild(el('b','','Next step: ')); nx.appendChild(el('span','',d.next_step)); body.appendChild(nx);
    if(d.updated_at){body.appendChild(el('p','mut small','Updated '+new Date(d.updated_at).toLocaleString()));}
    tellParent();
  }
  var API='/api/tier/v1/me/', courses=[];
  function get(url){return fetch(url,{credentials:'same-origin',headers:{'Accept':'application/json'}}).then(function(r){
      if(r.status===401||r.status===403) throw new Error('Please sign in to see your progress.');
      if(r.status===404) throw new Error('No progress yet. Submit a graded quiz and check again in a few minutes.');
      if(!r.ok) throw new Error('Progress is not available right now.'); return r.json();});}
  function loadCourse(cid){
    show('Loading your progress...');
    get(API+'progress/?course_id='+encodeURIComponent(cid)).then(function(d){render(d);
      if(courses.length>1){var b=el('button','pick','All my courses');b.onclick=showPicker;body.insertBefore(b,body.firstChild);}
    }).catch(function(e){show(e.message);});
  }
  function showPicker(){
    body.textContent=''; body.appendChild(el('h4','','Choose a course'));
    courses.forEach(function(c){var b=el('button','pick',c.title);b.onclick=function(){loadCourse(c.course_id);};body.appendChild(b);});
    tellParent();
  }
  var cid=courseId();
  if(cid){loadCourse(cid);}
  else{get(API+'courses/').then(function(d){courses=d.courses||[];
      if(!courses.length) show('You are not enrolled in a course with progress yet.');
      else if(courses.length===1) loadCourse(courses[0].course_id); else showPicker();
    }).catch(function(e){show(e.message);});}
})();
</script>
</div>
"""

PAGE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>My progress</title>
<style>body{margin:0;background:#fff;color:#1c2330}@media (prefers-color-scheme:dark){body{background:#10151d;color:#e8ecf3}}
main{max-width:860px;margin:0 auto;padding:16px}h1{font-size:22px;margin:8px 4px}
body.embed{background:transparent}body.embed main{padding:0;max-width:none}body.embed h1{display:none}</style></head>
<body><main><h1>My progress</h1>
""" + PANEL_HTML + """
</main>
<script>if(/[?&]embed=1/.test(location.search)){document.body.className='embed';}</script>
</body></html>
"""

LOADER_HTML = """<div id="tp-frame-root">
<script>
(function(){
  var href=location.href; try{href=decodeURIComponent(href);}catch(e){}
  var q=new URLSearchParams(location.search).get('course_id'), cid=q||'';
  if(!cid){var m=href.match(/block-v1:([^+\\/]+\\+[^+\\/]+\\+[^+\\/]+)\\+type@/); if(m) cid='course-v1:'+m[1];}
  var f=document.createElement('iframe');
  f.src='/api/tier/progress/?embed=1'+(cid?'&course_id='+encodeURIComponent(cid):'');
  f.title='My progress'; f.style.cssText='width:100%;height:900px;border:0';
  window.addEventListener('message',function(e){
    if(e.source===f.contentWindow&&e.data&&e.data.tierPanelHeight){f.style.height=(e.data.tierPanelHeight+16)+'px';}
  });
  document.getElementById('tp-frame-root').appendChild(f);
})();
</script>
<noscript><p>Open <a href="/api/tier/progress/">your progress page</a>.</p></noscript>
</div>
"""

# kept so older imports of WIDGET_HTML keep working
WIDGET_HTML = LOADER_HTML
