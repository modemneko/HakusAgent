import { useRef, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { cn, copyToClipboard } from '@/lib/utils'

type CodeBlockProps = React.HTMLAttributes<HTMLPreElement> & { node?: unknown }

/**
 * 自定义 `<pre>` 渲染：在代码块右上角叠加语言标签和复制按钮。
 * 复制按钮 hover 时显示，点击复制代码块纯文本内容。
 *
 * 通过 ReactMarkdown 的 `components={{ pre: CodeBlock }}` 接入。
 * `node` 是 react-markdown 传递的 hast 节点，这里剥离掉避免泄漏到 DOM。
 */
export function CodeBlock({ children, className, node: _node, ...props }: CodeBlockProps) {
  const preRef = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)

  // 从 <code> 子元素的 className 提取语言 (e.g. "hljs language-python")
  // children can be string | number | ReactElement | array thereof; only
  // ReactElement has a `props.className` we care about. Cast through a
  // minimal structural shape so TS narrows `unknown` without needing
  // @types/react's internal ReactElement typing.
  const child = Array.isArray(children) ? children[0] : children
  type ElementWithProps = { props?: { className?: unknown } }
  const childProps =
    child && typeof child === 'object' && 'props' in (child as object)
      ? (child as ElementWithProps).props
      : undefined
  const childClassName: string =
    childProps && typeof childProps.className === 'string' ? childProps.className : ''
  const langMatch = /language-([\w-]+)/.exec(childClassName)
  const lang = langMatch?.[1] || ''

  const handleCopy = async () => {
    const text = preRef.current?.textContent || ''
    const ok = await copyToClipboard(text)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className="group/code relative">
      <div className="absolute right-1 top-1 z-10 flex items-center gap-1">
        {lang && (
          <span className="rounded bg-muted/70 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            {lang}
          </span>
        )}
        <button
          type="button"
          onClick={handleCopy}
          className={cn(
            'flex items-center rounded bg-muted/70 px-1.5 py-0.5 text-muted-foreground transition-opacity',
            'opacity-0 hover:bg-accent hover:text-accent-foreground group-hover/code:opacity-100',
          )}
          title="Copy code"
        >
          {copied ? (
            <Check className="h-3 w-3 text-emerald-500" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
        </button>
      </div>
      <pre ref={preRef} className={className} {...props}>
        {children}
      </pre>
    </div>
  )
}
