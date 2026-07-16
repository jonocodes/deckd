"""Check whether deckd can inject scroll through /dev/uinput."""

from __future__ import annotations

import grp
import os
import stat
from pathlib import Path

from deckd.input import UinputScrollSink


def main() -> None:
    ok = True
    uinput = Path("/dev/uinput")

    if not uinput.exists():
        print("FAIL /dev/uinput does not exist; load the uinput kernel module")
        ok = False
    else:
        st = uinput.stat()
        mode = stat.filemode(st.st_mode)
        owner = _name_for_uid(st.st_uid)
        group = _name_for_gid(st.st_gid)
        writable = os.access(uinput, os.W_OK)
        print(f"INFO /dev/uinput {mode} {owner}:{group} writable={writable}")
        if not writable:
            print("FAIL current user cannot write /dev/uinput")
            ok = False

    groups = {_name_for_gid(gid) for gid in os.getgroups()}
    print(f"INFO user={_name_for_uid(os.getuid())} groups={','.join(sorted(groups))}")
    if "input" not in groups:
        print("WARN current shell is not in group 'input'; ACL/uaccess may be carrying this session")

    try:
        sink = UinputScrollSink()
    except Exception as exc:
        print(f"FAIL could not create uinput scroll sink: {exc}")
        ok = False
    else:
        try:
            sink.emit_scroll(1)
            print("OK created uinput scroll sink and emitted REL_WHEEL_HI_RES=1")
        finally:
            sink.close()

    raise SystemExit(0 if ok else 1)


def _name_for_uid(uid: int) -> str:
    import pwd

    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _name_for_gid(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


if __name__ == "__main__":
    main()
