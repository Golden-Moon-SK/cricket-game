# 8-Bit Cricket

Retro arcade cricket with real local accounts.

## Run

```bash
python3 -m pip install -r requirements.txt
python3 -m frontend.main
```

## Play

- **Sign up / log in** — usernames and salted PBKDF2 password hashes are stored in `database/users.db` (not plain text).
- **Bat now** — 5 overs or 3 wickets.
- **Left / Right** — pick DEFEND, DRIVE, or LOFT.
- **Space** — start the over, then swing when the red needle hits the gold window.
- **Esc** — back / quit.

Scores are saved to your account. Records shows your innings and a high-score board.

## Project layout

```text
frontend/       # Pygame interface and rendering helpers
backend/        # Authentication and game-record application logic
database/       # SQLite schema; local users.db is generated here and ignored by Git
```
