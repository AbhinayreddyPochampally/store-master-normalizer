# Store Master Normalizer

A local desktop tool that turns a brand's monthly store-master
export into an up-to-date copy of the backend master, plus a change
report you can hand to the operator.

Runs entirely on your computer — files are read locally and written to
a local folder. Nothing is sent anywhere.

## Run

From the repo root:

```sh
python -m pip install -r requirements.txt
python -m web.run
```

The console prints *"Starting Store Master Normalizer…"* and your
default browser opens to `http://127.0.0.1:8000/`. The console stays
open while you work; press Ctrl-C (or close it) to stop the tool.

## Use

![Home page](screenshots/01_idle.png)

1. **Brand** — pick the brand the source file belongs to.
   *(For TCNS, a "Sheet name" field appears — the data tab name shifts
   month to month. Type the new tab name if it isn't "Mar".)*
2. **Source workbook** — drag the brand's monthly export onto the
   dropzone, or click to browse. `.xlsx` and `.xlsb` are both accepted.
3. **Backend master** — drag the most recent backend master `.xlsx`.
4. **Convert** — the tool reads the brand's reference sheet, applies the
   rules, reconciles against the master, and produces:
   - **Updated Master** (`<brand>_Updated_Master_<date>.xlsx`)
   - **Change Report** (`<brand>_Change_Report_<date>.xlsx`)
5. Click **Verify output** to run an independent check that walks the
   output cell by cell against the rules + source + master. Verdict
   appears below the results card.

Outputs are written to the `temp/` folder in the repo root. You can
also download them straight from the browser via the two buttons on
the results card.

### What the counts mean

- **New** — a store in the source but not yet in the master. Added.
- **Updated** — a store in both, where at least one field differs.
- **Closed** — a store in the master no longer in the source.
  `Isactive` is flipped to `NO`.
- **Warnings** — surfaced issues that don't block the run
  (e.g. a master row with no Store Id, or two duplicated source columns
  carrying different values).

The tool ignores cosmetic differences: `'WEST BENGAL'` vs `'West Bengal'`,
`'27000'` vs `27000`, `'Jul-17'` vs `datetime(2017, 7, 1)`, underscores
vs spaces. Only real changes show up in the change report.

## See also

- **for-developers.md** — running from source and adding a new brand.
- **analysis/findings.md** — the original reference-sheet audit that
  drove the engine design.
