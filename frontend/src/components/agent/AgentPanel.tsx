import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';
import { MessageSquare, Settings, X, Send, Square, Download, Plus } from 'lucide-react';
import { useProjectStore } from '../../store/useProjectStore';
import { useSimulatorStore } from '../../store/useSimulatorStore';
import { registerEditorCommand } from '../../lib/editorCommands';
import {
  agentBrowserId,
  agentRequest,
  connectAgentEvents,
  projectRevision,
} from '../../services/agentService';
import type { AgentEvent, AgentSession, AgentSettings } from '../../services/agentService';
import {
  applyAgentSnapshot,
  handleAgentBrowserCommand,
  snapshotForAgent,
} from '../../services/agentBrowserBridge';
import type { VlxPayload } from '../../utils/vlxFile';
import { AgentSettingsDialog } from './AgentSettingsDialog';
import { cancelAgentProjectRun } from '../../services/projectExecution';
import { generateUUID } from '../../utils/uuid';
import { reduceAgentEvent } from '../../services/agentEvents';
import { AgentMessageBody, AgentTimeline } from './AgentTimeline';
import './AgentPanel.css';

const defaults: AgentSettings = {
  base_url: 'http://127.0.0.1:11434/v1',
  model: '',
  max_steps: 20,
  max_output_tokens: 8192,
  context_window: 65536,
  timeout_seconds: 300,
};
export function AgentPanel({ onDockChange }: { onDockChange?: (width: number) => void } = {}) {
  const { t, i18n } = useTranslation();
  const errorText = useCallback(
    (error: unknown) => {
      const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : '';
      return code && i18n.exists(`agent.errors.${code}`)
        ? t(`agent.errors.${code}`)
        : error instanceof Error
          ? error.message
          : t('agent.errors.generic');
    },
    [t, i18n],
  );
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState(defaults);
  const [session, setSession] = useState<AgentSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [message, setMessage] = useState('');
  const [partial, setPartial] = useState('');
  const partials = useRef<Record<string, string>>({});
  const [error, setError] = useState('');
  const [width, setWidth] = useState(390);
  const savedProjectId = useProjectStore((state) => state.currentProject?.id);
  const location = useLocation();
  const projectKey = String(savedProjectId ?? location.pathname);
  const connectionReady = useRef(false);
  const browserRevision = useRef('');
  const revision = useRef('');
  const seen = useRef(0);
  const end = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);
  const handler = useRef<(event: AgentEvent) => void>(() => {});
  const sessionRef = useRef(session);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    onDockChange?.(open ? width : 0);
    return () => onDockChange?.(0);
  }, [open, width, onDockChange]);

  const refresh = useCallback(async (id: string, apply: boolean) => {
    const updated = await agentRequest<AgentSession>(`/sessions/${id}`);
    if (sessionRef.current?.id !== id) return;
    setSession(updated);
    // A terminal event can arrive while the server task is still cleaning up.
    // Its persisted turn status is already final at that point.
    setBusy(updated.busy && (updated.turns?.at(-1)?.status ?? 'running') === 'running');
    if (!updated.busy || updated.messages.at(-1)?.role === 'assistant') {
      setPartial('');
      partials.current = {};
    }
    revision.current = updated.revision;
    if (apply) {
      const workspace = await agentRequest<{ document: VlxPayload; revision: string }>(
        `/sessions/${id}/workspace`,
      );
      const local = await projectRevision();
      if (local !== workspace.revision)
        await applyAgentSnapshot(workspace.document, browserRevision.current);
      browserRevision.current = workspace.revision;
    }
  }, []);

  useEffect(() => registerEditorCommand('agent.open', () => setOpen(true)), []);
  useEffect(
    () =>
      registerEditorCommand('agent.settings', () => {
        setOpen(true);
        setSettingsOpen(true);
      }),
    [],
  );

  useEffect(() => {
    if (!open) return;
    let alive = true;
    void agentRequest<AgentSettings>('/settings')
      .then((value) => {
        if (alive) setSettings(value);
      })
      .catch((cause: unknown) => {
        if (alive) setError(errorText(cause));
      });
    return () => {
      alive = false;
    };
  }, [open, errorText]);

  useEffect(() => {
    // A different editor project must detach the previous server conversation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSession(null);
    setBusy(false);
    setPartial('');
    partials.current = {};
    seen.current = 0;
    const id = sessionStorage.getItem(`velxio-agent:${projectKey}`);
    if (!id) return;
    let alive = true;
    void agentRequest<AgentSession>(`/sessions/${id}`)
      .then(async (value) => {
        if (!alive) return;
        let local = await projectRevision();
        const baseline = sessionStorage.getItem(`velxio-agent-base:${projectKey}`);
        if (!value.busy && baseline === local && local !== value.revision) {
          const workspace = await agentRequest<{ document: VlxPayload }>(
            `/sessions/${id}/workspace`,
          );
          if (!alive) return;
          await applyAgentSnapshot(workspace.document, local);
          local = await projectRevision();
        }
        if (!alive) return;
        browserRevision.current = local;
        revision.current = value.revision;
        seen.current = value.sequence;
        setSession(value);
        setBusy(value.busy);
      })
      .catch(() => {
        sessionStorage.removeItem(`velxio-agent:${projectKey}`);
      });
    return () => {
      alive = false;
    };
  }, [projectKey]);

  useEffect(() => {
    handler.current = (event) => {
      if (event.event_id <= seen.current) return;
      seen.current = event.event_id;
      const current = sessionRef.current;
      if (!current) return;
      setSession((value) =>
        value ? { ...value, turns: reduceAgentEvent(value.turns ?? [], event) } : value,
      );
      if (
        event.type === 'message.delta' ||
        (event.type === 'part.updated' && event.payload.kind === 'text')
      ) {
        const id = String(event.payload.part_id ?? 'text');
        partials.current[id] =
          event.type === 'message.delta'
            ? (partials.current[id] ?? '') + String(event.payload.text ?? '')
            : String(event.payload.text ?? '');
        setPartial(Object.values(partials.current).join('\n\n'));
      }
      if (event.type === 'message.completed') setPartial(String(event.payload.text ?? ''));
      if (event.type === 'browser.command') {
        void handleAgentBrowserCommand(event.payload)
          .then(async (result) => {
            if (typeof result.applied_revision === 'string')
              browserRevision.current = result.applied_revision;
            await agentRequest(`/sessions/${current.id}/browser-result`, 'POST', {
              command_id: event.payload.command_id,
              browser_id: agentBrowserId(),
              result,
            });
          })
          .catch((cause: unknown) => setError(errorText(cause)));
      }
      if (
        event.type === 'turn.completed' ||
        event.type === 'turn.interrupted' ||
        event.type === 'error'
      ) {
        setBusy(false);
        if (event.type === 'error')
          setError(
            errorText(
              Object.assign(new Error(String(event.payload.message ?? t('agent.errors.generic'))), {
                code: event.payload.code,
              }),
            ),
          );
        void refresh(current.id, true).catch((cause: unknown) => setError(errorText(cause)));
      }
    };
  }, [refresh, errorText, t]);

  useEffect(() => {
    if (!session?.id) return;
    const id = session.id;
    return connectAgentEvents(
      id,
      seen.current,
      (event) => handler.current(event),
      () => {
        void refresh(id, false).catch((cause: unknown) => setError(errorText(cause)));
      },
      (value) => {
        connectionReady.current = value;
        setConnected(value);
      },
    );
  }, [session?.id, refresh, errorText]);

  useEffect(() => {
    if (autoScroll.current) end.current?.scrollIntoView({ block: 'nearest' });
  }, [session?.messages, session?.turns, partial]);

  async function send() {
    if (!message.trim() || busy) return;
    setError('');
    setBusy(true);
    autoScroll.current = true;
    partials.current = {};
    setPartial('');
    try {
      let current = session;
      const document = snapshotForAgent();
      const local = await projectRevision(document);
      if (!current) {
        connectionReady.current = false;
        current = await agentRequest<AgentSession>('/sessions', 'POST', { document });
        setSession(current);
        sessionStorage.setItem(`velxio-agent:${projectKey}`, current.id);
        sessionStorage.setItem(`velxio-agent-base:${projectKey}`, local);
        seen.current = 0;
        // The browser event stream must be connected before the agent can run.
        for (let attempt = 0; attempt < 100 && !connectionReady.current; attempt++)
          await new Promise((resolve) => setTimeout(resolve, 50));
        if (!connectionReady.current) throw new Error(t('agent.errors.editorNotReady'));
      } else {
        current = await agentRequest<AgentSession>(`/sessions/${current.id}/workspace`, 'PATCH', {
          document,
          expected_revision: revision.current,
        });
      }
      revision.current = current.revision;
      browserRevision.current = local;
      const text = message.trim();
      await agentRequest(`/sessions/${current.id}/messages`, 'POST', {
        message: text,
        request_id: generateUUID(),
      });
      const accepted = current;
      setSession((previous) => ({
        ...accepted,
        turns: previous?.turns ?? accepted.turns,
        messages: [...accepted.messages, { role: 'user', content: text }],
      }));
      setMessage('');
    } catch (cause) {
      setError(errorText(cause));
      setBusy(false);
    }
  }

  async function stop() {
    if (!session) return;
    cancelAgentProjectRun();
    try {
      await agentRequest(`/sessions/${session.id}/stop`, 'POST', {});
      const sim = useSimulatorStore.getState();
      sim.boards.filter((board) => board.running).forEach((board) => sim.stopBoard(board.id));
      setBusy(false);
    } catch (cause) {
      setError(errorText(cause));
    }
  }

  async function download() {
    if (!session) return;
    try {
      const value = await agentRequest<{ document: VlxPayload }>(
        `/sessions/${session.id}/workspace`,
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(value.document, null, 2)], { type: 'application/json' }),
      );
      const link = document.createElement('a');
      link.href = url;
      link.download = 'velxio-agent.vlx';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setError(errorText(cause));
    }
  }

  return (
    <>
      {!open && (
        <button className="agent-launcher" type="button" onClick={() => setOpen(true)}>
          <MessageSquare size={17} /> {t('agent.title')}
        </button>
      )}
      {open && (
        <aside className="agent-panel" style={{ width }} aria-label={t('agent.title')}>
          <div
            className="agent-resizer"
            role="separator"
            aria-label={t('agent.resize')}
            aria-orientation="vertical"
            onPointerDown={(event) => {
              const element = event.currentTarget;
              element.setPointerCapture(event.pointerId);
              const move = (next: PointerEvent) =>
                setWidth(Math.min(700, Math.max(300, window.innerWidth - next.clientX)));
              const up = () => {
                element.removeEventListener('pointermove', move);
                element.removeEventListener('pointerup', up);
              };
              element.addEventListener('pointermove', move);
              element.addEventListener('pointerup', up);
            }}
          />
          <header className="agent-panel-header">
            <div>
              <strong>{t('agent.title')}</strong>
              <small>
                {settings.model || t('agent.configure')}{' '}
                {session && `· ${t(connected ? 'agent.connected' : 'agent.reconnecting')}`}
              </small>
            </div>
            <div className="agent-buttons">
              <button
                type="button"
                title={t('agent.newConversation')}
                disabled={busy}
                onClick={() => {
                  setSession(null);
                  setPartial('');
                  setError('');
                  sessionStorage.removeItem(`velxio-agent:${projectKey}`);
                }}
              >
                <Plus size={16} />
              </button>
              <button
                type="button"
                title={t('agent.download')}
                disabled={!session || busy}
                onClick={() => void download()}
              >
                <Download size={16} />
              </button>
              <button
                type="button"
                title={t('agent.settings')}
                onClick={() => setSettingsOpen(true)}
              >
                <Settings size={16} />
              </button>
              <button type="button" title={t('agent.minimize')} onClick={() => setOpen(false)}>
                <X size={17} />
              </button>
            </div>
          </header>
          <div
            className="agent-messages"
            onScroll={(event) => {
              const el = event.currentTarget;
              autoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
            }}
          >
            {!session?.messages.length && (
              <div className="agent-welcome">
                <MessageSquare size={28} />
                <h3>{t('agent.welcomeTitle')}</h3>
                <p>{t('agent.welcomeBody')}</p>
                <button type="button" onClick={() => setSettingsOpen(true)}>
                  {t('agent.configure')}
                </button>
                <button type="button" onClick={() => setMessage(t('agent.examplePrompt'))}>
                  {t('agent.example')}
                </button>
              </div>
            )}
            {session?.messages.map((item, index) => (
              <Fragment key={index}>
                <article className={`agent-message agent-message--${item.role}`}>
                  <small>{t(item.role === 'user' ? 'agent.you' : 'agent.assistant')}</small>
                  <AgentMessageBody text={item.content} />
                </article>
                {item.role === 'user' &&
                  session.turns
                    ?.filter((turn) => turn.message_index === index)
                    .map((turn) => <AgentTimeline key={turn.id} turn={turn} />)}
              </Fragment>
            ))}
            {partial && (
              <article className="agent-message agent-message--assistant">
                <small>{t('agent.assistant')}</small>
                <AgentMessageBody text={partial} />
              </article>
            )}
            {error && (
              <p className="agent-error" role="alert">
                {error}
              </p>
            )}
            <div ref={end} />
          </div>
          <form
            className="agent-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={t('agent.placeholder')}
              aria-label={t('agent.messageLabel')}
              disabled={busy}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <footer>
              <small>{busy ? t('agent.working') : t('agent.yourModel')}</small>
              {busy ? (
                <button type="button" onClick={() => void stop()}>
                  <Square size={14} /> {t('agent.stop')}
                </button>
              ) : (
                <button
                  className="agent-primary"
                  type="submit"
                  disabled={!message.trim() || !settings.model || !settings.available}
                >
                  <Send size={14} /> {t('agent.send')}
                </button>
              )}
            </footer>
          </form>
        </aside>
      )}
      {settingsOpen && (
        <AgentSettingsDialog
          settings={settings}
          onSaved={setSettings}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </>
  );
}
