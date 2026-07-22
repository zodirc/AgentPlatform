import { markdown } from "@codemirror/lang-markdown";
import { lazy, Suspense } from "react";

const CodeMirror = lazy(() => import("@uiw/react-codemirror"));

type Props = {
  value: string;
  title?: string;
  readOnly?: boolean;
};

export function SectionEditor({ value, title, readOnly = true }: Props) {
  return (
    <div className="rounded-lg border border-border bg-background">
      {title ? (
        <p className="border-b border-border px-3 py-2 text-xs text-muted-foreground">
          {title}
        </p>
      ) : null}
      <Suspense
        fallback={<pre className="p-3 text-xs text-muted-foreground">加载编辑器…</pre>}
      >
        <CodeMirror
          value={value}
          height="200px"
          extensions={[markdown()]}
          readOnly={readOnly}
          basicSetup={{ lineNumbers: false, foldGutter: false }}
        />
      </Suspense>
    </div>
  );
}
