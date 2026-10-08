---
name: Streamlit preview capture timing
description: A transient blank screenshot can occur while a restarted Streamlit app is still connecting its frontend.
---

If a Streamlit preview screenshot is blank while the managed workflow is running and the app endpoint returns HTTP 200, the capture may have happened before the browser finished connecting. Check fresh logs, wait for the page to settle, and retry one screenshot before changing application code.

**Why:** The first capture after a restart or concurrent viewport captures intermittently showed a blank frame despite a healthy workflow; a later single capture rendered normally.

**How to apply:** Treat a blank capture as inconclusive until workflow logs and an HTTP check are reviewed. Retry once after settling rather than debugging the app prematurely.
