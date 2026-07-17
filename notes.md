# Developer Tooling Notes

This document provides a summary of the agentic developer tools utilized during this implementation session, detailing **what** tools were used, **where** and **when** they were invoked, and **how** they facilitated development.

---

## Technical Tool Inventory

| Tool Name | Scope & Context (Where) | Invocations (When) | Functional Role (How) |
|---|---|---|---|
| **`task_boundary`** | System orchestration and UI display management. | Set at the beginning of each major task transition (Planning, Execution, Verification). | Communicates high-level project milestones, checklists, and next steps to the user interface. |
| **`list_dir`** | Workspace root and system-generated artifact cache. | Used to inspect project layout, locate files (`requirements.txt`, script outputs), and check for other user directories. | Lists contents of relative or absolute directory paths to understand workspace setup. |
| **`view_file`** | `main.py`, `user_store.py`, `task.md`, `walkthrough.md`. | Called when reading exact line implementations or checking current checklist status. | Loads file contents into context (up to 800 lines) to parse logic, routes, and markdown structures. |
| **`write_to_file`** | `README.md`, `notes.md`, `test_mongo_store.py`, `walkthrough.md`. | Used when generating new documentation files, testing scripts, or creating initial artifacts. | Writes new target files or completely overwrites existing files. |
| **`replace_file_content`** | `main.py`, `user_store.py`, `task.md`, `walkthrough.md`. | Invoked to execute specific codebase modifications, append checklists, or correct validator image paths. | Replaces a single contiguous block of code targeting precise matches within standard files. |
| **`grep_search`** | `main.py` | Executed to search for text patterns (e.g. `download-report` or `pdf`). | Utilizes ripgrep to scan directories or files and returns exact matching line numbers and contents. |
| **`browser_subagent`** | Local server endpoint tests (`localhost:8000/auth`). | Started to verify user flow, registration forms, canvas graphs, and top navigation changes. | Launches an autonomous browser session to click buttons, fill forms, check routing paths, and save screenshots/videos. |
| **`run_command`** | Powershell console | Applied during shell connection tests, package installations (`pymongo`, `mongomock`), and test execution. | Proposes console commands on the host operating system to install dependencies or execute scripts. |
| **`command_status`** | Background jobs | Checked periodically after spawning asynchronous pip installations or Python script runs. | Retrieves stdout/stderr outputs and monitors exit codes of background shell executions. |
| **`notify_user`** | Chat boundary | Used to request plan reviews or sign off upon completing implementation/verification milestones. | Suspends task processing to communicate summarized completion details and request user feedback. |

---

## Operational Workflow Demonstration

### 1. Data Cleaning Wizard Navigation Fixes
- **Where**: Header navbar layout (`templates/base.html`).
- **When**: After identifying that the user profile dashboard did not have an easy route back to the active upload page.
- **How**: Used `replace_file_content` to make the logo clickable and anchor dynamic menus. Validated using the `browser_subagent` to click links and record redirects.

### 2. MongoDB Database Migration
- **Where**: User accounts and analysis data-store modules (`ml_core/user_store.py` and `main.py`).
- **When**: Upon the user's task request to transition from file-based persistent memory to MongoDB.
- **How**: Used `run_command` to install driver dependencies. Utilized `test_mongo_store.py` with `mongomock` in-memory mocks to verify that user logins, registration duplicate keys, and BSON binary PDF outputs run correctly.
