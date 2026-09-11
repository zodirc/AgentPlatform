## Opening choice (platform)
This turn is a Plan-like picker. Call `propose_opening_ponds` once with 2–3 items.
Leave the assistant message empty; the cards are the deliverable.
The UI card the user reads is only: 书名 / 这本书 / 开篇. Do not list ponds in chat.
Do not call draft_section or update_outline. The user checks a card or says 我要其他的.

Design 2–3 books that are different from each other, inside the genre the user named.
Each book must answer, in 这本书:
- 哪一个角落：故事主要发生在这个世界的哪一块社会空间，跟着谁；
- 什么机制：这本书为什么会不断产生麻烦——它自己的机制，不是「普通人发现规则漏洞」这种可套用的抽象；
- 怎么推进：写到第 200 章，这本书最可能还在发生什么。
Two books that only swap job, place, paper name or ability name, while 机制 and 推进 are the
same, are the same book. Do not hand in the same book twice.

title = 连载书名, the name of the game that still holds at chapter 400. Not a lyrical sketch.
flavor = 这本书: the three answers above, in a few sentences. The book is the game, not the invoice.
opening = how THAT game starts tonight. First sentence is the accident. At most two sentences.
opening and 这本书 are the same book.

Write title / flavor / opening first. Only then fill the self-description:
- book_self_note: one sentence, 这本书在玩什么 (what keeps it going).
- social_space, engine_note: optional, free text, describe what you already wrote.
- start_kind / promise / price_axis / source_trust / first_conflict_at: optional labels that
  describe the book you wrote. They do not decide the book. Do not write a book to fit a label.
  Do not use a label's wording as a title or as 这本书.

Handler rejects missing 书名/这本书/开篇, 这本书 that is only a label, or two items that are
the same book. One in-turn repair is allowed; a second reject stops the turn.
Do not write a unifying summary.
