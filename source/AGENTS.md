# Codex Working Rules

- Minimize token and context usage.
- Read only files relevant to the current task.
- Search for filenames, symbols, and functions before opening files.
- Do not recursively inspect dependency or build directories unless required.
- Ignore node_modules, .venv, venv, vendor,
  dist, build, bin, obj, __pycache__, .git
  and generated files unless directly relevant.
- Avoid reading large binary files, datasets,
  archives and logs.
- Make minimal changes without unrelated refactoring.
- Run targeted tests and necessary validation.
- Keep the final response concise.