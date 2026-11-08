from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from form_agent.agent import active_run, resume_run, start_run, stop_run
from form_agent.pdf_rag import add_pdf, list_documents, remove_document

app = FastAPI(title="Prompt-driven Browser Form Agent", version="0.2.0")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "prompt-driven-browser-form-agent"}


@app.get("/api/status")
def status() -> dict:
    run = active_run()
    return run.public() if run else {"status": "idle", "message": "Ready", "events": []}


@app.get("/api/documents")
def documents() -> list[dict]:
    return list_documents()


@app.post("/api/documents", status_code=201)
async def upload_document(file: UploadFile = File(...)) -> dict:
    content = await file.read(15 * 1024 * 1024 + 1)
    try:
        return add_pdf(file.filename or "attachment.pdf", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str) -> dict:
    if not remove_document(document_id):
        raise HTTPException(status_code=404, detail="PDF attachment not found")
    return {"removed": True}


@app.post("/api/start")
async def start(request: Request) -> dict:
    try:
        payload = await request.json()
        run = start_run(str(payload.get("prompt", "")), payload.get("document_ids") or [],
                        str(payload.get("mode", "navigate_only")))
        return run.public()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/resume")
def resume() -> dict:
    try:
        return resume_run().public()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/stop")
def stop() -> dict:
    try:
        return stop_run().public()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD


DASHBOARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Browser Form Agent</title><style>
body{font:16px system-ui,Segoe UI,sans-serif;max-width:850px;margin:2rem auto;padding:0 1rem;color:#1b1b1b;background:#f5f7fa}
main{background:white;border:1px solid #d8dee8;border-radius:12px;padding:1.5rem;box-shadow:0 4px 20px #16304a10}
label{display:block;font-weight:650;margin:.8rem 0 .3rem}textarea,input{box-sizing:border-box;width:100%;padding:.75rem;border:1px solid #9ca9b8;border-radius:6px;font:inherit}
textarea{min-height:180px;resize:vertical}
.row{display:flex;gap:.6rem;flex-wrap:wrap;margin:1rem 0}button{border:0;border-radius:6px;padding:.7rem 1rem;font:inherit;font-weight:650;cursor:pointer;background:#174ea6;color:white}button.secondary{background:#4b5563}button:disabled{opacity:.45;cursor:not-allowed}
 .muted{color:#536171;font-size:.92rem}.docrow{display:flex;gap:.5rem;align-items:center;justify-content:space-between;border-bottom:1px solid #e5e7eb;padding:.4rem 0}.docrow button{padding:.3rem .5rem;background:#6b7280}
.handoff{margin-top:1rem;border:1px solid #d39200;border-radius:8px;padding:1rem;background:#fffaf0;overflow-wrap:anywhere}.handoff[hidden]{display:none}#handoffDetails{white-space:pre-wrap}
.runpanel{margin-top:1rem;border:1px solid #cbd5e1;border-radius:8px;padding:1rem;background:#f8fafc;overflow-wrap:anywhere}.runpanel h2,.runpanel h3{margin:.25rem 0 .6rem}.runpanel ul,.runpanel ol{padding-left:1.4rem}.runpanel li{margin:.35rem 0}.error{color:#9b1c1c}
</style></head><body><main>
<label for="pdfs">Attach PDF context for retrieval</label><input id="pdfs" type="file" accept="application/pdf,.pdf" multiple><div class="row"><button class="secondary" onclick="uploadPdfs()">Add PDFs</button></div><div id="documents" class="muted">No PDFs attached.</div>
<label for="prompt">Prompt</label><textarea id="prompt" placeholder="Say which site or form to open and what information to use. Include a website URL/domain, or say “go to [site name]”. Do not include passwords, API keys, OTPs, or other login secrets."></textarea>
<label for="mode">Run mode</label><select id="mode" style="box-sizing:border-box;width:100%;padding:.75rem;border:1px solid #9ca9b8;border-radius:6px;font:inherit"><option value="navigate_only">Navigate to the form (leave fields unchanged)</option><option value="sec_pdf_assist">SEC form assistance from attached PDF (fills supported fields, never submits)</option></select>
<p class="muted">PDF text is extracted and searched locally. Only retrieved excerpts for visible fields, your prompt, and field labels/options are sent to your configured Nebius model. Credentials and existing browser field values are not sent to the model. Use only documents you are authorized to process.</p>
<div class="row"><button id="start" onclick="startRun()">Run in Chrome</button><button class="secondary" id="resume" onclick="resumeRun()" disabled>Resume after my intervention</button><button class="secondary" id="stop" onclick="stopRun()" disabled>Stop and close Chrome</button></div>
<section class="runpanel" id="runPanel" aria-live="polite"><h2 id="runHeading">Run status</h2><p id="runMessage">Ready. Choose a mode and click Run in Chrome to start visible Chrome.</p><div id="runDetails"></div><h3>Retrieved PDF passages</h3><ul id="sourceEvidence"><li>None retrieved yet.</li></ul><h3>Filled field evidence</h3><ul id="fieldEvidence"><li>No fields filled.</li></ul><h3>Recent events</h3><ol id="runEvents"><li>No run started.</li></ol></section>
<section class="handoff" id="handoffPanel" role="status" aria-live="polite" hidden><strong id="handoffTitle">User intervention needed</strong><div id="handoffDetails"></div></section>
</main><script>
let timer=null;let docs=[];
async function request(path,method='GET',body=null){const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Request failed');if(typeof renderHandoff==='function')renderHandoff(j);return j}
async function uploadPdfs(){const input=document.getElementById('pdfs');try{for(const f of input.files){const fd=new FormData();fd.append('file',f);const r=await fetch('/api/documents',{method:'POST',body:fd});const j=await r.json();if(!r.ok)throw new Error(j.detail||'PDF upload failed');docs.push(j)}input.value='';renderDocs()}catch(e){alert(e.message)}}
async function removePdf(id){try{await request('/api/documents/'+encodeURIComponent(id),'DELETE');docs=docs.filter(d=>d.document_id!==id);renderDocs()}catch(e){alert(e.message)}}
function renderDocs(){const box=document.getElementById('documents');if(!docs.length){box.textContent='No PDFs attached.';return}box.replaceChildren(...docs.map(d=>{const row=document.createElement('div');row.className='docrow';const span=document.createElement('span');span.textContent=d.filename+' · '+d.page_count+' pages · '+d.chunk_count+' chunks';const b=document.createElement('button');b.textContent='Remove';b.onclick=()=>removePdf(d.document_id);row.append(span,b);return row}))}
async function startRun(){try{document.getElementById('start').disabled=true;const s=await request('/api/start','POST',{prompt:document.getElementById('prompt').value,mode:document.getElementById('mode').value,document_ids:docs.map(d=>d.document_id)});render(s);startPolling()}catch(e){showRunError('Could not start run',e.message);document.getElementById('start').disabled=false}}
async function resumeRun(){try{render(await request('/api/resume','POST'))}catch(e){showRunError('Could not resume run',e.message)}}
async function stopRun(){try{render(await request('/api/stop','POST'))}catch(e){showRunError('Could not stop run',e.message)}}
function startPolling(){if(timer)clearInterval(timer);timer=setInterval(poll,1200);poll()}
async function poll(){try{const s=await request('/api/status');render(s);if(['stopped','finished','error','idle'].includes(s.status)){clearInterval(timer);timer=null;document.getElementById('start').disabled=false}}catch(e){showRunError('Connection to the agent was lost',e.message)}}
function showRunError(title,message){document.getElementById('runHeading').textContent=title;document.getElementById('runMessage').textContent=message;document.getElementById('runMessage').className='error'}
function addLines(id,items,empty){const box=document.getElementById(id);box.replaceChildren();if(!items||!items.length){const li=document.createElement('li');li.textContent=empty;box.append(li);return}for(const item of items){const li=document.createElement('li');li.textContent=item;box.append(li)}}
function render(s){const terminal=['stopped','finished','error','idle'].includes(s.status);document.getElementById('start').disabled=!terminal;document.getElementById('resume').disabled=s.status!=='waiting_user';document.getElementById('stop').disabled=terminal;document.getElementById('runHeading').textContent='Run status: '+(s.status||'unknown');const message=s.error||s.message||'No status message';const msg=document.getElementById('runMessage');msg.textContent=message;msg.className=s.status==='error'?'error':'';const details=[];if(s.destination_url)details.push('Destination: '+s.destination_url);if(s.current_url)details.push('Current page: '+s.current_url);if(s.mode)details.push('Mode: '+s.mode);if(s.fields_seen&&s.fields_seen.length)details.push('Fields detected: '+s.fields_seen.join(' · '));if(s.filled_fields&&s.filled_fields.length)details.push('Fields filled: '+s.filled_fields.join(' · '));if(s.skipped_fields&&s.skipped_fields.length)details.push('Fields skipped: '+s.skipped_fields.join(' · '));if(s.required_missing&&s.required_missing.length)details.push('Required fields still blank: '+s.required_missing.join(' · '));document.getElementById('runDetails').textContent=details.join('\\n');addLines('sourceEvidence',(s.retrieved_sources||[]).map(x=>`${x.filename}, page ${x.page}: ${x.excerpt}`),'No PDF passages retrieved yet.');addLines('fieldEvidence',(s.field_sources||[]).map(x=>`${x.field}: ${x.value} — ${x.filename}${x.page?' p. '+x.page:''}; quote: “${x.quote}”${x.choice_reason?' — '+x.choice_reason:''}`),'No fields filled.');addLines('runEvents',(s.events||[]).slice(-12).map(x=>`${x.time} ${x.event}: ${x.message}`),'No run events reported.')}
async function loadDocs(){try{docs=await request('/api/documents');renderDocs()}catch(e){showRunError('Could not load attachments',e.message)}}
async function loadInitialState(){await loadDocs();try{const s=await request('/api/status');render(s);if(!['stopped','finished','error','idle'].includes(s.status))startPolling()}catch(e){showRunError('Cannot reach the agent service',e.message)}}
let handoffWasActive=false;
function renderHandoff(s){const panel=document.getElementById('handoffPanel');const box=document.getElementById('handoffDetails');const heading=document.getElementById('handoffTitle');const c=s.handoff_context||{};if(!panel||!box)return;const active=['waiting_user','review_ready','form_ready'].includes(s.status);if(!active){panel.hidden=true;if(handoffWasActive)document.title='Browser Form Agent';handoffWasActive=false;return}panel.hidden=false;heading.textContent=s.status==='form_ready'?'Relevant form reached':s.status==='review_ready'?'Review required':'User intervention needed';const lines=[];if(c.fields&&c.fields.length){for(const f of c.fields){let line='• '+f.label;if(f.required&&!f.already_filled)line+=' [required; blank]';if(f.manual_only)line+=' [select manually]';lines.push(line);if(f.options&&f.options.length)lines.push('  Options: '+f.options.join(' | '))}}else{lines.push('No question or input field was detected on this page.')}box.textContent=lines.join('\\n');document.title=s.status==='form_ready'?'Form reached - Browser Form Agent':'User intervention needed - Browser Form Agent';if(!handoffWasActive)panel.scrollIntoView({behavior:'smooth',block:'center'});handoffWasActive=true}
loadInitialState();
</script></body></html>"""

