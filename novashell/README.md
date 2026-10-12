# NovaShell — NOVA firmware shell

NovaShell is a tiny interactive shell written in NOVA assembly. It **replaces the
default firmware**: it loads at address `0x0`, prints a `nova> ` prompt, reads
keyboard input via MMIO, and lets you browse the shared folder and run programs.

## Files

| File | Description |
|------|-------------|
| `gen_shell.py` | Generator: emits `shell.nova` (resolved assembly) and `shell.bin` |
| `shell.nova` | The assembly source (all addresses resolved, re-assemblable) |
| `shell.bin` | The firmware binary — **4041 bytes** (must stay under 4KB) |

Rebuild:

```bash
python3 gen_shell.py
# or assemble the .nova directly:
python3 ~/workspace/nova-cpu/novas.py shell.nova -o shell.bin
```

## Commands

| Command | Description |
|---------|-------------|
| `help` | List all commands with descriptions |
| `ls` | List files in the shared folder |
| `cat <file>` | Print file contents (first 384 bytes) |
| `run <file>` | Load a program into `0x1000` (up to 64KB) and jump to it |
| `pwd` | Print working directory (`/shared`) |
| `echo <text>` | Print text |
| `whoami` | Print user name (`user`) |
| `uname` | Print system info (`NOVA Nova-1`) |
| `date` | Print date (fixed string) |
| `uptime` | Print uptime (`0 mins`) |
| `ps` | List processes (the shell itself) |
| `env` | Show environment (`NOVA_VERSION`, `SHELL=novash`, `USER`, `HOME`, `PATH`) |
| `history` | Show numbered command history (last 20, entries truncated to 31 chars) |
| `clear` | Clear screen (ANSI `ESC[2J ESC[H`) |
| `ver` | Print firmware version |

Line editing: characters echo as you type; **Backspace** (BS/DEL) erases;
**Enter** (CR/LF) submits. Empty lines are ignored (and not recorded in history).

## Memory layout

The whole image lives at `0x0` and must stay under 4096 bytes:

```
0x0000  code            (~1745 bytes)
...     strings         (NUL-terminated, 8-byte padded)
...     LINE_BUF  128B  keyboard input line
...     TOK0       16B  command token
...     TOK1       64B  argument token (file path)
...     IO_BUF    384B  file listing / file read buffer
...     HIST_BUF  640B  history: 20 slots x 32 bytes
```

Register use: `R0`–`R6` hold the MMIO base addresses, `R8` = `IO_BUF`,
`R10` = entry data-stack pointer (restored before `run` jumps),
`R15` = history count, `R11`–`R14` = scratch.

## Host MMIO interface

| Address | Name | Direction | Description |
|---------|------|-----------|-------------|
| `0xFFFFFFFFFFFF0000` | `CONSOLE_OUT` | write | Write a byte (low 8 bits) to print it |
| `0xFFFFFFFFFFFF0008` | `KEYBOARD_IN` | read | Read a byte; `0` = no key pressed (poll) |
| `0xFFFFFFFFFFFF0010` | `FILE_CMD` | write | Command number (see below) |
| `0xFFFFFFFFFFFF0018` | `FILE_ARG0` | write | Command argument 0 |
| `0xFFFFFFFFFFFF0020` | `FILE_ARG1` | write | Command argument 1 |
| `0xFFFFFFFFFFFF0028` | `FILE_ARG2` | write | Command argument 2 |
| `0xFFFFFFFFFFFF0030` | `FILE_RESULT` | read | Result: byte count, or `-1` (`0xFFFF…`) on error |

### File commands

**`1` = LIST** — list the shared folder
- `ARG0` = buffer address, `ARG1` = buffer size
- `RESULT` = bytes written; buffer receives NUL-separated filenames

**`2` = READ** — read a file
- `ARG0` = address of NUL-terminated path, `ARG1` = buffer address,
  `ARG2` = buffer size
- `RESULT` = bytes read, or `-1` on error

Example (`ls` implementation sketch):

```asm
PUSH64 IO_BUF_ADDR
PUSHR 3              ; FILE_ARG0
STORE64              ; ARG0 = buffer
PUSH16 384
PUSHR 4              ; FILE_ARG1
STORE64              ; ARG1 = size
PUSH8 1
PUSHR 2              ; FILE_CMD
STORE64              ; CMD = LIST
PUSHR 6
LOAD64               ; RESULT -> byte count
```

`run` uses `READ` with `ARG1 = 0x1000`, `ARG2 = 65536`, then restores the
entry data-stack pointer (`DSPSET`) and jumps (`JMPI`) to `0x1000`.

## Testing

The shell was functionally verified with a purpose-built minimal NOVA emulator
(`STORE8`→console capture, `KEYBOARD_IN`→canned keystrokes, file LIST/READ
stubs). 18/18 scenario tests pass: banner/prompt, all 15 commands, backspace
editing, echo of multi-word text, `cat` of missing file (error path), usage
messages, unknown-command message, numbered history including the 20-entry
rollover, and `run` loading a test program to exactly `0x1000` and executing it.

One real bug was caught this way: `R8` (`IO_BUF`) was used by `ls`/`cat` but
never initialized, so `LIST` wrote filenames over the firmware code at address
0. It is now initialized at boot.
