# Saved changes reconciliation — September 21, 2026

The four saved stashes were reviewed oldest first. Clean June and July changes
were published in `cc94923` and `197defb`; the remaining decisions are recorded here.

| Area | Resolution |
|------|------------|
| 27 productivity notes | Keep current notes. Original Slack text is identical; old generated metadata is superseded. Notion remains authoritative for mirrored task properties. |
| Obsidian workspace | Keep the local layout and stop tracking only `.obsidian/workspace.json`. Keep app/plugin configuration versioned. |
| Requirements | Retain MCP; restore Google OAuth and newsletter UI/rendering dependencies used by existing code. Local Whisper remains an optional installation, as before. |
| Whisper | Preserve current chunking, temporary cleanup, logging, GPU DLL discovery and CPU fallback. Recover language/model options, configurable timeout, environment chunking defaults and empty/oversized chunk checks. Default request timeouts remain 120 seconds for a single file and 300 seconds per chunk unless overridden. |
| Knowledge extraction | Restore `build_knowledge_llm_config`, still imported by the extraction script, alongside the current editorial helper. |
| Research notes | Recover unique additions from the old `Temas/Alimentos.md` and `Temas/Guerra.md` paths into `40_News/Temas/`. Do not recreate obsolete folders. |
| YouTube listing | Keep the already merged June implementation, including bounded/all-page retrieval. July largely rewrites the same behavior. |
| September topic search | Keep current shared `src/embeddings/query.py`; it already contains the saved retrieval/prompt features. Do not reintroduce duplicated inline implementations. |
| Documentation and configuration | Keep current SMTP2GO/editorial documentation and current ignore rules. Retain scheduler-wrapper guidance and useful transcription environment options. Do not restore old Postmark defaults or ignore all podcast project files. |
| June saved untracked files | All 84 paths already exist: 32 identical, 52 changed. Keep current repaired transcripts, processing state and newer video/caption code rather than reverting to old exports and parsers. |

Verification uses offline mocked transcription tests, plus existing project tests.
No live transcription requests or Notion mutations are needed for this reconciliation.
