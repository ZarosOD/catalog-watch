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
of being one. That is the only structural change: nothing that was generic
became piece-specific.

## Which recipe

| | **VHS** (`lib/vhs.sh`) | **Playwright** (`lib/playwright.sh`) |
| --- | --- | --- |
| Records | A terminal session | A real browser page |
| You write | `demo.tape` — a script of keystrokes and pauses | `scene.py` — Playwright code |
| Good at | Crisp text at small sizes; tiny files (this repo: 280 KB) | Anything with a UI, a page, or a before/after to point at |
| Bad at | Anything that is not text in a terminal | Files are 10× bigger (this repo: 3.3 MB) |
| Timing | Declarative `Sleep 3s` | `page.wait_for_timeout(3000)` — same idea, in Python |
| Output | GIF | GIF **and** MP4, from one recording |

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
| `setup.sh` | How to get the project runnable — the venv, `npm ci`, a build. Must be re-runnable and must leave the repo ready to record. |
| `scene.py` | The Playwright recipe's script. Delete it if you chose VHS. |
| `demo.tape` | The VHS recipe's tape. Delete it if you chose Playwright. |

Leave `record.sh` and everything in `lib/` alone. If you find yourself editing
one of those to make your piece work, the split is wrong — fix the split, do
not fork the file.

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

## Toolchain

Everything lands in `demo/.toolchain/` (gitignored). Nothing system-wide, no
root, all pinned.

| File | Fetches | Pin | Why pinned |
| --- | --- | --- | --- |
| `lib/uv.sh` | uv | 0.12.13 | Checksum-verified against the published `.sha256`. |
| `lib/ffmpeg.sh` | ffmpeg, ffprobe | static build | Used by both recipes. A system `ffmpeg` is used if present. |
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
- **First Playwright run downloads about 170 MB of Chromium** and takes around
  three minutes on a cold machine; after that a re-record is about 40 seconds.
  The VHS recipe downloads its own Chromium separately, so running both costs
  two browser downloads.
- **The clip is a GIF and an MP4 of the same recording.** The GIF is for
  embedding in a README, the MP4 for anywhere that will play video — it is
  about a tenth the size at better quality.
