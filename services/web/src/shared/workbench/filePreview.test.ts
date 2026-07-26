import { describe, expect, it } from "vitest";

import { previewText, writePreviewFromApprovalPayload, writePreviewFromTimeline } from "./filePreview";

describe("previewText", () => {
  it("truncates long content", () => {
    const long = "x".repeat(9000);
    const result = previewText(long, { charLimit: 8000, lineLimit: 500 });
    expect(result.truncated).toBe(true);
    expect(result.text.length).toBeLessThan(9000);
    expect(result.totalChars).toBe(9000);
  });

  it("keeps short content intact", () => {
    const result = previewText("hello\nworld");
    expect(result.truncated).toBe(false);
    expect(result.text).toBe("hello\nworld");
    expect(result.totalLines).toBe(2);
  });
});

describe("writePreviewFromApprovalPayload", () => {
  it("builds edit_file span diff from arguments", () => {
    const preview = writePreviewFromApprovalPayload({
      tool_name: "edit_file",
      arguments: {
        path: "src/a.py",
        old_text: "foo",
        new_text: "bar",
      },
    });
    expect(preview).not.toBeNull();
    expect(preview?.kind).toBe("edit_file");
    expect(preview?.path).toBe("src/a.py");
    expect(preview?.old_text).toBe("foo");
    expect(preview?.new_text).toBe("bar");
  });

  it("builds write_file preview from content + old_text", () => {
    const preview = writePreviewFromApprovalPayload({
      tool_name: "write_file",
      path: "a.txt",
      old_text: "old",
      new_text: "new",
    });
    expect(preview?.kind).toBe("write_file");
    expect(preview?.old_text).toBe("old");
    expect(preview?.new_text).toBe("new");
  });
});

describe("writePreviewFromTimeline", () => {
  it("matches file_write artifact by tool_call_id", () => {
    const preview = writePreviewFromTimeline(
      { tool_name: "edit_file", tool_call_id: "tc-1" },
      [
        {
          type: "file_write",
          tool_call_id: "tc-1",
          tool_name: "edit_file",
          kind: "edit_file",
          path: "a.py",
          old_text: "a",
          new_text: "b",
          status: "applied",
        },
      ],
    );
    expect(preview?.kind).toBe("edit_file");
    expect(preview?.old_text).toBe("a");
    expect(preview?.new_text).toBe("b");
  });

  it("returns null when no matching artifact", () => {
    expect(
      writePreviewFromTimeline({ tool_name: "edit_file", tool_call_id: "x" }, []),
    ).toBeNull();
  });
});
