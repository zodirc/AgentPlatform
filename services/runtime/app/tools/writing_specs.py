"""写作工具的说明与参数。与服务器 ``build_registry()`` 的同名工具保持一致。"""

from __future__ import annotations

import json

SPECS: dict[str, dict] = json.loads(r"""
{
  "read_file": {
    "description": "Read a file from the workspace (preferred over any shell paging). Omit limit unless the file is very large. Summary (complete) / whole_file_complete=true means the whole file is in hand — stop reading that path this Turn (runtime enforces this). Tail windows that reach EOF use (eof_from_offset), not (complete). If truncated=true, continue with next_offset only; code files also include an outline of defs/classes to navigate without blind paging. Never head/tail/sed/cat. Optional offset (1-based) / limit for large files. For manuscript.md / draft manuscript, pass section_id to load one chapter (default lists chapters only); set full=true only for whole-book review.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string"
        },
        "offset": {
          "type": "integer",
          "description": "1-based start line (default 1). Use next_offset from a truncated read to continue."
        },
        "limit": {
          "type": "integer",
          "description": "Max lines to return from offset. Omit to read until EOF or the char budget."
        },
        "section_id": {
          "type": "string",
          "description": "Chapter id inside monofile manuscript (e.g. ch3)"
        },
        "full": {
          "type": "boolean",
          "description": "Read entire manuscript (review only)"
        }
      },
      "required": [
        "path"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "list_dir": {
    "description": "List one directory's entries (names only). Use only for a specific subdirectory you already care about. Do NOT list '.' / repo root to tour the project — read the issue/problem.md and use goto_definition/grep/glob instead. For content search use grep — not list_dir.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "default": "."
        }
      }
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "grep": {
    "description": "Regex/search file contents for exact error strings, unique literals, or regex patterns. Bare symbol/class/function names are redirected to search_codebase (Locate via language server) — do not use this tool to bypass structural locate. Use glob for filenames; do not use shell find/rg.",
    "parameters": {
      "type": "object",
      "properties": {
        "pattern": {
          "type": "string"
        },
        "path": {
          "type": "string",
          "default": "."
        },
        "limit": {
          "type": "integer",
          "default": 50
        }
      },
      "required": [
        "pattern"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "glob": {
    "description": "Find files by glob pattern under a path (e.g. '**/*.py', 'src/**/test_*.ts'). Use when you need paths by name/extension. For content matches use grep; for symbol Locate use search_codebase.",
    "parameters": {
      "type": "object",
      "properties": {
        "pattern": {
          "type": "string"
        },
        "path": {
          "type": "string",
          "default": "."
        },
        "limit": {
          "type": "integer",
          "default": 100
        }
      },
      "required": [
        "pattern"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "rename_file": {
    "description": "Rename or move an existing workspace file (path → new_path). Use for rename-only requests; do NOT export, rewrite, or invent titles. Fails if destination exists unless overwrite=true. Seed corpus is read-only.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Current relative path"
        },
        "new_path": {
          "type": "string",
          "description": "Destination relative path (new name and/or folder)"
        },
        "overwrite": {
          "type": "boolean",
          "description": "Replace destination if it already exists",
          "default": false
        }
      },
      "required": [
        "path",
        "new_path"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "propose_patch": {
    "description": "Queue a surgical edit for UI diff / accept flow (writing / intel): old_text must be an exact unique span; new_text replaces only that span. The target path must already exist — this tool cannot create outline.md or drafts/; use update_outline / draft_section for new files. Does NOT modify the file by itself — status stays pending until apply_patch or user accept (writing may auto-apply). Prechecks applyability (unique span; git apply --check when the worktree is a git repo) and returns status=error with apply_check_error if it would not apply — re-read and retry, do not resend the same span. Not available in agent mode — use edit_file there.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string"
        },
        "old_text": {
          "type": "string"
        },
        "new_text": {
          "type": "string"
        },
        "summary": {
          "type": "string"
        },
        "fragment": {
          "type": "string",
          "enum": [
            "plot_progress",
            "worldview_texture",
            "climax_beat",
            "battle_action",
            "dialogue_dyad",
            "mixed"
          ],
          "description": "Scene fragment type for writing_signals on applied prose"
        }
      },
      "required": [
        "path",
        "old_text",
        "new_text"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "draft_section": {
    "description": "Draft or update a chapter. Creates drafts/ and the chapter file if they do not exist — an empty workspace is allowed; do not switch to chat delivery. Default monofile: upserts a marked block in drafts/manuscript.md (visible work-surface draft; append new chapters / replace same section_id). If the user asked for a new standalone piece (写一篇 / 写个故事, not 续写) and the file already holds another story, pass occupy=fresh on the first call this Turn (archives the old file to drafts/archive/, then writes only this story). Inferred from the user text when occupy is omitted. Pass layout=sections for one-file-per-chapter under drafts/. History stays under .agent/work/history/. Default visible length is 3000–5000 characters unless the user named another quota. If the scene's facts cannot fill that, go back to the chapter note. Do not mode=append a second scene to hit the number. narrative_commitment is optional and does not block the draft. Mechanical fixes (duplicated paragraphs, broken quotes, bad headings) may be patched. Style notes are suggestions and do not auto-apply.",
    "parameters": {
      "type": "object",
      "properties": {
        "section_id": {
          "type": "string"
        },
        "content": {
          "type": "string"
        },
        "fragment": {
          "type": "string",
          "enum": [
            "plot_progress",
            "worldview_texture",
            "climax_beat",
            "battle_action",
            "dialogue_dyad",
            "mixed"
          ],
          "description": "Scene fragment type for writing_signals weights"
        },
        "layout": {
          "type": "string",
          "enum": [
            "monofile",
            "sections"
          ],
          "description": "Override WRITING_MANUSCRIPT_MODE for this call"
        },
        "occupy": {
          "type": "string",
          "enum": [
            "upsert",
            "fresh"
          ],
          "description": "fresh: archive the occupied manuscript and write only this section. upsert: keep other chapters. Omit to infer from the user text (写一篇 vs 续写)."
        },
        "mode": {
          "type": "string",
          "enum": [
            "upsert",
            "append",
            "rewrite_window"
          ],
          "description": "append: continue the same scene. Do not open a second scene to reach a length. upsert: replace the chapter. rewrite_window: replace one already located span."
        },
        "narrative_commitment": {
          "type": "object",
          "description": "Optional. Not a gate. Slots: time_order, subplot, resolution_agency, moral_polarity, affect_mode, locations. Fill from what this chapter actually does.",
          "properties": {
            "time_order": {
              "type": "string",
              "enum": [
                "linear",
                "open_in_media_res",
                "mid_flashback",
                "retold_recontext"
              ]
            },
            "subplot": {
              "type": "string",
              "enum": [
                "none",
                "parallel_theme",
                "interleaved"
              ]
            },
            "resolution_agency": {
              "type": "string",
              "enum": [
                "protagonist_choice",
                "external_force",
                "accident",
                "another_person",
                "unresolved"
              ]
            },
            "moral_polarity": {
              "type": "string",
              "enum": [
                "clear",
                "ambivalent"
              ]
            },
            "affect_mode": {
              "type": "string",
              "enum": [
                "embodied",
                "named",
                "mixed"
              ]
            },
            "locations": {
              "type": "string",
              "enum": [
                "1",
                "2+"
              ]
            }
          }
        },
        "choices": {
          "type": "object",
          "description": "Optional self-report of this chapter's choices (same slots as narrative_commitment). Author regime does not reject on quota.",
          "properties": {
            "time_order": {
              "type": "string",
              "enum": [
                "linear",
                "open_in_media_res",
                "mid_flashback",
                "retold_recontext"
              ]
            },
            "subplot": {
              "type": "string",
              "enum": [
                "none",
                "parallel_theme",
                "interleaved"
              ]
            },
            "resolution_agency": {
              "type": "string",
              "enum": [
                "protagonist_choice",
                "external_force",
                "accident",
                "another_person",
                "unresolved"
              ]
            },
            "moral_polarity": {
              "type": "string",
              "enum": [
                "clear",
                "ambivalent"
              ]
            },
            "affect_mode": {
              "type": "string",
              "enum": [
                "embodied",
                "named",
                "mixed"
              ]
            },
            "locations": {
              "type": "string",
              "enum": [
                "1",
                "2+"
              ]
            }
          }
        },
        "wild_card": {
          "type": "boolean",
          "description": "Strict regime only. Once per 5 chapters: this chapter may do something an editor would refuse. L1 observations are silenced."
        },
        "swerve": {
          "type": "boolean",
          "description": "Author regime: record a narrative debt on this chapter. No quota. Later chapters should show a consequence."
        },
        "outcomes": {
          "type": "array",
          "description": "Chapter results. Each item needs text and evidence that appears in content. Unmatched evidence is not stored.",
          "items": {
            "type": "object",
            "properties": {
              "text": {
                "type": "string"
              },
              "evidence": {
                "type": "string"
              },
              "subject": {
                "type": "string"
              },
              "constrains_next": {
                "type": "boolean"
              }
            },
            "required": [
              "text",
              "evidence"
            ]
          }
        },
        "plan_deviation": {
          "type": "string",
          "description": "How the prose left the chapter note. Diagnostic only; not written into canon."
        }
      },
      "required": [
        "section_id",
        "content"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "update_outline": {
    "description": "Create or update the outline. content still writes outline.md. documents writes work, volume, and chapter files in one commit without splitting a mixed markdown blob. Prefer mode=append for long outlines; replace requires the full target text (or force=true).",
    "parameters": {
      "type": "object",
      "properties": {
        "content": {
          "type": "string"
        },
        "scope": {
          "type": "string",
          "enum": [
            "work",
            "volume",
            "chapter"
          ]
        },
        "section_id": {
          "type": "string"
        },
        "volume_index": {
          "type": "integer"
        },
        "documents": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "scope": {
                "type": "string",
                "enum": [
                  "work",
                  "volume",
                  "chapter"
                ]
              },
              "content": {
                "type": "string"
              },
              "mode": {
                "type": "string",
                "enum": [
                  "replace",
                  "append"
                ]
              },
              "section_id": {
                "type": "string"
              },
              "volume_index": {
                "type": "integer"
              }
            },
            "required": [
              "scope",
              "content"
            ]
          }
        },
        "mode": {
          "type": "string",
          "enum": [
            "replace",
            "append"
          ],
          "default": "replace"
        },
        "force": {
          "type": "boolean",
          "description": "Allow replace that shrinks a large existing outline"
        },
        "volume": {
          "type": "object",
          "description": "Optional volume-question structure rendered as ## 卷 N. Syncs must_not_decide_yet into deferred and promises_due into promises.",
          "properties": {
            "index": {
              "type": "integer"
            },
            "chapters": {
              "type": "string"
            },
            "questions": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "must_not_decide_yet": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "promises_due": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "where_it_stands": {
              "type": "string"
            }
          }
        }
      }
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "propose_book_candidates": {
    "description": "Trigger sampling of 2 long-form web novels for the user to choose from. Pass empty items. Do not invent titles or pitches in this context; the tool samples each book independently, then compresses each into a working title plus a book-page pitch. Use when the user only gave a genre/direction or said 看看 / 我要其他的. The picker is the deliverable; do not list the candidates in chat.",
    "parameters": {
      "type": "object",
      "properties": {
        "items": {
          "type": "array",
          "minItems": 0,
          "maxItems": 3,
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "type": "string"
              },
              "title": {
                "type": "string",
                "description": "工作书名，二到八字。它是这本作品的名字，不要求出现在简介中。"
              },
              "pitch": {
                "type": "string",
                "description": "书页简介，约100–220字。是这本书的介绍，没有固定写法，不是构思过程，也不是第一章。"
              }
            },
            "required": [
              "title",
              "pitch"
            ]
          }
        }
      }
    },
    "requires_approval": false,
    "timeout_s": 600.0
  },
  "update_plan": {
    "description": "Update the visible turn plan / todo checklist. Call when starting a multi-step task and again whenever a step begins (status=in_progress) or finishes (status=done|completed). Replace the full items list each time so the UI stays accurate. During Plan executing phase, skipping status updates is a failure.",
    "parameters": {
      "type": "object",
      "properties": {
        "items": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "type": "string"
              },
              "title": {
                "type": "string"
              },
              "status": {
                "type": "string",
                "enum": [
                  "pending",
                  "in_progress",
                  "done",
                  "completed",
                  "cancelled"
                ]
              }
            }
          }
        },
        "summary": {
          "type": "string"
        }
      },
      "required": [
        "items"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "search_sources": {
    "description": "Hybrid search over workspace sources/ (BM25 + vector). Library layout (narrow with path_prefix when the type is known): sources/seed/writing/{persons,periods,dramas,novels,movie}/ for standing writing fact corpus; sources/seed/intel/{_demo,vendor,ioc}/ for threat-intel lab notes / ATT&CK / galaxy cards (vendor may be empty until `make intel-corpus-fetch`); sources/cards/ is pinned style/character material — do not search cards here; user uploads may appear under other sources/ trees (e.g. hr/, legal/, writing/). Prefer read_file when the source path is known. Optional path_prefix narrows to a subdirectory under sources/ (e.g. 'seed/writing/dramas', 'seed/intel', 'hr', or 'sources/hr'); rejects '..' / absolute paths. When omitted, ScenarioProfile may apply a default prefix (intel → seed/intel). Original fiction (立一个故事, no named drama/film): prefer path_prefix 'seed/writing/periods' for texture; do not imitate drama 主线剧情. First search: pass the user's information need / claim nearly verbatim as `query` (same wording and order). Do NOT compress into a keyword bag or synonym rewrite on the first call — hybrid search already handles phrasing. Default: at most **two** searches per topic (verbatim first; optional one rephrase). If the first call returns any on-topic paths, stop searching and `read_file` the top hits — do not burn the remaining budget on synonym cascades. A second search is only for clearly empty / off-topic first hits; keep distinctive entities. Prefer a larger limit (e.g. 30–100) when you need broad recall. Do not invent documents. For content questions, call this before list_dir inventory.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Search text. First call: copy the user's information need nearly verbatim. At most one follow-up rephrase if hits were empty/off-topic; otherwise read_file top paths instead of searching again."
        },
        "limit": {
          "type": "integer",
          "default": 30
        },
        "path_prefix": {
          "type": "string",
          "description": "Optional directory under sources/ to restrict search. Relative path; 'seed/writing/persons' or 'hr' means that tree. Original fiction: 'seed/writing/periods'. Omit to use ScenarioProfile default when configured (intel defaults to seed/intel). No '..' or absolute paths."
        }
      },
      "required": [
        "query"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "check_citation": {
    "description": "Verify that a citation_id appears in / is supported by the given source file. Use after drafting with [cite:…] markers; do not invent citations.",
    "parameters": {
      "type": "object",
      "properties": {
        "citation_id": {
          "type": "string"
        },
        "source_path": {
          "type": "string"
        }
      },
      "required": [
        "citation_id",
        "source_path"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "export_document": {
    "description": "Export an explicit ordered set of sections into one markdown file. Use current_draft for this turn's drafts or confirmed for accepted sections.",
    "parameters": {
      "type": "object",
      "properties": {
        "section_ids": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "minItems": 1
        },
        "source": {
          "type": "string",
          "enum": [
            "confirmed",
            "current_draft"
          ],
          "default": "current_draft"
        },
        "output_path": {
          "type": "string",
          "default": "exports/document.md"
        },
        "profile": {
          "type": "string",
          "enum": [
            "novel-zh",
            "essay",
            "none"
          ],
          "default": "novel-zh",
          "description": "Export structure lint profile (docs/14 D6)"
        }
      },
      "required": [
        "section_ids"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "remember": {
    "description": "Store a preference or durable note in a separate memory namespace (not the sources RAG index). Call only when the user asks to remember.",
    "parameters": {
      "type": "object",
      "properties": {
        "text": {
          "type": "string"
        },
        "namespace": {
          "type": "string",
          "default": "prefs",
          "description": "Logical bucket such as prefs|style|project"
        },
        "importance": {
          "type": "number",
          "default": 0.5
        }
      },
      "required": [
        "text"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "recall": {
    "description": "On-demand recall from memory namespaces. Do not call every turn — only when preferences/past notes are relevant.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string"
        },
        "namespace": {
          "type": "string",
          "default": "prefs"
        },
        "limit": {
          "type": "integer",
          "default": 5
        }
      },
      "required": [
        "query"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "forget": {
    "description": "Delete a remembered note by id or substring query in a namespace.",
    "parameters": {
      "type": "object",
      "properties": {
        "memory_id": {
          "type": "string",
          "default": ""
        },
        "query": {
          "type": "string",
          "default": ""
        },
        "namespace": {
          "type": "string",
          "default": "prefs"
        }
      }
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "load_skill": {
    "description": "Load a skill pack (delegate, memory, verify) into volatile context. Does not change tools[] schema bytes.",
    "parameters": {
      "type": "object",
      "properties": {
        "name": {
          "type": "string",
          "description": "Pack stem: delegate|memory|verify"
        }
      },
      "required": [
        "name"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "delegate": {
    "description": "Delegate a sub-task to a specialized sub-agent. Prefer context_refs/paths over pasting large text into context. For dependent follow-ups, pass prior artifact_refs / artifacts/collab/ paths. Result may include artifact_refs for the next handoff.",
    "parameters": {
      "type": "object",
      "properties": {
        "task": {
          "type": "string"
        },
        "agent_type": {
          "type": "string",
          "default": "explore"
        },
        "context": {
          "type": "string",
          "default": "",
          "description": "Short optional notes; keep brief. Prefer context_refs for files."
        },
        "context_refs": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "Workspace-relative file paths the sub-agent should read (handoff / shared blackboard)"
        },
        "paths": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "Alias of context_refs"
        },
        "wait": {
          "type": "boolean",
          "default": true,
          "description": "If false, still joins this child in the current batch; pair with a sibling readonly delegate for parallel wait/join."
        }
      },
      "required": [
        "task"
      ]
    },
    "requires_approval": true,
    "timeout_s": 300.0
  },
  "author_state": {
    "description": "Maintain this book's first-person author notebook (stance / doubt / want-to-try / regret / deferred). Not a summary. Not scored. reread_note is only writable on a reread turn.",
    "parameters": {
      "type": "object",
      "properties": {
        "section": {
          "type": "string",
          "enum": [
            "我现在怎么看这本书",
            "我在疑心什么",
            "我想试什么",
            "我后悔什么",
            "我故意还不决定的事",
            "回读记",
            "立场",
            "疑心",
            "想试",
            "后悔",
            "悬置"
          ]
        },
        "text": {
          "type": "string"
        },
        "mode": {
          "type": "string",
          "enum": [
            "replace",
            "append"
          ],
          "default": "replace"
        }
      },
      "required": [
        "section",
        "text"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "reread_book": {
    "description": "Reread-phase only. Return a budgeted pack of original prose (not a synopsis): opening, user taste marks, overdue promises, volume tail, editor flags. No scores.",
    "parameters": {
      "type": "object",
      "properties": {}
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "propose_retcon": {
    "description": "Reread-phase only. Propose earlier-chapter patches as a pending list. Does not write the manuscript. Stops the turn until the user confirms. Then each item is applied via propose_patch.",
    "parameters": {
      "type": "object",
      "properties": {
        "items": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "ch": {
                "type": "string"
              },
              "old_text": {
                "type": "string"
              },
              "new_text": {
                "type": "string"
              },
              "why": {
                "type": "string"
              }
            },
            "required": [
              "ch",
              "old_text",
              "new_text"
            ]
          }
        }
      },
      "required": [
        "items"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "editor_report": {
    "description": "Editor-phase only. Typed flags that protect the book. Never edits prose. evidence must not contain should/please/change-to/must/remember. keep: up to 3 passages that ARE this book.",
    "parameters": {
      "type": "object",
      "properties": {
        "section_id": {
          "type": "string"
        },
        "flags": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "type": {
                "type": "string",
                "enum": [
                  "continuity_break",
                  "promise_overdue",
                  "identity_drift",
                  "reader_confusion",
                  "author_state_stale",
                  "surface_observation"
                ]
              },
              "where": {
                "type": "string"
              },
              "evidence": {
                "type": "string"
              },
              "severity": {
                "type": "string",
                "enum": [
                  "hard",
                  "soft",
                  "info"
                ]
              }
            },
            "required": [
              "type",
              "evidence"
            ]
          }
        },
        "keep": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "maxItems": 3
        }
      },
      "required": [
        "section_id"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  },
  "propose_chapter_openings": {
    "description": "When the user asks to see two openings for this chapter, submit exactly 2 items with title + opening (≤600 visible chars). UI picker is the deliverable; do not list them in chat. Default off.",
    "parameters": {
      "type": "object",
      "properties": {
        "items": {
          "type": "array",
          "minItems": 2,
          "maxItems": 2,
          "items": {
            "type": "object",
            "properties": {
              "title": {
                "type": "string"
              },
              "opening": {
                "type": "string"
              }
            },
            "required": [
              "title",
              "opening"
            ]
          }
        },
        "summary": {
          "type": "string"
        }
      },
      "required": [
        "items"
      ]
    },
    "requires_approval": false,
    "timeout_s": 60.0
  }
}
""")
