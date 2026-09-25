"""Tests for demo/scene.py's narration: the bar and the change marks.

This piece is the only one of the five whose beats are a *served* page. The
other four hand `set_content` a string that is already complete, so their
captions cannot be late. This one navigates, and for most of its life it then
painted the bar on afterwards with `add_style_tag` + `evaluate` -- CDP round
trips that land after the page has painted. The bare, un-captioned storefront
was on camera 0.48 s, 0.44 s and 0.52 s, three times per 21-second clip
(THE-308, measured frame by frame on the committed mp4 at 25 fps).

The fix is a page init script, which Chromium runs inside the document before
any of the document's own scripts, carrying its per-beat text on the URL. What
is tested below is the shape of that: one definition of each script, a URL that
really does force a fresh document, and no surviving path that paints the
narration on after the navigation.

--- what these cannot see -------------------------------------------------

**Whether the JavaScript works.** Every test here is over source and strings;
none of them starts a browser. Running NARRATE_JS for real needs the vendored
Chromium and the LD_LIBRARY_PATH only demo/lib/playwright.sh exports, so a test
of it would be dormant under `make test` -- green in a way indistinguishable
from a check that ran (the hazard test_demo_card.py names beside its own skip).
What proves a given take is the recording: `./demo/record.sh` runs the real
script in the real browser, and the clip is then scanned frame by frame.

So these are regression guards on the *structure*, and the structure is what a
later edit would break: re-inlining an `add_style_tag`, or "tidying" the query
string into the fragment it looks like it should be.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = REPO_ROOT / "demo" / "scene.py"

sys.path.insert(0, str(REPO_ROOT / "demo" / "lib"))
spec = importlib.util.spec_from_file_location("demo_scene", SCENE_PATH)
assert spec and spec.loader
scene = importlib.util.module_from_spec(spec)
sys.modules["demo_scene"] = scene
spec.loader.exec_module(scene)

SOURCE = SCENE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)

BASE = "http://127.0.0.1:41725/"


def spec_in(url: str) -> dict:
    """The narration NARRATE_JS would read back out of ``url``."""
    query = dict(parse_qsl(urlsplit(url).query))
    return json.loads(query["cw"])


# --------------------------------------------------------------------------
# the URL a beat travels on
# --------------------------------------------------------------------------


def test_the_narration_rides_in_the_query_not_the_fragment() -> None:
    """The one design decision here that looks wrong until it is measured.

    A fragment is the tidier place for something the server must not see, and
    it does not work: beats 2 and 4 are the same page, so `#cw=B` after `#cw=A`
    is a same-document navigation. Measured on this repo's Chromium (1134) --
    goto(today#cw=A), set_content(terminal), goto(today#cw=B) leaves the
    terminal panel on screen. No reload, no init script, no storefront.

    The query forces a fresh document every time, which is the whole point.
    """
    url = scene.narrated(BASE, "BEFORE", "Mon 06:00", "yesterday's catalogue")
    assert "#" not in url, (
        f"{url} carries a fragment: beat 4 revisits beat 2's page, and a "
        "fragment-only change is a same-document navigation -- the init "
        "script would not run and the previous beat would stay on screen"
    )
    assert urlsplit(url).query.startswith("cw="), url
    assert url.startswith(BASE + "?"), url


def test_the_spec_survives_the_url() -> None:
    marks = {"TW-1004": "price cut", "TW-1078": "stock"}
    url = scene.narrated(BASE, "AFTER", "Tue 06:00",
                         "6 changes, found unprompted", marks)
    assert spec_in(url) == {
        "step": "AFTER", "when": "Tue 06:00",
        "what": "6 changes, found unprompted", "marks": marks,
    }


def test_punctuation_in_a_caption_survives() -> None:
    """The captions are prose written for a viewer, not identifiers.

    Two of the three already carry an apostrophe or a question mark, and `&`,
    `?` and `#` would each end the query early if the spec were not quoted.
    """
    what = "yesterday's catalogue & today's — spot the difference? #1"
    url = scene.narrated(BASE, "BEFORE", "Mon 06:00", what)
    assert spec_in(url)["what"] == what


def test_a_beat_with_no_marks_still_carries_the_field() -> None:
    """NARRATE_JS passes `spec.marks` straight to MARK_JS, which iterates it.

    `undefined` there is a TypeError inside the page -- silent from Python,
    and it would take the bar down with it, since the bar goes up after the
    marks in the same function.
    """
    url = scene.narrated(BASE, "BEFORE", "Mon 06:00", "yesterday's catalogue")
    assert spec_in(url)["marks"] == {}


# --------------------------------------------------------------------------
# one definition of each script
# --------------------------------------------------------------------------


def test_the_init_script_uses_the_one_banner_and_the_one_mark_function() -> None:
    """Embedded by reference, so there is nothing to keep in step.

    BANNER_JS and MARK_JS are still the definition of what the bar and the
    marks look like; NARRATE_JS composes them. A copy pasted into the init
    script would be a second definition that drifts.
    """
    assert scene.BANNER_JS in scene.NARRATE_JS
    assert scene.MARK_JS in scene.NARRATE_JS
    assert json.dumps(scene.BANNER_CSS) in scene.NARRATE_JS


def test_the_css_and_prefix_reach_the_page_as_json() -> None:
    """Both are interpolated into JavaScript source, so both are `json.dumps`ed.

    BANNER_CSS is an f-string full of braces, quotes and newlines; dropping it
    in raw would be a syntax error in the page at best.
    """
    assert json.dumps(scene.SPEC_PREFIX) in scene.NARRATE_JS
    assert "cw=" == scene.SPEC_PREFIX


# --------------------------------------------------------------------------
# nothing paints the narration on after the navigation
# --------------------------------------------------------------------------


def _attributes_called() -> set[str]:
    """Every `x.name(...)` in demo/scene.py, by name.

    From the tree rather than from the text. The comment above NARRATE_JS
    explains what `add_style_tag` used to do and why it is gone, so a grep for
    the name matches the sentence that records its removal -- the same trap
    that scored two THE-305 mutations as caught when they were not.
    """
    return {
        node.func.attr for node in ast.walk(TREE)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_no_narration_is_painted_after_the_navigation() -> None:
    """The THE-308 regression guard.

    `add_style_tag` and an `evaluate` after the `goto` are the two calls that
    put the bar and the marks on a page that had already painted. Neither has
    any other use in this scene, so their absence is the property.
    """
    called = _attributes_called()
    for gone in ("add_style_tag", "add_script_tag", "evaluate"):
        assert gone not in called, (
            f"scene.py calls {gone}(): that is a round trip landing after the "
            "served page has painted, which is THE-308"
        )
    assert "add_init_script" in called, (
        "nothing installs the init script, so no beat gets a narration bar"
    )


def _record_body() -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == "record":
            return node
    raise AssertionError("demo/scene.py has no record()")


def _goto_calls() -> list[ast.Call]:
    return [
        node for node in ast.walk(_record_body())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "goto"
    ]


def test_every_goto_is_narrated() -> None:
    """A beat that forgot its caption is a `goto` with no `narrated()` in it.

    This is the arm that would have caught the defect if it had existed: the
    old scene called `scene.goto(today, 0)` and then narrated the page
    separately, so the navigation and its caption were two statements with
    time in between. Now they are one call and the test says so.
    """
    calls = _goto_calls()
    assert len(calls) == 3, f"expected three goto beats, found {len(calls)}"
    for call in calls:
        first = call.args[0]
        assert (isinstance(first, ast.Call)
                and isinstance(first.func, ast.Name)
                and first.func.id == "narrated"), (
            f"line {call.lineno}: scene.goto() is navigating to something that "
            "is not narrated(...), so that beat paints with no caption"
        )


def test_every_goto_holds_for_a_named_beat_length() -> None:
    """The hold moved into the `goto` when the banner call went away.

    It used to be `scene.goto(url, 0)` followed by a `banner(..., hold)`, and
    that literal 0 is what made the un-captioned window exactly as long as the
    round trips took. A 0 here again would mean the hold had drifted back out
    to some later call.
    """
    holds = {"HOLD_YESTERDAY", "HOLD_TODAY", "HOLD_MARKED"}
    named = set()
    for call in _goto_calls():
        assert len(call.args) == 2, f"line {call.lineno}: goto wants a hold"
        hold = call.args[1]
        assert isinstance(hold, ast.Name), (
            f"line {call.lineno}: the hold is {ast.dump(hold)}, not one of the "
            f"named beat lengths {sorted(holds)}"
        )
        named.add(hold.id)
    assert named == holds, f"the three beats hold for {sorted(named)}"


def test_the_marks_come_from_the_tools_own_output() -> None:
    """Unchanged by THE-308 and worth pinning while the marks move.

    The marks are read out of the CSV the run wrote seconds earlier, so the
    clip cannot highlight a change the tool did not find. They are now passed
    through the URL instead of a second `evaluate`, which is a change of
    transport and must not become a change of source.
    """
    body = _record_body()
    assigns = [n for n in ast.walk(body) if isinstance(n, ast.Assign)]
    sources = [
        n.value.func.id for n in assigns
        if isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
        and any(isinstance(t, ast.Name) and t.id == "marks" for t in n.targets)
    ]
    assert sources == ["marks_from_output"], sources
