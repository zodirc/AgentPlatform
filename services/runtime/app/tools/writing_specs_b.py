"""写作工具说明的一部分。由 writing_specs 合并。"""

from __future__ import annotations

RAW = r'''
{
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
'''
