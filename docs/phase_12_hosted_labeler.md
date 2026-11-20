# Phase 12 — hosted labeler: people correct the book-wide OCR

**Status:** planned, not built · **Created:** 2026-11-17 · **Owner:** maintainer
**Depends on:** Phase 9's gate and its "After the gate" steps; the region-keyed migration
(`docs/backlog/region_keyed_data.md`), including moving the answers to private storage
(step 4b); the book-wide OCR run with the chosen pipeline (Phase 11: hye-calfa-n + Paddle
→ Gemini 3.1 Pro v4 → `՚ի` rule).
**Feeds:** `corpus/` (a draft text, then the final text), Phase 11's v6 comparison (scored
on the corrections), Phase 10's test set (typed in this app's blank mode).

## Goal

Contributors log in at `ocr.andylitalo.com` and correct the OCR of every line in the
book, page by page. The target is **99.9% of lines fully correct**: about 14 wrong lines
in ~14,388 (~410k characters, ~190 pages). The v4 output is about 95% of lines (about
99.8% of characters) correct, so the work is finding the ~720 wrong lines without
breaking the right ones.

The first deliverable is a **draft**: one full pass, published with a measured accuracy
estimate. A second, blind pass is optional and follows if the draft isn't good enough
for its uses.

## Decisions (maintainer, 2026-10-11 → 2026-11-17)

### How 99.9% is reached

- One careful pass can't get there. Leftover wrong lines = OCR errors missed + correct
  lines broken, and even a careful typist slips (2 of the first 160 ceiling lines typed,
  p512 and p604, caught only because the engines read otherwise). Most of v4's remaining
  errors (7 of 9) are on lines where both engines agree, plausible enough to fool people
  too.
- So accuracy comes from the process, not from policing people:
  - **C, two full blind passes + adjudication.** Pass B corrects from the same prefill
    and never sees pass A's text. Lines where the passes agree are accepted; where they
    differ, a trusted labeler decides. If each pass catches 90% and the passes were
    independent, about 720 × 0.1 × 0.1 ≈ 7 lines stay wrong; the shared misses make it
    more, which is what E and F are for.
  - **E, a machine third reader.** Another model re-reads the human-final text with the
    image; differences go to the adjudication queue (~$20–40 for the book).
  - **F, word and consistency checks.** Words never seen elsewhere in the corpus or the
    Grabar Bible texts; recurring liturgical formulas typed two ways.
- **Breadth-first.** Pass A covers the whole book first and is published as the draft,
  with E and F run on it first. Pass B is optional. There is no review mode: a blind
  pass B costs about the same as checking A's text, and keeps the passes independent.
- **Deferred: D** (pass B starts from a different prefill). Raw Paddle or Tesseract output
  doesn't help, because it contains the agreed-line errors. Promote D only if a later
  evaluation shows a reader of similar accuracy with a different error profile.

### Line statuses and certainty

- Every line has one status: `single` (one pass), `verified` (two passes agree),
  `resolved` (a trusted labeler settled a disagreement or a flag), or `invalid` (an
  unlisted character, or a bad crop). The corpus manifest carries the status per line.
- Draft text per line: `resolved` → `verified` → `single` → OCR prefill. Lines nobody has
  labeled stay as OCR and are marked so.
- **Draft certainty** (before pass B): wrong lines left ≈ errors found × (1 − c) / c +
  correct lines broken. *c* is the team's catch rate on plants (about 63 plants over the
  book); lines broken come from the gold lines. Gold lines are drawn from engine
  disagreements, which are harder than average, so this errs pessimistic.
  - **Main risk: plant realism.** If plants are easier than real errors, *c* is too high.
    Check: the catch rate on gold lines whose prefill was really wrong is a second,
    honest *c*. A large gap between the two is a warning.
- **After pass B:** capture–recapture. (Errors only A found × errors only B found) /
  errors both found estimates the errors both missed. It undercounts when the passes
  share misses; the plants check it.
- The estimate is published with its interval: "draft: ~X% of lines correct (interval …)".

### Releases

- **R0:** the maintainer alone: practice pages, then real pages. Tests the operational
  unknowns (see "Risks to test in R0").
- **R1:** recalibration pages and the trusted-labeler adjudication queue are built.
- **R2:** invited contributors.

### Cloud

```
 browser ──HTTPS──> ocr.andylitalo.com: Firebase Hosting (static frontend, managed TLS)
                        │  /api/** rewrite
                  Cloud Run: FastAPI (1 vCPU / 512 MiB, min 1, max 2 instances)
                   │              │                 │
          Cloud SQL Postgres   GCS, private     Secret Manager
          (accounts, claims,   (page images)    (DB password)
           submissions, ...)
     Firebase Auth / Identity Platform (email + password; sign-up off)
```

- **Project:** `grabar-ocr` on the lectionary's billing account, in us-central1. It keeps
  the org's Workspace-only IAM rule; Cloud Run is made public with
  `--no-invoker-iam-check` instead of an override (see the infrastructure smoke test).
- **Frontend:** Firebase Hosting serves the static files and rewrites `/api/**` to Cloud
  Run. Its custom domains are generally available and the certificate is managed. Firebase
  Hosting strips every cookie except `__session`, so the browser sends the Firebase ID
  token as an `Authorization` header instead of using a cookie session.
- **Cloud Run:** min 1 instance, so there is no cold start; max 2, so the bill is capped.
- **Cloud SQL:** smallest shared-core Postgres, with automated backups and point-in-time
  recovery. Reached from Cloud Run over its built-in connection, and from the Mac with
  the Cloud SQL Auth Proxy.
- **Alerts:** an uptime check on `/health`; a $50/month budget alert. Labeler alerts: the
  app writes a structured log entry, and a log-based alert in Cloud Monitoring emails
  the maintainer a link to that person's report.
- **Cost:** roughly $20–30 a month.
- **Not now: a load balancer + Cloud Armor** (~$25–30 a month more, plus setup). They
  protect against floods of junk requests; with max 2 instances such a flood would slow
  or stop the site, but can't reach the data, and the bill stays capped. Login attacks hit
  Google's sign-in servers, not this app. Per-user rate limits and the ability to disable
  an account cover a rogue account, which Cloud Armor wouldn't stop. Add Firebase App
  Check first, then the load balancer, if the logs show sustained junk traffic or
  labelers hit errors. Adding it is front-door work, not an app change.

### Code layout

- `labeler_app/`: the hosted app, a uv workspace member with its own `pyproject.toml`
  (FastAPI, a Postgres driver, the Firebase Admin SDK), so the container doesn't carry the
  repo's PDF, OpenCV and LLM dependencies. Server and static frontend in subfolders
  (e.g. `server/`, `web/`).
- `layout_app/`: `dev/line_review` moved, local only, layout review only.
- **One shared module** for what both apps and the scoring use: the fold table, the
  allowlist, the record format and `line_crop`.
- **The transcription UI moves to the hosted app.** Gold lines, the practice answer
  keys and Phase 10's test set are typed in its admin **blank mode** (no prefill, as
  Phase 10 decided). One transcription tool, writing straight to the database. The
  `/transcribe` page in `dev/line_review` retires once the region migration has moved
  its data.
- **`labeling_ui/` retires.** Its web UI is superseded, but `labeling_ui/storage.py` and
  `pipeline.py` are imported by `pipeline/` (orchestrator, corpus, scoring, stages),
  seven `data_prep/` scripts, `ml_vision/scripts/predict_lines.py` and two test files.
  Move that library code first (into `pipeline/`, `data_prep/` or the shared module),
  then delete the UI and update AGENTS.md, `pyproject.toml` and the docs.
- **When:** the moves happen after the layout review is done, so the review's PRs never
  rebase a rename.
- AGENTS.md's conventions name Kubernetes Secrets; this app uses Secret Manager. Update
  the convention when the app is built.

### Lines and pages

- **Keyed by region**, as `docs/backlog/region_keyed_data.md` decides: each line is a
  region of layout `review-2026`, shown by its line id (`p520.013`). The layout is frozen
  when the lines are seeded.
- **A bad crop** goes to the admin queue. Fixing it gives the line a new region; the old
  region's submissions stay where they are, and the new region goes to the trusted
  queue to be typed. Nothing is renamed.

### Claims

- One page at a time per person, for the context. Pages are offered in book order as
  "the lowest-numbered page free for this pass". Contributors can also search by page
  number or section title (`section_titles` in the verified lines) and pick a free page.
- A database constraint allows one active claim per page and pass. Consistency over
  availability: a second request waits or gets another page.
- **Lease:** a week, renewed by any activity.
- **Can't Finish** releases the page. It is then the lowest free page, so it's served
  next and fills the gap. It isn't served again automatically to the person who released
  it (they can still pick it in search). A page released twice alerts the maintainer.
- **Resume:** the claim and every submitted line are stored. After login, "Continue
  page N" opens at the first unfinished line.
- **Taken over:** if a lease lapses and someone else claims the page, they start fresh
  from the prefill, never seeing the earlier text. The earlier lines are kept for
  measuring how much readers differ. If the original labeler returns to their own lapsed
  page and nobody has claimed it, they resume with their lines. If someone else has
  claimed it, they see a warning that the page was released and is being labeled.
- **Pass B** can't be claimed by the person who did pass A on that page, never sees pass
  A's text, and has its own plants.
- A page is served only once its gold lines are typed.

### The labeling screen

- Modelled on Phase 10's `/transcribe`: the line text box with its prefill; Enter submits
  and advances; Back/Next; a strip of pills per line; the character palette.
- **Context view:** opens on the full line, legible, with some page around it. Zoom
  (wheel, ±), pan (drag), and one click (and a key) back to the opening view. The page
  image is loaded once per claim; the browser cuts the line views itself from the
  polygons.
- Buttons: **Illegible**, **Bad crop**, and **Unlisted character** (saves the line as
  `invalid` instead of submitting).
- **Optimistic submit:** the next line shows at once; the save runs in the background,
  is kept in browser storage and retried until the server confirms. A pill turns green
  only once the server confirms; until then it shows "unsaved". The end-of-page reveal
  waits until every line is confirmed. If the server rejects a save (the claim was lost,
  say), the warning shows.
- Desktop only.

### Text rules

**Allowlist:** Armenian capitals U+0531–U+0556 and small letters U+0561–U+0587 (with
`և`), `՚ ՛ ՜ ՝ ՞ ՟`, `։`, `֊`, `․`, `—`, `« »`, `( )`, `,`, `=`, ASCII digits, and space.
`+` is not in it.

- ASCII digits stay ASCII; numerals the book prints as letters (`Ղուկ. Բ. 8.`, chapter
  in letters and verse in digits; the year `ՌՅԿԴ`) are typed as letters.
- `=` is printed (p453.023, `ՌՅԿԴ =1364`).
- `,` is the Armenian comma and is never folded. `՝` (U+055D, the "but" mark) is a
  different printed mark.

**Folding** (one table, applied as the labeler types, at seeding, to the existing ground
truth before comparing, and in scoring). Armenian punctuation is canonical:

| typed or OCR'd | stored | why |
|---|---|---|
| `.` | `․` (U+2024) | every printed dot, including abbreviations (`Ս․`) and after digits (`8․`) |
| `:` | `։` | the Armenian full stop |
| `'` | `՚` | the apostrophe in `՚ի` |
| `-`, `‐` (U+2010), `֊` at line end, right after a letter | `֊` (U+058A) | the word break at a line end: all 43 line-end hyphens typed so far, ~2,200 in the OCR |
| `—`, `–`, and a `-` after a space, punctuation or the line start | `—` (U+2014) | the printed punctuation dash: `Հիպերիքեանց, — և`, line-initial `— և`, the separator `- - -`. It was typed both as `—` and `–` for the same printed mark, and the OCR gives it as `-` about 120 times |
| a `-` anywhere else (between letters, or a letter then a space mid-line) | not folded | the check blocks it: the four cases in the OCR are misreads (`ա-ա`, `Ե- զայլն` twice for `Ե․ զայլն`, `մինչե- ՚ի`) |

Also: Unicode NFC; zero-width characters and non-breaking spaces removed; runs of spaces
collapsed.

- The em dash was chosen as the one dash (it was typed more often). Phase 11 scoring
  folded `—` into `-`; scoring moves to this table, and the re-score records any change
  in the Phase 11 doc.
- The raw text is stored beside the folded text.
- **The check:** a line with a character outside the allowlist can't be submitted. The
  error names the character; the escape hatch is **Unlisted character**.
- **Pativ (`՟`)** is allowed. A line containing one also goes to the maintainer's review
  queue: it appears nowhere in the OCR or in the lines typed so far, so either the book
  uses pativ and everyone has missed it (a gap across many lines), or the labeler
  mistook another mark for it.
- **Seeding report:** prefill lines that still fail the check after folding, for rule
  fixes. Tried on the ceiling output (v4 + rule, 8,500 lines, 2026-11-17): 65 fail. 60 are
  printed page numbers (`—(516)-`) on pages not yet reviewed; Phase 9 makes page numbers
  page elements, so they leave the lines at review. The other 5 are real: the four `-`
  misreads above and p604 `SoԵց` (Latin look-alikes). p453.023 (`=`) passes.

### Audit: gold lines and plants

- **Gold lines:** 1–2 per page, typed blank by the maintainer and verified by Claude,
  drawn from engine disagreements first. The ceiling and test-set lines already typed
  are reused as gold. A page with no disagreement line gets a plant instead.
- **Plants:** a realistic corruption of the prefill, drawn from the engines' actual
  errors (a tone-code letter, a confusable letter pair, a dropped `՚`, a missing `։`).
  Applied on the server, so the browser sees just "prefill". Scored by whether that
  change was undone, so a plant needs no typed answer and can go on any line.
  - About 1 per 3 real pages (never fewer than 1 per 5); about 3 per practice page.
  - Planted prefills are kept out of the engine's own error figures.
- **Every miss** sends that page for an extra pass, even during pass A. So the draft
  has some `verified` pages.
- **End-of-page reveal** (after the last line is confirmed): lines done, time taken, and
  "hidden errors: 1 found ✓" or "1 slipped by", with the planted change shown and a short
  "what to look for" note matched to its type. Encouraging in tone. Contributors are told
  up front, once, that some pages hide planted OCR mistakes, and that finding them
  measures how many errors are left in the book. Gold lines are never revealed (the
  reference could be wrong; disagreements go to the maintainer).

### Contributors

- **Practice first:** two fixed practice pages, with ~3 plants each and feedback after
  every line. **Passing means 100%:** every line matches the key exactly after folding,
  and every plant is caught, judged on each line's first submission (before its
  feedback). A fail allows one retry on the same pages with the plants moved. A second
  fail blocks the contributor and alerts the maintainer, and the contributor is told the
  maintainer will check in about next steps. Practice work is kept for internal analysis
  only.
- **Practice keys** are the maintainer's full corrections of those pages, verified by
  Claude. Each key also becomes its page's final text, as `resolved`.
- **Trust states:** practice → trained → back to practice or paused, only by the
  maintainer's choice. The maintainer makes contributors trusted labelers.
- **Recalibration:** a real page with ~3 extra plants (it counts as real work), after 25
  pages, then 50, then 100 (capped at 100) while every plant is caught; a miss resets the
  interval to 25.
- **Alerts** (to the maintainer only; nothing happens automatically to the person):
  - 2 or more misses in the person's last 20 plants. A person sees about 5 plants in pass
    A (about 10 if pass B runs), so in practice this means 2 misses at all;
  - any gold-line disagreement;
  - a practice second fail;
  - a page released twice.

  Each alert links to the person's report (pages, lines, time, catch rate, gold
  agreement, misses with their lines), so the maintainer can tell a borderline slip from
  something that needs a conversation. Thresholds are adjusted if they prove noisy.
- **Stats** (pages, lines, catches) are shown to the contributor and to the maintainer.
  Misses never reduce credit. There's no accuracy leaderboard.

### Accounts and licence

- **Invite-only.** Self sign-up is off. The maintainer creates each account, and Firebase
  emails a set-password link from its default `…firebaseapp.com` sender. The maintainer
  warns invitees about spam folders; a custom sender domain is for later.
- **At sign-up:** first name (required), last name (optional), the contributor agreement,
  and a privacy note on what is stored.
  - The agreement: corrections are licensed **CC BY-NC 4.0**, matching the corpus, and the
    project may relicense them within non-commercial terms (for example to BY-NC-SA later).
    Claude drafts the text; the maintainer reviews it. It isn't legal advice.
  - Both texts live in `docs/labeler/` and write the contact address as `{contact_email}`.
    The app fills it in from the `LABELER_CONTACT_EMAIL` environment variable, so the
    address is shown only to invited contributors, never published in this public repo.
  - The grant runs to Andy Ylitalo as maintainer, and to anyone he passes the project to,
    so the relicensing right survives a handover.
  - **Collective attribution:** contributors agree that crediting "grabar-ocr, Andy
    Ylitalo, and contributors" (with Calfa for the OCR), plus the published credits list,
    meets CC BY's attribution requirement. Researchers copying a line can't name every
    contributor. When volunteer text first lands, `corpus/LICENSE`'s copyright line
    ("Andy Ylitalo, for the compilation, corrections …") gains "and contributors", and its
    reuse credit matches this wording.
- **Credit by name** is an opt-in checkbox at sign-up, changeable in settings. Otherwise
  the contributor is counted as an anonymous contributor.
- **Names never enter public git.** The credits list (names who opted in, plus a count of
  anonymous contributors) is published in each release's notes (a GitHub Release), not
  committed. It isn't keyed by the submission ids, so a name isn't linked to anyone's
  lines, timings or accuracy. Withdrawing credit or deleting an account removes the name
  from the next release and from earlier releases' notes; copies others already made
  can't be recalled.
- **Deleting an account** keeps the corrections, re-attributed to "anonymous contributor",
  and erases the name and email.

### Where the data lives

The repo is public on GitHub, so anything exported to it is world-readable.

| place | what |
|---|---|
| **Database** (live source of truth for all human work) | accounts, claims, every submission, line statuses, gold, plants, practice keys, alerts |
| **Public git** (`grabar-ocr`) | the layout and regions; the corrections export (opaque contributor ids, no names); `certainty.json`. The prefill comes from the book-wide outputs (GCS + manifest, AGENTS.md "Data storage") |
| **Private git** (`grabar-ocr-private`, a private GitHub repo cloned beside this one; maintainer, 2026-11-17) | answers: the ceiling and test-set transcriptions, gold lines, practice keys, the plant log, alert history, and the opaque id → credit name map. Scripts find it through a configured path |
| **GCS, private** | page images for the app |
| **Firebase** | emails and passwords (Google's side) |

- **Private stays private:**
  - The server enforces it, never the browser. Gold and practice answers never leave the
    server, except in the end-of-page reveal, fetched after the page is done, and only for
    planted lines. Admin endpoints check the role on the server. Logs never contain emails
    or answer text.
  - Buckets use uniform access control with no public access; only the Cloud Run service
    account reads them. Only the maintainer's Google account has roles on the project.
  - The export writes public and private parts to different destinations. A test checks
    that the public export contains no private fields, and `.gitignore` excludes the
    private paths.
- **The answers committed so far** (ceiling, test set) leave `main` at the region
  migration (step 4b). Older commits still contain them; that risk is accepted, since
  contributors are people the maintainer knows.

### Seed and export

Both are scripts the maintainer runs from the Mac; no scheduled jobs.

- **Seed:** the frozen layout's regions, the prefill, the risk signals per line (engines
  agree?, which reading v4 chose, did v4 change an agreed line, risk pattern hit?), gold
  lines and practice keys. It writes the seeding report.
  - It refuses to run while answer files are still in the public tree (the guard that
    the move in step 4b has happened).
- **Export:**
  - Public: `data/transcriptions/corrections/page_<N>.json`, one record per region:
    `typed_as`, `geometry`, `prefill {engine, text}`, `final {text, status}`, and every
    submission `{contributor, pass, text, raw_text, status, at, seconds}` under an opaque
    contributor id. Also `certainty.json` (the estimate with its interval, and counts per
    status).
  - Credits: the release-notes list (names who opted in, anonymous ones as a count), not
    committed and not keyed by contributor id.
  - Private, to `grabar-ocr-private`: plants (line, type, caught?), gold and practice
    answers, alert history, the opaque id → credit name map. Emails are never exported.

### Non-functional

- About 12 people at once; one instance is plenty.
- Under 200 ms from Enter to the next line (optimistic submit, the page image already
  loaded).
- A line counts as saved only once it is committed to the database. At most the line in
  flight can be lost.
- No uptime guarantee; a short outage is fine if no data is lost.
- Per-user rate limits; an account can be disabled.

## Where this stands (pick-up note, 2026-11-17)

- **Planning is done; nothing is built.** Every decision is in this doc. Don't write
  `labeler_app/` code until the order of work below reaches step 5 and the maintainer says
  to start.
- **The box fix is in** (#21, with its data in #22, 2026-11-19). This doc was rebased
  onto it and p497 re-checked (see Practice pages).
- **The fix reshapes line polygons,** so region ids, which hash the boundary polygon, will
  differ from ids hashed before it. That's harmless: the region migration hasn't run, and
  it hashes the polygons as they stand when it does.
- **Can run beside the layout review, if the maintainer wants:**
  - ~~create the empty private repo~~: done 2026-11-17 (`andylitalo/grabar-ocr-private`).
    No data moves before migration step 4b;
  - ~~draft the contributor agreement and privacy note~~: done, PR #20, awaiting the
    maintainer's review;
  - a throwaway "hello world" behind Firebase Hosting on `ocr.andylitalo.com`, to
    surface domain, certificate and org-policy surprises before the real build: in
    progress, see the infrastructure smoke test below.
- **Open, decided later:** the Vol II practice page; the gold-agreement alert threshold
  (after pilot data); whether pass B runs (after the draft).

## Infrastructure smoke test (2026-11-20, in progress)

A throwaway two-route API (`/api/health`, `/api/echo`, never committed) behind Firebase
Hosting, to find the cloud surprises before the real build. The project, billing link,
budget and domain are kept for the real build; the hello-world service is not.

**Set up so far:**

- **Project** `grabar-ocr` (number 46107812726), under the lectionary org, linked to
  "Armenian Lectionary Billing".
- **Budgets** on that billing account, each scoped to one project: "grabar-ocr monthly"
  ($50, alerts at 50/90/100%) and the existing "Free Tier Safeguard" ($1, now
  `armenian-lectionary` only; it had covered the whole account, so OCR spend would have
  set it off every month). Both email the billing admins and, through a Monitoring email
  channel, the maintainer's Gmail. The channel lives in `armenian-lectionary`, because
  Monitoring refused calls in the newly created project (`USER_PROJECT_DENIED`, although
  the caller was owner; probably a delay before a new project's permissions take effect); budgets can use a channel from any project.
- **Cloud Run** service `labeler-hello`, deployed with `gcloud run deploy --source`.

**Findings:**

- **No org-policy override.** The org lets IAM roles go only to Workspace accounts
  (`iam.allowedPolicyMemberDomains`), so `allUsers` can't be granted `run.invoker`.
  Firebase Hosting forwards `/api/**` as an ordinary anonymous request (there is no
  Hosting identity to grant invoker to), so the service must be public.
  `--no-invoker-iam-check` makes it public without any IAM grant, and the org rule stays
  in force: the service's IAM policy is empty. Contributors are Firebase Auth users, not
  IAM principals, and never need roles. The lectionary could switch the same way.
- **The `*.run.app` URL stays reachable,** bypassing Hosting. Ingress settings can't close
  it without also blocking Hosting, so the app's own token check guards every route.
- **The `Authorization` header and cookies reach Cloud Run directly** (`/api/echo`). The
  check through the Hosting rewrite, where every cookie but `__session` should be
  stripped, comes in step 7.
- **Builds run as the default compute account.** New projects (since 2024) build as
  `<number>-compute@developer.gserviceaccount.com`, which needed
  `roles/cloudbuild.builds.builder` before `--source` deploys could read the uploaded
  source. The legacy Cloud Build account (`<number>@cloudbuild.gserviceaccount.com`) still
  holds that role but is used only if something selects it. **For the real build:** a
  dedicated build account with only the roles it needs (`--build-service-account`), and a
  dedicated runtime account for the service (Cloud SQL, its bucket, its secrets) instead of
  the compute default. Then remove the builder role from the compute account and the
  legacy account.
- **No Container Registry in the real build.** Enabling Cloud Build also turned on
  `containerregistry.googleapis.com` and added its service agent. Container Registry is
  retired; images go to Artifact Registry (`cloud-run-source-deploy`). Disable the API and
  confirm the agent's binding is gone, then check a `--source` deploy still works.

## Considered and not chosen

So that later sessions don't reopen them:

- **Cloud Run domain mapping** (still Preview, certificates can stall) → Firebase Hosting.
- **A load balancer + Cloud Armor now** → later, only on the triggers under "Cloud".
- **Identity-Aware Proxy** (Google accounts only, needs a load balancer) and **building
  password handling in the app** → Firebase Auth.
- **Firestore** → Cloud SQL Postgres (the data is relational; SQL for exports and
  review).
- **One labeler per line** → page claims, for context.
- **Review mode for pass B** → blind pass B (about the same cost, independent).
- **D (pass B from a different prefill)** → deferred; raw engine output shares v4's
  agreed-line errors.
- **One pass + targeted second pass** → can't reach 99.9%: most remaining errors are
  on lines the engines agree on, which targeting misses.
- **A strict miss cascade** (miss → redo the page → onboarding → suspension) → teaching
  on every miss, an extra pass for the page, and alerts to the maintainer. One miss is
  mostly chance at this plant rate, redoing your own page tests memory, and pass B
  protects the data.
- **An accuracy leaderboard** → private stats only.
- **Planted errors only from typed truth** → plants are scored by whether the planted
  change was undone, so they need no typed answer.
- **Retrying on extra practice pages** → the same pages with the plants moved, once;
  then the maintainer decides.
- **CC BY-NC-SA, CC BY-NC-ND** → CC BY-NC 4.0, with a grant to relicense within
  non-commercial terms.
- **Folding `,` to `՝`** → never: different marks.
- **One hyphen character for every dash** → two: the line-end word break `֊` and the
  punctuation dash `—`.
- **An `apps/` folder** → top-level `layout_app/` and `labeler_app/`, the labeler as a
  uv workspace member.
- **Keeping the answers in the public repo** → private repo at migration step 4b.
- **A public `contributors.json` mapping submission ids to names** → names in release
  notes only, unlinked to ids: the mapping would publish each credited person's lines,
  timings and effective accuracy, and git history can't forget a name.
- **A private GCS bucket or encrypted files for the answers** → a private GitHub repo
  (versioned, readable diffs, local scripts).

## Practice pages

Both should have display lines and a drop cap, and no answers already in the public repo.

- **Vol I: p497** (maintainer, 2026-11-17): 64 lines, 2 display lines (p497.001–002, by
  the 1.4× median-height rule in `dev/line_review/transcribe.py`), 1 drop cap (p497.003),
  no ceiling or test-set lines. Re-checked after the box fix (#21, #22) on 2026-11-19: the
  same counts and ids. The fix did reshape 41 of its boxes, so its line crops change.
- **Vol II:** chosen later, once its pages are verified (only pp.453–516 are verified so
  far). Look for a page of about 60–90 lines with a commemoration list (`, — և`, tone
  codes such as `Գշ. ԴԿ.`), display lines and a drop cap.

## Order of work

1. Phase 9's gate, then its "After the gate" steps.
2. The region-keyed migration (`docs/backlog/region_keyed_data.md`), including step 4b:
   the answers move to `grabar-ocr-private`.
3. The moves: `dev/line_review` → `layout_app/`; `labeling_ui/` retired.
4. The book-wide OCR run (Phase 11).
5. Build `labeler_app/`, then the seed, with the layout frozen.
6. **R0:** the maintainer types the practice keys and gold lines, and labels real pages.
7. **R1:** recalibration and the trusted queue.
8. **R2:** invites.
9. Pass A over the book → E and F → the draft is published with its certainty.
10. Pass B, if needed.

## Risks to test in R0

- **Operational setup.** The Firebase Hosting custom domain and certificate; the
  org-policy override; Cloud SQL's smallest tier (it has no SLA) and the connection from
  Cloud Run; cold start with min 1 instance; alert emails arriving; invite emails landing
  in spam.
- **The fold table over the full book's prefill.** The seeding report should be short.
- **The labeling flow.** Context-view zoom and pan on a full page image; two browsers
  claiming the same page at once; optimistic submit while offline, then on
  reconnecting.
- **Plant realism.** The catch rate on plants against the catch rate on real errors in
  gold lines.

## Gate

- **Draft:** every content line has a status (no line left as OCR only, `invalid` lines
  resolved); E and F have run and their queue is empty; the draft certainty is recorded
  here with its interval; the export is committed and `corpus/` is built from it.
- **Final** (only if pass B runs): every line is `verified` or `resolved`; the
  capture–recapture estimate, checked by the plants, is at least 99.9% of lines correct.

## Out of scope

The review design beyond the trusted-labeler queue; a load balancer and Cloud Armor; D;
mobile and tablet layouts; a custom email sender; a fuller admin interface (the
maintainer is the only admin); translation.
