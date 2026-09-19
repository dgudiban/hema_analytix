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

demo = gr.Interface(
    fn=lambda: "BloodIQ API is running. The full app UI is served at the Space root (/).",
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
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
