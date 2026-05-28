#!/usr/bin/env python3
"""
Commit and push the current HTML files to GitHub Pages.

Usage:
    python scripts/deploy.py "your commit message"

Safety:
- Only stages the two dashboard HTML files (index.html and
  campaign_schedule_outreach.html) — never your data/records.json
- Refuses to run if there are unrelated staged changes
- Pushes to origin/main (the GitHub Pages branch)
"""
import subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FILES = ["index.html", "campaign_schedule_outreach.html"]


def run(*args, **kw):
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True, **kw)


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: python scripts/deploy.py "commit message"')
    msg = sys.argv[1]

    # Refuse if anything else is already staged
    staged = run("git", "diff", "--name-only", "--cached").stdout.splitlines()
    unrelated = [f for f in staged if f not in FILES]
    if unrelated:
        sys.exit(f"ERROR: unrelated staged files: {unrelated}\nReset with 'git reset HEAD' first.")

    # Stage only the dashboard files
    run("git", "add", *FILES)

    # Anything to commit?
    diff = run("git", "diff", "--cached", "--quiet")
    if diff.returncode == 0:
        sys.exit("Nothing to commit — HTML files are unchanged.")

    commit = run("git", "commit", "-m", msg)
    print(commit.stdout or commit.stderr)
    if commit.returncode != 0: sys.exit(1)

    push = run("git", "push")
    print(push.stdout or push.stderr)
    if push.returncode != 0:
        sys.exit("ERROR: git push failed. You may need to set upstream:\n  git push --set-upstream origin main")

    print("\nDeployed. GitHub Pages usually picks up within 1-2 minutes.")
    print("Site: https://mike1776agschedule.github.io/")


if __name__ == "__main__":
    main()
