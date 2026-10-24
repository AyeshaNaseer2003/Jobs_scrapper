# LinkedIn job scraper

## First-time setup (Windows PowerShell)

Install **Python 3.11 or newer** and **Microsoft Edge or Google Chrome** before starting. No paid API or API key is needed. Run the following steps in order.

### 1. Open the project folder

```powershell
cd "D:\My work\Scrapper\Jobs_scrapper"
python --version
```

Use the folder containing `run.cmd` and `requirements.txt`. On another computer, replace the path with your project location.

### 2. Create the virtual environment

```powershell
python -m venv .venv
```

Do this once. If you already have a working `.venv` here, skip this step. This workspace also supports reusing the existing parent environment at `..\.venv` instead of creating a second one.

### 3. Activate the environment

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run these instead:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`. If reusing the parent environment, activate it with `..\.venv\Scripts\Activate.ps1` instead.

### 4. Install the requirements

```powershell
python -m pip install -r requirements.txt
```

This installs all dependencies, including the browser library. Edge or Chrome must already be installed; no separate browser download command is needed for those browsers.

### 5. Create your .env file

```powershell
if (!(Test-Path .env)) { cp .env.example .env }
```

This copies the template only if `.env` does not already exist, keeping your existing settings. The defaults work as they are. To change them:

```powershell
notepad .env
```

For example, set `JOB_KEYWORDS=data science`, `JOB_LOCATION=Pakistan`, and `MAX_JOBS=25`. You can override these defaults through the terminal questions each time you search.

### 6. Run the scraper

```powershell
.\run.cmd
```

Choose **1** and follow the questions below. The scraper opens a visible browser.

## Every run after setup

```powershell
cd "D:\My work\Scrapper\Jobs_scrapper"
.\run.cmd
```

You do not need to reinstall requirements, copy `.env` again, or activate the environment. The launcher automatically finds `.venv` in this folder, your active environment, or `.venv` in the parent folder.

## Find jobs

1. Choose **1 - Search LinkedIn jobs** (or press Enter).
2. Enter the job you want, for example **data science**.
3. Enter a **city or country**, for example **Pakistan** or **Lahore**. This question does not take a yes/no answer. Press Enter to use Pakistan.
4. Enter how many days back to search, for example **30**.
5. Enter the maximum jobs to check, for example **100**.
6. Review the search summary. Press Enter to start, or type **n** to cancel.
7. A separate browser window opens. Leave it open while jobs are collected. If LinkedIn asks you to sign in or verify, complete that step yourself in the browser, then press Enter in the terminal. Enter **q** to stop instead.

Example:

```text
Job title or keywords [software engineer]: data science
City or country (e.g. Lahore, Pakistan, Remote) [Pakistan]: Pakistan
Posted within how many days [7]: 30
Maximum jobs to check [25]: 100

Your search: data science | Pakistan | last 30 days | up to 100 jobs
Published contact details will be collected automatically.
Start this search [Y/n]:
```

Press Enter at any question to use the value in brackets. Contacts are collected only when publicly available; some jobs have none. The maximum is a limit, not a guarantee. Seven days means the last 168 hours. The browser uses a separate temporary session: your usual browser profile is not accessed, and you may need to sign in again on a later run. Do not type passwords into this terminal or chat.

## Get your files

When the search finishes, the terminal prints the full file paths:

- **jobs.csv** - open this in Excel to view jobs.
- **contacts.csv** - published emails and phone numbers, with their source links.

Files are saved inside `data/searches/`. Each search has its own folder. Repeating the same role, location and day window updates that folder and keeps earlier results, including jobs that may now be older than the window. If a new search is blocked before collecting any jobs, no spreadsheet is created; only the diagnostic report and log are saved. Older versions may have left header-only spreadsheets from failed runs.

## If LinkedIn says to wait

LinkedIn sometimes limits automated access, even in a browser and on the first request. This is separate from what you enter in the location field. Browser mode is a free alternative to the guest endpoint, not a guaranteed solution to LinkedIn restrictions. The tool does not bypass verification or access blocks.

The scraper shows the earliest retry time in **Pakistan time**. If a cooldown from an earlier run is active, no browser or network request has started yet. The terminal offers to **wait and start automatically**: press Enter to wait, or type **n** to finish without waiting. Ctrl+C cancels the wait. A shared cooldown prevents requests across searches until the wait has passed. Saved jobs are kept. Changing your search does not fix a rate limit. LinkedIn can remain unavailable after the suggested time.

Technical details are saved in `run-report.json` and `run.log` inside the search folder. You do not need to read them for normal use.

## Run tests or exit

Run `.\run.cmd` and choose **2** to run automated tests without the internet, or **3** to exit.

Use `.\run.cmd --help` for optional commands. LinkedIn may ask you to sign in through its own browser page; do not enter passwords in the terminal.
