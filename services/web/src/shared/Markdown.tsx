import { useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const BODY_CLASS =
  "markdown-body space-y-2 text-xs leading-relaxed text-foreground/90 [&_a]:text-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[11px] [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-xs [&_h3]:font-semibold [&_li]:ml-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:px-2 [&_th]:py-1 [&_ul]:list-disc [&_ul]:pl-4";

/** http(s) and protocol-relative URLs would send data out as soon as the page loads them. */
export function isExternalUrl(src: string | undefined): boolean {
  const raw = (src || "").trim();
  if (!raw) return false;
  if (raw.startsWith("//")) return true;
  const head = raw.slice(0, 8).toLowerCase();
  return head.startsWith("http:") || head.startsWith("https:");
}

function GuardedImage({ src, alt }: { src?: string; alt?: string }) {
  const [revealed, setRevealed] = useState(false);
  if (!src) return null;
  if (isExternalUrl(src) && !revealed) {
    return (
      <button
        type="button"
        className="rounded border border-border px-2 py-1 text-left text-[11px] text-muted-foreground"
        onClick={() => setRevealed(true)}
      >
        外部图片未加载{alt ? `：${alt}` : ""}
      </button>
    );
  }
  return <img src={src} alt={alt ?? ""} />;
}

function GuardedLink({
  href,
  children,
}: {
  href?: string;
  children?: ReactNode;
}) {
  return (
    <a href={href} rel="noreferrer noopener" target="_blank">
      {children}
      {href ? (
        <span className="ml-1 font-mono text-[10px] text-muted-foreground">
          ({href})
        </span>
      ) : null}
    </a>
  );
}

const COMPONENTS: Components = {
  img: ({ src, alt }) => <GuardedImage src={typeof src === "string" ? src : undefined} alt={alt} />,
  a: ({ href, children }) => <GuardedLink href={href}>{children}</GuardedLink>,
};

/**
 * I16: assistant output as GFM when settled.
 * While `streaming`, skip remark/GFM re-parse each frame (plain text only).
 * External images stay unloaded until the user clicks. Links show the full target.
 */
export function Markdown({
  text,
  streaming = false,
}: {
  text: string;
  streaming?: boolean;
}) {
  if (streaming) {
    return (
      <div className={BODY_CLASS} data-streaming="true">
        <pre className="m-0 whitespace-pre-wrap font-sans text-xs leading-relaxed text-foreground/90">
          {text}
        </pre>
      </div>
    );
  }
  return (
    <div className={BODY_CLASS}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
