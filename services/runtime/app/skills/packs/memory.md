# Memory remember / recall / forget

`remember` stores user preferences and notes per Work. Namespaces: prefs, style, project. Do not dump `search_sources` excerpts into memory; retrieval stays in `search_sources`. Explicit `trust=retrieved` is rejected. Namespaces `sources`/`rag` are reserved.

`recall` is on-demand; do not call every turn.

`forget` deletes by id or by query in a namespace. Session-scope rows are invisible to other sessions.

Memory is not `search_sources`.
