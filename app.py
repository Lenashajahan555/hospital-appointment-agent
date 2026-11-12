"""Appointment desk: Streamlit chat GUI for the APIM-backed agent.

Run from this folder:  streamlit run app.py

This is the whole front end in one file: styling, theme and UI helpers are all
here. The agent, booking and infra code are not touched by it.
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "agent"))
from agent import Agent  # noqa: E402

# Read .env next to this file, and let it win over stale shell variables.
load_dotenv(ROOT / ".env", override=True)

ORG_NAME = os.environ.get("ORG_NAME", "Hospital")

STARTERS = [
    ("Book a cardiology visit", "I'd like to book a cardiology appointment."),
    ("See pediatrics availability", "Which pediatrics time slots are free this week?"),
    ("Cancel an appointment", "I need to cancel an appointment."),
]

# ------------------------------------------------------------------- styling
CSS = """
@import url("https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,600&display=swap");

:root {
  color-scheme: light;
  --ink: #14283B;
  --muted: #53667A;
  --line: #D3DEE5;
  --paper: #FFFFFF;
  --mist: #F8FAFB;
  --side: #E9F0F3;
  --accent: #0B6E75;
  --accent-ink: #08565C;
  --user: #E3F0F1;
  --serif: "Source Serif 4", Georgia, serif;
}

/* Fixed light palette, so the page looks the same in light and dark browsers */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: var(--mist); }
[data-testid="stBottom"], [data-testid="stBottom"] > div { background: var(--mist); }
.stApp { color: var(--ink); }
.stApp :where([data-testid="stMarkdownContainer"] p,
              [data-testid="stMarkdownContainer"] li,
              [data-testid="stMarkdownContainer"] strong,
              [data-testid="stCaptionContainer"], summary, label) { color: var(--ink); }

/* Type: set on text elements only so icon glyphs keep their own font */
.stApp, .stApp p, .stApp li, .stApp label, .stApp button,
.stApp textarea, .stApp input, .stApp summary, .stApp code {
  font-family: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
}

/* Chrome: keep the sidebar toggle, drop the rest */
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }

.block-container { max-width: 820px; padding-top: 2.4rem; padding-bottom: 6rem; }

/* Page header */
.desk-title {
  font-family: var(--serif);
  font-weight: 600;
  font-size: 2rem;
  line-height: 1.2;
  letter-spacing: -0.01em;
  margin: 0 0 .35rem;
  padding: 0;
  color: var(--ink);
}
.desk-sub { margin: 0 0 1.6rem; max-width: 60ch; color: var(--muted); line-height: 1.55; }
.starter-lead { margin: 0 0 .6rem; color: var(--muted); }

/* Buttons (starters and sidebar actions) */
.stButton > button {
  width: 100%;
  justify-content: flex-start;
  text-align: left;
  background: var(--paper);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: .7rem .9rem;
  font-weight: 500;
  transition: border-color .15s, color .15s;
}
.stButton > button:hover { border-color: var(--accent); color: var(--accent-ink); }
.stApp button:focus-visible, .stApp textarea:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Conversation: flat messages, no avatars; the person's messages get a tint */
[data-testid^="stChatMessageAvatar"] { display: none; }
[data-testid="stChatMessage"] {
  background: transparent;
  border: none;
  padding: .55rem 0;
  gap: 0;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: var(--user);
  border-radius: 10px;
  padding: .7rem 1rem;
  margin-left: 14%;
}
[data-testid="stChatMessage"] p { line-height: 1.6; }

/* Tool progress and technical details */
[data-testid="stStatus"], [data-testid="stExpander"] {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
}
[data-testid="stCode"], [data-testid="stCode"] pre { background: var(--side); color: var(--ink); }

/* Composer */
[data-testid="stChatInput"] { border-radius: 10px; border: 1px solid var(--line); background: var(--paper); }
[data-testid="stChatInput"] textarea { color: var(--ink); }

/* Sidebar */
section[data-testid="stSidebar"] { background: var(--side); border-right: 1px solid var(--line); }
.side-title {
  font-family: var(--serif);
  font-weight: 600;
  font-size: 1.25rem;
  margin: .2rem 0 .8rem;
  padding: 0;
  color: var(--ink);
}
.side-note { color: var(--muted); font-size: .8rem; line-height: 1.5; margin: 1rem 0 0; }

@media (max-width: 640px) {
  .block-container { padding-top: 1.2rem; }
  .desk-title { font-size: 1.6rem; }
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { margin-left: 0; }
}
"""

# ---------------------------------------------------------------- UI helpers
STEP_LABELS = {
    "calculator": "Calculating",
    "get_current_time": "Checking the time",
    "search_notes": "Searching notes",
    "list_departments": "Looking up departments",
    "check_availability": "Checking availability",
    "book_appointment": "Booking the appointment",
    "list_bookings": "Looking up bookings",
    "cancel_booking": "Cancelling the booking",
}


def step_text(name: str, args: dict | None) -> str:
    """One line describing a tool call, e.g. '**Checking availability** (cardiology, 2026-11-16)'."""
    label = STEP_LABELS.get(name, name.replace("_", " ").capitalize())
    detail = ", ".join(str(v) for v in (args or {}).values() if str(v).strip())
    return f"**{label}**" + (f" ({detail})" if detail else "")


def friendly_error(message: str) -> str:
    """Turn a raw SDK/gateway error into a sentence that says what to check."""
    m = message or ""
    low = m.lower()
    if "DeploymentNotFound" in m or "deployment for this resource does not exist" in low:
        return ("The model deployment wasn't found. Check that AOAI_DEPLOYMENT in .env matches "
                "a deployment name in your Azure OpenAI resource.")
    if "429" in m or ("token" in low and "limit" in low):
        return "The token limit was reached. Wait a minute, then try again."
    if "PermissionDenied" in m or "401" in m or "403" in m:
        return ("The gateway rejected the request. Check the subscription key and that the API "
                "Management identity has the Cognitive Services OpenAI User role.")
    if "404" in m:
        return ("The gateway couldn't find the API. Check AOAI_API_VERSION in .env and the API "
                "URL suffix in API Management.")
    if "stopped after" in low:
        return "The assistant took too many steps. Try rephrasing your request."
    if "connection" in low or "timed out" in low:
        return "Couldn't reach the gateway. Check APIM_GATEWAY_URL and your network connection."
    return "Something went wrong while contacting the model."


# ---------------------------------------------------------------------- page
st.set_page_config(page_title="Appointment desk", layout="centered")
st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

if "history" not in st.session_state:
    st.session_state.history = []   # raw messages including tool traffic (agent state)
    st.session_state.display = []   # what the page renders
    st.session_state.tokens = 0


def queue(text: str) -> None:
    st.session_state.queued = text


def reset() -> None:
    st.session_state.clear()


# ------------------------------------------------------------------ header
st.markdown(
    f'<h1 class="desk-title">{html.escape(ORG_NAME)} appointment desk</h1>'
    '<p class="desk-sub">Book, check or cancel a visit by chatting. '
    "Doctors and time slots shown here are demo data.</p>",
    unsafe_allow_html=True,
)

typed = st.chat_input("Ask about appointments")
prompt = typed or st.session_state.pop("queued", None)

# ----------------------------------------------------------- empty state
if not st.session_state.display and not prompt:
    st.markdown('<p class="starter-lead">Start with one of these, or type your own request below.</p>',
                unsafe_allow_html=True)
    for col, (label, text) in zip(st.columns(len(STARTERS)), STARTERS):
        col.button(label, on_click=queue, args=(text,), key=f"starter-{label}")

# ------------------------------------------------------------ conversation
for item in st.session_state.display:
    with st.chat_message(item["role"]):
        if item.get("steps"):
            with st.expander(f"Actions taken ({len(item['steps'])})"):
                for line in item["steps"]:
                    st.markdown(line)
        st.markdown(item["content"])

if prompt:
    st.session_state.display.append({"role": "user", "content": prompt})
    st.session_state.history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            agent = Agent()
        except KeyError as missing:
            st.error(f"Missing setting {missing}. Add it to the .env file next to app.py, "
                     "then restart the app.")
            st.stop()

        steps: list[str] = []
        final, error = "", None
        with st.status("Working on it", expanded=True) as status:
            for ev in agent.run(st.session_state.history):
                if ev["type"] == "tool_call":
                    steps.append(step_text(ev["name"], ev["args"]))
                    st.markdown(steps[-1])
                elif ev["type"] == "final":
                    final = ev["content"]
                    usage = ev["usage"]
                    st.session_state.tokens += usage["prompt"] + usage["completion"]
                elif ev["type"] == "error":
                    error = ev["message"]
            if error:
                status.update(label="Couldn't finish", state="error", expanded=False)
            elif steps:
                status.update(label=f"Done ({len(steps)} actions)", state="complete", expanded=False)
            else:
                status.update(label="Answered", state="complete", expanded=False)

        if error:
            final = friendly_error(error)
            st.error(final)
            with st.expander("Technical details"):
                st.code(error, language=None)
        else:
            st.markdown(final)

    st.session_state.display.append({"role": "assistant", "content": final, "steps": steps})

# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown('<h2 class="side-title">Appointment desk</h2>', unsafe_allow_html=True)
    st.button("New conversation", on_click=reset, key="reset")
    with st.expander("Connection details"):
        st.caption("Gateway")
        st.code(os.environ.get("APIM_GATEWAY_URL", "not set"), language=None)
        st.caption(f"Deployment: {os.environ.get('AOAI_DEPLOYMENT', 'not set')}")
        st.caption(f"API version: {os.environ.get('AOAI_API_VERSION', 'not set')}")
        st.caption(f"Tokens used this session: {st.session_state.tokens}")
    st.markdown(
        '<p class="side-note">For an emergency, call your local emergency number. '
        "This assistant can't give medical advice.</p>",
        unsafe_allow_html=True,
    )