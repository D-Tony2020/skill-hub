"""Minimal lark-cli stand-in for tests: docs +update (append blank whiteboard), whiteboard +update/+export.
Boards live in $FAKE_LARK_STATE (json); every call is logged as its own file in $FAKE_LARK_STATE.calls.d/."""
import json, os, sys, time
from pathlib import Path

state_p = Path(os.environ["FAKE_LARK_STATE"])
st = json.loads(state_p.read_text()) if state_p.exists() else {"boards": {}, "n": 0}
argv = sys.argv[1:]
calls = Path(str(state_p) + ".calls.d")  # one file per call: concurrent calls never interleave (Windows appends do)
calls.mkdir(exist_ok=True)
(calls / f"{time.time_ns():020d}-{os.getpid()}.json").write_text(json.dumps(argv, ensure_ascii=False), encoding="utf-8")
MUTATES = argv[:2] in (["docs", "+update"], ["whiteboard", "+update"])


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def done(obj, rc=0):
    if MUTATES and rc == 0:
        state_p.write_text(json.dumps(st, ensure_ascii=False))
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(rc)


if os.environ.get("FAKE_LARK_FAIL") and os.environ["FAKE_LARK_FAIL"] in " ".join(argv):
    done({"ok": False, "error": {"message": "simulated failure"}}, 1)
if argv[:2] == ["docs", "+update"]:
    st["n"] += 1
    tok = f"wbtok{st['n']:04d}"
    st["boards"][tok] = []
    done({"ok": True, "identity": "user", "data": {"document": {"revision_id": 2, "new_blocks": [
        {"block_id": f"blk{st['n']}", "block_type": "whiteboard", "block_token": tok}]}, "result": "success"}})
if argv[:2] == ["whiteboard", "+update"]:
    tok, src = arg("--whiteboard-token"), arg("--source")
    assert src.startswith("@") and not os.path.isabs(src[1:]), "lark-cli needs relative @file paths"
    nodes = json.loads(Path(src[1:]).read_text(encoding="utf-8"))["nodes"]
    # the server assigns its own ids
    st["boards"][tok] = [dict(n, id=f"srv{i}") for i, n in enumerate(nodes)] + ([] if "--overwrite" in argv else st["boards"].get(tok, []))
    done({"ok": True, "data": {"result": "success"}})
if argv[:2] == ["whiteboard", "+export"]:
    tok, kind = arg("--whiteboard-token"), arg("--output-type")
    if kind == "raw":
        done({"ok": True, "data": {"nodes": st["boards"].get(tok, [])}})
    if kind == "preview":
        out = arg("--output")
        assert not os.path.isabs(out)
        Path(out).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        done({"ok": True, "data": {"file": out}})
done({"ok": False, "error": {"message": "unsupported " + " ".join(argv[:2])}}, 2)
