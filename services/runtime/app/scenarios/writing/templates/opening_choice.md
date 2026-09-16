## Book choice

This turn only triggers sampling. Call `propose_book_candidates` once with empty `items`.
Do not invent the two books in this context. The tool samples each book in a fresh context.

Leave the assistant message empty; the cards are the deliverable.
Do not call `draft_section` or `update_outline`.
Do not list the candidates in chat.

Stay inside the genre the user named.
不要把简介写成第一章。

工具内部各自形成一本书，再压成 `title` + `pitch`。
不要在这一轮聊天里构思两本，也不要为了互相不同去换职业、地点或道具。

用户选中的是这一本作品。后续从这本继续。
