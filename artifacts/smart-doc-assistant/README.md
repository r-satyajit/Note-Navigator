# Notes Navigator

Upload PDF and TXT files, ask questions in the chat, and expand the source panel
under each answer to see the exact passages retrieved from the documents.

## Gemini API key

In Replit, open **Tools → Secrets** and add `GEMINI_API_KEY`. The app also accepts
`GOOGLE_API_KEY` as a fallback. Do not put the key in `app.py`, commit it to
source control, or paste it into chat.

## Run locally

From this directory, install the dependencies and start Streamlit:

```bash
python -m pip install -r requirements.txt
streamlit run app.py --server.port 5000
```

The app uses LangChain loaders and text splitting, Gemini embeddings, an
in-memory FAISS index, and Gemini Flash for answers. The index and conversation
are session-only and are cleared when the app process restarts.
