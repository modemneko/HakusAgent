/**
 * Right-panel Flow run monitor — node timeline, outputs, human prompt.
 */

import { Workflow } from 'lucide-react'
import { useFlowStore } from '@/store/flow'
import { getNodeDef } from '@/lib/flow/registry'
import { toDisplay } from '@/lib/flow/template'
import { cn } from '@/lib/utils'
import {
  RpBody,
  RpChip,
  RpEmpty,
  RpFooter,
  RpHeader,
  RpSection,
  RpShell,
  useRpCopy,
} from '@/components/review/PanelChrome'

const statusTone = (s: string) =>
  s === 'done' ? 'ok' : s === 'error' ? 'danger' : s === 'running' || s === 'waiting' ? 'warn' : s === 'skipped' ? 'muted' : 'muted'

export function FlowRunPanel() {
  const copy = useRpCopy()
  const graph = useFlowStore((s) => s.graph)
  const run = useFlowStore((s) => s.run)
  const startRun = useFlowStore((s) => s.startRun)
  const stopRun = useFlowStore((s) => s.stopRun)
  const submitHuman = useFlowStore((s) => s.submitHuman)
  const selectNode = useFlowStore((s) => s.selectNode)

  const nodes = graph.nodes
  const ordered = [...nodes].sort((a, b) => {
    const sa = run.nodeStates[a.id]?.status || 'idle'
    const sb = run.nodeStates[b.id]?.status || 'idle'
    const rank = (s: string) => (s === 'running' || s === 'waiting' ? 0 : s === 'done' ? 1 : s === 'error' ? 2 : 3)
    return rank(sa) - rank(sb)
  })

  const outputEntries = Object.entries(run.outputs || {})

  return (
    <RpShell>
      <RpHeader
        icon={Workflow}
        title={copy('Flow 运行', 'Flow run')}
        meta={<RpChip tone={run.status === 'done' ? 'ok' : run.status === 'error' ? 'danger' : run.status === 'running' ? 'info' : 'muted'}>{run.status}</RpChip>}
        actions={
          run.status === 'running' || run.status === 'waiting_human' ? (
            <button type="button" className="rp-icon-btn" onClick={stopRun} title={copy('停止', 'Stop')}>
              ■
            </button>
          ) : (
            <button type="button" className="rp-icon-btn" onClick={() => void startRun()} title={copy('运行', 'Run')}>
              ▶
            </button>
          )
        }
      />

      <RpBody>
        {run.status === 'waiting_human' && run.human ? (
          <RpSection label={copy('人工确认', 'Human input')}>
            <div className="rp-card space-y-2">
              <div className="text-[11px] leading-relaxed text-foreground">{run.human.prompt}</div>
              <input
                id="flow-run-panel-human"
                className="rp-input"
                placeholder={copy('输入后提交…', 'Type and submit…')}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') submitHuman((e.target as HTMLInputElement).value)
                }}
              />
              <button
                type="button"
                className="rp-scope-btn w-full justify-center"
                onClick={() => {
                  const el = document.getElementById('flow-run-panel-human') as HTMLInputElement | null
                  submitHuman(el?.value || '')
                }}
              >
                {copy('提交', 'Submit')}
              </button>
            </div>
          </RpSection>
        ) : null}

        <RpSection label={copy('节点时间线', 'Node timeline')} icon={Workflow}>
          {nodes.length === 0 ? (
            <RpEmpty icon={Workflow} title={copy('画布为空', 'Canvas empty')} desc={copy('在 Flow 模式左侧节点库添加节点。', 'Add nodes from the palette in Flow mode.')} />
          ) : (
            <div className="space-y-1">
              {ordered.map((n) => {
                const st = run.nodeStates[n.id]
                const def = getNodeDef(n.type)
                return (
                  <button
                    key={n.id}
                    type="button"
                    className="rp-card rp-card-tight w-full text-left"
                    onClick={() => selectNode(n.id)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="flow-node-dot" style={{ background: def?.color }} />
                      <span className="min-w-0 flex-1 truncate text-[12px] font-medium">
                        {String(n.data.label || def?.labelZh || n.type)}
                      </span>
                      <RpChip tone={statusTone(st?.status || 'idle') as any}>{st?.status || 'idle'}</RpChip>
                    </div>
                    {st?.preview ? (
                      <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground">{st.preview}</div>
                    ) : null}
                    {st?.error ? (
                      <div className="mt-1 truncate text-[10px] text-rose-500">{st.error}</div>
                    ) : null}
                  </button>
                )
              })}
            </div>
          )}
        </RpSection>

        {outputEntries.length > 0 && (
          <RpSection label={copy('运行输出', 'Run outputs')}>
            <div className="space-y-1.5">
              {outputEntries.map(([k, v]) => (
                <div key={k} className="rp-card rp-card-tight">
                  <div className="font-mono text-[10px] text-muted-foreground">{k}</div>
                  <div className="mt-0.5 max-h-24 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px]">
                    {toDisplay(v).slice(0, 800)}
                  </div>
                </div>
              ))}
            </div>
          </RpSection>
        )}

        {run.error ? (
          <div className="rp-card border-rose-500/40 bg-rose-500/10 text-[11px] text-rose-500">{run.error}</div>
        ) : null}
      </RpBody>

      <RpFooter>
        <span>
          {graph.nodes.length} {copy('节点', 'nodes')} · {graph.edges.length} {copy('边', 'edges')}
        </span>
        <span className={cn('font-mono')}>{graph.name}</span>
      </RpFooter>
    </RpShell>
  )
}
