# 8-Bit Cricket

Retro arcade cricket with real local accounts.

## Run

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

## Play

- **Sign up / log in** — usernames and salted PBKDF2 password hashes are stored in `users.db` (not plain text).
- **Bat now** — 5 overs or 3 wickets.
- **Left / Right** — pick DEFEND, DRIVE, or LOFT.
- **Space** — start the over, then swing when the red needle hits the gold window.
- **Esc** — back / quit.

Scores are saved to your account. Records shows your innings and a high-score board.

## Project layout

```text
main.py          # Pygame game client
pixel.py         # Rendering helpers
auth.py          # Authentication and game-record logic
schema.sql       # SQLite database schema
```
