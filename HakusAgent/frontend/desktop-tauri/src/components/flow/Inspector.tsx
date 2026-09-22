/**
 * Inspector — the right rail's parameter tab.
 *
 * Renders one selected node's fields, its run log and its resolved outputs.
 * With several nodes selected it shows a bulk summary instead (the fields of
 * one node are meaningless for a selection).
 *
 * Text inputs batch their edits: focus opens a batch and blur closes it, so a
 * typed label is ONE undo step rather than one per keystroke.
 */

import { MousePointerClick, Trash2 } from 'lucide-react'
import { useFlowStore } from '@/store/flow'
import { getNodeDef } from '@/lib/flow/registry'
import { toDisplay } from '@/lib/flow/template'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/lib/i18n'

export function Inspector() {
  const selectedNodeIds = useFlowStore((s) => s.selectedNodeIds)
  const graph = useFlowStore((s) => s.graph)
  const run = useFlowStore((s) => s.run)
  const updateNodeData = useFlowStore((s) => s.updateNodeData)
  const removeNodes = useFlowStore((s) => s.removeNodes)
  const beginBatch = useFlowStore((s) => s.beginBatch)
  const endBatch = useFlowStore((s) => s.endBatch)
  const { locale } = useI18n()
  const zh = locale === 'zh-CN'

  const selectedId = selectedNodeIds.length === 1 ? selectedNodeIds[0] : null
  const node = graph.nodes.find((n) => n.id === selectedId)
  const def = node ? getNodeDef(node.type) : undefined
  const state = node ? run.nodeStates[node.id] : undefined

  const batchProps = {
    onFocus: beginBatch,
    onBlur: endBatch,
  }

  if (selectedNodeIds.length > 1) {
    return (
      <div className="flow-inspector">
        <div className="rp-section-label">
          {zh ? `已选中 ${selectedNodeIds.length} 个节点` : `${selectedNodeIds.length} nodes selected`}
        </div>
        <ul className="flow-hint-list">
          <li>{zh ? '拖动可整体移动' : 'Drag to move them together'}</li>
          <li>{zh ? 'Delete 删除选中' : 'Delete removes the selection'}</li>
          <li>{zh ? 'Ctrl+C / Ctrl+V 复制粘贴' : 'Ctrl+C / Ctrl+V to copy'}</li>
        </ul>
        <Button
          size="sm"
          variant="ghost"
          className="mt-2 h-7 w-full justify-start text-destructive"
          onClick={() => removeNodes(selectedNodeIds)}
        >
          <Trash2 className="mr-1 h-3 w-3" /> {zh ? '删除选中节点' : 'Delete selected'}
        </Button>
      </div>
    )
  }

  if (!node || !def) {
    return (
      <div className="flow-inspector">
        <div className="flow-hint">
          <MousePointerClick className="h-5 w-5 opacity-50" />
          <div className="flow-hint-title">{zh ? '未选中节点' : 'No node selected'}</div>
          <ul className="flow-hint-list">
            <li>{zh ? '双击画布空白处 → 搜索并添加节点' : 'Double-click the canvas → search and add a node'}</li>
            <li>{zh ? '拖动节点右侧圆点连线到下一个节点' : 'Drag a port dot to wire nodes together'}</li>
            <li>{zh ? '单击节点 → 在这里编辑它的参数' : 'Click a node → edit its parameters here'}</li>
            <li>{zh ? '右键节点或画布 → 更多操作' : 'Right-click a node or the canvas → more actions'}</li>
            <li>{zh ? 'Shift 拖拽框选多个节点' : 'Shift-drag to select several nodes'}</li>
          </ul>
        </div>
      </div>
    )
  }

  return (
    <div className="flow-inspector">
      <div className="rp-section-label">
        <span className="flow-node-dot" style={{ background: def.color }} />
        {zh ? def.labelZh : def.label}
        <span className="ml-auto text-[10px] font-normal normal-case tracking-normal opacity-60">{node.id}</span>
      </div>

      <label className="flow-field">
        <span>{zh ? '名称' : 'Label'}</span>
        <input
          className="rp-input"
          value={String(node.data.label || '')}
          onChange={(e) => updateNodeData(node.id, { label: e.target.value })}
          {...batchProps}
        />
      </label>

      {def.fields.map((field) => {
        if (field.showWhen) {
          const cur = node.data[field.showWhen.key]
          if (String(cur) !== String(field.showWhen.equals)) return null
        }
        const value = node.data[field.key]
        return (
          <label key={field.key} className="flow-field">
            <span>{field.label}</span>
            {field.kind === 'textarea' || field.kind === 'code' || field.kind === 'json' ? (
              <textarea
                className="rp-textarea"
                rows={field.rows || 3}
                value={String(value ?? '')}
                placeholder={field.placeholder}
                onChange={(e) => updateNodeData(node.id, { [field.key]: e.target.value })}
                {...batchProps}
              />
            ) : field.kind === 'select' ? (
              <select
                className="rp-input"
                value={String(value ?? '')}
                onChange={(e) => updateNodeData(node.id, { [field.key]: e.target.value })}
              >
                {field.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : field.kind === 'number' ? (
              <input
                className="rp-input"
                type="number"
                value={String(value ?? '')}
                onChange={(e) => updateNodeData(node.id, { [field.key]: Number(e.target.value) })}
                {...batchProps}
              />
            ) : (
              <input
                className="rp-input"
                value={String(value ?? '')}
                placeholder={field.placeholder}
                onChange={(e) => updateNodeData(node.id, { [field.key]: e.target.value })}
                {...batchProps}
              />
            )}
          </label>
        )
      })}

      {state?.log?.length ? (
        <div className="flow-field">
          <span>{zh ? '运行日志' : 'Run log'}</span>
          <pre className="flow-log">{state.log.join('\n')}</pre>
        </div>
      ) : null}

      {state?.outputs ? (
        <div className="flow-field">
          <span>{zh ? '输出端口' : 'Outputs'}</span>
          <pre className="flow-log">
            {Object.entries(state.outputs)
              .map(([k, v]) => `${k}: ${toDisplay(v).slice(0, 200)}`)
              .join('\n')}
          </pre>
        </div>
      ) : null}

      <Button
        size="sm"
        variant="ghost"
        className="mt-2 h-7 w-full justify-start text-destructive"
        onClick={() => removeNodes([node.id])}
      >
        <Trash2 className="mr-1 h-3 w-3" /> {zh ? '删除节点' : 'Delete node'}
      </Button>
    </div>
  )
}
