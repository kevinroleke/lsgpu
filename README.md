# lsgpu

Minimal CLI tool for displaying connected GPUs

## Installing
uv:
```
uv tool install lsgpu
```
pipx:
```
pipx install lsgpu
```

## Usage
```
:: ~/ » lsgpu --help
usage: lsgpu [-h] [--theme NAME] [--entities a,b,c] [--entities-random N] [--fire] [--connect-spotify] [--spotify] [--sysinfo] [--weather] [--eightball] [--play GAME]

List connected GPUs

options:
  -h, --help           show this help message and exit
  --theme NAME         display theme (default: default)
  --entities a,b,c     comma-separated entity names to bounce on screen
  --entities-random N  spawn N randomly chosen entities
  --fire               enable fire animation along the bottom of the screen
  --connect-spotify    run Spotify OAuth flow and save credentials, then exit
  --spotify            show Spotify now-playing widget
  --sysinfo            show CPU/memory usage widget
  --weather            show weather widget for Rochester, NY
  --eightball          show Magic 8-ball widget
  --play GAME          jump straight into a game: wordle, snake, roulette

themes:   default, america, canada, china, christmas, 420, halloween, israel, matrix, rainbow
entities: anime_girl, arch, bible_quote, bill_100, crab, debian, dvd, empty_wallet, ethereum, fedora, ghost, gorilla, greeting, grim_reaper, jesus, jewish_star, maui, nuke, nvidia, rxknephew, scrooge, shadow_wizard, ship, slot_machine, stuffed_wallet, trophy, tux, ufo
games:    wordle, snake, roulette

TUI keys: / → command prompt   q → quit   /help → command list
```
