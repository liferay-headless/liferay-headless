(function () {
  "use strict";
  var D = window.D, TODAY = D.meta.date, J = "https://liferay.atlassian.net/browse/";
  function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  function $(id){ return document.getElementById(id); }

  // ── Theme switch (v0.13.0-beta): per-viewer, saved in this browser when allowed ──
  var THEME_KEY = "headless-board-theme";
  function applyTheme(mode){
    if (mode === "light" || mode === "dark") document.documentElement.setAttribute("data-theme", mode);
    else { mode = "system"; document.documentElement.removeAttribute("data-theme"); }
    var bs = document.querySelectorAll("[data-theme-set]");
    for (var i = 0; i < bs.length; i++) bs[i].setAttribute("aria-pressed", String(bs[i].getAttribute("data-theme-set") === mode));
  }
  (function(){
    var saved = null;
    try { saved = window.localStorage.getItem(THEME_KEY); } catch (e) {}
    applyTheme(saved);
    var bs = document.querySelectorAll("[data-theme-set]");
    for (var i = 0; i < bs.length; i++) bs[i].addEventListener("click", function(){
      var m = this.getAttribute("data-theme-set"); applyTheme(m);
      try { if (m === "system") window.localStorage.removeItem(THEME_KEY); else window.localStorage.setItem(THEME_KEY, m); } catch (e) {}
    });
  })();

  // ── Meters ──────────────────────────────────────────────
  var MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  function dms(s){ var p=s.split("-"); return Date.UTC(+p[0], +p[1]-1, +p[2]); }
  function daysBetween(a,b){ return Math.round((dms(b)-dms(a))/86400000); }
  function round1(x){ return Math.round(x*10)/10; }
  function scheduleMeter(cfg, name, doneTxt, noteOverride){
    var total = daysBetween(cfg.start, cfg.end), el = Math.max(0, Math.min(total, daysBetween(cfg.start, TODAY)));
    var sched = total ? el/total : 0, done = Math.max(0, Math.min(1, cfg.done || 0));
    var off = (sched - done) * total, behind = off > 0.5, ahead = off < -0.5;
    var cls = behind ? (off > total*0.25 ? "crit" : "warn") : "good";
    var note = behind ? round1(off)+"d behind" : ahead ? round1(-off)+"d ahead" : "on schedule";
    if (noteOverride) { note = noteOverride; cls = "warn"; }
    var lbl = name+' · '+esc(cfg.label);
    lbl = cfg.url ? '<a class="meter-lbl" href="'+cfg.url+'" target="_blank" rel="noopener">'+lbl+'</a>' : '<span class="meter-lbl">'+lbl+'</span>';
    return '<div class="meter"><div class="meter-head">'+lbl+'<span class="meter-note '+cls+'">'+note+'</span></div>'+
      '<div class="mtrack"><div class="mfill '+cls+'" style="width:'+Math.round(done*100)+'%"></div><i class="mgoal" style="left:'+Math.max(1,Math.min(99,Math.round(sched*100)))+'%"></i></div>'+
      '<div class="meter-foot"><span>'+Math.round(done*100)+'% done ('+doneTxt+') · '+Math.round(sched*100)+'% scheduled</span><span>'+(total-el)+'d left</span></div></div>';
  }

  var it = D.iteration, ms = D.milestone;
  var top = "";
  if (it && it.start) top += scheduleMeter({label:it.label, start:it.start, end:it.end, done: it.total ? it.done/it.total : 0, url:it.url}, "Iteration", it.done+"/"+it.total+" items");
  var committed = D.epics.filter(function(e){ return e.committed; });
  // Milestone progress weighted by T-shirt size (person-months): each epic counts with its size,
  // its done share = done/total stories (an epic with no stories counts as 0% done).
  var wTot=0, wDone=0, noSize=0;
  committed.forEach(function(e){ var w = e.pm; if (w == null) { noSize++; w = 1; } wTot += w; wDone += w * (e.total ? (e.done||0)/e.total : 0); });
  var unsliced = committed.filter(function(e){ return !e.total; }).length;
  var msNote = [unsliced ? unsliced+" epic"+(unsliced>1?"s":"")+" not sliced yet" : "", noSize ? noSize+" without size" : ""].filter(Boolean).join(" · ");
  if (ms && ms.start) top += scheduleMeter({label:ms.label, start:ms.start, end:ms.end, done: wTot ? wDone/wTot : 0}, "Milestone",
    (Math.round(wDone*10)/10)+" of "+(Math.round(wTot*10)/10)+" person-months, by T-shirt size", msNote || null);
  $("metrics").innerHTML = top;

  // ── Tabs ────────────────────────────────────────────────
  var tabs = document.querySelectorAll(".tab");
  tabs.forEach(function(t){ t.onclick = function(){
    tabs.forEach(function(x){ x.classList.toggle("on", x===t); });
    document.querySelectorAll(".panel").forEach(function(p){ p.hidden = p.id !== t.dataset.p; });
  };});

  // ── Rows ────────────────────────────────────────────────
  function labelCls(tier){
    if (/Critical/i.test(tier)) return "l-crit";
    if (/Expedite/i.test(tier)) return "l-exp";
    if (/Slack/i.test(tier)) return "l-slack";
    if (/^PR$/.test(tier)) return "l-pr";
    if (/High|BPR|SEV|Blocker/i.test(tier)) return "l-high";
    if (/Focus/i.test(tier)) return "l-focus";
    return "l-reg";
  }
  function daysCell(d, isEpic){
    var n = parseInt(d,10), clean = String(d).replace(/ ?[🔴🟠]/g,"");
    var ct = isEpic || /in progress|in review|in development/.test(d), cls = "";
    if (ct && !isNaN(n)) cls = isEpic ? (n>65?"ct-red":n>45?"ct-orange":"") : (n>14?"ct-red":n>7?"ct-orange":"");
    return '<span class="days '+cls+'">'+esc(clean)+'</span>';
  }
  function splitAction(html){
    var pr=[], other=[];
    String(html||"").split(/<br\s*\/?>\s*<br\s*\/?>/i).forEach(function(p){
      p = p.trim(); if (!p) return;
      (/github\.com|PR#|^💬|review|merge|Changes requested/i.test(p) ? pr : other).push('<div class="note">'+p+'</div>');
    });
    return [pr.join(""), other.join("")];
  }
  var team = D.team || [];
  function typeCls(t){
    t = (t||"").toLowerCase();
    if (/story/.test(t)) return "t-story";
    if (/sub-?task/.test(t)) return "t-subtask";
    if (/task/.test(t)) return "t-task";
    if (/bug|defect/.test(t)) return "t-bug";
    if (/spike|research/.test(t)) return "t-spike";
    if (/epic/.test(t)) return "t-epic";
    if (/improvement|feature/.test(t)) return "t-impr";
    if (/customer|issue|analysis|fix/.test(t)) return "t-cust";
    return "";
  }
  var roster = D.roster || {};
  // v0.16.0: review requests need a GitHub login, so people without one (designer, PT User Headless) are only offered for Jira assignment
  function opts(ph, mode){ return '<option value="">'+ph+'</option>'+team.filter(function(m){ return mode !== "review" || ((roster[m]||{}).gh); }).map(function(m){return '<option>'+esc(m)+'</option>';}).join(""); }
  // Assign: works only inside the Apps Script web app (google.script.run) and when the roster is known.
  var live = !!(window.google && google.script && google.script.run) && Object.keys(roster).length > 0;
  // mode "issue": Jira assignee (+ PR assignee on linked PRs) · mode "review": request GitHub review on the PR row
  function assignUI(td, tr, r, mode){
    var ph = mode === "review" ? "— reviewer —" : "— assign —";
    function build(){
      td.innerHTML = '<div class="as"><select class="picker sm"'+(live?'':' disabled title="Assigning works on the Google Sites page"')+'>'+opts(ph, mode)+'</select><button class="act-btn" disabled>'+(mode==="review"?"Request review":"Assign")+'</button></div>';
      var sel = td.querySelector("select"), btn = td.querySelector("button");
      sel.onchange = function(){ btn.disabled = !sel.value; };
      btn.onclick = function(){
        var who = sel.value, p = roster[who] || {};
        td.innerHTML = '<span class="status-note">sending…</span>';
        google.script.run.withSuccessHandler(function(res){
          tr.classList.add("assigned");
          td.innerHTML = '<span class="check">✓</span> <b>'+esc(who)+'</b> <span class="status-note">'+esc(res || "done")+'</span>';
        }).withFailureHandler(function(e){
          td.innerHTML = '<span class="status-note">failed: '+esc(e && e.message || e)+'</span>'; setTimeout(build, 6000);
        }).assign({mode: mode, key: r.key, url: r.url, prUrls: r.prUrls || [], name: who, accountId: p.aid || "", ghLogin: p.gh || ""});
      };
    }
    build();
  }
  // ── Jira status chip (v0.14) — carries data-live-key so the live refresh (v0.17) can update it ──
  function catCls(c){ return c==="done"?"done":c==="new"?"new":"prog"; }
  function statusChip(key, status, cat){
    return '<span class="chip st js-'+catCls(cat)+'" data-live-key="'+esc(key)+'" data-orig="'+esc(status)+'" title="Jira status at '+esc(TODAY)+' run"'+(status?'':' hidden')+'>'+esc(status)+'</span>';
  }
  function table(list, mountId, opt){
    var m = $(mountId);
    if (!list || !list.length) { m.innerHTML = '<p class="sec-sub">No items.</p>'; return; }
    var t = document.createElement("table"); t.className = "rt";
    t.innerHTML = '<colgroup><col style="width:3%"><col style="width:11%"><col style="width:22%"><col style="width:11%"><col style="width:11%"><col style="width:23%"><col style="width:19%"></colgroup>'+
      '<thead><tr><th>#</th><th>Priority</th><th>Issue</th><th>Assignee</th><th>'+(opt.queue?"Days in queue":"Cycle time")+'</th><th>PRs &amp; review</th><th>Other updates</th></tr></thead>';
    var tb = document.createElement("tbody");
    list.forEach(function(r, i){
      var isSlack = /slack\.com/.test(r.url), isPR = /^PR/.test(r.key);
      var type = isSlack ? "Slack thread" : isPR ? "Pull request" : (r.type || "");
      var summary = r.summary || r.topic || "";
      var parent = (!isSlack && r.topic && r.topic !== summary) ? '<div class="epicname">Epic: '+(r.epicKey ? '<a href="'+J+r.epicKey+'" target="_blank" rel="noopener">'+esc(r.epicKey)+' · '+esc(r.topic)+' ↗</a>' : esc(r.topic))+'</div>' : "";
      if (isPR && r.prJira) {
        var pj = r.prJira, st = statusChip(pj.key, pj.status || "", pj.statusCat || "");
        parent = '<div class="epicname">Jira: <a href="'+J+esc(pj.key)+'" target="_blank" rel="noopener">'+esc(pj.key)+(pj.summary && pj.summary!==summary ? ' · '+esc(pj.summary) : '')+' ↗</a> '+st+'</div>' + parent;
      }
      var a = splitAction(r.action);
      var tr = document.createElement("tr");
      if (/atlassian\.net\/browse\//.test(r.url)) tr.setAttribute("data-row-key", r.key);
      tr.innerHTML = '<td class="rk">'+(i+1)+'</td>'+
        '<td><span class="lbl '+labelCls(r.tier)+'">'+esc(r.tier)+'</span><div class="kind">'+esc(r.kind)+'</div></td>'+
        '<td><div class="ik"><span class="type '+typeCls(type)+'">'+esc(type)+'</span><a class="key" href="'+esc(r.url)+'" target="_blank" rel="noopener">'+esc(isSlack?"Open thread":r.key)+'</a>'+(r.status?statusChip(r.key, r.status, r.statusCat):'')+'</div><div class="sum">'+esc(summary)+'</div>'+parent+'</td>'+
        '<td class="who">'+esc(r.assignee)+'</td><td>'+daysCell(r.days,false)+'</td>'+
        '<td class="col-pr">'+(a[0]||'<span class="faint">—</span>')+'</td><td>'+(a[1]||'<span class="faint">—</span>')+'</td>';
      if (opt.assign && /PT User Headless/.test(r.assignee) && /atlassian\.net\/browse\//.test(r.url)) assignUI(tr.querySelector(".who"), tr, r, "issue");
      else if (opt.assign && opt.queue && /github\.com\/.+\/pull\/\d+/.test(r.url)) assignUI(tr.querySelector(".who"), tr, r, "review");
      tb.appendChild(tr);
    });
    t.appendChild(tb); m.appendChild(t);
  }
  var S = D.sections;
  table(S.s1a,"t1a",{assign:true}); table(S.s1h,"t1h",{assign:true}); table(S.s1b,"t1b",{assign:true});
  table(S.s2a,"t2a",{assign:true,queue:true}); table(S.s2b,"t2b",{queue:true});
  table(S.hidden||[],"tHid",{}); $("hidCount").textContent = (S.hidden||[]).length;
  Object.keys(S).forEach(function(k){ var c=document.querySelector('[data-c="'+k+'"]'); if(c) c.textContent=S[k].length; });

  // ── AVD tiles ───────────────────────────────────────────
  var A = D.avd || {};
  function tile(lbl, m, unit, goal, goalTxt){
    var v = m && m.value != null ? m.value : null, over = v != null && v > goal;
    var outl = (m && m.outliers || []).slice(0,6).map(function(o){ return '<a href="'+J+o.key+'" target="_blank" rel="noopener">'+esc(o.key)+'</a> '+esc(o.days!=null?o.days+"d":""); }).join(" · ");
    return '<div class="meter"><div class="meter-head"><span class="meter-lbl">'+lbl+'</span>'+(v!=null?'<span class="meter-note '+(over?"crit":"good")+'">'+(over?"over goal":"within goal")+'</span>':'')+'</div>'+
      '<div class="lead-row"><span class="meter-big">'+(v!=null?esc(v)+'<small>'+unit+'</small>':'?')+'</span></div>'+
      '<div class="meter-foot"><span>'+(v!=null?esc(m.basis||"85th pct · AVD"):"AVD data not connected yet")+'</span><span>'+goalTxt+'</span></div>'+
      (outl?'<div class="avd-out">Over goal: '+outl+'</div>':'')+'</div>';
  }
  $("avd").innerHTML = tile("Story cycle time", A.story, "d", 15, "goal 15d") + tile("Epic full cycle time", A.epic, "d", 65, "goal 65d") +
    tile("Flow handoff", A.handoff, "d", 24, "goal 24d") + tile("Epic WIP", A.wip, "", 18, "goal ≤ 18");

  // ── Milestone status ────────────────────────────────────
  function flags(e){
    var f = [];
    if (e.status==="Development Complete") f.push(["Dev complete — close epic","r"]);
    if (e.days>65) f.push(["Over 65d epic cycle time","r"]);
    if (!e.total) f.push(["No stories — slice it","o"]);
    if (e.stale100) f.push([e.stale100+" stories untouched 100d+","o"]);
    if (e.slow14) f.push([e.slow14+" stories over 14d","o"]);
    if (e.cat==="indeterminate" && e.total && !e.inProgress && e.done<e.total) f.push(["Nothing in progress","o"]);
    if (e.total && e.done===e.total) f.push(["All stories done — close?","o"]);
    if (!e.committed) f.push(["Counts in WIP, not committed","g"]);
    if (!e.fixVersions.length) f.push(["No Fix Version","o"]);
    return f.map(function(x){ return '<span class="flag f-'+x[1]+'">'+esc(x[0])+'</span>'; }).join("");
  }
  function epicTable(list, mountId){
    if (!list.length) { $(mountId).innerHTML = '<p class="sec-sub">No epics.</p>'; return; }
    var rows = list.map(function(e){
      var pct = e.total ? Math.round(e.done/e.total*100) : 0, d = Math.round(e.days||0);
      return '<tr><td><div class="ik"><span class="type t-epic">Epic</span><a class="key" href="'+J+e.key+'" target="_blank" rel="noopener">'+e.key+'</a></div><div class="sum">'+esc(e.summary)+'</div></td>'+
        '<td>'+statusChip(e.key, e.status, e.cat)+'</td><td>'+(e.size?'<span class="size">'+esc(e.size)+'</span><div class="kind">'+(e.pm!=null?e.pm+' person-month'+(e.pm==1?'':'s'):'')+'</div>':'<span class="flag f-o">No size</span>')+'</td><td class="fv">'+esc(e.fixVersions.join(", ")||"—")+'</td>'+
        '<td>'+(d?daysCell(d+"d in progress",true):'<span class="faint">not started</span>')+'</td>'+
        '<td><div class="mtrack"><div class="mfill '+(pct>=70?"good":"")+'" style="width:'+pct+'%"></div></div><div class="eprog-foot"><span>'+(e.total!=null?(e.done||0)+'/'+e.total+' done · '+(e.inProgress||0)+' in progress':'—')+'</span><span>'+pct+'%</span></div></td>'+
        '<td>'+flags(e)+'</td></tr>';
    }).join("");
    $(mountId).innerHTML = '<table class="rt et"><colgroup><col style="width:25%"><col style="width:9%"><col style="width:8%"><col style="width:14%"><col style="width:10%"><col style="width:16%"><col style="width:18%"></colgroup>'+
      '<thead><tr><th>Epic</th><th>Status</th><th>Size</th><th>Fix Version</th><th>Cycle time</th><th>Stories</th><th>Flags</th></tr></thead><tbody>'+rows+'</tbody></table>';
  }
  var byDays = function(a,b){ return (b.days||0)-(a.days||0); };
  var com = committed.slice().sort(byDays);
  var notCom = D.epics.filter(function(e){ return !e.committed && !e.discovery && e.cat==="indeterminate"; }).sort(byDays);
  var wipN = D.epics.filter(function(e){ return e.cat==="indeterminate"; }).length;
  epicTable(com,"tCom"); epicTable(notCom,"tNot");
  $("cCom").textContent = com.length; $("cNot").textContent = notCom.length;
  $("msName").textContent = ms ? ms.label : "";
  $("wipNote").innerHTML = 'Headless epics only (Team field). Epic WIP: <b>'+wipN+'</b> in progress (goal ≤ 18). Sorted by cycle time, longest first.';

  $("exclCount").textContent = D.excl.length;
  $("exclBody").innerHTML = D.excl.map(function(x){ return '<tr><td><a class="key" href="'+esc(x.url)+'" target="_blank" rel="noopener">'+esc(x.key)+'</a></td><td>'+esc(x.why)+'</td></tr>'; }).join("");

  // ── Live status (v0.17.0) ───────────────────────────────
  // Inside the Apps Script web app only: asks liveStatus() (Live.gs) for the current Jira status of every
  // issue on the board and the current state of every linked PR. Board content stays as of the morning run.
  var note = $("liveNote");
  var canLive = !!(window.google && google.script && google.script.run);
  function setNote(txt, cls){ if (note) { note.textContent = txt; note.className = "live-note " + (cls||""); note.hidden = false; } }
  if (canLive) {
    var keys = {}, prs = {};
    Array.prototype.forEach.call(document.querySelectorAll("[data-live-key]"), function(el){ keys[el.getAttribute("data-live-key")] = 1; });
    Array.prototype.forEach.call(document.querySelectorAll('a[href*="github.com/"][href*="/pull/"]'), function(a){
      var m = a.getAttribute("href").match(/\/pull\/(\d+)/); if (m) prs[m[1]] = 1;
    });
    setNote("Live status: loading…");
    var answered = false;
    // v0.17.1: never leave the header on "loading…" — after 30 s say so (a late answer still applies)
    setTimeout(function(){ if (!answered) setNote("Live status not answering — showing the " + TODAY + " run", "off"); }, 30000);
    google.script.run.withSuccessHandler(function(res){
      answered = true;
      if (res && (res.jiraError || res.githubError) && window.console) console.warn("liveStatus partial:", res.jiraError || "", res.githubError || "");
      res = res || {}; var iss = res.issues || {}, pst = res.prs || {}, changed = 0, done = 0;
      Array.prototype.forEach.call(document.querySelectorAll("[data-live-key]"), function(el){
        var k = el.getAttribute("data-live-key"), v = iss[k]; if (!v || !v.status) return;
        var orig = el.getAttribute("data-orig");
        el.textContent = v.status; el.hidden = false;
        el.className = "chip st js-" + catCls(v.cat);
        if (orig && orig !== v.status) { el.classList.add("live-changed"); el.title = "Live from Jira · was " + orig + " at the " + TODAY + " run"; changed++; }
        else el.title = "Live from Jira";
      });
      Array.prototype.forEach.call(document.querySelectorAll("tr[data-row-key]"), function(tr){
        var v = iss[tr.getAttribute("data-row-key")]; if (v && v.cat === "done") { tr.classList.add("live-done"); done++; }
      });
      var LBL = {MERGED:["merged","m"], CLOSED:["closed","c"], DRAFT:["draft","c"], APPROVED:["approved","a"],
                 CHANGES_REQUESTED:["changes requested","x"], REVIEW_REQUIRED:["review required","r"]};
      Array.prototype.forEach.call(document.querySelectorAll('a[href*="github.com/"][href*="/pull/"]'), function(a){
        var m = a.getAttribute("href").match(/\/pull\/(\d+)/), v = m && pst[m[1]]; if (!v) return;
        var code = v.state !== "OPEN" ? v.state : (v.isDraft ? "DRAFT" : (v.reviewDecision || "REVIEW_REQUIRED"));
        var l = LBL[code]; if (!l) return;
        var nx = a.nextSibling; if (nx && nx.classList && nx.classList.contains("pr-live")) nx.remove();
        var s = document.createElement("span"); s.className = "chip pr-live pr-" + l[1]; s.textContent = l[0];
        s.title = "Live from GitHub"; a.parentNode.insertBefore(s, a.nextSibling);
      });
      var t = new Date(res.at || Date.now());
      setNote("Live status · " + ("0"+t.getHours()).slice(-2) + ":" + ("0"+t.getMinutes()).slice(-2) +
              (changed ? " · " + changed + " changed since the run" : "") + (done ? " · " + done + " now done" : "") +
              (res.jiraError ? " · Jira not reachable" : "") + (res.githubError ? " · GitHub not reachable" : ""),
              (res.jiraError || res.githubError) ? "off" : "on");
    }).withFailureHandler(function(e){
      answered = true;
      setNote("Live status unavailable — showing the " + TODAY + " run", "off");
      if (window.console) console.warn("liveStatus failed:", e && e.message || e);
    }).liveStatus({keys: Object.keys(keys), prs: Object.keys(prs).map(Number)});
  }
})();
