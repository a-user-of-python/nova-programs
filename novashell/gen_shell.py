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

MAX_SIZE = 65536

# (name, python-string) — NUL-terminated in the image, 8-byte padded
STRINGS = [
    ("S_banner", "NovaShell v1.0 -- NOVA firmware shell\n"),
    ("S_banner2", "Type 'help' for a command list.\n"),
    ("S_datestr", "Date: "),
    ("S_timestr", "   Time: "),
    ("S_utcstr", " UTC\n"),
    ("S_prompt", "nova> "),
    ("S_help",
     "Commands:\n"
     "  help          list commands\n"
     "  ls            list shared folder\n"
     "  cat <file>    show file contents\n"
     "  run <file>    run program\n"
     "  ps            list processes\n"
     "  kill <pid>    kill process\n"
     "  pwd           print working directory\n"
     "  echo <text>   print text\n"
     "  whoami        print user name\n"
     "  uname         print system info\n"
     "  date          print date\n"
     "  uptime        print uptime\n"
     "  clear         clear screen\n"
     "  ver           firmware version\n"
     "  env           show environment\n"
     "  history       command history\n"
     "  fetch <url>   fetch URL over HTTP(S)\n"),
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
    ("S_c_kill", "kill"),
    ("S_killuse", "usage: kill <pid>\n"),
    ("S_killdone", "killed\n"),
    ("S_killfail", "kill failed\n"),
    ("S_c_fetch", "fetch"),
    ("S_fetchuse", "usage: fetch <url>\n"),
    ("S_fetchfail", "fetch failed\n"),
    ("S_timeapi", "https://timeapi.io/api/Time/current/zone?timeZone=UTC"),
    ("S_datetime_key", "\"dateTime\":\""),
    ("S_datefail", "date sync failed\n"),
    ("S_seconds", " seconds\n"),
    ("S_noslot", "no free process slot\n"),
    ("S_ps_header", "  PID TTY          CMD\n"),
    ("S_ps_indent", "    "),
    ("S_ps_mid", " con          program\n"),
    ("S_ps_shell", "    8 con          novash\n"),
]

# (name, size in bytes) — zero-filled buffers after the strings
BUFFERS = [
    ("LINE_BUF", 128),   # keyboard input line
    ("TOK0", 16),        # command token
    ("TOK1", 64),        # argument token (file path)
    ("IO_BUF", 384),     # file listing / file read buffer
    ("HIST_BUF", 640),   # command history: 20 slots x 32 bytes
    ("PROC_TABLE", 1584), # 9 slots x 176 bytes (0-7 programs, 8 shell)
    ("CUR_PID", 8),      # current process ID
    ("HANDLER_SCRATCH", 40), # 5 x 8 bytes for R11-R15 in timer handler
    ("UPTIME", 8),            # 64-bit tick counter, incremented every timer tick
    ("DATETIME", 48),         # cached date/time string from network sync
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
    ; ---- Zero all BSS buffers (do NOT rely on VM zeroing memory) ----
    ; LINE_BUF(128)+TOK0(16)+TOK1(64)+IO_BUF(384)+HIST_BUF(640)
    ; +PROC_TABLE(1584)+CUR_PID(8)+HANDLER_SCRATCH(40)+UPTIME(8)+DATETIME(48) = 2920 bytes = 365 qwords
    PUSH64 @LINE_BUF@
    POPR 11                    ; R11 = addr
    PUSH16 365
    POPR 12                    ; R12 = qword count
bss_zero:
    PUSHR 12
    BZ bss_zero_done
    PUSH8 0
    PUSHR 11
    STORE64                    ; *addr = 0
    PUSHR 11
    PUSH8 8
    ADD
    POPR 11                    ; addr += 8
    PUSHR 12
    DEC
    POPR 12                    ; count -= 1
    JMP bss_zero
bss_zero_done:
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
    PUSH64 0xFFFFFFFFFFFF0040
    POPR 7                     ; R7 = timer interval
    PUSH64 0xFFFFFFFFFFFF0050
    POPR 9                     ; R9 = timer vector
    PUSH8 0
    POPR 15                    ; R15 = history count
    PUSH64 @IO_BUF@
    POPR 8                     ; R8 = IO_BUF (used by ls/cat via PUSHR 8)
    ; NOTE: R8 is reused for IO_BUF; timer uses R7 and R9.
    ; ---- Preemptive scheduler ----
    PUSH64 100000
    PUSHR 7
    STORE64                    ; timer interval = 100k cycles
    PUSH64 timer_handler
    PUSHR 9
    STORE64                    ; timer vector
    PUSH8 8
    PUSH64 @CUR_PID@
    STORE64                    ; CUR_PID = 8 (shell)
    ; Process table for 2-program scheduler (firmware not counted).
    ; Process table zeroed at boot (see bss_zero above); all slots FREE.
    PUSH64 @S_banner@
    CALL print_str
    ; ---- Auto-sync date/time at boot (quick 5s timeout; skip if offline) ----
    CALL date_sync
    BZ boot_no_date
    CALL print_date_time
boot_no_date:
    PUSH64 @S_banner2@
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
    BZ tk_space_cmd            ; in cmd: end tok0, switch to arg
    ; in arg: preserve the space (filenames may contain spaces),
    ; but skip leading spaces in the arg.
    PUSHR 12
    BZ tk_next                 ; leading space in arg: skip
    PUSHR 12
    PUSH8 63
    LT
    BZ tk_next                 ; tok1 full: drop
    PUSH64 @TOK1@
    PUSHR 12
    ADD
    PUSH8 32
    SWAP
    STORE8                     ; store the space
    PUSHR 12
    INC
    POPR 12
    JMP tk_next
tk_space_cmd:
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
    PUSH64 @S_c_kill@
    CALL streq
    BNZ do_kill
    PUSH64 @TOK0@
    PUSH64 @S_c_fetch@
    CALL streq
    BNZ do_fetch
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
    ; Manual sync uses the full timeout, then parses and prints.
    PUSH64 @S_timeapi@
    PUSH8 1
    CALL net_get
    POPR 11
    PUSHR 11
    PUSH64 0xFFFFFFFFFFFFFFFF
    EQ
    BNZ date_fail
    PUSHR 11
    PUSH8 0
    EQ
    BNZ date_fail
    CALL date_parse_buf
    BZ date_fail
    CALL print_date_time
    JMP main_loop
date_fail:
    PUSH64 @S_datefail@
    CALL print_str
    JMP main_loop

do_uptime:
    PUSH64 @UPTIME@
    LOAD64
    PUSH8 10
    DIVU                       ; ~10 ticks/sec -> seconds
    CALL print_uint64
    PUSH64 @S_seconds@
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
; ---------- do_run: load program into a free slot, scheduler starts it ----------
; Slot layout (176 bytes): +0 state, +8 PC, +16 DSP, +24 CSP, +32..+152 R0-R15
do_run:
    PUSH64 @TOK1@
    LOADU8
    BZ run_usage               ; no filename given
    ; --- Find a free slot 0-7 ---
    PUSH8 0
    POPR 11                    ; R11 = slot
find_slot:
    PUSHR 11
    PUSH8 8
    LTU
    BZ run_noslot
    PUSHR 11
    PUSH16 176
    MUL
    PUSH64 @PROC_TABLE@
    ADD
    LOAD64                     ; state
    PUSH8 0
    EQ
    BNZ found_slot
    PUSHR 11
    INC
    POPR 11
    JMP find_slot
found_slot:
    ; R11 = slot. R13 = load_addr = 0x10000 + slot*0x10000 (64KB slots)
    PUSHR 11
    PUSH32 65536
    MUL
    PUSH32 65536
    ADD
    POPR 13
    ; --- Load file via MMIO ---
    PUSH64 @TOK1@
    PUSHR 3
    STORE64                    ; ARG0 = path
    PUSHR 13
    PUSHR 4
    STORE64                    ; ARG1 = load_addr
    PUSH32 65536
    PUSHR 5
    STORE64                    ; ARG2 = 64KB max
    PUSH8 2
    PUSHR 2
    STORE64                    ; CMD = READ
    PUSHR 6
    LOAD64
    POPR 14                    ; R14 = bytes read (temp)
    PUSHR 14
    PUSH64 0xFFFFFFFFFFFFFFFF
    EQ
    BNZ run_failed
    JMP run_setup
run_failed:
    PUSH64 @S_runfail@
    CALL print_str
    JMP main_loop
run_setup:
    ; R14 = prog DSP = shell DSP - 1MB - slot*512KB
    ; (adapts to any RAM size; stays within [dslim, dataStackBase])
    DSPGET
    PUSH32 1048576
    SUB
    PUSHR 11
    PUSH32 524288
    MUL
    SUB
    POPR 14
    ; R12 = slot_addr = PROC_TABLE + slot*176
    PUSHR 11
    PUSH16 176
    MUL
    PUSH64 @PROC_TABLE@
    ADD
    POPR 12
    ; slot.state = 1
    PUSH8 1
    PUSHR 12
    STORE64
    ; slot.PC = load_addr (R13)
    PUSHR 13
    PUSHR 12
    PUSH8 8
    ADD
    STORE64
    ; slot.DSP = R14
    PUSHR 14
    PUSHR 12
    PUSH8 16
    ADD
    STORE64
    ; slot.CSP = shell CSP - 64KB - slot*64KB
    CSPGET
    PUSH32 65536
    SUB
    PUSHR 11
    PUSH32 65536
    MUL
    SUB
    PUSHR 12
    PUSH8 24
    ADD
    STORE64
    ; R15 = load_addr (so position-dependent programs can find their data)
    PUSHR 13
    PUSHR 12
    PUSH16 152
    ADD
    STORE64
    ; Done. The timer will preempt the shell and start the program.
    ; (R0-R14 in the slot are zero = fresh process; R15 = load address.)
    JMP main_loop
run_noslot:
    PUSH64 @S_noslot@
    CALL print_str
    JMP main_loop
run_usage:
    PUSH64 @S_runuse@
    CALL print_str
    JMP main_loop

; ---------- do_ps: list processes ----------
do_ps:
    PUSH64 @S_ps_header@
    CALL print_str
    PUSH8 0
    POPR 14                    ; R14 = pid (R11 is clobbered by print_str)
sched_ps_loop:
    PUSHR 14
    PUSH8 8
    LTU
    BZ sched_ps_shell
    PUSHR 14
    PUSH16 176
    MUL
    PUSH64 @PROC_TABLE@
    ADD
    LOAD64                     ; state
    PUSH8 1
    EQ
    BZ sched_ps_next
    PUSH64 @S_ps_indent@
    CALL print_str
    PUSHR 14
    PUSH8 48
    ADD                        ; '0' + pid
    PUSHR 0
    STORE8                     ; emit digit
    PUSH64 @S_ps_mid@
    CALL print_str
sched_ps_next:
    PUSHR 14
    INC
    POPR 14
    JMP sched_ps_loop
sched_ps_shell:
    PUSH64 @S_ps_shell@
    CALL print_str
    JMP main_loop

; ---------- do_kill: terminate a process ----------
do_kill:
    PUSH64 @TOK1@
    LOADU8
    BZ kill_usage
    ; Parse multi-digit PID from TOK1
    PUSH64 @TOK1@
    POPR 11                    ; R11 = ptr
    PUSH8 0
    POPR 12                    ; R12 = pid accumulator
kill_parse:
    PUSHR 11
    LOADU8
    BZ kill_parsed             ; NUL terminator
    PUSHR 11
    LOADU8
    PUSH8 48
    SUB
    POPR 13                    ; R13 = digit
    PUSHR 13
    PUSH8 10
    LTU
    BZ kill_fail               ; not a digit
    PUSHR 12
    PUSH8 10
    MUL
    PUSHR 13
    ADD
    POPR 12                    ; pid = pid*10 + digit
    PUSHR 11
    PUSH8 1
    ADD
    POPR 11                    ; ptr++
    JMP kill_parse
kill_parsed:
    PUSHR 12
    POPR 11                    ; R11 = pid
    PUSHR 11
    PUSH8 8
    LTU
    BZ kill_fail               ; pid >= 8: cannot kill shell/nonexistent
    ; slot.state = 0
    PUSHR 11
    PUSH16 176
    MUL
    PUSH64 @PROC_TABLE@
    ADD
    POPR 12
    PUSH8 0
    PUSHR 12
    STORE64
    PUSH64 @S_killdone@
    CALL print_str
    JMP main_loop
kill_fail:
    PUSH64 @S_killfail@
    CALL print_str
    JMP main_loop
kill_usage:
    PUSH64 @S_killuse@
    CALL print_str
    JMP main_loop

; ---------- net_get: url cmd -> n (bytes written, or -1) ----------
; Drives the app's MMIO network device. Pure Nova machine code.
; cmd=1: full GET (20s timeout), cmd=2: quick GET (5s timeout).
net_get:
    POPR 12                    ; R12 = cmd
    POPR 11                    ; R11 = url
    PUSHR 11
    PUSH64 0xFFFFFFFFFFFF0060  ; netUrl
    STORE64
    PUSH64 0x4000
    PUSH64 0xFFFFFFFFFFFF0068  ; netBuf
    STORE64
    PUSH16 16384
    PUSH64 0xFFFFFFFFFFFF0070  ; netBufSize
    STORE64
    PUSHR 12
    PUSH64 0xFFFFFFFFFFFF0058  ; netCmd (blocks like a syscall)
    STORE64
    PUSH64 0xFFFFFFFFFFFF0078  ; netResult
    LOAD64
    RET

; ---------- date_parse_buf: -> flag (1=ok, 0=fail) ----------
; Parses the 16KB response buffer at 0x4000 into DATETIME.
date_parse_buf:
    PUSH64 0x4000
    POPR 11
dpb_scan:
    PUSHR 11
    LOADU8
    BZ dpb_fail
    PUSHR 11
    POPR 13
    PUSHR 11
    PUSH64 @S_datetime_key@
    CALL startswith
    PUSHR 13
    POPR 11
    BNZ dpb_found
    PUSHR 11
    INC
    POPR 11
    JMP dpb_scan
dpb_found:
    PUSH8 12
    PUSHR 11
    ADD
    POPR 11
    PUSH64 @DATETIME@
    POPR 12
    PUSH8 47
    POPR 14
dpb_copy:
    PUSHR 14
    BZ dpb_copy_done
    PUSHR 11
    LOADU8
    DUP
    BZ dpb_copy_done
    DUP
    PUSH8 10
    EQ
    BNZ dpb_copy_done
    DUP
    PUSH8 34
    EQ
    BNZ dpb_copy_done
    DUP
    PUSH8 46
    EQ
    BNZ dpb_copy_done
    POPR 13
    PUSHR 13
    PUSHR 12
    STORE8
    PUSHR 11
    INC
    POPR 11
    PUSHR 12
    INC
    POPR 12
    PUSHR 14
    PUSH8 1
    SUB
    POPR 14
    JMP dpb_copy
dpb_copy_done:
    POP
    PUSH8 0
    PUSHR 12
    STORE8
    ; Validate format: YYYY-MM-DDTHH:MM:SS (positions 4,7='-', 10='T')
    PUSH64 @DATETIME@
    PUSH8 4
    ADD
    LOADU8
    PUSH8 45
    EQ
    BZ dpb_fail
    PUSH64 @DATETIME@
    PUSH8 7
    ADD
    LOADU8
    PUSH8 45
    EQ
    BZ dpb_fail
    PUSH64 @DATETIME@
    PUSH8 10
    ADD
    LOADU8
    PUSH8 84
    EQ
    BZ dpb_fail
    PUSH8 1
    RET
dpb_fail:
    PUSH8 0
    RET

; ---------- date_sync: -> flag (1=ok, 0=fail) ----------
; Fetches real UTC time (quick timeout) and caches it in DATETIME.
; No output. Used at boot and by the date command.
date_sync:
    PUSH64 @S_timeapi@
    PUSH8 2
    CALL net_get
    POPR 11
    PUSHR 11
    PUSH64 0xFFFFFFFFFFFFFFFF
    EQ
    BNZ ds_fail
    PUSHR 11
    PUSH8 0
    EQ
    BNZ ds_fail                ; 0 bytes = fail
    CALL date_parse_buf
    RET
ds_fail:
    PUSH8 0
    RET

; ---------- print_date_time: -> (prints "Date: <d>   Time: <t> UTC") ----------
print_date_time:
    PUSH64 @S_datestr@
    CALL print_str
    PUSH64 @DATETIME@
    POPR 11
pdt_loop:
    PUSHR 11
    LOADU8
    DUP
    BZ pdt_end
    DUP
    PUSH8 84                   ; 'T'
    EQ
    BNZ pdt_time
    PUSHR 0
    STORE8
    PUSHR 11
    INC
    POPR 11
    JMP pdt_loop
pdt_time:
    POP                        ; drop 'T'
    PUSHR 11
    POPR 13                    ; R13 = save pos (print_str clobbers R11)
    PUSH64 @S_timestr@
    CALL print_str
    PUSHR 13
    PUSH8 1
    ADD
    POPR 11
    PUSHR 11
    CALL print_str
    PUSH64 @S_utcstr@
    CALL print_str
    RET
pdt_end:
    POP
    RET

; ---------- do_fetch: HTTP(S) GET a URL and print the body ----------
do_fetch:
    PUSH64 @TOK1@
    LOADU8
    BZ fetch_usage
    PUSH64 @TOK1@
    PUSH8 1
    CALL net_get
    POPR 11
    PUSHR 11
    PUSH64 0xFFFFFFFFFFFFFFFF
    EQ
    BNZ fetch_failed
    PUSHR 11
    PUSH64 0x4000
    ADD
    POPR 12
    PUSH8 0
    PUSHR 12
    STORE8                     ; NUL-terminate
    PUSH64 0x4000
    CALL print_str
    CALL print_newline
    JMP main_loop
fetch_failed:
    PUSH64 @S_fetchfail@
    CALL print_str
    JMP main_loop
fetch_usage:
    PUSH64 @S_fetchuse@
    CALL print_str
    JMP main_loop

; ---------- startswith: hay needle -> 1 if hay starts with needle ----------
startswith:
    POPR 12                    ; R12 = needle
    POPR 11                    ; R11 = hay
sw_loop:
    PUSHR 12
    LOADU8
    DUP
    BZ sw_yes
    PUSHR 11
    LOADU8
    EQ
    BZ sw_no
    PUSHR 11
    INC
    POPR 11
    PUSHR 12
    INC
    POPR 12
    JMP sw_loop
sw_yes:
    POP
    PUSH8 1
    RET
sw_no:
    PUSH8 0
    RET

; ---------- print_uint64: u64 -> (decimal) ----------
print_uint64:
    POPR 11                    ; R11 = value
    PUSH64 @IO_BUF@
    PUSH8 32
    ADD
    POPR 12                    ; R12 = cursor
    PUSH8 0
    PUSHR 12
    STORE8
    PUSHR 11
    PUSH8 0
    EQ
    BZ pu64_loop
    PUSHR 12
    PUSH8 1
    SUB
    POPR 12
    PUSH8 48
    PUSHR 12
    STORE8
    JMP pu64_done
pu64_loop:
    PUSHR 11
    PUSH8 0
    EQ
    BNZ pu64_done
    PUSHR 11
    PUSH8 10
    REMU
    PUSH8 48
    ADD
    POPR 13
    PUSHR 12
    PUSH8 1
    SUB
    POPR 12
    PUSHR 13
    PUSHR 12
    STORE8
    PUSHR 11
    PUSH8 10
    DIVU
    POPR 11
    JMP pu64_loop
pu64_done:
    PUSHR 12
    CALL print_str
    RET

; ================= Timer Handler: preemptive context switch =================
; On entry (from VM): data stack has [epc, cause] (cause on top).
; Interrupts are disabled by the VM; MRET re-enables them.
; Saves: PC, DSP, CSP, R0-R15 of CUR_PID.
; Restores: next runnable PID's state. Uses CSRSET+MRET to resume.
timer_handler:
    ; ---- Save R11-R15 to scratch (they are our temporaries) ----
    PUSHR 11
    PUSH64 @HANDLER_SCRATCH@
    STORE64
    PUSHR 12
    PUSH64 @HANDLER_SCRATCH@
    PUSH8 8
    ADD
    STORE64
    PUSHR 13
    PUSH64 @HANDLER_SCRATCH@
    PUSH8 16
    ADD
    STORE64
    PUSHR 14
    PUSH64 @HANDLER_SCRATCH@
    PUSH8 24
    ADD
    STORE64
    PUSHR 15
    PUSH64 @HANDLER_SCRATCH@
    PUSH8 32
    ADD
    STORE64
    ; ---- Uptime tick ----
    PUSH64 @UPTIME@
    LOAD64
    PUSH8 1
    ADD
    POPR 11
    PUSHR 11
    PUSH64 @UPTIME@
    STORE64
    ; ---- Pop trap frame ----
    POPR 15                    ; cause
    POPR 14                    ; epc
    ; If ECALL (cause=8) from user program, exit it
    PUSHR 15
    PUSH8 8
    EQ
    BZ not_ecall
    PUSH64 @CUR_PID@
    LOAD64
    POPR 13
    PUSHR 13
    PUSH8 8
    EQ
    BNZ not_ecall              ; shell ECALL: ignore
    ; Kill user process: slot.state = 0
    PUSHR 13
    PUSH16 176
    MUL
    PUSH64 @PROC_TABLE@
    ADD
    POPR 12
    PUSH8 0
    PUSHR 12
    STORE64
    ; Fall through to scheduler (will pick next runnable)
not_ecall:
    ; ---- R13 = CUR_PID ----
    PUSH64 @CUR_PID@
    LOAD64
    POPR 13
    ; ---- R12 = slot addr ----
    PUSHR 13
    PUSH16 176
    MUL
    PUSH64 @PROC_TABLE@
    ADD
    POPR 12
    ; ---- Save PC ----
    PUSHR 14
    PUSHR 12
    PUSH8 8
    ADD
    STORE64
    ; ---- Save DSP ----
    DSPGET
    PUSHR 12
    PUSH8 16
    ADD
    STORE64
    ; ---- Save CSP ----
    CSPGET
    PUSHR 12
    PUSH8 24
    ADD
    STORE64
    ; ---- Save R0-R10 ----
    PUSHR 0
    PUSHR 12
    PUSH8 32
    ADD
    STORE64
    PUSHR 1
    PUSHR 12
    PUSH8 40
    ADD
    STORE64
    PUSHR 2
    PUSHR 12
    PUSH8 48
    ADD
    STORE64
    PUSHR 3
    PUSHR 12
    PUSH8 56
    ADD
    STORE64
    PUSHR 4
    PUSHR 12
    PUSH8 64
    ADD
    STORE64
    PUSHR 5
    PUSHR 12
    PUSH8 72
    ADD
    STORE64
    PUSHR 6
    PUSHR 12
    PUSH8 80
    ADD
    STORE64
    PUSHR 7
    PUSHR 12
    PUSH8 88
    ADD
    STORE64
    PUSHR 8
    PUSHR 12
    PUSH8 96
    ADD
    STORE64
    PUSHR 9
    PUSHR 12
    PUSH8 104
    ADD
    STORE64
    PUSHR 10
    PUSHR 12
    PUSH8 112
    ADD
    STORE64
    ; ---- Save R11-R15 from scratch ----
    PUSH64 @HANDLER_SCRATCH@
    LOAD64
    PUSHR 12
    PUSH8 120
    ADD
    STORE64
    PUSH64 @HANDLER_SCRATCH@
    PUSH8 8
    ADD
    LOAD64
    PUSHR 12
    PUSH16 128
    ADD
    STORE64
    PUSH64 @HANDLER_SCRATCH@
    PUSH8 16
    ADD
    LOAD64
    PUSHR 12
    PUSH16 136
    ADD
    STORE64
    PUSH64 @HANDLER_SCRATCH@
    PUSH8 24
    ADD
    LOAD64
    PUSHR 12
    PUSH16 144
    ADD
    STORE64
    PUSH64 @HANDLER_SCRATCH@
    PUSH8 32
    ADD
    LOAD64
    PUSHR 12
    PUSH16 152
    ADD
    STORE64
    ; ---- Select next PID: round-robin from cur+1, PID 8 always runnable ----
    PUSHR 13
    INC
    POPR 11                    ; R11 = candidate
select_loop:
    PUSHR 11
    PUSH8 9
    LTU
    BNZ select_check
    PUSH8 0
    POPR 11                    ; wrap to 0
select_check:
    PUSHR 11
    PUSH8 8
    EQ
    BNZ select_found           ; shell always runnable
    PUSHR 11
    PUSH16 176
    MUL
    PUSH64 @PROC_TABLE@
    ADD
    LOAD64
    PUSH8 1
    EQ
    BNZ select_found
    PUSHR 11
    INC
    POPR 11
    JMP select_loop
select_found:
    ; R11 = next PID. Update CUR_PID.
    PUSHR 11
    PUSH64 @CUR_PID@
    STORE64
    ; R12 = new slot addr
    PUSHR 11
    PUSH16 176
    MUL
    PUSH64 @PROC_TABLE@
    ADD
    POPR 12
    ; ---- Restore DSP ----
    PUSHR 12
    PUSH8 16
    ADD
    LOAD64
    DSPSET
    ; ---- Restore CSP ----
    PUSHR 12
    PUSH8 24
    ADD
    LOAD64
    CSPSET
    ; ---- Restore R0-R10 ----
    PUSHR 12
    PUSH8 32
    ADD
    LOAD64
    POPR 0
    PUSHR 12
    PUSH8 40
    ADD
    LOAD64
    POPR 1
    PUSHR 12
    PUSH8 48
    ADD
    LOAD64
    POPR 2
    PUSHR 12
    PUSH8 56
    ADD
    LOAD64
    POPR 3
    PUSHR 12
    PUSH8 64
    ADD
    LOAD64
    POPR 4
    PUSHR 12
    PUSH8 72
    ADD
    LOAD64
    POPR 5
    PUSHR 12
    PUSH8 80
    ADD
    LOAD64
    POPR 6
    PUSHR 12
    PUSH8 88
    ADD
    LOAD64
    POPR 7
    PUSHR 12
    PUSH8 96
    ADD
    LOAD64
    POPR 8
    PUSHR 12
    PUSH8 104
    ADD
    LOAD64
    POPR 9
    PUSHR 12
    PUSH8 112
    ADD
    LOAD64
    POPR 10
    ; ---- Restore R11, R13, R14, R15 (R12 last) ----
    PUSHR 12
    PUSH8 120
    ADD
    LOAD64
    POPR 11
    PUSHR 12
    PUSH16 136
    ADD
    LOAD64
    POPR 13
    PUSHR 12
    PUSH16 144
    ADD
    LOAD64
    POPR 14
    PUSHR 12
    PUSH16 152
    ADD
    LOAD64
    POPR 15
    ; ---- Load new PC, set epc, restore R12, MRET ----
    PUSHR 12
    PUSH8 8
    ADD
    LOAD64                     ; [new_pc]
    PUSHR 12
    PUSH16 128
    ADD
    LOAD64                     ; [new_pc, saved_R12]
    POPR 12                    ; [new_pc], R12 restored
    CSRSET 0                   ; epc = new_pc
    MRET                       ; pc = epc, interrupts re-enabled

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
    import json as _json
    with open("firmware_addrs.json", "w") as _f:
        _json.dump({"UPTIME": addrs["UPTIME"], "DATETIME": addrs["DATETIME"]}, _f)
    print(f"UPTIME @ {addrs['UPTIME']} (0x{addrs['UPTIME']:x}), DATETIME @ {addrs['DATETIME']} (0x{addrs['DATETIME']:x})")
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
