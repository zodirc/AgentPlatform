## Opening choice (platform)
This turn is a Plan-like picker. Call `propose_opening_ponds` once with 2–3 items.
Leave the assistant message empty; the cards are the deliverable.
Each item needs title, flavor (这本书), opening, start_kind, promise,
price_axis, source_trust, first_conflict_at.
The UI card the user reads is only: 书名 / 这本书 / 开篇.
Do not split a book into 账单 / 走向 / 气味.
Do not list the ponds in the assistant message. Do not call draft_section or
update_outline. The user checks a card (no chat bubble) or 我要其他的.

title = 连载书名, the name of the game that still holds at chapter 400.
Not a lyrical sketch. Not a finite stack of props.
flavor = 这本书: who you follow on the board + the unfair rule of this world,
in a few sentences. The book is the game, not the invoice.
opening = how THAT game starts tonight. First sentence is the accident
（第一句写事故）.
opening and 这本书 are the same book.
who/where/want are optional and only if they are already inside 这本书/开篇.

start_kind (required, unique): self_notice | pulled_in | granted_path |
world_already | no_extraordinary
price_axis (required, unique): lifespan | memory | contract | status | none
Who pays, not the workplace. After 我要其他的, do not reuse previous price_axis.
promise (required, not all identical): power_steps | costly_truth |
survive_relation | dread_decode | social_place
source_trust (required): trusted | dubious | false. At least one of three must
not be trusted.
first_conflict_at (required): first_300 | first_1000 | chapter_one | later.
At most one later.
price and arc are optional leftovers; do not write them as the card.

Handler rejects missing fields, duplicate start_kind, duplicate price_axis,
all-same promise, reused previous start_kinds / price_axis (only after
我要其他的), all-trusted source_trust (items≥3), more than one later,
过日子 over quota, slot-honesty misses, or a set too close to the ledger.
修真/玄幻: at least one of self_notice / pulled_in / granted_path.
Change a narrative decision, not the skin.
First sentence is the accident. One in-turn repair is allowed; a second
reject stops the turn. Do not write a unifying summary.
Novelty is the game played straight. Different start_kind is not a different
book if the engine is the same.
Opening is at most two sentences.
world_already = ability-users already live among people.
granted_path = 系统/金手指落到身上。
no_extraordinary = 这一章先过班、房租、家里的日子，超凡往后放。
At least one book should put a concrete ability on a person; the fight is
other people, not repairing a city.
凡人流/都市修真: pulled_in is a normal opening. Do not invent new start_kind
names. Change who pays and what they pay, not the workplace.
