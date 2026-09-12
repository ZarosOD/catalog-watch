# demo/ — the recording pipeline

One command regenerates a clip from scratch, headless, from a clean checkout:

```bash
./demo/record.sh              # this piece: Playwright, a real browser page
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

`lib/` has since gained one file from a later piece rather than from this one:
**`lib/fetch.sh`**, the download retry ladder, was written for piece #3
(`feed-clean`) after GitHub's release CDN returned HTTP 500 on one asset for a
couple of minutes and took `make demo` down with it. It was back-synced here so
that `lib/` is one version across every piece that carries it — a shared file
that differs between repos is three files wearing the same name.

## Which recipe

| | **VHS** (`lib/vhs.sh`) | **Playwright** (`lib/playwright.sh`) |
| --- | --- | --- |
| Records | A terminal session | A real browser page |
| You write | `demo.tape` — a script of keystrokes and pauses | `scene.py` — Playwright code |
| Good at | Crisp text at small sizes; tiny files (this repo: 343 KB) | Anything with a UI, a page, or a before/after to point at |
| Bad at | Anything that is not text in a terminal | Files are about 7× bigger (this repo: 2.3 MB) |
| Timing | Declarative `Sleep 3s` | `page.wait_for_timeout(3000)` — same idea, in Python |
| Output | GIF **and** MP4, from one recording | GIF **and** MP4, from one recording |

Both recipes write both formats because the two are for different places. The
**GIF** is the README thumbnail: it animates inline on GitHub and needs no
player. The **MP4** is the portfolio cover, because Upwork's gallery renders an
uploaded GIF as a single static first frame — a GIF there is a screenshot with
extra bytes. Neither is generated from the other; they are two encodes of the
same captured frames, so they cannot drift apart.

**Pick VHS when the deliverable is a command.** A client watching a CLI wants
to read the output, and VHS renders text natively rather than photographing it.

**Pick Playwright when the deliverable is something you look at.** This piece
qualifies: the story is "the storefront changed overnight and you did not have
to notice", which needs the storefront on screen. A terminal recording of the
same tool is still useful — it is `make demo-terminal` here — but it shows the
answer without showing the question.

Both are live in this repo precisely so the next piece can choose rather than
reinvent. Copy `demo/` from here, not from the first piece.

## Copying this into another piece

Copy the whole `demo/` folder. Then change **these files and nothing else**:

| File | What to change |
| --- | --- |
| `recipe` | One word: `playwright` or `vhs`. |
| `setup.sh` | Two lines in practice: the import names you pass `ensure_venv`, and whatever the piece needs regenerated before recording. A non-Python piece replaces the `ensure_venv` call with its own build. |
| `scene.py` | The Playwright recipe's script. Delete it if you chose VHS. |
| `demo.tape` | The VHS recipe's tape. Delete it if you chose Playwright. |

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

`record.sh` handles the rest: reading `demo/recipe`, running `setup.sh`,
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
| `lib/playwright.sh` | the `playwright` wheel + Chromium | 1.47.0 | Playwright for *Python*, not Node: the wheel ships its own driver, so a machine with no Node can still record. |
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
- **The clip is a GIF and an MP4 of the same recording.** The GIF is for
  embedding in a README, the MP4 for anywhere that will play video — it is
  about a tenth the size at better quality.
- **Re-recording reproduces the committed clip closely, not exactly.** Over six
  recordings: the browser GIF stays within 4% (0.3% from a clean clone), the
  browser MP4 within 8%, the terminal clip within 1%. VHS is the steady one
  because it renders text to frames itself. The Playwright recipe records a
  live browser, so page-load timing decides which frames land either side of a
  cut, and the MP4 moves more than the GIF because nothing quantises it — it
  spends real bits on whatever detail that capture happened to carry. Sizes to
  expect: browser 2.3 MB GIF / 331 KB MP4, terminal 343 KB / 263 KB. Much
  outside that is worth a look rather than a shrug; a 37% jump is what sent us
  looking and found the VP8 noise that `GIF_QUANT` in `lib/playwright.sh` now
  removes.
- **The report beat shows a live timestamp.** `changes.txt` prints the time of
  the run it compared against, so those characters differ on every recording.
  It costs nothing in file size and it is honest about what the tool writes, but
  it does mean no two clips are pixel-identical.
