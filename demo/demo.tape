# The terminal telling of the same story, for the VHS recipe.
# EDIT THIS FILE for a new piece that records a terminal.
#
#   DEMO_RECIPE=vhs make demo-terminal      (or: make demo-terminal)
#
# There is no `Output` line on purpose: demo/record.sh passes `vhs -o` so the
# clip lands in whichever output directory it was asked for, and the Playwright
# clip in demo/out/ does not get overwritten. Running `vhs demo/demo.tape` by
# hand writes ./out.gif instead.
#
# Conventions that make a tape read well: set Height to the tallest *single*
# screen rather than the tallest total, clear between beats inside Hide blocks,
# hide the venv wiring, and sleep long enough after each Enter to actually read
# the output.

Set Shell bash
Set FontSize 15
Set Width 1180
Set Height 520
Set Padding 20
Set TypingSpeed 22ms
Set Theme "Catppuccin Mocha"

Hide
Type "export PS1='$ ' PATH=$PWD/.venv/bin:$PATH" Enter
Type "rm -f state/catalog.json" Enter
Type "clear" Enter
Show

Type "# yesterday morning: nothing to compare against yet" Enter
Sleep 900ms
Type "python watch.py --serve fixtures/site --report --quiet" Enter
Sleep 4.5s

Hide
Type "clear" Enter
Show

Type "# this morning: the same command, 24 hours later" Enter
Sleep 900ms
Type "python watch.py --serve fixtures/site-day2 --report --quiet" Enter
Sleep 7s

Hide
Type "clear" Enter
Show

Type "ls out/" Enter
Sleep 3.5s
