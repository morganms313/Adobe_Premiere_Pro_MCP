# Working off the morganms313 fork

This repo is a **fork**. All of Morgan's work must land on **`morganms313`**, never on
**`hetpatel-11`** (that's the upstream we fork *from* — code pushed there is out of our control).

## The convention

| remote     | points at                              | used for            |
|------------|----------------------------------------|---------------------|
| `origin`   | `morganms313/Adobe_Premiere_Pro_MCP`   | push + pull (yours) |
| `upstream` | `hetpatel-11/Adobe_Premiere_Pro_MCP`   | fetch-only (sync)   |

With remotes named this way, a bare `git push` / `git pull` defaults to **your fork** — nothing to remember.

## Fresh setup on a new machine (e.g. the office mac)

```bash
git clone https://github.com/morganms313/Adobe_Premiere_Pro_MCP.git
cd Adobe_Premiere_Pro_MCP
git remote add upstream https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP.git
```

## If the machine ALREADY has a clone

First see how its remotes are named:

```bash
git remote -v
```

- **If `origin` already points at morganms313** — you're good. Just `git pull`.
- **If `origin` points at hetpatel** (the old backwards layout) — fix it once:

  ```bash
  git remote rename origin upstream     # hetpatel becomes upstream
  git remote rename fork origin         # morganms313 becomes origin  (skip if no 'fork' remote)
  git config --unset remote.pushDefault # remove the old guard, no longer needed
  git branch --set-upstream-to=origin/main   # track your fork (run on your main branch)
  ```

## Syncing upstream changes from hetpatel

```bash
git fetch upstream
git merge upstream/main      # or: git rebase upstream/main
```

Then push the result to your fork with a plain `git push`.
