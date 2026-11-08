# Prompt-driven web agent with PDF context

This app opens visible Chrome at the site named in your prompt. Give it a full URL/domain or say "go to [site name]"; known SEC TCR requests open the SEC TCR welcome page, and other named sites are searched in Chrome. The default **Navigate to the form** mode leaves all fields unchanged and pauses at the first relevant form. The explicit **SEC form assistance from attached PDF** mode is limited to SEC.gov and uses retrieved PDF passages to populate supported fields with source provenance. Both modes pause for CAPTCHA, sign-in/MFA, consent, legal attestations, unavailable required data, and unsupported controls. It never clicks Submit, File, Send, Sign, or Certify.

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

Open [http://127.0.0.1:8210](http://127.0.0.1:8210). Choose **Navigate to the form** by default, or select SEC PDF assistance and attach a readable PDF before starting. Enter the destination and task in the prompt, then click **Run in Chrome**. The dashboard shows retrieved PDF excerpts, fields/options, filled values, and their source quotes. Uploaded PDFs live in memory only and are cleared when the app restarts; they are not saved to disk by this app.

Navigation-only mode does not need a model or API token. SEC PDF assistance requires `NEBIUS_MODEL` and `NEBIUS_API_KEY` in `form_agent/.env`. The dashboard reports browser startup errors and run progress; if Chrome does not open, read the run status and recent events before retrying.

See [PHASED_BUILD_PROMPTS.md](PHASED_BUILD_PROMPTS.md) for the staged implementation prompts and cross-validation gates. General web crawling is a later phase and is not enabled by this app.

### PDF retrieval and model data flow

- The app extracts selectable text locally with `pypdf`, splits it into overlapping page-specific chunks, and ranks those chunks locally with BM25 for the prompt and current field labels/options.
- At most 12 relevant excerpts are sent to Nebius for the current page, along with the user prompt and visible field labels/options. The PDF itself, browser cookies, and existing field values are not sent.
- For ordinary text inputs, the value must be an exact substring of an exact quote from the prompt or a retrieved chunk. For dropdown/radio/checkbox options, the selected value must exactly match an available option, and the model must provide an exact evidence quote plus a reason that connects the fact to that option. Review the displayed value, reason, and quote; this helps expose mistakes but does not independently prove the semantic choice or the source's accuracy.
- Scanned/image-only PDFs are not OCR'd and will be rejected if no selectable text is found. Export an OCR/text-enabled PDF before uploading. Encrypted PDFs are unsupported. Limits: 15 MB per PDF, 250 pages, 10 PDFs, and 2 million extracted characters total per PDF.
- PDFs with untrusted instructions are treated as data; only exact source passages can support values. Do not upload material you are not authorized to send to the configured model provider.

### Human handoffs

When the dashboard shows "Human intervention needed", it lists the question, field, required fields left blank, and available options. Chrome is brought forward when Windows permits it. Complete the step yourself, then Alt+Tab to the dashboard and press **Resume**. This includes CAPTCHA, sign-in, account setup, MFA, consent, legal declarations, and required details not supplied by you. The app does not solve CAPTCHA, bypass access controls, create accounts, or handle passwords/OTP codes. A newly opened hostname requires your review before the run continues.

At `review_ready`, inspect the page in Chrome and stop the run. The agent never performs the final submission action. The SEC TCR site is live; do not use fictional/demo facts on it.

## Limits

The agent handles supported visible text fields, dropdowns, multi-selects, and labeled radio/checkbox groups. For choice controls, it considers available labels/options and selects only choices explicitly supported by the prompt or retrieved PDF text. It leaves file inputs, custom widgets, unlabelled controls, and inaccessible shadow-DOM fields for you. Website markup and flows may change, and the app may pause for manual navigation. The prompt and retrieved excerpts are sent to the Nebius model you configured; use suitable data only. Browser session state is stored locally in the ignored `form_agent/.browser_profile` directory.
