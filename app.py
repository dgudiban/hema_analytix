"""Hugging Face Spaces entrypoint (Gradio SDK, free tier).

Runs the BloodIQ FastAPI app under uvicorn on port 7860. A minimal Gradio
interface is mounted at /gradio so the Space satisfies the Gradio SDK
contract; the product UI (static frontend) is served by FastAPI at /.

Local equivalent of the Docker CMD:
    python app.py
"""
import os
import sys

import gradio as gr
import spaces

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from app.main import app as fastapi_app  # noqa: E402

# main.py mounts the static frontend at "/" (Starlette normalizes the Mount
# path to ""), which would swallow /gradio. Move any root mounts to the end
# so the Gradio demo stays reachable.
_root_mounts = [
    r
    for r in fastapi_app.routes
    if type(r).__name__ == "Mount" and getattr(r, "path", "") in ("", "/")
]
for _m in _root_mounts:
    fastapi_app.routes.remove(_m)

@spaces.GPU
def _gradio_status() -> str:
    """Status endpoint for the /gradio demo.

    Decorated with @spaces.GPU so the Space satisfies the ZeroGPU hardware
    requirement (at least one GPU-decorated function must be detected at
    startup). The function itself is a trivial status check; the product UI
    and API are served by the FastAPI app.
    """
    return "BloodIQ API is running. The full app UI is served at the Space root (/)."


demo = gr.Interface(
    fn=_gradio_status,
    inputs=[],
    outputs="text",
    title="BloodIQ",
    description="AI blood report analysis. Use the main page for uploads and chat.",
)

# Single uvicorn process serves the FastAPI app (/, /api/...) plus Gradio at /gradio.
app = gr.mount_gradio_app(fastapi_app, demo, path="/gradio")

for _m in _root_mounts:
    fastapi_app.mount(_m.path, _m.app, name=_m.name)

if __name__ == "__main__":
    # TEMPORARY DIAGNOSTIC: identify the process holding port 7860 via /proc.
    import os

    def _find_port_holder(port: int):
        _hex_port = f"{port:04X}"
        _inodes = set()
        for _f in ("/proc/net/tcp", "/proc/net/tcp6"):
            try:
                with open(_f) as fh:
                    for _line in fh.read().splitlines()[1:]:
                        _parts = _line.split()
                        if len(_parts) > 9 and _parts[1].endswith(":" + _hex_port):
                            _inodes.add(_parts[9])
            except OSError:
                pass
        _holders = []
        for _pid in os.listdir("/proc"):
            if not _pid.isdigit():
                continue
            try:
                _fds = os.listdir(f"/proc/{_pid}/fd")
            except OSError:
                continue
            for _fd in _fds:
                try:
                    _target = os.readlink(f"/proc/{_pid}/fd/{_fd}")
                except OSError:
                    continue
                if _target.startswith("socket:["):
                    _ino = _target[8:-1]
                    if _ino in _inodes:
                        try:
                            with open(f"/proc/{_pid}/cmdline", "rb") as fh:
                                _cmd = fh.read().replace(b"\x00", b" ").decode().strip()
                        except OSError:
                            _cmd = "?"
                        _holders.append((_pid, _cmd))
                        break
        return _holders

    _holders = _find_port_holder(7860)
    print(f"DIAG: processes holding port 7860: {_holders}", flush=True)
    print(f"DIAG: this process pid={os.getpid()}", flush=True)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
