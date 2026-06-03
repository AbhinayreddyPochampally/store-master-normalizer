# Store Master Normalizer — Demo Script

A 10-minute walkthrough that takes someone from "what is this thing" to
"I've seen every feature, including the gnarly edge cases." Run it
from the running uvicorn server.

Open the app first: run `python -m web.run` from the repo root. Wait
for the browser tab to land on `http://127.0.0.1:8000`.

---

## 0. Frame the problem (~1 min, no clicks)

> **What the tool does.** Every month each retail brand exports its
> stores as a workbook. Every brand uses a different layout —
> different sheet names, different column orders, different vocabularies
> for the same fields. The backend store master has one fixed
> 42-column schema. Reconciling those exports into the master by hand
> is a person-week of cell-by-cell tedium and a frequent source of bad
> data getting promoted up to production.
>
> This tool reads the brand's *reference sheet* (which the brand owners
> already maintain — a 42-row mapping of master fields to source
> columns), applies the rules, and reconciles against the master in
> seconds. It produces an updated master and a change report that lists
> every real change. Nothing leaves the machine — it's a local web app.

Two key promises to mention out loud:

1. **Cosmetic differences don't fire.** `'27000'` and `27000` are the
   same. So are `'WEST BENGAL'` and `'West Bengal'`, `'Jul-17'` and
   `datetime(2017, 7, 1)`, and `'Uttar_Pradesh'` and `'Uttar Pradesh'`.
2. **There's an independent verifier.** After every conversion you can
   click "Verify output" — a second pass that re-derives every cell
   from the rules and source, and PASS/FAIL is a definitive check.

---

## 1. The home page (~30 sec)

![Idle](screenshots/demo_01_idle.png)

Point out:

- **Brand dropdown** — four brands today: Pantaloons, Planet Fashion,
  TASVA, TCNS. The list is read from `brands.json` next to the EXE on
  every request, so brands added via *Manage brands* show up here
  without restart.
- **Two dropzones** — drag-and-drop or click. Source accepts `.xlsx`
  and `.xlsb` (TASVA exports as xlsb). Master is the backend
  `Backend Data - Store Master.xlsx`.
- **Tip box** — for TCNS, the data sheet name shifts month to month
  (`Mar` → `Apr` → `May` …); a "Sheet name" field appears once you
  pick TCNS.
- **Footer** — *Engine vX.Y.Z · Manage brands · What this tool does*.
  Click *What this tool does* to show the plain-language modal for
  non-technical viewers in the room.

---

## 2. Pantaloons run (~1 min)

Walk through the easy, fast case first to set expectations.

1. Brand = **Pantaloons**.
2. Drop **Pantaloons_Apr_2026.xlsx** into Source.
3. Drop **Backend_Data_-_Store_Master.xlsx** into Backend master.
4. Click **Convert**. Talk through the loading state: the form
   disables, the button shows a spinner with "Converting…", a thin
   progress bar runs across the top of the card.

![Pantaloons results](screenshots/demo_02_pantaloons_results.png)

Read out the result card:

> **399 source rows, sheet `Sheet1`.**
> 0 NEW, **137 UPDATED**, 0 Code Changed, 0 Closed, 0 Warnings.

Then point at the top-5 fields by change count — Showroom Manager
Name (81), Showroom Manager No (46), ARM Contact No (32), Store Email
Id (30), Store Opening Date (13). These are real changes — staff
moves, phone updates, date corrections. The 262 stores that *didn't*
change have nothing to do, which is the whole point of the comparator
ignoring cosmetic noise.

Click **Updated Master** and **Change Report** — both download as
xlsx, both open cleanly in Excel.

---

## 3. The independent verifier (~30 sec)

Click **Verify output** on the same card.

![Verify pass](screenshots/demo_03_verify_pass.png)

> **PASS. Brand: Pantaloons. Rows checked: 6234 (scope: 545, passthrough:
> 5689). Cells: 22 890.** *All scope cells match the rules — engine output
> is consistent.*

Explain what the verifier did: it re-loaded the source workbook,
re-read the reference rules, and walked every cell of every Pantaloons
row in the output, comparing against what those rules *should* have
produced. It uses the same `_canonical` comparator the engine uses, so
cosmetic differences don't false-fail. The point: even if you don't
trust the conversion, the verifier proves the output is internally
consistent with the rules.

---

## 4. TASVA run — duplicate columns + reference correction (~1.5 min)

Reset (refresh the page, or scroll up).

1. Brand = **TASVA**.
2. Source = `TASVA_Stores_-_April_26.xlsb` (note the .xlsb extension —
   that's the Excel binary format Microsoft uses for big sheets; the
   tool reads it via pyxlsb).
3. Master = same backend master as before.
4. Convert.

> **94 source rows, sheet `Contact Master`. 1 NEW, 87 UPDATED,
> 0 Code Changed, 1 Closed, 0 Warnings.**

Two things make TASVA interesting; mention both:

### 4a. Duplicate column names

The TASVA `Contact Master` sheet has the column name `Contact No`
twice — once for the Regional Manager, once for the Area Manager.
Same for `Email id`. The engine resolves these by **adjacency to an
anchor**: when a unique column name appears (like `RM` or `ARM`), the
mapper "anchors" there, then duplicates get matched to the nearest
column index to the right of the current anchor.

### 4b. Reference correction overlay

The original TASVA reference sheet *appears to swap the RM rows* —
`RM Contact No` → `Email id` and vice versa. Rather than asking the
brand owners to fix their workbook (which would break their other
processes), the engine carries a **brand override** in `brands.json`
that corrects the swap. Show it: navigate to `/brands` → click *Edit*
on TASVA.

![TASVA edit](screenshots/demo_05_brand_edit_tasva.png)

Point at the two field overrides:

- `RM Contact No` → `COLUMN` → `Contact No`
- `Regional Manager E-mail Id` → `COLUMN` → `Email id`

Mention that operations staff can edit these overrides directly through
this form — no code change, no restart. The dropdown picks up changes
on the next request.

Go back to the result and download the **Change Report**. Open it in
Excel; show the Changes sheet. Every change row has the matched-on key
in the *Notes* column. Useful for an audit trail.

---

## 5. PF run — divergence warnings (~1 min)

Reset.

1. Brand = **Planet Fashion** (key `PF`).
2. Source = `Planet_Fashion_Dealer_Panel_-Mar_26.xlsx`.
3. Master = the backend master.
4. Convert.

> **100 source rows. 0 NEW, 48 UPDATED, 0 Code Changed, 0 Closed,
> 8 Warnings.**

Click the warning count or scroll down — the eight warnings are all
*ASP Code divergences*. The PF workbook has the column `ASP Code`
twice (columns 1 and 55, 1-indexed). For 8 stores those two columns
disagree. The engine doesn't block on this — it just surfaces it so
the operator can investigate. The leftmost ASP Code is what the
reference uses for Legacy Code; the rightmost looks like a legacy
identifier the operator may want to migrate into Old Sapcode.

Mention that this is configured in *Manage brands* → PF → *Divergence
warnings* as a `[1, 55]` pair. The list of pairs is brand-specific
and editable.

---

## 6. TCNS run — multiple sub-brands, sheet override (~1.5 min)

This is the biggest brand and the most complex configuration.

1. Brand = **TCNS**. **Notice the "Sheet name" field appears** with
   "Mar" pre-filled.
2. Source = `TCNS_-_Store_Master_-_Mar_Final.xlsx`.
3. Master = the backend master.
4. Convert. (Takes ~5 seconds — TCNS has 478 source rows.)

> **478 source rows, sheet `Mar`. 23 NEW, 370 UPDATED, 0 Code Changed,
> 10 Closed, 1 Warning.**

Things to call out:

### 6a. Per-row brand from the source

TCNS isn't a single brand — it's a portfolio: W, Aurelia, Dual,
Elleven, Wishful. Every store has its own `Brand` column. The
reference for the target fields `brand`, `Brand2`, and `NewSubBrand`
maps to that source column rather than a constant. Download the
**Updated Master** and filter `Organization = TCNS` — you'll see all
five values populating those target columns per row.

### 6b. The lone warning

> *In-scope master row 6225 has null/blank Store Id: Legacy Code='141516',
> brand='Folksong', Region='NORTH'*

Explain: somewhere in the master there's a row tagged `Organization =
TCNS` but with `brand = Folksong` (which isn't a TCNS brand) and no
Store Id. The engine can't match it (no Store Id) so it would silently
get closed — instead, the tool surfaces it so the operator can fix the
master directly.

### 6c. Sheet-name override

Next month the brand will export a sheet named `Apr` instead of `Mar`.
The operator types `Apr` into that field; no code change, no JSON
edit. The dropdown configuration drives the field-appearance behavior
through the `sheet_overridable` flag in `brands.json`.

---

## 7. CODE_CHANGED — the third matching tier (~1 min)

> **Scenario.** A brand renumbers stores. The source row now carries the
> new SAP code in its main column, *and* the previous SAP code in an
> `Old SAP` column. The master still has the old code in Store Id. If
> the tool naively matched on Store Id, this would surface as one
> spurious NEW (the new code) plus one spurious CLOSED (the old code)
> — and the operator would have to manually merge them.

The engine handles this with a **third matching tier**: when Store Id
and Legacy Code both miss, if the brand has an `Old Sapcode` rule that
points at a source column (today: only PF), it tries matching the
source row's *Old Sapcode value* against the master's *Store Id*. On
hit, the row is classified **CODE_CHANGED**:

- The master row's Store Id is updated to the new code.
- A note is appended to the master's Remarks:
  `"Code changed from <old> to <new> on <YYYY-MM-DD>"`. This append
  overrides the reference's normal Remarks rule (which is usually
  EMPTY).
- The master row is consumed — it does *not* also appear in the CLOSED
  bucket.
- The change report flags every cell of that row with status
  `CODE_CHANGED` and shows both old and new Store Ids in the detail.

If you want to demo this live: pick any PF source row, look at its
mapped `Store Id`, `Legacy Code`, and `Old Sapcode`. Then open the
backend master in Excel, find that store, change Store Id to the
`Old Sapcode` value, change Legacy Code to anything else, and save.
Run PF again. You'll see CODE_CHANGED = 1 and the Store Id correctly
updated, with a Remarks append and no spurious CLOSED.

For brands without an `Old Sapcode → <source column>` rule
(Pantaloons, TASVA, TCNS today), the third tier is disabled
gracefully — code-changes continue to surface as NEW + CLOSED pairs
that the operator reconciles manually, exactly as before.

---

## 8. Manage brands — adding a new brand (~1 min)

Open `/brands` (footer link → *Manage brands*).

![Brands list](screenshots/demo_04_brands_list.png)

Walk through:

- Each row shows the brand key, label, scope (column = value), the
  sheet name, the header row, and the counts of overrides /
  divergence warnings.
- The pill `OVERRIDABLE` next to TCNS's sheet indicates the
  sheet-name field on the main form is editable.

Click **+ Add brand**. Fill in:

- Brand key: `AllenSolly`
- Label: `Allen Solly`
- Scope column: `brand`
- Scope value: `AS`
- Default sheet: `Sheet1`
- Header row: `1`
- Sheet overridable: unchecked

Click **Create brand**. You'll redirect to `/brands` showing five
rows. Open the main page in a new tab — Allen Solly is already in the
dropdown. No restart.

If you have an Allen Solly source workbook, you can convert against
it; otherwise edit the brand to add field overrides and divergence
warnings.

Finally, **delete** Allen Solly. Confirm the dialog. Refresh the main
page — the dropdown drops back to the original four.

---

## 9. The change report — what an audit looks like (~30 sec)

Open one of the change reports in Excel (Pantaloons is fine). Two
sheets:

- **Summary.** Source row count, matched-to-master count,
  NEW/UPDATED/CODE_CHANGED/CLOSED/ORPHAN counts, warnings list.
- **Changes.** One row per detected diff. Columns: Status, Store Id
  (old → new for CODE_CHANGED), Field Changed, Old Value, New Value,
  Notes (which match key was used).

Mention: this is the operator's audit trail. If anything looks wrong
post-deploy, they filter the change report for that Store Id and see
exactly what the tool wrote.

---

## 10. Why it's safe (~1 min, no clicks)

Three claims to leave on:

1. **No data leaves the machine.** It's a local web app. Files are
   uploaded into a `temp/` folder next to the EXE, processed, and
   written back. No outbound HTTP. Easy for security/compliance.

2. **The reference sheet is the source of truth.** Every brand owner
   already maintains their reference sheet. The engine reads it
   verbatim each run — operations doesn't have to edit code to handle
   a new field. The handful of *brand_overrides* in `brands.json` are
   surgical: only where the reference sheet is wrong or two source
   columns collide.

3. **The verifier provides an independent check.** Even if the engine
   has a bug, the verifier — which re-derives every cell from first
   principles — catches it. PASS means the output truly matches the
   rules. FAIL gives you the cell-level detail to debug.

End with the delivery: the operator runs `python -m web.run` from the
repo root and the browser opens to the local UI. Nothing leaves the
machine.

---

## Appendix — Cheat sheet of the four brand runs

| Brand | Source rows | NEW | UPDATED | CODE_CHANGED | CLOSED | Warnings |
|---|---:|---:|---:|---:|---:|---:|
| Pantaloons | 399 | 0 | 137 | 0 | 0 | 0 |
| Planet Fashion | 100 | 0 | 48 | 0 | 0 | 8 (ASP Code divergence) |
| TASVA | 94 | 1 | 87 | 0 | 1 | 0 |
| TCNS | 478 | 23 | 370 | 0 | 10 | 1 (null-Store-Id master row) |

Memorize these numbers for the demo — they're the receipts you can
quote when someone asks "are you sure this is reproducible?"
