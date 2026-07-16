# Upload AI Master Pro without terminal commands

The ChatGPT GitHub connector can inspect this repository but currently receives
HTTP 403 for repository writes. Use GitHub Desktop for the one-time initial
upload; future source changes can still be reviewed here.

1. Install and sign in to GitHub Desktop.
2. Choose **File → Clone repository → URL**.
3. Enter `https://github.com/wwwmrtayyab1234-dot/Ai-master-pro.git`.
4. Choose a simple local path such as `D:\AMP_GITHUB\Ai-master-pro` and clone.
5. Extract `AI_Master_Pro_GitHub_Ready.zip`.
6. Copy the extracted folder contents into the cloned `Ai-master-pro` folder.
   `main.py`, `.github`, `services`, `assets`, and `pyproject.toml` must be at
   the repository root; do not copy the outer folder itself.
7. Return to GitHub Desktop. Enter summary `Upload AI Master Pro MVP`.
8. Click **Commit to main**, then **Push origin**.
9. Create the nine repository secrets before running the Android workflow.

Never upload `.env`, `.venv`, `build`, `release`, database files, or API keys.
