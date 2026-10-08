import streamlit as st


def apply_aurora_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            color-scheme: dark;
            --nn-bg: #090c12;
            --nn-panel: #131b2e;
            --nn-panel-raised: #1a233a;
            --nn-line: #29344a;
            --nn-text: #f3f4f6;
            --nn-body: #a0aec0;
            --nn-muted: #75839a;
            --nn-cyan: #06b6d4;
            --nn-blue: #3b82f6;
            --nn-indigo: #6366f1;
            background: var(--nn-bg);
            color: var(--nn-text);
            font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
                "Segoe UI", sans-serif;
        }
        html, body, #root {
            min-height: 100%;
            background: #090c12 !important;
        }
        .stApp [data-testid="stAppViewContainer"] {
            background: var(--nn-bg);
            color: var(--nn-text);
            background-image:
                radial-gradient(ellipse 42rem 25rem at 88% 0%, rgba(59, 130, 246, .12), transparent 72%),
                radial-gradient(ellipse 30rem 20rem at 8% 3%, rgba(6, 182, 212, .08), transparent 72%),
                linear-gradient(180deg, #0d1117 0%, #090c12 34rem);
        }
        .stApp [data-testid="stHeader"] { background: transparent; }
        .stApp [data-testid="stMainBlockContainer"] {
            max-width: 1180px;
            padding-top: 2.7rem;
            padding-bottom: 4rem;
        }
        .stApp [data-testid="stSidebar"] {
            background: #0d121d;
            border-right: 1px solid var(--nn-line);
        }
        .stApp [data-testid="stSidebar"] > div:first-child { padding-top: 1.5rem; }
        .stApp h1, .stApp h2, .stApp h3,
        .stApp [data-testid="stMarkdownContainer"] strong {
            color: var(--nn-text);
            letter-spacing: -.025em;
        }
        .stApp p, .stApp li, .stApp [data-testid="stCaptionContainer"] {
            color: var(--nn-body);
            line-height: 1.65;
        }
        .nn-kicker {
            color: #67d9ed;
            font-size: .72rem;
            font-weight: 700;
            letter-spacing: .16em;
            text-transform: uppercase;
            margin-bottom: .85rem;
        }
        .nn-title {
            color: var(--nn-text);
            font-size: clamp(2.2rem, 5vw, 3.35rem);
            line-height: 1.03;
            font-weight: 680;
            letter-spacing: -.055em;
            margin: 0;
        }
        .nn-subtitle {
            max-width: 690px;
            color: var(--nn-body);
            font-size: 1rem;
            line-height: 1.7;
            margin: .9rem 0 1.5rem;
        }
        .nn-section-label {
            color: #8ba2bd;
            font-size: .75rem;
            font-weight: 700;
            letter-spacing: .11em;
            text-transform: uppercase;
            margin: .65rem 0 .35rem;
        }
        .nn-library-stat {
            display: flex;
            align-items: baseline;
            gap: .55rem;
            padding: .35rem 0 .15rem;
        }
        .nn-library-stat-number {
            color: #a7eff7;
            font-size: 1.5rem;
            font-weight: 700;
            letter-spacing: -.04em;
        }
        .nn-library-stat-label {
            color: var(--nn-muted);
            font-size: .74rem;
            font-weight: 650;
            letter-spacing: .08em;
            text-transform: uppercase;
        }
        .stApp [data-testid="stFileUploader"] section,
        .stApp [data-testid="stChatInput"] > div,
        .stApp [data-testid="stExpander"],
        .stApp [data-testid="stAlert"],
        .stApp [data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid var(--nn-line);
            border-radius: 12px;
            background: var(--nn-panel);
        }
        .stApp [data-testid="stFileUploader"] section {
            transition: border-color .18s ease, background-color .18s ease;
        }
        .stApp [data-testid="stFileUploader"] section:hover {
            border-color: #3d5c7b;
            background: #172238;
        }
        .stApp [data-testid="stFileUploader"] button,
        .stApp [data-testid="stChatInput"] button {
            border: 0;
            background: linear-gradient(120deg, var(--nn-cyan), var(--nn-blue) 58%, var(--nn-indigo));
            color: #07111c;
            font-weight: 700;
        }
        .stApp [data-testid="stFileUploader"] button:hover,
        .stApp [data-testid="stChatInput"] button:hover {
            filter: brightness(1.1);
            color: #07111c;
        }
        .stApp [data-testid="stFileUploader"] [data-testid="stTooltipIcon"],
        .stApp [data-testid="stFileUploader"] [data-testid="stTooltipIcon"] button {
            background: transparent !important;
            background-color: transparent !important;
            border-color: transparent !important;
            box-shadow: none !important;
            color: var(--nn-muted) !important;
        }
        .stApp [data-testid="stFileUploader"] [data-testid="stTooltipIcon"] svg {
            background: transparent !important;
            color: var(--nn-muted) !important;
            fill: currentColor !important;
            filter: none;
        }
        .stApp [data-testid="stFileUploader"] [data-testid="stTooltipIcon"]:hover,
        .stApp [data-testid="stFileUploader"] [data-testid="stTooltipIcon"]:hover button {
            background: transparent !important;
            color: #91a0b4 !important;
            text-shadow: 0 0 6px rgba(6, 182, 212, .42);
        }
        .stApp [data-testid="stFileUploader"] [data-testid="stTooltipIcon"]:hover svg {
            color: #91a0b4 !important;
            filter: drop-shadow(0 0 3px rgba(6, 182, 212, .48));
        }
        .stApp [data-testid="stFileUploader"] small,
        .stApp [data-testid="stFileUploader"] [data-testid*="DropzoneInstructions"] {
            color: var(--nn-body) !important;
            opacity: 1 !important;
        }
        .stApp [data-testid="stFileUploader"] section *:not(button):not(button *) {
            color: var(--nn-body) !important;
            opacity: 1 !important;
        }
        .stApp [data-testid="stChatInput"] > div:focus-within {
            border-color: var(--nn-cyan);
            box-shadow: 0 0 0 1px rgba(6, 182, 212, .22);
        }
        .stApp [data-testid="stChatInput"] textarea,
        .stApp [data-testid="stTextInput"] input {
            color: var(--nn-text);
        }
        .stApp [data-testid="stChatInput"] textarea::placeholder {
            color: #91a0b4;
            opacity: 1;
        }
        .stApp [data-testid="stButton"] button,
        .stApp [data-testid="stFormSubmitButton"] button {
            border: 1px solid #2a3850;
            border-radius: 9px;
            background: #151e30;
            color: #d9e3f0;
            font-weight: 600;
            transition: border-color .18s ease, background-color .18s ease,
                transform .18s ease;
        }
        .stApp [data-testid="stButton"] button:hover,
        .stApp [data-testid="stFormSubmitButton"] button:hover {
            border-color: #38758d;
            background: #1b2b40;
            color: #f3f4f6;
            transform: translateY(-1px);
        }
        .stApp [data-testid="stChatMessage"] {
            border: 1px solid rgba(41, 52, 74, .82);
            border-radius: 12px;
            background: rgba(19, 27, 46, .64);
            padding: .65rem 1rem;
            margin-bottom: .75rem;
        }
        .stApp [data-testid="stText"] pre {
            color: #d3deeb;
            line-height: 1.65;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }
        .stApp [data-testid="stExpander"] summary:hover { color: #67d9ed; }
        .stApp [data-testid="stSpinner"] svg {
            filter: drop-shadow(0 0 5px rgba(6, 182, 212, .38));
        }
        .stApp hr { border-color: var(--nn-line); }
        .stApp [data-testid="stHorizontalBlock"] { gap: .6rem; }
        @media (max-width: 767px) {
            .stApp [data-testid="stMainBlockContainer"] {
                padding: 2rem 1rem 3rem;
            }
            .nn-title { font-size: 2.35rem; }
            .nn-subtitle { font-size: .96rem; margin-bottom: 1.25rem; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                scroll-behavior: auto !important;
                transition-duration: .01ms !important;
                animation-duration: .01ms !important;
                animation-iteration-count: 1 !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
