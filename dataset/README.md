# Dataset directory

Project data and generated data artifacts live here:

- `databases/`: local SQLite databases
- `spreadsheets/`: source data and ontology workbooks
- `graphs/`: generated or maintained graph-library files
- `charts/`: generated standalone chart pages
- `conversations/`: persisted BI conversation history
- `uploaded_reports/`: runtime report uploads and parsed metadata
- `documents/`: source/demo business documents
- `logs/`: local runtime logs

Application code should use the shared paths in `bi_agent.paths` instead of
hard-coding these directories.
