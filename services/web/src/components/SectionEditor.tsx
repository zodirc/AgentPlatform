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
    <div className="rounded-lg border border-slate-800 bg-slate-950">
      {title ? (
        <p className="border-b border-slate-800 px-3 py-2 text-xs text-slate-400">
          {title}
        </p>
      ) : null}
      <Suspense
        fallback={<pre className="p-3 text-xs text-slate-500">加载编辑器…</pre>}
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
