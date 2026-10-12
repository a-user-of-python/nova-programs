#!/usr/bin/env python3
"""Generate NovaShell firmware: shell.nova (assembly) + shell.bin (binary).

NovaShell is a tiny interactive shell firmware for the NOVA CPU.
It replaces the default firmware: loads at 0x0, prints a prompt,
reads keyboard input via MMIO, and implements help/ls/cat/run/clear/ver.

Two-pass layout: pass 1 measures code size (placeholders -> 0),
then strings and buffers are placed after the code and placeholders
are resolved to real addresses. Total image must stay under 4KB.
"""
import sys, os
sys.path.insert(0, os.path.expanduser("~/workspace/nova-cpu"))
from novas import assemble

MAX_SIZE = 4096

# (name, python-string) — NUL-terminated in the image, 8-byte padded
STRINGS = [
    ("S_banner", "NovaShell v1.0 -- NOVA firmware shell\nType 'help' for a command list.\n"),
    ("S_prompt", "nova> "),
    ("S_help",
     "Commands:\n"
     "  help          list commands\n"
     "  ls            list shared folder\n"
     "  cat <file>    show file contents\n"
     "  run <file>    load program at 0x1000 and run it\n"
     "  pwd           print working directory\n"
     "  echo <text>   print text\n"
     "  whoami        print user name\n"
     "  uname         print system info\n"
     "  date          print date\n"
     "  uptime        print uptime\n"
     "  ps            list processes\n"
     "  env           show environment\n"
     "  history       show command history\n"
     "  clear         clear screen\n"
     "  ver           firmware version\n"),
    ("S_unknown", "unknown command: "),
    ("S_catuse", "usage: cat <file>\n"),
    ("S_runuse", "usage: run <file>\n"),
    ("S_fileerr", "file error\n"),
    ("S_runfail", "run failed\n"),
    ("S_vertext", "NovaShell v1.0 (NOVA firmware)\n"),
    ("S_clearseq", "\x1b[2J\x1b[H"),
    ("S_pwd_t", "/shared\n"),
    ("S_whoami_t", "user\n"),
    ("S_uname_t", "NOVA Nova-1\n"),
    ("S_date_t", "Mon Oct 12 00:00:00 UTC 2026\n"),
    ("S_uptime_t", "0 mins\n"),
    ("S_ps_t", "  PID TTY          CMD\n    1 con          novash\n"),
    ("S_env_t", "NOVA_VERSION=1.0\nSHELL=novash\nUSER=user\nHOME=/shared\nPATH=/bin\n"),
    ("S_c_pwd", "pwd"),
    ("S_c_echo", "echo"),
    ("S_c_whoami", "whoami"),
    ("S_c_uname", "uname"),
    ("S_c_date", "date"),
    ("S_c_uptime", "uptime"),
    ("S_c_ps", "ps"),
    ("S_c_env", "env"),
    ("S_c_history", "history"),
    ("S_c_help", "help"),
    ("S_c_ls", "ls"),
    ("S_c_cat", "cat"),
    ("S_c_run", "run"),
    ("S_c_clear", "clear"),
    ("S_c_ver", "ver"),
]

# (name, size in bytes) — zero-filled buffers after the strings
BUFFERS = [
    ("LINE_BUF", 128),   # keyboard input line
    ("TOK0", 16),        # command token
    ("TOK1", 64),        # argument token (file path)
    ("IO_BUF", 384),     # file listing / file read buffer
    ("HIST_BUF", 640),   # command history: 20 slots x 32 bytes
]

CODE = r"""
; ================= NovaShell firmware =================
; Stack machine shell. Replaces the default firmware.
; Register map (set at boot):
;   R0=CONSOLE_OUT  R1=KEYBOARD_IN R2=FILE_CMD   R3=FILE_ARG0
;   R4=FILE_ARG1    R5=FILE_ARG2   R6=FILE_RESULT R7=LINE_BUF
;   R8=IO_BUF       R10=saved DSP (entry data-stack pointer)
;   R11-R14 = scratch

_start:
    DSPGET
    POPR 10                    ; save entry DSP for `run`
    PUSH64 0xFFFFFFFFFFFF0000
    POPR 0                     ; R0 = console
    PUSH64 0xFFFFFFFFFFFF0008
    POPR 1                     ; R1 = keyboard
    PUSH64 0xFFFFFFFFFFFF0010
    POPR 2                     ; R2 = file cmd
    PUSH64 0xFFFFFFFFFFFF0018
    POPR 3                     ; R3 = file arg0
    PUSH64 0xFFFFFFFFFFFF0020
    POPR 4                     ; R4 = file arg1
    PUSH64 0xFFFFFFFFFFFF0028
    POPR 5                     ; R5 = file arg2
    PUSH64 0xFFFFFFFFFFFF0030
    POPR 6                     ; R6 = file result
    PUSH8 0
    POPR 15                    ; R15 = history count
    PUSH64 @IO_BUF@
    POPR 8                     ; R8 = IO_BUF (used by ls/cat via PUSHR 8)
    PUSH64 @S_banner@
    CALL print_str
    JMP main_loop

; ---------- print_char: c -> ----------
print_char:
    PUSHR 0
    STORE8                     ; v addr -> ; pops addr, pops c
    RET

; ---------- print_str: addr -> (NUL-terminated) ----------
print_str:
    POPR 11                    ; R11 = cursor
ps_loop:
    PUSHR 11
    LOADU8                     ; [b]
    DUP
    BZ ps_done                 ; pops test copy
    PUSHR 0
    STORE8                     ; print b
    PUSHR 11
    INC
    POPR 11
    JMP ps_loop
ps_done:
    POP                        ; drop NUL
    RET

; ---------- print_newline: -> ----------
print_newline:
    PUSH8 10
    CALL print_char
    RET

; ---------- read_line: -> len ----------
; Reads a line into LINE_BUF via KEYBOARD_IN polling.
; Echoes input, handles backspace (8/127), ends on CR/LF.
read_line:
    PUSH8 0
    POPR 12                    ; R12 = len
rl_poll:
    PUSHR 1
    LOADU8
    POPR 13                    ; R13 = key
    PUSHR 13
    BZ rl_poll                 ; 0 = no key yet
    PUSHR 13
    PUSH8 10
    EQ
    BNZ rl_done
    PUSHR 13
    PUSH8 13
    EQ
    BNZ rl_done
    PUSHR 13
    PUSH8 8
    EQ
    BNZ rl_bs
    PUSHR 13
    PUSH8 127
    EQ
    BNZ rl_bs
    ; printable: store if room (127 max + NUL)
    PUSHR 12
    PUSH8 127
    LT                         ; len < 127 ?
    BZ rl_poll                 ; full: ignore char
    PUSH64 @LINE_BUF@
    PUSHR 12
    ADD
    PUSHR 13
    SWAP
    STORE8                     ; buf[len] = key
    PUSHR 13
    CALL print_char            ; echo
    PUSHR 12
    INC
    POPR 12
    JMP rl_poll
rl_bs:
    PUSHR 12
    BZ rl_poll                 ; len==0: nothing to erase
    PUSHR 12
    DEC
    POPR 12
    PUSH8 8
    CALL print_char
    PUSH8 32
    CALL print_char
    PUSH8 8
    CALL print_char            ; erase: "\b \b"
    JMP rl_poll
rl_done:
    PUSH64 @LINE_BUF@
    PUSHR 12
    ADD
    PUSH8 0
    SWAP
    STORE8                     ; NUL-terminate
    CALL print_newline
    PUSHR 12
    RET

; ---------- tokenize: -> ----------
; Splits LINE_BUF into TOK0 (command) and TOK1 (argument).
tokenize:
    PUSH8 0
    POPR 11                    ; i = src index
    PUSH8 0
    POPR 12                    ; j = dst index
    PUSH8 0
    POPR 13                    ; tok = 0 (cmd) / 1 (arg)
tk_next:
    PUSH64 @LINE_BUF@
    PUSHR 11
    ADD
    LOADU8
    POPR 14                    ; R14 = c
    PUSHR 11
    INC
    POPR 11                    ; i++
    PUSHR 14
    BZ tk_end                  ; NUL -> finish
    PUSHR 14
    PUSH8 32
    EQ
    BNZ tk_space
    ; store char into current token
    PUSHR 13
    BZ tk_st0
    PUSHR 12
    PUSH8 63
    LT
    BZ tk_next                 ; tok1 full: drop
    PUSH64 @TOK1@
    JMP tk_store
tk_st0:
    PUSHR 12
    PUSH8 15
    LT
    BZ tk_next                 ; tok0 full: drop
    PUSH64 @TOK0@
tk_store:
    PUSHR 12
    ADD
    PUSHR 14
    SWAP
    STORE8
    PUSHR 12
    INC
    POPR 12
    JMP tk_next
tk_space:
    PUSHR 13
    BNZ tk_next                ; already in arg: skip spaces
    PUSHR 12
    BZ tk_next                 ; leading space: skip
    PUSH64 @TOK0@              ; end tok0 ...
    PUSHR 12
    ADD
    PUSH8 0
    SWAP
    STORE8
    PUSH8 1
    POPR 13                    ; tok = 1
    PUSH8 0
    POPR 12                    ; j = 0
    JMP tk_next
tk_end:
    PUSHR 13
    BNZ tk_end1
    PUSH64 @TOK0@
    JMP tk_endt
tk_end1:
    PUSH64 @TOK1@
tk_endt:
    PUSHR 12
    ADD
    PUSH8 0
    SWAP
    STORE8                     ; terminate current token
    PUSHR 13
    BNZ tk_done2
    PUSH64 @TOK1@              ; no arg seen: empty tok1
    PUSH8 0
    SWAP
    STORE8
tk_done2:
    RET

; ---------- streq: a b -> flag (1 if equal NUL strings) ----------
streq:
    POPR 11                    ; R11 = b
    POPR 12                    ; R12 = a
se_loop:
    PUSHR 12
    LOADU8
    PUSHR 11
    LOADU8
    NE
    BNZ se_no
    PUSHR 12
    LOADU8
    BZ se_yes                  ; both ended together
    PUSHR 12
    INC
    POPR 12
    PUSHR 11
    INC
    POPR 11
    JMP se_loop
se_yes:
    PUSH8 1
    RET
se_no:
    PUSH8 0
    RET

; ---------- print_u64: n -> (decimal) ----------
print_u64:
    POPR 11                    ; R11 = n
    PUSH8 0
    POPR 12                    ; R12 = digit count
    PUSHR 11
    BZ pu_zero
    JMP pu_l1
pu_zero:
    PUSH8 48
    CALL print_char
    RET
pu_l1:
    PUSHR 11
    BZ pu_l2
    PUSHR 11
    PUSH8 10
    REMU                       ; r = n % 10
    PUSH8 48
    ADD                        ; digit char
    PUSHR 11
    PUSH8 10
    DIVU
    POPR 11                    ; n /= 10
    PUSHR 12
    INC
    POPR 12
    JMP pu_l1
pu_l2:                         ; pop digits (most significant on top) and print
    PUSHR 12
    BZ pu_done
    CALL print_char
    PUSHR 12
    DEC
    POPR 12
    JMP pu_l2
pu_done:
    RET

; ---------- hist_add: append LINE_BUF to history (20 x 32B slots) ----------
hist_add:
    PUSHR 15
    PUSH8 20
    LT                         ; count < 20 ?
    BNZ ha_nofull
    PUSH16 608                 ; full: shift left one slot (19*32)
    PUSH64 @HIST_BUF@
    PUSH64 @HIST_BUF@
    PUSH8 32
    ADD                        ; src = HIST+32
    MEMCPY                     ; n dst src ->
    PUSH8 19
    POPR 15                    ; count = 19 (bump back to 20 below)
ha_nofull:
    PUSHR 15
    PUSH8 32
    MUL
    PUSH64 @HIST_BUF@
    ADD
    POPR 11                    ; R11 = dst slot
    PUSH8 0
    POPR 12                    ; i = 0
ha_cl:
    PUSHR 12
    PUSH8 31
    EQ
    BNZ ha_cterm               ; i == 31 -> terminate
    PUSH64 @LINE_BUF@
    PUSHR 12
    ADD
    LOADU8
    POPR 13                    ; R13 = c
    PUSHR 13
    BZ ha_cterm                ; NUL -> terminate
    PUSHR 11
    PUSHR 12
    ADD
    PUSHR 13
    SWAP
    STORE8
    PUSHR 12
    INC
    POPR 12
    JMP ha_cl
ha_cterm:
    PUSHR 11
    PUSHR 12
    ADD
    PUSH8 0
    SWAP
    STORE8
    PUSHR 15
    INC
    POPR 15
    RET

; ---------- main loop ----------
main_loop:
    PUSH64 @S_prompt@
    CALL print_str
    CALL read_line              ; [len]
    DUP
    BZ hskip
    POPR 14
    CALL hist_add              ; record non-empty lines
    JMP hdone
hskip:
    POP
hdone:
    CALL tokenize
    PUSH64 @TOK0@
    LOADU8
    BZ main_loop               ; empty line
    PUSH64 @TOK0@
    PUSH64 @S_c_help@
    CALL streq
    BNZ do_help
    PUSH64 @TOK0@
    PUSH64 @S_c_ls@
    CALL streq
    BNZ do_ls
    PUSH64 @TOK0@
    PUSH64 @S_c_cat@
    CALL streq
    BNZ do_cat
    PUSH64 @TOK0@
    PUSH64 @S_c_run@
    CALL streq
    BNZ do_run
    PUSH64 @TOK0@
    PUSH64 @S_c_clear@
    CALL streq
    BNZ do_clear
    PUSH64 @TOK0@
    PUSH64 @S_c_ver@
    CALL streq
    BNZ do_ver
    PUSH64 @TOK0@
    PUSH64 @S_c_pwd@
    CALL streq
    BNZ do_pwd
    PUSH64 @TOK0@
    PUSH64 @S_c_echo@
    CALL streq
    BNZ do_echo
    PUSH64 @TOK0@
    PUSH64 @S_c_whoami@
    CALL streq
    BNZ do_whoami
    PUSH64 @TOK0@
    PUSH64 @S_c_uname@
    CALL streq
    BNZ do_uname
    PUSH64 @TOK0@
    PUSH64 @S_c_date@
    CALL streq
    BNZ do_date
    PUSH64 @TOK0@
    PUSH64 @S_c_uptime@
    CALL streq
    BNZ do_uptime
    PUSH64 @TOK0@
    PUSH64 @S_c_ps@
    CALL streq
    BNZ do_ps
    PUSH64 @TOK0@
    PUSH64 @S_c_env@
    CALL streq
    BNZ do_env
    PUSH64 @TOK0@
    PUSH64 @S_c_history@
    CALL streq
    BNZ do_history
    PUSH64 @S_unknown@
    CALL print_str
    PUSH64 @TOK0@
    CALL print_str
    CALL print_newline
    JMP main_loop

do_help:
    PUSH64 @S_help@
    CALL print_str
    JMP main_loop

do_clear:
    PUSH64 @S_clearseq@
    CALL print_str
    JMP main_loop

do_ver:
    PUSH64 @S_vertext@
    CALL print_str
    JMP main_loop

do_pwd:
    PUSH64 @S_pwd_t@
    CALL print_str
    JMP main_loop

do_whoami:
    PUSH64 @S_whoami_t@
    CALL print_str
    JMP main_loop

do_uname:
    PUSH64 @S_uname_t@
    CALL print_str
    JMP main_loop

do_date:
    PUSH64 @S_date_t@
    CALL print_str
    JMP main_loop

do_uptime:
    PUSH64 @S_uptime_t@
    CALL print_str
    JMP main_loop

do_ps:
    PUSH64 @S_ps_t@
    CALL print_str
    JMP main_loop

do_env:
    PUSH64 @S_env_t@
    CALL print_str
    JMP main_loop

; ---------- do_echo: print rest of line after "echo " ----------
do_echo:
    PUSH64 @LINE_BUF@
    POPR 11                    ; R11 = cursor
eo1:                           ; skip the word "echo"
    PUSHR 11
    LOADU8
    POPR 14                    ; R14 = c
    PUSHR 14
    BZ eo_print
    PUSHR 14
    PUSH8 32
    EQ
    BNZ eo2
    PUSHR 11
    INC
    POPR 11
    JMP eo1
eo2:                           ; skip spaces
    PUSHR 11
    INC
    POPR 11
eo2l:
    PUSHR 11
    LOADU8
    POPR 14
    PUSHR 14
    BZ eo_print
    PUSHR 14
    PUSH8 32
    EQ
    BNZ eo2
    JMP eo_print
eo_print:
    PUSHR 11
    CALL print_str
    CALL print_newline
    JMP main_loop

; ---------- do_history: list recorded commands ----------
do_history:
    PUSH8 0
    POPR 13                    ; R13 = i (R11/R12 used by print_u64)
dh_loop:
    PUSHR 13
    PUSHR 15
    EQ
    BNZ main_loop
    PUSHR 13
    INC
    CALL print_u64             ; line number
    PUSH8 32
    CALL print_char
    PUSHR 13
    PUSH8 32
    MUL
    PUSH64 @HIST_BUF@
    ADD
    CALL print_str
    CALL print_newline
    PUSHR 13
    INC
    POPR 13
    JMP dh_loop

; ---------- do_ls: list shared folder ----------
do_ls:
    PUSH64 @IO_BUF@
    PUSHR 3
    STORE64                    ; ARG0 = buffer
    PUSH16 384
    PUSHR 4
    STORE64                    ; ARG1 = size
    PUSH8 1
    PUSHR 2
    STORE64                    ; CMD = LIST
    PUSHR 6
    LOAD64
    POPR 11                    ; R11 = byte count (-1 = error)
    PUSHR 11
    PUSH64 0xFFFFFFFFFFFFFFFF
    EQ
    BNZ ls_err
    PUSHR 8
    POPR 12                    ; R12 = cursor
    PUSHR 8
    PUSHR 11
    ADD
    POPR 13                    ; R13 = end
ls_loop:
    PUSHR 12
    PUSHR 13
    EQ
    BNZ main_loop
    PUSHR 12
    CALL print_str              ; names are NUL-separated
    CALL print_newline
ls_adv:
    PUSHR 12
    LOADU8
    BZ ls_advd
    PUSHR 12
    INC
    POPR 12
    JMP ls_adv
ls_advd:
    PUSHR 12
    INC
    POPR 12
    JMP ls_loop
ls_err:
    PUSH64 @S_fileerr@
    CALL print_str
    JMP main_loop

; ---------- file_cat: path -> (print file) ----------
file_cat:
    POPR 11                    ; R11 = path
    PUSHR 11
    PUSHR 3
    STORE64                    ; ARG0 = path
    PUSH64 @IO_BUF@
    PUSHR 4
    STORE64                    ; ARG1 = buffer
    PUSH16 384
    PUSHR 5
    STORE64                    ; ARG2 = size
    PUSH8 2
    PUSHR 2
    STORE64                    ; CMD = READ
    PUSHR 6
    LOAD64
    POPR 12                    ; R12 = n (-1 = error)
    PUSHR 12
    PUSH64 0xFFFFFFFFFFFFFFFF
    EQ
    BNZ fc_err
    PUSH8 0
    POPR 13                    ; i = 0
fc_loop:
    PUSHR 13
    PUSHR 12
    EQ
    BNZ fc_done
    PUSHR 8
    PUSHR 13
    ADD
    LOADU8
    CALL print_char
    PUSHR 13
    INC
    POPR 13
    JMP fc_loop
fc_done:
    CALL print_newline
    RET
fc_err:
    PUSH64 @S_fileerr@
    CALL print_str
    RET

do_cat:
    PUSH64 @TOK1@
    LOADU8
    BZ cat_usage
    PUSH64 @TOK1@
    CALL file_cat
    JMP main_loop
cat_usage:
    PUSH64 @S_catuse@
    CALL print_str
    JMP main_loop

; ---------- do_run: load program at 0x1000 and jump ----------
do_run:
    PUSH64 @TOK1@
    LOADU8
    BZ run_usage
    PUSH64 @TOK1@
    PUSHR 3
    STORE64                    ; ARG0 = path
    PUSH16 4096
    PUSHR 4
    STORE64                    ; ARG1 = 0x1000
    PUSH32 65536
    PUSHR 5
    STORE64                    ; ARG2 = 64KB max
    PUSH8 2
    PUSHR 2
    STORE64                    ; CMD = READ
    PUSHR 6
    LOAD64
    POPR 11                    ; R11 = bytes read
    PUSHR 11
    PUSH64 0xFFFFFFFFFFFFFFFF
    EQ
    BNZ run_err
    PUSHR 10
    DSPSET                     ; restore entry data-stack pointer
    PUSH16 4096
    JMPI                       ; PC = 0x1000 (no return)
run_err:
    PUSH64 @S_runfail@
    CALL print_str
    JMP main_loop
run_usage:
    PUSH64 @S_runuse@
    CALL print_str
    JMP main_loop
"""


def main():
    outdir = os.path.expanduser("~/workspace/nova-programs/novashell")
    os.makedirs(outdir, exist_ok=True)

    # Collect placeholder names
    names = [n for n, _ in STRINGS] + [n for n, _ in BUFFERS]

    # Pass 1: placeholders -> 0, measure code size
    src1 = CODE
    for n in names:
        src1 = src1.replace("@" + n + "@", "0")
    code = assemble(src1)
    print(f"pass 1: code = {len(code)} bytes")

    # Lay out strings (NUL-terminated, 8-byte padded) then buffers
    addr = len(code)
    addrs = {}
    blobs = []
    for n, s in STRINGS:
        b = s.encode("utf-8") + b"\x00"
        while len(b) % 8:
            b += b"\x00"
        addrs[n] = addr
        blobs.append(b)
        addr += len(b)
    for n, size in BUFFERS:
        addrs[n] = addr
        blobs.append(bytes(size))
        addr += size

    total = addr
    print(f"strings+buffers = {total - len(code)} bytes, total = {total} bytes")
    if total > MAX_SIZE:
        raise SystemExit(f"firmware too large: {total} > {MAX_SIZE}")

    # Pass 2: resolve placeholders, assemble final code
    src2 = CODE
    for n, a in addrs.items():
        src2 = src2.replace("@" + n + "@", str(a))
    code2 = assemble(src2)
    assert len(code2) == len(code), "code size changed between passes!"

    binary = code2 + b"".join(blobs)

    nova_path = os.path.join(outdir, "shell.nova")
    bin_path = os.path.join(outdir, "shell.bin")
    with open(nova_path, "w") as f:
        f.write(src2)
    with open(bin_path, "wb") as f:
        f.write(binary)
    print(f"wrote {nova_path} ({len(src2)} chars)")
    print(f"wrote {bin_path} ({len(binary)} bytes)")


if __name__ == "__main__":
    main()
