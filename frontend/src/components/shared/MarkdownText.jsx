import { useState } from "react"

// Copy icon component
function CopyIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
      <path d="M0 6.75C0 5.784.784 5 1.75 5h1.5a.75.75 0 0 1 0 1.5h-1.5a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-1.5a.75.75 0 0 1 1.5 0v1.5A1.75 1.75 0 0 1 9.25 16h-7.5A1.75 1.75 0 0 1 0 14.25Z" />
      <path d="M5 1.75C5 .784 5.784 0 6.75 0h7.5C15.216 0 16 .784 16 1.75v7.5A1.75 1.75 0 0 1 14.25 11h-7.5A1.75 1.75 0 0 1 5 9.25Zm1.75-.25a.25.25 0 0 0-.25.25v7.5c0 .138.112.25.25.25h7.5a.25.25 0 0 0 .25-.25v-7.5a.25.25 0 0 0-.25-.25Z" />
    </svg>
  )
}

// Code block copy button
function CodeBlockCopyButton({ code }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      onClick={handleCopy}
      title="Copy code"
      className="flex items-center gap-1 px-2 py-1 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors text-xs"
    >
      <CopyIcon />
      {copied && <span className="text-[10px]">Copied!</span>}
    </button>
  )
}

// Inline parser: bold (**text**), links ([text](url)), inline code (`text`)
export function renderInline(text) {
  const parts = []
  let remaining = text
  let key = 0

  while (remaining.length > 0) {
    const linkMatch = remaining.match(/^(.*?)\[([^\]]+)\]\(([^)]+)\)(.*)$/)
    if (linkMatch) {
      if (linkMatch[1]) parts.push(<span key={key++}>{renderInline(linkMatch[1])}</span>)
      parts.push(
        <a key={key++} href={linkMatch[3]} target="_blank" rel="noopener noreferrer"
          className="text-blue-400 hover:text-blue-300 underline underline-offset-[3px] decoration-blue-400/40 hover:decoration-blue-300/60 transition-colors">
          {linkMatch[2]}
        </a>
      )
      remaining = linkMatch[4]
      continue
    }

    const boldMatch = remaining.match(/^(.*?)\*\*(.+?)\*\*(.*)$/)
    if (boldMatch) {
      if (boldMatch[1]) parts.push(<span key={key++}>{renderInline(boldMatch[1])}</span>)
      parts.push(<strong key={key++} className="font-semibold text-slate-100">{boldMatch[2]}</strong>)
      remaining = boldMatch[3]
      continue
    }

    const codeMatch = remaining.match(/^(.*?)`([^`]+)`(.*)$/)
    if (codeMatch) {
      if (codeMatch[1]) parts.push(<span key={key++}>{renderInline(codeMatch[1])}</span>)
      parts.push(
        <code key={key++} className="bg-slate-800/80 border border-slate-700/50 rounded-md px-[5px] py-[1.5px] text-[12.5px] font-mono text-violet-300 leading-none">
          {codeMatch[2]}
        </code>
      )
      remaining = codeMatch[3]
      continue
    }

    parts.push(<span key={key++}>{remaining}</span>)
    break
  }

  return parts.length === 1 && typeof parts[0].props?.children === "string"
    ? parts[0].props.children
    : parts
}

// Line-by-line markdown renderer
export default function MarkdownText({ text, variant = "default", className = "" }) {
  const lines = text.split("\n")
  const isThinking = variant === "thinking"
  const headingClass = isThinking
    ? "text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7]"
    : "text-[16px] sm:text-[18px] font-bold text-slate-50 mt-6 sm:mt-8 mb-2.5 sm:mb-3 first:mt-0 leading-tight tracking-tight"
  const subheadingClass = isThinking
    ? "font-medium text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7]"
    : "font-semibold text-slate-100 text-[14px] sm:text-[15px] mt-5 sm:mt-6 mb-2 sm:mb-2.5 first:mt-0 leading-snug"
  const paragraphClass = isThinking
    ? "text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7]"
    : "text-slate-300 leading-[1.72] sm:leading-[1.78] text-[14px] sm:text-[15px]"
  const elements = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    if (line.startsWith("### ")) {
      elements.push(
        <h3 key={i} className={isThinking ? "text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7] mt-3 sm:mt-4 mb-1 first:mt-0" : "text-[11px] sm:text-[11.5px] font-semibold text-slate-400 mt-5 sm:mt-6 mb-1.5 sm:mb-2 first:mt-0 uppercase tracking-widest"}>
          {renderInline(line.slice(4))}
        </h3>
      )
      i++
      continue
    }

    if (line.startsWith("## ")) {
      elements.push(
        <h2 key={i} className={isThinking ? "text-slate-400 text-[13px] sm:text-[14px] leading-[1.6] sm:leading-[1.7] mt-3 sm:mt-4 mb-1 first:mt-0" : "text-[14.5px] sm:text-[15.5px] font-semibold text-slate-100 mt-5 sm:mt-7 mb-2 sm:mb-2.5 first:mt-0 leading-snug tracking-tight"}>
          {renderInline(line.slice(3))}
        </h2>
      )
      i++
      continue
    }

    if (line.startsWith("# ")) {
      elements.push(
        <h1 key={i} className={headingClass}>
          {renderInline(line.slice(2))}
        </h1>
      )
      i++
      continue
    }

    if (line.startsWith("```")) {
      const lang = line.slice(3).trim()
      const codeLines = []
      i++
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i])
        i++
      }
      const codeContent = codeLines.join("\n")
      elements.push(
        <div key={i} className="bg-slate-900 border border-slate-700/60 rounded-xl overflow-hidden my-4">
          <div className="flex items-center justify-between px-4 pt-3">
            {lang && <div className="text-slate-500 text-[10.5px] font-medium uppercase tracking-widest">{lang}</div>}
            <CodeBlockCopyButton code={codeContent} />
          </div>
          <pre className="px-4 pb-3 pt-1 overflow-x-scroll-touch">
            <code className="text-[13px] font-mono text-slate-200 leading-[1.68] block whitespace-pre">{codeContent}</code>
          </pre>
        </div>
      )
      i++
      continue
    }

    if (line.startsWith("**") && line.endsWith("**") && !line.slice(2, -2).includes("**")) {
      elements.push(
        <p key={i} className={subheadingClass}>
          {line.slice(2, -2)}
        </p>
      )
      i++
      continue
    }

    if (line.startsWith("|") && line.endsWith("|")) {
      const tableLines = []
      while (i < lines.length && lines[i].startsWith("|")) {
        tableLines.push(lines[i])
        i++
      }
      const headerCells = tableLines[0].split("|").filter(Boolean).map(c => c.trim())
      const dataRows = tableLines.slice(2).map(row =>
        row.split("|").filter(Boolean).map(c => c.trim())
      )
      elements.push(
        <div key={i} className="overflow-x-scroll-touch my-4 rounded-xl border border-slate-700/50">
          <table className="w-full text-[13.5px] border-collapse">
            <thead>
              <tr className="border-b border-slate-700/70">
                {headerCells.map((cell, ci) => (
                  <th key={ci} className="text-left px-3.5 py-2.5 bg-slate-800/60 text-slate-200 font-semibold text-[12px] uppercase tracking-wide">
                    {renderInline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dataRows.map((row, ri) => (
                <tr key={ri} className={ri % 2 === 0 ? "bg-transparent" : "bg-slate-800/20"}>
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-3.5 py-2.5 text-slate-300 border-b border-slate-800/60 leading-relaxed">
                      {renderInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      continue
    }

    if (line.startsWith("- ") || line.startsWith("* ") || line.startsWith("• ")) {
      const items = []
      while (i < lines.length && (lines[i].startsWith("- ") || lines[i].startsWith("* ") || lines[i].startsWith("• "))) {
        items.push(lines[i].replace(/^[-*•] /, ""))
        i++
      }
      elements.push(
        <ul key={i} className="my-2.5 sm:my-3.5 space-y-2 sm:space-y-2.5 pl-0">
          {items.map((item, idx) => (
            <li key={idx} className="flex gap-2.5 text-[14px] sm:text-[15px] text-slate-300 leading-[1.7] sm:leading-[1.75]">
              <span className="text-blue-400/50 flex-shrink-0 mt-[3px] select-none text-[13px] sm:text-[14px]">•</span>
              <span>{renderInline(item)}</span>
            </li>
          ))}
        </ul>
      )
      continue
    }

    if (/^\d+\.\s/.test(line)) {
      const items = []
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s/, ""))
        i++
      }
      elements.push(
        <ol key={i} className="my-2.5 sm:my-3.5 space-y-2 sm:space-y-2.5 pl-0 list-none">
          {items.map((item, idx) => (
            <li key={idx} className="flex gap-2.5 text-[14px] sm:text-[15px] text-slate-300 leading-[1.7] sm:leading-[1.75]">
              <span className="text-blue-400/60 flex-shrink-0 tabular-nums text-[13px] font-semibold mt-[2px] min-w-[1.4em] text-right">{idx + 1}.</span>
              <span>{renderInline(item)}</span>
            </li>
          ))}
        </ol>
      )
      continue
    }

    if (!line.trim()) {
      if (!isThinking) elements.push(<div key={i} className="h-1 sm:h-1.5" />)
      i++
      continue
    }

    elements.push(
      <p key={i} className={paragraphClass}>
        {renderInline(line)}
      </p>
    )
    i++
  }

  return <div className={`reading-text prose-wrap ${className || "space-y-1.5"}`}>{elements}</div>
}
