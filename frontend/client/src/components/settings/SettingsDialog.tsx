import { useState, useEffect } from 'react'
import { Server, Palette, Sliders, Info } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { useSettingsStore } from '@/store/settings'
import { useConnectionStore } from '@/store/connection'
import { apiClient } from '@/api/client'

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const settings = useSettingsStore()
  const connCheck = useConnectionStore((s) => s.check)
  const connState = useConnectionStore((s) => s.state)
  const connError = useConnectionStore((s) => s.error)

  const [serverUrl, setServerUrl] = useState(settings.connection.serverUrl)
  const [useWebSocket, setUseWebSocket] = useState(settings.connection.useWebSocket)
  const [timeout, setTimeout] = useState(settings.connection.timeout)
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    if (open) {
      setServerUrl(settings.connection.serverUrl)
      setUseWebSocket(settings.connection.useWebSocket)
      setTimeout(settings.connection.timeout)
    }
  }, [open])

  const handleSaveConnection = async () => {
    await settings.update({
      connection: { serverUrl, useWebSocket, timeout },
    })
    apiClient.setBaseUrl(serverUrl)
    apiClient.setTimeout(timeout)
    await connCheck(serverUrl)
  }

  const handleTestConnection = async () => {
    setTesting(true)
    apiClient.setBaseUrl(serverUrl)
    await connCheck(serverUrl)
    setTesting(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Configure connection, appearance, and chat behavior.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="connection" className="w-full">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="connection" className="gap-1.5">
              <Server className="h-3.5 w-3.5" /> Connection
            </TabsTrigger>
            <TabsTrigger value="appearance" className="gap-1.5">
              <Palette className="h-3.5 w-3.5" /> Appearance
            </TabsTrigger>
            <TabsTrigger value="chat" className="gap-1.5">
              <Sliders className="h-3.5 w-3.5" /> Chat
            </TabsTrigger>
          </TabsList>

          {/* Connection tab */}
          <TabsContent value="connection" className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="server-url">HakusAI Server URL</Label>
              <Input
                id="server-url"
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
                placeholder="http://localhost:8080"
              />
              <p className="text-[11px] text-muted-foreground">
                The URL of your HakusAI backend (FastAPI server from <code>src/hakusai_server/</code>).
                Defaults to <code>http://localhost:8080</code>.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="timeout">Request timeout (ms)</Label>
              <Input
                id="timeout"
                type="number"
                value={timeout}
                onChange={(e) => setTimeout(Number(e.target.value) || 30000)}
                min={5000}
                max={300000}
                step={1000}
              />
            </div>

            <div className="flex items-center justify-between rounded-md border p-3">
              <div className="space-y-0.5">
                <Label htmlFor="ws-toggle">Use WebSocket (experimental)</Label>
                <p className="text-[11px] text-muted-foreground">
                  Use full-duplex WebSocket instead of SSE. Enables mid-stream interruption.
                </p>
              </div>
              <Switch
                id="ws-toggle"
                checked={useWebSocket}
                onCheckedChange={setUseWebSocket}
              />
            </div>

            <div className="flex items-center gap-2">
              <Button onClick={handleSaveConnection} size="sm">Save</Button>
              <Button onClick={handleTestConnection} variant="outline" size="sm" disabled={testing}>
                {testing ? 'Testing...' : 'Test connection'}
              </Button>
              {connState === 'connected' && (
                <span className="text-xs text-emerald-500">● Connected</span>
              )}
              {connState === 'error' && (
                <span className="text-xs text-destructive" title={connError || ''}>
                  ✕ {connError?.slice(0, 40) || 'Failed'}
                </span>
              )}
            </div>
          </TabsContent>

          {/* Appearance tab */}
          <TabsContent value="appearance" className="space-y-4">
            <div className="space-y-2">
              <Label>Theme</Label>
              <div className="grid grid-cols-3 gap-2">
                {(['light', 'dark', 'system'] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => settings.setTheme(t)}
                    className={`rounded-md border p-3 text-sm capitalize transition-colors ${
                      settings.theme === t
                        ? 'border-violet-500 bg-violet-500/10 text-foreground'
                        : 'border-border hover:bg-accent'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            <Separator />

            <div className="space-y-2">
              <Label htmlFor="font-size">Chat font size: {settings.fontSize}px</Label>
              <input
                id="font-size"
                type="range"
                min={12}
                max={20}
                step={1}
                value={settings.fontSize}
                onChange={(e) => settings.update({ fontSize: Number(e.target.value) })}
                className="w-full"
              />
            </div>
          </TabsContent>

          {/* Chat tab */}
          <TabsContent value="chat" className="space-y-4">
            <div className="flex items-center justify-between rounded-md border p-3">
              <div className="space-y-0.5">
                <Label htmlFor="enter-toggle">Send on Enter</Label>
                <p className="text-[11px] text-muted-foreground">
                  Press Enter to send. Shift+Enter inserts a newline. When off, use Ctrl/Cmd+Enter.
                </p>
              </div>
              <Switch
                id="enter-toggle"
                checked={settings.sendOnEnter}
                onCheckedChange={(v) => settings.update({ sendOnEnter: v })}
              />
            </div>

            <div className="flex items-center justify-between rounded-md border p-3">
              <div className="space-y-0.5">
                <Label htmlFor="reasoning-toggle">Show reasoning</Label>
                <p className="text-[11px] text-muted-foreground">
                  Display the model's chain-of-thought (Claude / O-series) when available.
                </p>
              </div>
              <Switch
                id="reasoning-toggle"
                checked={settings.showReasoning}
                onCheckedChange={(v) => settings.update({ showReasoning: v })}
              />
            </div>

            <div className="flex items-center justify-between rounded-md border p-3">
              <div className="space-y-0.5">
                <Label htmlFor="autoscroll-toggle">Auto-scroll</Label>
                <p className="text-[11px] text-muted-foreground">
                  Automatically scroll to the latest message while streaming.
                </p>
              </div>
              <Switch
                id="autoscroll-toggle"
                checked={settings.autoScroll}
                onCheckedChange={(v) => settings.update({ autoScroll: v })}
              />
            </div>
          </TabsContent>
        </Tabs>

        <Separator />
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <Info className="h-3 w-3" /> Settings are stored locally via electron-store.
          </span>
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>Close</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
