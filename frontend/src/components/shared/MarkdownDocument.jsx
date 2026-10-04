/**
 * A Markdown document rendered as a document — full CommonMark + GitHub extensions
 * (tables, task lists, strikethrough, autolinks, fenced code). Used for previewing
 * .md files and the Markdown Curivio stores for Word/PowerPoint text; the chat's
 * own MarkdownText stays for chat replies (it handles maths and streaming).
 * Raw HTML in the file is not rendered (react-markdown's default), so a previewed
 * file can't inject markup.
 */
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

const C = {
  h1: (p) => <h1 className="mt-6 first:mt-0 mb-3 text-[22px] font-semibold text-slate-100 leading-snug" {...p} />,
  h2: (p) => <h2 className="mt-6 first:mt-0 mb-2.5 pb-1.5 border-b border-slate-800 text-[18px] font-semibold text-slate-100 leading-snug" {...p} />,
  h3: (p) => <h3 className="mt-5 first:mt-0 mb-2 text-[15.5px] font-semibold text-slate-100" {...p} />,
  h4: (p) => <h4 className="mt-4 mb-1.5 text-[14px] font-semibold text-slate-200" {...p} />,
  h5: (p) => <h5 className="mt-4 mb-1.5 text-[13px] font-semibold text-slate-300" {...p} />,
  h6: (p) => <h6 className="mt-4 mb-1.5 text-[12.5px] font-semibold text-slate-400" {...p} />,
  p: (p) => <p className="my-2.5 text-[14px] leading-relaxed text-slate-300" {...p} />,
  a: ({ href, ...p }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-sky-400 underline underline-offset-2 hover:text-sky-300" {...p} />,
  ul: ({ className, ...p }) => <ul className={`my-2.5 pl-5 space-y-1 text-[14px] text-slate-300 ${className?.includes("contains-task-list") ? "list-none pl-1" : "list-disc"} marker:text-slate-500`} {...p} />,
  ol: (p) => <ol className="my-2.5 pl-5 space-y-1 list-decimal text-[14px] text-slate-300 marker:text-slate-500" {...p} />,
  li: (p) => <li className="leading-relaxed [&>ul]:my-1 [&>ol]:my-1" {...p} />,
  input: (p) => <input {...p} disabled className="mr-2 align-middle accent-sky-500" />,
  blockquote: (p) => <blockquote className="my-3 border-l-2 border-slate-600 pl-3.5 text-slate-400 [&_p]:text-slate-400" {...p} />,
  hr: () => <hr className="my-5 border-slate-800" />,
  table: (p) => <div className="my-3 overflow-x-auto"><table className="w-full border-collapse text-[13px]" {...p} /></div>,
  th: (p) => <th className="border border-slate-700 bg-slate-800/60 px-2.5 py-1.5 text-left font-semibold text-slate-200" {...p} />,
  td: (p) => <td className="border border-slate-800 px-2.5 py-1.5 align-top text-slate-300" {...p} />,
  pre: (p) => <pre className="my-3 overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-[12.5px] leading-relaxed" {...p} />,
  code: ({ className, children, ...p }) => className?.startsWith("language-") || String(children).includes("\n")
    ? <code className={`font-mono text-slate-200 ${className || ""}`} {...p}>{children}</code>
    : <code className="rounded bg-slate-800/80 px-1 py-0.5 font-mono text-[0.9em] text-slate-200" {...p}>{children}</code>,
  // Web images show; a relative path points into the author's folder, which isn't here.
  img: ({ src, alt }) => /^https:\/\//i.test(src || "")
    ? <img src={src} alt={alt || ""} loading="lazy" className="my-2 max-w-full rounded-lg" />
    : <span className="text-[12px] text-slate-500">[image{alt ? `: ${alt}` : ""}]</span>,
  strong: (p) => <strong className="font-semibold text-slate-100" {...p} />,
}

export default function MarkdownDocument({ text, className = "" }) {
  return (
    <div className={`min-w-0 break-words ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={C}>{text || ""}</ReactMarkdown>
    </div>
  )
}
