"""The learner-facing panel. WIDGET_HTML goes into a course HTML unit; PAGE_HTML is the standalone page.

The panel reads /api/tier/v1/me/progress/ with the learner's own login session. It finds the course id
from its own address (an HTML unit is served from .../block-v1:Org+Course+Run+type@html+block@...)
or from ?course_id=. Text from the server is inserted with textContent, never as HTML.
"""

WIDGET_HTML = """<div id="tp-root" class="tp">
<style>
.tp{--bg:#fff;--fg:#1c2330;--mut:#5b6678;--line:#dde2ea;--card:#f6f8fb;--ok:#1a7f4b;--warn:#b45309;--info:#2563eb;--bar:#2563eb;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--fg);background:var(--bg);padding:4px}
@media (prefers-color-scheme:dark){.tp{--bg:#10151d;--fg:#e8ecf3;--mut:#9aa6b8;--line:#2a3342;--card:#171e29;--ok:#4ade80;--warn:#fbbf24;--info:#7aa7ff;--bar:#7aa7ff}}
.tp h4{margin:18px 0 8px;font-size:15px}.tp .mut{color:var(--mut)}
.tp .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.tp .stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tp .stat b{display:block;font-size:22px}.tp .stat span{font-size:12px;color:var(--mut)}
.tp .note{border-left:4px solid var(--info);background:var(--card);padding:8px 12px;margin:8px 0;border-radius:0 8px 8px 0}
.tp .note.warn{border-color:var(--warn)}.tp .note.good{border-color:var(--ok)}.tp .note b{display:block}
.tp .row{display:grid;grid-template-columns:minmax(120px,38%) 1fr 56px;gap:8px;align-items:center;margin:6px 0}
.tp .track{background:var(--line);border-radius:6px;height:10px;overflow:hidden}.tp .fill{height:100%;background:var(--bar)}
.tp .row.weak .fill{background:var(--warn)}.tp .row.strong .fill{background:var(--ok)}
.tp .val{text-align:right;font-variant-numeric:tabular-nums}
.tp .next{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:14px}
.tp .tier{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:13px}
@media (max-width:480px){.tp .row{grid-template-columns:1fr 56px}.tp .track{grid-column:1/3;order:3}}
</style>
<div id="tp-body" aria-live="polite"><p class="mut">Loading your progress...</p></div>
<script>
(function(){
  var body=document.getElementById('tp-body');
  function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;if(txt!==undefined)e.textContent=txt;return e;}
  function courseId(){
    var q=new URLSearchParams(location.search).get('course_id'); if(q) return q;
    var href=location.href; try{href=decodeURIComponent(href);}catch(e){}
    var m=href.match(/block-v1:([^+\\/]+\\+[^+\\/]+\\+[^+\\/]+)\\+type@/); if(m) return 'course-v1:'+m[1];
    m=href.match(/course-v1:[^\\/?#]+/); return m?m[0]:'';
  }
  function show(msg){body.textContent='';body.appendChild(el('p','mut',msg));}
  function render(d){
    body.textContent='';
    var o=d.overall, st=el('div','stats');
    [[o.average_score===null?'-':o.average_score+'%','Average quiz score'],
     [o.subjects_attempted+' / '+o.subjects_total,'Subjects attempted'],
     [o.quizzes_attempted_pct+'%','Graded quizzes done'],
     [o.active_weeks_pct+'%','Recent weeks active']].forEach(function(p){
      var s=el('div','stat'); s.appendChild(el('b','',p[0])); s.appendChild(el('span','',p[1])); st.appendChild(s);});
    body.appendChild(el('div','mut',d.exam_label));
    body.appendChild(st);
    if(d.tier){var t=el('p','');t.appendChild(el('span','tier','Your level: '+d.tier.name+(d.tier.meaning?' - '+d.tier.meaning:'')));body.appendChild(t);}
    body.appendChild(el('h4','','Notifications'));
    d.notifications.forEach(function(n){var b=el('div','note '+n.level);b.appendChild(el('b','',n.title));b.appendChild(el('span','',n.text));body.appendChild(b);});
    body.appendChild(el('h4','','Subjects'));
    d.subjects.forEach(function(s){
      var r=el('div','row '+s.status); r.appendChild(el('span','',s.name));
      var tr=el('div','track'), f=el('div','fill'); f.style.width=(s.score===null?0:Math.max(2,s.score))+'%'; tr.appendChild(f); r.appendChild(tr);
      r.appendChild(el('span','val',s.score===null?'-':Math.round(s.score)+'%')); body.appendChild(r);});
    var nx=el('div','next'); nx.appendChild(el('b','','Next step: ')); nx.appendChild(el('span','',d.next_step)); body.appendChild(nx);
    if(d.updated_at){body.appendChild(el('p','mut','Updated '+new Date(d.updated_at).toLocaleString()));}
  }
  var cid=courseId();
  fetch('/api/tier/v1/me/progress/'+(cid?'?course_id='+encodeURIComponent(cid):''),{credentials:'same-origin',headers:{'Accept':'application/json'}})
    .then(function(r){ if(r.status===401||r.status===403) throw new Error('Please sign in to see your progress.');
                       if(r.status===404) throw new Error('No progress yet. Submit a graded quiz and check again in a few minutes.');
                       if(!r.ok) throw new Error('Progress is not available right now.'); return r.json();})
    .then(render).catch(function(e){show(e.message);});
})();
</script>
</div>
"""

PAGE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>My progress</title>
<style>body{margin:0;background:#fff;color:#1c2330}@media (prefers-color-scheme:dark){body{background:#10151d;color:#e8ecf3}}
main{max-width:760px;margin:0 auto;padding:16px}h1{font-size:22px;margin:8px 4px}</style></head>
<body><main><h1>My progress</h1>
""" + WIDGET_HTML + """
</main></body></html>
"""
