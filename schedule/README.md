# schedule/ — running it every morning without you

Four files:

| File | What it is |
| --- | --- |
| `run.sh` | What the scheduler calls. Both installs below point here, so there is one place that knows how to run a scheduled scrape. |
| `check.sh` | Proof that `run.sh` works under `env -i`. `make schedule-check`. |
| `catalog-watch.cron` | A crontab fragment, 06:00 daily. |
| `catalog-watch.service` + `.timer` | The systemd equivalent. |

## Check it before you install it

```bash
make schedule-check
```

That runs `run.sh` three times with `env -i` — cron's environment, not your
shell's — against yesterday's fixture, then this morning's, then this morning's
again. It asserts a baseline, then a short list of deltas, then nothing. If
this passes, the cron line will work; the two things that break scheduled jobs
are a missing PATH/virtualenv and a diff that was never really a diff, and both
are covered here.

## cron

```bash
crontab -l > /tmp/ct
cat schedule/catalog-watch.cron >> /tmp/ct
crontab /tmp/ct
crontab -l          # check
```

Edit `REPO` and `MAILTO` at the top. Cron mails whatever the job prints, and
`run.sh` prints exactly the change summary, so a quiet morning is a short mail
and a busy one is a list.

## systemd

```bash
sudo cp schedule/catalog-watch.service schedule/catalog-watch.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now catalog-watch.timer

systemctl list-timers catalog-watch.timer     # when it next fires
sudo systemctl start catalog-watch.service    # run it now
journalctl -u catalog-watch -n 50             # what it said
```

`Persistent=true` means a machine that was off at 06:00 runs as soon as it is
back. The state file makes that safe: the late run still reports everything
that moved since the last real one, rather than losing a day.

## Pointing it at a real catalogue

Both installs read the same environment variables:

```
CATALOG_WATCH_TARGET     a URL, or "--serve DIR" for a local fixture
CATALOG_WATCH_SITE       path to the site profile JSON
CATALOG_WATCH_STATE      where the previous run is kept
CATALOG_WATCH_OUT        where the CSV/XLSX/txt go
CATALOG_WATCH_LOG_DIR    where run.sh appends its log
```

Write a site profile for the real catalogue (see `sites/fixture.json` and the
main README), set `CATALOG_WATCH_TARGET` to the URL, and nothing else changes.

## Exit codes, for alerting

`run.sh` passes watch.py's exit code straight through, and forwards any extra
arguments, so `run.sh --fail-on-change` exits `2` on a morning when something
moved. Point your alerting at that rather than at parsing the text.

| Code | Meaning |
| --- | --- |
| 0 | Ran. Nothing flagged. |
| 1 | Something needs review (with `--fail-on-review`). |
| 2 | Something changed (with `--fail-on-change`). |
| 3 | Usage or site-profile problem. |
| 4 | The site could not be fetched. |

## The log

`run.sh` appends to `$CATALOG_WATCH_LOG_DIR/catalog-watch.log`: a start line, a
finish line with the exit status, and the summary in between. It does not
rotate it. On a real install point `CATALOG_WATCH_LOG_DIR` at `/var/log/...`
and let logrotate do that job rather than reinventing it here.
