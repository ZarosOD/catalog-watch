# demo/ — the recording pipeline

One command regenerates a clip from scratch, headless, from a clean checkout:

```bash
./demo/record.sh              # this piece: Playwright, a rendered page
make demo-terminal            # the same story recorded with VHS instead
```

No screen capture, no window manager, no display server, no root. Everything
the recording needs is fetched into `demo/.toolchain/` and nothing is installed
system-wide. `record.sh` fails loudly if the clip is missing, empty, or longer
than 35 seconds.

This is the second piece to use this pipeline. The first
(`pdf-to-csv`) had one recipe, VHS, wired straight into the orchestrator. This
one adds the browser recipe, so the orchestrator now **picks** a recipe instead
of being one. Nothing that was generic became piece-specific; two things went
the other way, because they were about to be copy-pasted into a third piece:

- **`lib/python-venv.sh`** — the uv / `python3 -m venv` / fail-with-advice
  ladder. It was thirty lines inside `setup.sh`, a file this README calls
  project-specific, of which one string actually differed per project. A file
  you copy and edit one line of is forked, not reused.
- **`lib/preview.py`** — renders a CSV as a fixed-width table. The first piece
  had a one-off version, this piece does not need one, and a piece whose story
  is "dirty file in, clean file out" needs exactly this. Written generically
  once instead of specifically three times.

Two things have since been back-synced here from a later piece rather than
written for this one:

- **`lib/fetch.sh`**, the download retry ladder, written for piece #3
  (`feed-clean`) after GitHub's release CDN returned HTTP 500 on one asset for
  a couple of minutes and took `make demo` down with it.
- **`record.sh` calling `setup.sh --fresh`**, also from piece #3, after that
  piece shipped a `setup.sh` that deleted `out/` on every `make` target — so
  `make test` threw away the output of the last `make run`. Wanting an empty
  repo is the *recording's* requirement, so it is a flag the recording passes;
  what "fresh" means stays in `setup.sh`, because only the piece knows which
  directories it writes. Here that is `out/`, and it is not decorative: the VHS
  tape films `ls out/`, so a file left over from an older run would show in the
  clip as though this morning's run had produced it. This repo took the change
  late. It sat on two of the four pieces for a day, which is why the drift
  check now reads all of `demo/` and not only `demo/lib/`.

Both were copied in so the shared half is one version across every piece that
carries it — a shared file that differs between repos is three files wearing
the same name.

## The spreadsheet renderer, `lib/sheet.py`

All four pieces end their clip on the file the run just wrote, open in a
spreadsheet grid. That is one job, so it is one file — shared, byte-identical
everywhere, and policed by `tools/demo_lib_drift.py` like the rest of `lib/`.
What stays per-piece is `scene.py`: which files this piece opens, which of its
columns are worth showing, and what the narration says.

**It cannot render a table it was handed.** The only way in is
`read_table(path)` or `read_dir(path)`, both of which open something real and
raise if it is not there. `View` cannot be built without a `Table` and `Table`
cannot be built without a file on disk. That is deliberate: a terminal ASCII
table cannot be told apart from a mock-up, and a renderer that reads a fixture
reproduces exactly that flaw with better borders.

**A filtered view says it is filtered.** Showing six of twenty-one columns is
fine and is normal — nobody wants twenty-one on screen. So the columns keep the
letter they have in the source file (picking columns 1, 2, 4 and 9 renders as
A, B, D, I, which is what hiding columns in Excel looks like), rows keep their
real sheet row number so a filtered set reads 2, 3, 4, 287, 288 with the join
marked, and the footer says how many of each are on screen out of how many are
in the file.

**The number format is honoured.** A price cell holding 1299 with a `0.00`
format reads "1299.00" in Excel and "1299" if you only look at the value —
while the CSV beside it says "1299.00". Rendering the value alone would put a
difference on screen that does not exist in the file.

**The command and its output come from one call.** `run_command` runs the
argv, keeps the captured stdout with it, and `terminal_html` renders that one
object — so the line on screen cannot drift from the output underneath it. The
interpreter path is the one thing rewritten, to `python`, because
`/home/somebody/repo/.venv/bin/python3.12` is machine-specific noise and not
the thing being demonstrated.

Covered by `tests/test_demo_sheet.py`, which is byte-identical in all four
repos for the same reason the module is.

## Which recipe

**All four pieces use Playwright today**, and the reason is the grid
above: a spreadsheet frame is a rendered page, and the terminal recipe
cannot draw one. This piece records a browser because its input really is a web
page: the storefront is the BEFORE, and the clip closes on `out/products.xlsx`
in the grid. The VHS sibling is still live in every
repo — `make demo-terminal` — because the choice is the point of
`demo/recipe`, and a recipe nobody can run is a recipe that has rotted.

| | **VHS** (`lib/vhs.sh`) | **Playwright** (`lib/playwright.sh`) |
| --- | --- | --- |
| Records | A terminal session | A real browser page |
| You write | `demo.tape` — a script of keystrokes and pauses | `scene.py` — Playwright code |
| Good at | Crisp text at small sizes; smaller files | Anything with a UI, a page, or a before/after to point at |
| Bad at | Anything that is not text in a terminal | Files are several times bigger |
| Timing | Declarative `Sleep 3s` | `page.wait_for_timeout(3000)` — same idea, in Python |
| Output | GIF **and** MP4, from one recording | GIF **and** MP4, from one recording |

Both recipes write both formats because the two are for different places. The
**GIF** is the README thumbnail: it animates inline on GitHub and needs no
player. The **MP4** is the portfolio cover, because Upwork's gallery renders an
uploaded GIF as a single static first frame — a GIF there is a screenshot with
extra bytes. Neither is generated from the other; they are two encodes of the
same captured frames, so they cannot drift apart.

## Copying this into another piece

Copy the whole `demo/` folder. Then change **these files and nothing else**:

| File | What to change |
| --- | --- |
| `recipe` | One word: `playwright` or `vhs`. |
| `setup.sh` | Two lines in practice: the import names you pass `ensure_venv`, and whatever the piece needs regenerated before recording. A non-Python piece replaces the `ensure_venv` call with its own build. Anything it deletes belongs under `--fresh` unless the piece itself owns it — every `make` target runs this file, so a wipe outside that flag is a wipe of the user's work. |
| `scene.py` | The Playwright recipe's script: which files to open, which columns to show, what the narration says. The rendering is `lib/sheet.py` and is not yours to edit. |
| `demo.tape` | The VHS recipe's tape. Delete it if you only want the browser one. |

Leave `record.sh` and everything in `lib/` alone. If you find yourself editing
one of those to make your piece work, the split is wrong — fix the split, do
not fork the file. `lib/python-venv.sh` and `lib/preview.py` are both there
because that rule was applied rather than quoted.

## Adding a recipe

A recipe is `demo/lib/<name>.sh` defining exactly two functions:

```bash
recipe_bootstrap          # fetch what it needs: no root, inside the repo
recipe_record OUT_DIR     # leave a clip in OUT_DIR; set RECIPE_CLIP to it
```

`record.sh` handles the rest: reading `demo/recipe`, running `setup.sh --fresh`,
wiping the output directory, and checking the clip exists, is non-empty and is
inside the time budget. `DEMO_RECIPE=<name> ./demo/record.sh` overrides the
choice for one run; `DEMO_OUT_DIR=...` sends the clip somewhere else, which is
how this repo keeps both clips without one wiping the other.

## Writing a scene (Playwright)

`scene.py` is ordinary Playwright, with three conventions worth keeping:

- **Aim for 25 to 30 seconds.** `record.sh` rejects anything over 35.
- **Hold still.** Four beats of 5–11 seconds reads far better than constant
  movement, and a GIF of a static page costs almost nothing extra.
- **Drive the annotations from the tool's own output.** The highlights on the
  "what changed" beat come from `out/products.csv`, which the scene runs the
  tool to produce seconds earlier. Nothing in the scene has its own copy of
  what changed, so the clip cannot drift away from what the tool does.
- **Synthetic data only.** The scene serves `fixtures/` on localhost. No live
  site is contacted. Check every frame before shipping.

## Writing a tape (VHS)

`demo.tape` is [VHS tape syntax](https://github.com/charmbracelet/vhs#vhs-command-reference).

- **Set the height to fit the tallest *single* screen, not the tallest total.**
  Use `Hide` / `Type "clear"` / `Enter` / `Show` between beats. A short frame is
  much more readable in a proposal thumbnail than a tall one with dead space.
- **Hide the setup.** Activating a venv or exporting variables goes in a `Hide`
  block so it never appears in the clip.
- **`Sleep` after each `Enter`**, long enough to read the output. 3 to 4.5
  seconds is about right for a table; 7 for a long report.
- **No `Output` line.** `record.sh` passes `vhs -o` so the clip goes where it
  was asked to go.
- **Show a CSV with `lib/preview.py`, not `cat`.** Raw CSV wraps, and a wrapped
  line is unreadable at GIF sizes. The helper picks columns, caps rows,
  truncates cells with `…` and right-aligns numeric columns:

  ```bash
  python demo/lib/preview.py out/products.csv sku name price change --rows 6
  ```

  It prints `... and 25 more rows (31 total)` under a capped table, on purpose:
  a clip that shows six rows of a thirty-one-row file should say so. Naming a
  column the file does not have is an error listing the ones it does, rather
  than a blank column that looks fine on camera. `--collapse` drops a row
  identical to the one above it, for a file that repeats parent fields across
  child rows. Tested in `tests/test_demo_preview.py`.

## Toolchain

Everything lands in `demo/.toolchain/` (gitignored). Nothing system-wide, no
root, versions pinned except where noted.

| File | Fetches | Pin | Why pinned |
| --- | --- | --- | --- |
| `lib/fetch.sh` | nothing itself | — | Every download below goes through it: a few attempts, a widening gap, and a message that separates "the host is having a moment" from "the URL is wrong". Failure is fatal for vhs (no recording without it) and a fallback for uv (there is still `python3 -m venv`). |
| `lib/uv.sh` | uv | 0.12.13 | Checksum-verified against the published `.sha256`. |
| `lib/python-venv.sh` | nothing directly | — | The venv ladder. Calls `lib/uv.sh` when the machine has no uv. |
| `lib/ffmpeg.sh` | ffmpeg, ffprobe | 7.0.2 | Checksum-verified against a constant in the file, so a swapped tarball fails instead of quietly changing what the clip looks like. A system `ffmpeg` is used only if it reports the same version. Used by both recipes. |
| `lib/vhs.sh` | vhs, ttyd | 0.10.0, 1.7.7 | **vhs deliberately**: 0.12.x starts Chromium, captures every frame, then exits 0 having written no file at all on some Linux hosts. 0.10.0 encodes reliably. |
| `lib/playwright.sh` | the `playwright` wheel + Chromium | 1.47.0 | The recipe this piece records with. Playwright for *Python*, not Node: the wheel ships its own driver, so a machine with no Node can still regenerate the clip. |
| `lib/chromium-libs.sh` | the shared objects Chromium links against | — | See below. |

`lib/uv.sh` applies the pinning rule to the *project's* toolchain, because a
clean checkout is not a clean machine. Stock Ubuntu 24.04 has no `uv` and a
`python3` with no `ensurepip` (that lives in the separate `python3-venv`
package), so `setup.sh` would stop dead there and take `make test`, `make run`
and `make demo` with it. It fetches a pinned uv into `demo/.toolchain/bin`, and
uv then supplies the interpreter too, so the machine does not need a Python 3.12
of its own. A system `uv` is used if present; `python3 -m venv` is the fallback;
the "install uv or python3-venv" error is the last resort.

Both recipes end up driving a headless Chromium — VHS downloads one into
`~/.cache/rod`, Playwright into `demo/.toolchain/browsers` — and on a server
image neither has the desktop libraries it links against.
`playwright install-deps` and `apt-get install` both want root, which a demo
script has no business asking for. So `lib/chromium-libs.sh` runs `ldd`, works
out exactly which `.so` files are missing, fetches those `.deb`s with
`apt-get download` (no root) and unpacks them into `demo/.toolchain/sysroot`.
It loops up to three times, because unpacking one library reveals the next one
down. On a non-Debian host it prints the library names and stops rather than
guessing.

`./demo/record.sh --clean` throws the toolchain away and re-fetches it, which
is how to verify the from-nothing path still works.

## Known limits

- **x86_64 Linux.** The pinned ttyd and ffmpeg URLs are architecture-specific.
  macOS would need `brew install vhs ttyd ffmpeg` and a small edit; the
  Playwright recipe is closer to portable, since the wheel and the browser
  download are both platform-aware already.
- **The first run downloads a browser.** Measured from a dead clone with an
  empty `HOME` and `PATH=/usr/bin:/bin`: Playwright about 80 s from nothing, 41 s
  to re-record; VHS about 100 s from nothing. The download is the variable, not
  the recording — expect these to move with the network, and the re-record time
  not to. The two recipes download *separate* Chromiums (Playwright's into
  `demo/.toolchain/browsers`, VHS's into `~/.cache/rod`), so a repo that records
  both pays for both. The toolchain comes to roughly 750 MB; `make clean`
  removes it.
- **The clip is a GIF and an MP4 of the same recording, at different sizes.**
  The GIF is for embedding in a README, so it is scaled to `GIF_WIDTH` (1000)
  to keep the page loading; the MP4 is for anywhere that will play video, and
  since THE-267 it keeps the full 1280x720 capture — `MP4_WIDTH` is its own
  knob now, empty by default. It is still about a fifth the size of the GIF,
  at the higher resolution.
- **Re-recording reproduces the committed clip closely, not exactly.** VHS is
  the steady one because it renders text to frames itself; the terminal clip
  holds within 1%. The Playwright recipe records a live browser, so page-load
  timing decides which frames land either side of a cut, and the MP4 moves more
  than the GIF because nothing quantises it — it spends real bits on whatever
  detail that capture happened to carry. Sizes to expect **for this piece**:
  browser 2.0 MB GIF / 435 KB MP4, terminal 352 KB / 270 KB. The browser MP4
  is re-measured as of THE-267: it was 296 KB while it inherited `GIF_WIDTH`,
  and 1280x720 costs about 47% more bytes for 64% more pixels. The GIF number
  is one sample, not a target — read the next bullet before comparing against
  it. The terminal pair did not move, because the VHS tape does not go through
  `lib/sheet.py`.
- ⚠️ **The spreadsheet scene's size band is wider than the old one's, and it is
  not yet characterised.** The pre-THE-255 browser scene held within 4% over six
  recordings. Two recordings of the BEFORE/command/AFTER scene, same machine,
  same commit, measured 2026-09-23: `catalog-watch` +1.3% GIF / +3.9% MP4 and
  `pdf-to-csv` −2.7% / −0.2%, but `feed-clean` **+46.7% / +21.4%** and
  `inbox-filer` **+53.0% / +35.6%**. What it is *not*: frame noise. Both
  recordings carry the same frame count ±1, and a single frame lifted from the
  final hold re-encodes to within 3% either way — the held pixels are clean, so
  `GIF_QUANT` is still doing its job. The bytes are in the inter-frame deltas:
  a timing shift of one frame changes how many frames land mid-transition, and
  a GIF pays full price for each. Two samples is not a band, so **do not read
  the four numbers above as a tolerance for the three pieces that are not
  catalog-watch** — re-measure before treating any jump as a defect. A third
  sample, 2026-09-23 under THE-267: `inbox-filer` re-recorded from the *same*
  commit with the lib byte-identical came out **+7.9% GIF**, and its MP4
  duration landed 17.88s against a committed 17.92s. Nothing had changed. If
  you are writing a gate, gate on dimensions and on the final frame, not on a
  byte count or a duration equality — neither is reproducible here.
- **The report beat shows a live timestamp.** `changes.txt` prints the time of
  the run it compared against, so those characters differ on every recording.
  It costs nothing in file size and it is honest about what the tool writes, but
  it does mean no two clips are pixel-identical.
