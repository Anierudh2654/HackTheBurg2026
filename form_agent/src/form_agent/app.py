from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.responses import Response
from pydantic import BaseModel, Field
from urllib.parse import quote

from form_agent.agent import active_run, resolve_destination, resume_run, start_run, stop_run
from form_agent.modes import choose_run_mode
from form_agent.pdf_rag import add_pdf, list_documents, remove_document
from form_agent.pdf_forms import add_template, fill_template, get_result, list_templates, remove_template

app = FastAPI(title="Prompt-driven Browser Form Agent", version="0.2.0")


class PdfFillRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=40000)
    document_ids: list[str] = Field(default_factory=list, max_length=10)


@app.get("/api/pdf/templates")
def pdf_templates() -> list[dict]:
    return list_templates()


@app.post("/api/pdf/templates", status_code=201)
async def upload_pdf_template(file: UploadFile = File(...)) -> dict:
    content = await file.read(15 * 1024 * 1024 + 1)
    try:
        return add_template(file.filename or "form.pdf", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/pdf/templates/{template_id}")
def delete_pdf_template(template_id: str) -> dict:
    if not remove_template(template_id):
        raise HTTPException(status_code=404, detail="PDF template not found")
    return {"removed": True}


@app.post("/api/pdf/fill")
def fill_pdf(payload: PdfFillRequest) -> dict:
    try:
        return fill_template(payload.template_id, payload.prompt, payload.document_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PDF filling failed: {type(exc).__name__}. Check your model configuration and retry.") from exc


@app.get("/api/pdf/results/{result_id}/download")
def download_pdf(result_id: str) -> Response:
    result = get_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Filled PDF expired or was removed; fill the form again")
    return Response(content=result["content"], media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(result["filename"]),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


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
        prompt = str(payload.get("prompt", ""))
        document_ids = payload.get("document_ids") or []
        mode = payload.get("mode")
        if mode is None:
            destination, _ = resolve_destination(prompt)
            mode = choose_run_mode(destination, bool(document_ids))
        run = start_run(prompt, document_ids, str(mode))
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


DASHBOARD = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Form Agent</title><style>
*{box-sizing:border-box}body{font:16px system-ui,Segoe UI,sans-serif;max-width:800px;margin:3rem auto;padding:0 1rem;color:#182333;background:#f7f8fa}
main{background:#fff;border:1px solid #e0e5eb;border-radius:16px;padding:2rem}h1{font-size:1.45rem;margin:0 0 1.5rem}h2{font-size:1.05rem;margin:0}label{display:block;font-weight:600;margin-bottom:.5rem}
textarea{width:100%;min-height:150px;resize:vertical;padding:1rem;border:1px solid #bac4d1;border-radius:10px;font:inherit;line-height:1.5}textarea:focus-visible,button:focus-visible,.upload:focus-within{outline:3px solid #b3ceff;outline-offset:3px}
.attachments{margin:.8rem 0 1.3rem}.upload{display:inline-block;border:1px solid #cbd3de;border-radius:7px;padding:.5rem .8rem;cursor:pointer;font-weight:500}.upload input{position:absolute;width:1px;height:1px;opacity:0}.docrow{display:flex;align-items:center;gap:.5rem;justify-content:space-between;margin:.4rem 0;font-size:.9rem;overflow-wrap:anywhere}.docrow button{padding:.25rem .5rem;background:#edf0f5;color:#334155}
.download{display:inline-block;margin:0 0 1rem;padding:.75rem 1rem;border-radius:8px;background:#2159c2;color:white;text-decoration:none;font-weight:600}[hidden]{display:none!important}.actions{display:flex;gap:.6rem;flex-wrap:wrap}button{border:0;border-radius:8px;padding:.75rem 1rem;font:inherit;font-weight:600;cursor:pointer;background:#2159c2;color:#fff}button.secondary{background:#edf0f5;color:#334155}button:disabled{opacity:.45;cursor:not-allowed}.muted{color:#667386;font-size:.9rem;line-height:1.5}.error{color:#ae2424}
#pdfSource,#templateInfo{overflow-wrap:anywhere}#runMessage{margin:1rem 0;overflow-wrap:anywhere}.interventions{border-top:1px solid #e5e9ef;padding-top:1.3rem;margin-top:1.5rem}.questions{list-style:none;padding:0;margin:.8rem 0 0}.question{padding:1rem 0;border-bottom:1px solid #e5e9ef;overflow-wrap:anywhere}.question h3{font-size:1rem;margin:0 0 .5rem;font-weight:600}.question p{margin:.35rem 0;font-size:.9rem;color:#536171}.options{padding-left:1.3rem;margin:.4rem 0;font-size:.95rem}.options li{margin:.25rem 0}
@media(max-width:520px){body{margin:1rem auto}main{padding:1.2rem}.actions button{width:100%}}
</style></head><body><main>
<h1>Form Agent</h1>
<label for="prompt">Prompt</label><textarea id="prompt" oninput="updateButtons()" placeholder="Tell the agent which form to find and what information to use."></textarea>
<div class="attachments"><label class="upload" for="pdfs">+ Add files<input id="pdfs" type="file" accept="application/pdf,.pdf" multiple onchange="uploadPdfs()"></label><span class="muted"> Reference PDFs</span><div id="documents"></div><label class="upload" for="formPdf">+ Add form PDF<input id="formPdf" type="file" accept="application/pdf,.pdf" onchange="uploadFormPdf()"></label><div id="templateInfo" class="muted"></div><button class="secondary" id="removeTemplate" onclick="clearTemplate()" hidden>Remove form PDF</button></div>
<div class="actions"><button id="start" onclick="startRun()">Search on Google</button><button class="secondary" id="resume" onclick="resumeRun()" disabled>Resume after intervention</button><button class="secondary" id="stop" onclick="stopRun()" disabled>Close</button></div>
<p id="runMessage" class="muted" role="status" aria-live="polite">Ready.</p>
<div id="pdfResult" hidden><a id="downloadPdf" class="download">Download filled PDF</a><p id="pdfSource" class="muted"></p></div>
<section class="interventions" aria-labelledby="interventionHeading"><h2 id="interventionHeading">Human intervention needed</h2><p id="handoffMessage" class="muted">Questions that need your input will appear here.</p><ul id="questions" class="questions"></ul></section>
</main><script>
let timer=null;let docs=[];let template=null;let uploading=false;let busy=false;let lastState={status:'idle'};
function webPdfRequest(){const p=document.getElementById('prompt').value||'';return /\bpdf\b/i.test(p)&&(/\b(?:find|search|navigate|browse|visit|go to)\b/i.test(p)||/https?:\/\//i.test(p)||/^\s*(?:download|fetch)\b/i.test(p))}
const terminal=s=>['stopped','finished','error','idle'].includes(s.status);
async function request(path,method='GET',body=null){const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},body:body===null?undefined:JSON.stringify(body)});const j=await r.json();if(!r.ok)throw new Error(j.detail||'Request failed');return j}
function showError(message){const box=document.getElementById('runMessage');box.textContent=message;box.className='error'}
function updateButtons(){document.getElementById('start').disabled=busy||uploading||!terminal(lastState);document.getElementById('resume').disabled=busy||lastState.status!=='waiting_user';document.getElementById('stop').disabled=busy||terminal(lastState)||lastState.status==='stopping';document.getElementById('pdfs').disabled=uploading||busy||!terminal(lastState);document.getElementById('formPdf').disabled=uploading||busy||!terminal(lastState);document.getElementById('removeTemplate').disabled=busy||uploading||!terminal(lastState);document.getElementById('start').textContent=template&&!webPdfRequest()?'Fill PDF':'Search on Google'}
async function uploadPdfs(){const input=document.getElementById('pdfs');uploading=true;updateButtons();try{for(const f of input.files){const fd=new FormData();fd.append('file',f);const r=await fetch('/api/documents',{method:'POST',body:fd});const j=await r.json();if(!r.ok)throw new Error(j.detail||'PDF upload failed');docs.push(j);renderDocs()}document.getElementById('runMessage').textContent='Files added.'}catch(e){showError(e.message)}finally{input.value='';uploading=false;updateButtons()}}
async function removePdf(id){busy=true;updateButtons();try{await request('/api/documents/'+encodeURIComponent(id),'DELETE');docs=docs.filter(d=>d.document_id!==id);renderDocs()}catch(e){showError(e.message)}finally{busy=false;updateButtons()}}
function renderDocs(){const box=document.getElementById('documents');box.replaceChildren(...docs.map(d=>{const row=document.createElement('div');row.className='docrow';const span=document.createElement('span');span.textContent=d.filename;const b=document.createElement('button');b.textContent='Remove';b.setAttribute('aria-label','Remove '+d.filename);b.disabled=busy||!terminal(lastState);b.onclick=()=>removePdf(d.document_id);row.append(span,b);return row}))}
async function action(path,body=null){busy=true;updateButtons();try{render(await request(path,'POST',body));startPolling()}catch(e){showError(e.message)}finally{busy=false;updateButtons();renderDocs()}}
function startRun(){if(!document.getElementById('prompt').value.trim()){showError('Enter a prompt first.');document.getElementById('prompt').focus();return}if(template&&!webPdfRequest())return fillPdf();document.getElementById('pdfResult').hidden=true;return action('/api/start',{prompt:document.getElementById('prompt').value,document_ids:docs.map(d=>d.document_id)})}
function resumeRun(){return action('/api/resume')}
function stopRun(){return action('/api/stop')}
function startPolling(){if(timer)clearInterval(timer);timer=setInterval(poll,1200)}
async function poll(){try{render(await request('/api/status'));if(terminal(lastState)){clearInterval(timer);timer=null}}catch(e){showError('Cannot reach the agent: '+e.message)}}
function render(s){lastState=s;updateButtons();renderDocs();const box=document.getElementById('runMessage');box.textContent=s.error||s.message||'Ready.';box.className=s.status==='error'?'error':'muted';renderHandoff(s);if(s.pdf_result)renderPdfResult(s.pdf_result,s.pdf_source_url);else document.getElementById('pdfResult').hidden=true}
function renderHandoff(s){const active=['waiting_user','review_ready','form_ready'].includes(s.status);const box=document.getElementById('questions');const note=document.getElementById('handoffMessage');box.replaceChildren();document.title=active?'Intervention needed — Form Agent':'Form Agent';if(!active){document.getElementById('interventionHeading').textContent='Human intervention needed';note.textContent=terminal(s)?'Questions that need your input will appear here.':'No intervention needed right now.';return}const reason=s.handoff_reason||'';const heading=document.getElementById('interventionHeading');heading.textContent=s.status==='review_ready'?'Ready for your review':'Human intervention needed';note.textContent=s.message||'Complete the requested step in Chrome, then resume here.';const showFields=s.status==='form_ready'||['missing_required_fields','write_verification'].includes(reason);const fields=showFields?((s.handoff_context||{}).fields||[]).filter(f=>!f.already_filled&&(reason!=='missing_required_fields'||f.required||f.manual_only)):[];if(!fields.length)return;for(const [index,f] of fields.entries()){const item=document.createElement('li');item.className='question';const title=document.createElement('h3');title.textContent=(index+1)+'. '+f.label;const input=document.createElement('p');input.textContent='Input field: '+(f.tag==='textarea'?'Long text':f.field_type||f.tag||'Text')+(f.required?' · Required':' · Optional')+(f.manual_only?' · Complete manually':'');item.append(title,input);if(f.options&&f.options.length){const label=document.createElement('p');label.textContent='Options';const options=document.createElement('ul');options.className='options';for(const value of f.options){const option=document.createElement('li');option.textContent=value;options.append(option)}item.append(label,options)}box.append(item)}}
function renderTemplate(){document.getElementById('templateInfo').textContent=template?template.filename+' · '+template.page_count+' pages · '+template.field_count+' fields detected':'';document.getElementById('removeTemplate').hidden=!template;updateButtons()}
async function uploadFormPdf(){const input=document.getElementById('formPdf');if(!input.files.length)return;uploading=true;updateButtons();try{const fd=new FormData();fd.append('file',input.files[0]);const response=await fetch('/api/pdf/templates',{method:'POST',body:fd});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Could not inspect PDF');const previous=template;template=result;renderTemplate();document.getElementById('pdfResult').hidden=true;document.getElementById('runMessage').textContent='Form PDF ready. Enter your instructions and click Fill PDF.';if(previous)await request('/api/pdf/templates/'+encodeURIComponent(previous.template_id),'DELETE')}catch(e){showError(e.message)}finally{input.value='';uploading=false;updateButtons()}}
async function clearTemplate(){if(!template)return;busy=true;updateButtons();try{await request('/api/pdf/templates/'+encodeURIComponent(template.template_id),'DELETE');template=null;renderTemplate()}catch(e){showError(e.message)}finally{busy=false;updateButtons()}}
function renderPdfResult(result,source=''){const link=document.getElementById('downloadPdf');link.href=result.download_url;link.download=result.filename;document.getElementById('pdfResult').hidden=false;document.getElementById('runMessage').textContent=result.filled_count+' fields filled. '+result.remaining_fields.length+' left for you. The PDF stays editable.';document.getElementById('interventionHeading').textContent='Details left for you';document.getElementById('handoffMessage').textContent=(result.warnings||[]).join(' ')||'Download the PDF to review the filled values and complete the remaining fields.';const questions=document.getElementById('questions');for(const f of result.remaining_fields){const li=document.createElement('li');li.className='question';li.textContent=f.label+' · Page '+f.page;const skipped=(result.skipped_fields||[]).find(x=>x.field===f.label);if(skipped){const reason=document.createElement('p');reason.textContent=skipped.reason;li.append(reason)}questions.append(li)};document.getElementById('pdfSource').textContent=source?'Source: '+source:''}
async function fillPdf(){busy=true;updateButtons();document.getElementById('pdfResult').hidden=true;document.getElementById('questions').replaceChildren();document.getElementById('runMessage').className='muted';document.getElementById('runMessage').textContent='Reading the form and matching your prompt and reference PDFs…';try{const result=await request('/api/pdf/fill','POST',{template_id:template.template_id,prompt:document.getElementById('prompt').value,document_ids:docs.map(d=>d.document_id)});renderPdfResult(result)}catch(e){showError(e.message)}finally{busy=false;updateButtons()}}
async function loadInitialState(){busy=true;updateButtons();try{docs=await request('/api/documents');const templates=await request('/api/pdf/templates');template=templates.length?templates[templates.length-1]:null;renderTemplate();render(await request('/api/status'));if(!terminal(lastState))startPolling()}catch(e){showError(e.message)}finally{busy=false;updateButtons();renderDocs()}}
loadInitialState();
</script></body></html>"""
