# Prompt-driven web agent with PDF context

This app opens visible Chrome at the site named in your prompt. Give it a full URL/domain or say "go to [site name]"; known SEC TCR requests open the SEC TCR welcome page, and other named sites are searched in Chrome. The dashboard uses general AI form assistance: it maps information from your prompt and optional attached PDFs to supported visible text fields and choice controls on the requested site. It fills only source-supported answers, leaves missing or ambiguous information for you, and keeps source provenance for filled values. It pauses for CAPTCHA, sign-in/MFA, consent, legal attestations, unavailable required data, and unsupported controls. It stops at review or final-action controls and never clicks Submit, File, Send, Sign, or Certify.

Only the destination and details you put in the prompt determine where it goes. The app does not have a fixed target website. Use accurate information that you are authorized to provide; fictional Northwind scenario details must not be entered into a live SEC TCR form.

## Install and configure

You need Python 3.11 or newer and Google Chrome installed. You do **not** need to install ChromeDriver separately: Selenium Manager will find or download a compatible driver when Selenium launches Chrome. [Selenium Manager documentation](https://www.selenium.dev/documentation/selenium_manager/).

In PowerShell:

```powershell
cd C:\Users\anier\OneDrive\Desktop\HacktheBurg\form_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Open `form_agent/.env` and set:

```dotenv
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_MODEL=your-model-id-from-the-Nebius-Token-Factory-catalog
NEBIUS_API_KEY=your-token
CHROME_PROFILE_DIR=.browser_profile
MAX_FORM_PAGES=20
```

Use the model ID shown in your Nebius Token Factory catalog. Keep the token in this local `.env`; do not put it in the prompt, commit it, or send it in chat. The `.env` file is ignored by git. Nebius Token Factory provides an OpenAI-compatible API; the app sends chat-completion requests to its configured endpoint. [Nebius Token Factory API](https://api.tokenfactory.nebius.com/docs).

## Run

```powershell
.\.venv\Scripts\python.exe -m uvicorn form_agent.app:app --app-dir src --host 127.0.0.1 --port 8210
```

Open [http://127.0.0.1:8210](http://127.0.0.1:8210). Enter the destination and task in **Prompt**, use **Add files** to attach readable PDFs, then click **Search on Google**. Named sites are searched on Google; explicit URLs open directly. There is no mode dropdown. Below the three action buttons, the dashboard lists unanswered intervention questions, available options, and input field types. Complete those fields in Chrome, then click **Resume after intervention** when enabled. **Close** stops the run and closes its Chrome session. The same AI assistance works with prompt details alone, PDFs alone, or a combination, on SEC and other requested destinations. Source evidence and detailed events remain available from `/api/status`. Uploaded PDFs live in memory only and are cleared when the app restarts; they are not saved to disk by this app.

AI form assistance requires `NEBIUS_MODEL` and `NEBIUS_API_KEY` in `form_agent/.env`, including prompt-only runs. The API still supports explicit `navigate_only` runs, which leave fields unchanged and do not require a model. The dashboard reports browser startup errors and run progress; if Chrome does not open, read the status message (or detailed events from `/api/status`) before retrying.

### PDF retrieval and model data flow

- The app extracts selectable text locally with `pypdf`, splits it into overlapping page-specific chunks, and ranks those chunks locally with BM25 for the prompt and current field labels/options.
- At most 12 relevant excerpts are sent to Nebius for the current page, along with the user prompt and visible field labels/options. For browser form filling, the PDF itself, browser cookies, and existing browser field values are not sent. PDF-template vision discovery, when explicitly configured, sends rendered template pages as described below.
- Both prompt and PDF evidence can support text and choice answers. No PDF is required when the prompt supplies the details. The model is instructed to respect requests to leave fields blank and to leave conflicting or ambiguous answers for the user. Source quotes validate where values came from; they do not independently prove that a choice answers the question correctly.
- For ordinary text inputs, the value must be an exact substring of an exact quote from the prompt or a retrieved chunk. For dropdown/radio/checkbox options, the selected value must exactly match an available option, and the model must provide an exact evidence quote plus a reason that connects the fact to that option. Review the value, reason, and quote from `/api/status`; this helps expose mistakes but does not independently prove the semantic choice or the source's accuracy.
- Scanned/image-only reference PDFs are not OCR'd and will be rejected if no selectable text is found. Export an OCR/text-enabled PDF before uploading. Encrypted PDFs are unsupported. Limits: 15 MB per PDF, 250 pages, 10 PDFs, and 2 million extracted characters total per PDF.
- PDFs with untrusted instructions are treated as data; only exact source passages can support values. Do not upload material you are not authorized to send to the configured model provider.

### Human handoffs

When the dashboard shows "Human intervention needed", it lists the question, field, required fields left blank, and available options. Chrome is brought forward when Windows permits it. Complete the step yourself, then Alt+Tab to the dashboard and press **Resume**. This includes CAPTCHA, sign-in, account setup, MFA, consent, legal declarations, and required details not supplied by you. The app does not solve CAPTCHA, bypass access controls, create accounts, or handle passwords/OTP codes. A newly opened hostname requires your review before the run continues.

At `review_ready`, inspect the page in Chrome and stop the run. The agent never performs the final submission action. The SEC TCR site is live; do not use fictional/demo facts on it.

## Limits

The agent handles supported visible text fields, dropdowns, multi-selects, and labeled radio/checkbox groups. For choice controls, it considers available labels/options and selects only choices explicitly supported by the prompt or retrieved PDF text. It leaves file inputs, custom widgets, unlabelled controls, and inaccessible shadow-DOM fields for you. Website markup and flows may change, and the app may pause for manual navigation. The prompt and retrieved excerpts are sent to the Nebius model you configured; use suitable data only. Browser session state is stored locally in the ignored `form_agent/.browser_profile` directory.


## Fill an uploaded PDF

This is a general PDF workflow with no form-specific mapping. It follows the field-name/coordinate approach of [GSA/pdf-filler](https://github.com/GSA/pdf-filler), adapted to the existing Python application and AI/RAG mapper; it does not require running the Ruby service or PDFtk.

1. Upload the PDF you want to complete with **Add form PDF**. The primary action becomes **Fill PDF**.
2. Optionally attach supporting/reference PDFs with **Add files**.
3. Write a prompt such as: "Fill this form using my details: Full name: Alex Morgan. Use the reference PDFs for the other answers. Leave missing information and signatures blank. Return an editable PDF."
4. Click **Fill PDF**, then **Download filled PDF**. The page lists detected fields left for you. Review the result and complete any remaining answers in a PDF editor.

The app inspects the uploaded template dynamically, maps supplied prompt and retrieved reference details to its fields, and fills all pages. Existing answers and read-only fields are preserved. Text answers require source quotes; choice answers must match available options. Signatures and attestations remain manual. Responses include the evidence for each filled field, remaining fields, and any fields skipped because the answer cannot fit legibly. The output is not flattened, so remaining form fields stay editable.

- **Fillable PDFs:** existing text fields, dropdowns/list boxes, checkboxes and radio buttons are supported. Labels, nearby printed labels, and export values are inspected rather than configured per form.
- **Flat PDFs:** empty vector boxes and ruled text-answer lines are detected conservatively and converted to editable text fields while preserving the page background.
- **Scanned or complex templates:** set `PDF_VISION_MODEL` in `.env` to a vision-capable model available at your configured API endpoint. The app sends rendered template page images to that model to locate blank answer areas, then uses the normal prompt/RAG mapper to fill them. Review visually inferred field placement. Without a suitable model, unsupported pages are reported instead of claiming that they were filled. Scanned reference PDFs still require OCR before being added as reference documents.
- Encrypted PDFs, XFA forms, and already digitally signed PDFs require an unlocked, standard, unsigned copy. Ambiguous duplicate fields are rejected. Unsupported controls remain manual. Automatic discovery cannot guarantee every writable area in every PDF layout.
- Templates: 15 MB, 100 pages, 500 detected fields, at most 5 active templates. Templates and generated downloads remain in memory for one hour or until restart; the latest 10 results are retained. Download a copy to keep it. Original uploaded files are not written to disk by the service.

API endpoints: `POST /api/pdf/templates` (multipart `file`), `GET /api/pdf/templates`, `DELETE /api/pdf/templates/{template_id}`, `POST /api/pdf/fill` (`template_id`, `prompt`, optional `document_ids`), and the returned `download_url`. PDF filling does not open Chrome or submit anything to the issuing organisation. Remove the selected form template to return the primary action to browser search.


## Find, download, and fill a PDF from the web

A PDF task can start with just a prompt and optional reference attachments. There is no need to upload the blank form:

```text
Go to the issuing organisation's forms page at https://issuer.example/forms.
Find and download Form X11 as a PDF, then fill it using my details below and the attached reference PDFs.
Full name: Alex Morgan.
Leave missing details, signatures, and attestations blank. Return an editable PDF for download. Do not submit or send it.
```

Use **Add files** for reference PDFs and click **Search on Google**. An explicit site URL opens directly; a named-site/form search starts in Google. The agent follows matching document links, downloads the PDF, applies the same template-independent PDF filler, and displays **Download filled PDF** with the original source URL and detected fields left for you. Prompts to find a web PDF take precedence over a previously selected uploaded template.

The agent identifies form links from their labels, nearby page text, and URLs using the configured AI model. It prefers the requested official form/version and pauses when the match is ambiguous. It pauses for CAPTCHA, sign-in, consent, or a newly encountered download/redirect host, then continues after **Resume**. Browser cookies are domain-scoped for downloads and are not sent to the model. A downloaded PDF is handled in memory, with a 15 MB size limit, bounded redirects, HTTPS for public downloads, and checks against private-network destinations. A blocked download or a link returning HTML is handed back to the user in Chrome.

`GET /api/status` exposes `pdf_source_url` and `pdf_result` (including `download_url`, evidence, and remaining fields). Status moves through `downloading_pdf`, `filling_pdf`, and `pdf_ready`. At `pdf_ready` the agent waits; **Close** ends its browser session while the generated download remains available until its normal expiry. The issuing website is not submitted to or updated. Existing PDF detection/vision limits still apply; generated JavaScript/blob downloads and POST-only download flows may require manual intervention.
