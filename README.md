# BudgetRoom 💸

**A budgeting coach that lives in your chat rooms.** Students and parents text their
spending the way they'd text a friend; an AI agent running on
[Switch](https://www.wemakedevs.org/hackathons/switch) keeps the books, warns before
the money runs out, and answers "can I afford this?" with real numbers.

Built solo for the WeMakeDevs **Flip the Switch** hackathon (Track 2: Personal/Creative).

```
Yasmine: spent 85 on groceries and 20 for a taxi
BudgetRoom: ✅ Logged. 🟢 food 375/900 MAD · 🟡 transport 150/200 MAD (75%, day 5)
Yasmine: can I afford a 350 MAD concert ticket?
BudgetRoom: ❌ Not without breaking the plan: 620 MAD left for 26 days (~24/day),
            and leisure would go 190 MAD over. A 100 MAD ticket would be tight but OK.
```

## Profiles in the demo

| Profile | Who | Currency |
|---|---|---|
| `yasmine` | Student in Rabat: scholarship + parents + tutoring | MAD |
| `karim` | Her father in Casablanca: salary, rent, school fees | MAD |
| `lea` | Student in Lyon working weekends in a café | EUR |
| `maria` | Single parent in Austin building an emergency fund | USD |

Yasmine and Karim form a **household**: Yasmine can request money with a reason, Karim
sees the impact on his own budget before approving, and both ledgers update.

## How it works

```
Mattermost room ──► Switch ──► Claude Code (reads CLAUDE.md)
                                   │  turns chat into commands
                                   ▼
                              budget.py  ──► data/profiles/*.json  (the plan)
                              (all math)     data/ledgers/*.csv    (every expense)
                                             data/households/*     (allowance requests)
```

- **The LLM never does arithmetic.** It parses messages and calls `budget.py`, which
  owns every number. Answers are deterministic and tested.
- **Plain files as state:** profiles are JSON, ledgers are CSV. You can open them in a
  spreadsheet, diff them in git, and nothing is hidden in a database.
- **Fixed costs** (rent, phone, school) are reserved up front; the agent coaches on the
  *flexible* part, which is where budgets actually break.
- Per-category pace alerts: 🟢 on track · 🟡 spending faster than the month passes ·
  🔴 over limit · ⚪ unplanned category.

## Run it

```bash
git clone <this repo> && cd switch-budget
./reset_demo.sh                       # copy seed/ data into data/
python3 -m unittest discover tests    # 7 tests, stdlib only
export BUDGET_TODAY=2026-11-05        # optional: freeze the demo date
python3 budget.py status yasmine
python3 budget.py afford yasmine 350 leisure --what "Concert ticket"
python3 budget.py request yasmine 300 "train to Casa"
python3 budget.py approve karim 1
pip install -r requirements.txt       # optional, for PNG charts
python3 budget.py report maria --png report.png
```

### With Switch

1. Install and start Switch (local server with Mattermost).
2. Create an agent whose working directory is this repo (so Claude Code picks up `CLAUDE.md`).
3. Invite it to rooms, e.g. `#yasmine-budget`, `#alaoui-family`, `#lea-budget`.
4. Create Mattermost users matching `chat_users` in the profiles, or prefix messages
   with `as yasmine:` when demoing alone.

## Not financial advice

BudgetRoom is a budgeting coach. It does not give investment, credit, loan or tax
advice, and it never moves real money: "approve" only records a transfer.
