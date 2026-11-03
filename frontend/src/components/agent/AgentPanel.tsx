import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
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
import './AgentPanel.css';

const defaults: AgentSettings = {
  base_url: 'http://127.0.0.1:11434/v1',
  model: '',
  max_steps: 20,
  timeout_seconds: 300,
};
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : 'L’agent a rencontré une erreur.';

export function AgentPanel() {
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState(defaults);
  const [session, setSession] = useState<AgentSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [message, setMessage] = useState('');
  const [partial, setPartial] = useState('');
  const [activity, setActivity] = useState('');
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
  const handler = useRef<(event: AgentEvent) => void>(() => {});
  const sessionRef = useRef(session);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    const app = document.querySelector<HTMLElement>('.app');
    if (!app || !open) return;
    app.dataset.connectableAgentOpen = 'true';
    app.style.setProperty('--connectable-agent-width', `${width + 24}px`);
    return () => {
      delete app.dataset.connectableAgentOpen;
      app.style.removeProperty('--connectable-agent-width');
    };
  }, [open, width]);

  const refresh = useCallback(async (id: string, apply: boolean) => {
    const updated = await agentRequest<AgentSession>(`/sessions/${id}`);
    if (sessionRef.current?.id !== id) return;
    setSession(updated);
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
  }, [open]);

  useEffect(() => {
    // A different editor project must detach the previous server conversation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSession(null);
    setBusy(false);
    setPartial('');
    seen.current = 0;
    const id = sessionStorage.getItem(`velxio-agent:${projectKey}`);
    if (!id) return;
    let alive = true;
    void agentRequest<AgentSession>(`/sessions/${id}`)
      .then(async (value) => {
        if (!alive) return;
        const local = await projectRevision();
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
      if (event.type === 'message.delta')
        setPartial((value) => value + String(event.payload.text ?? ''));
      if (event.type === 'tool.state')
        setActivity(`${event.payload.title ?? event.payload.name} · ${event.payload.status ?? ''}`);
      if (event.type === 'browser.command') {
        setActivity(
          event.payload.action === 'run'
            ? 'Compilation et lancement dans Velxio…'
            : 'Observation de la simulation…',
        );
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
        setActivity('');
        setPartial('');
        if (event.type === 'error')
          setError(String(event.payload.message ?? 'Connexion interrompue.'));
        void refresh(current.id, true).catch((cause: unknown) => setError(errorText(cause)));
      }
    };
  }, [refresh]);

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
  }, [session?.id, refresh]);

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' });
  }, [session?.messages, partial, activity]);

  async function send() {
    if (!message.trim() || busy) return;
    setError('');
    setBusy(true);
    try {
      let current = session;
      const document = snapshotForAgent();
      const local = await projectRevision(document);
      if (!current) {
        connectionReady.current = false;
        current = await agentRequest<AgentSession>('/sessions', 'POST', { document });
        setSession(current);
        sessionStorage.setItem(`velxio-agent:${projectKey}`, current.id);
        seen.current = 0;
        // The browser event stream must be connected before the agent can run.
        for (let attempt = 0; attempt < 100 && !connectionReady.current; attempt++)
          await new Promise((resolve) => setTimeout(resolve, 50));
        if (!connectionReady.current)
          throw new Error(
            'La connexion avec l’éditeur n’est pas prête. Réessayez dans quelques secondes.',
          );
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
      setSession({ ...current, messages: [...current.messages, { role: 'user', content: text }] });
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
      setActivity('');
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
          <MessageSquare size={17} /> Agent IA
        </button>
      )}
      {open && (
        <aside className="agent-panel" style={{ width }} aria-label="Agent IA Velxio">
          <div
            className="agent-resizer"
            role="separator"
            aria-label="Largeur du panneau"
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
              <strong>Agent IA</strong>
              <small>
                {settings.model || 'Connecter un modèle'}{' '}
                {session && (connected ? '· connecté' : '· reconnexion…')}
              </small>
            </div>
            <div className="agent-buttons">
              <button
                type="button"
                title="Nouvelle conversation"
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
                title="Télécharger le projet de l’agent"
                disabled={!session || busy}
                onClick={() => void download()}
              >
                <Download size={16} />
              </button>
              <button type="button" title="Paramètres IA" onClick={() => setSettingsOpen(true)}>
                <Settings size={16} />
              </button>
              <button type="button" title="Réduire le panneau" onClick={() => setOpen(false)}>
                <X size={17} />
              </button>
            </div>
          </header>
          <div className="agent-messages" aria-live="polite">
            {!session?.messages.length && (
              <div className="agent-welcome">
                <MessageSquare size={28} />
                <h3>Du code à la simulation</h3>
                <p>
                  Décris ce que tu veux construire. L’agent travaille sur le projet ouvert et peut
                  lancer les cartes AVR puis lire la sortie série.
                </p>
                <button type="button" onClick={() => setSettingsOpen(true)}>
                  Configurer mon modèle
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setMessage(
                      'Fais clignoter la LED et affiche son état sur le port série. Lance la simulation et vérifie la sortie.',
                    )
                  }
                >
                  Essayer avec une LED
                </button>
              </div>
            )}
            {session?.messages.map((item, index) => (
              <article key={index} className={`agent-message agent-message--${item.role}`}>
                <small>{item.role === 'user' ? 'Vous' : 'Agent'}</small>
                <ReactMarkdown>{item.content}</ReactMarkdown>
              </article>
            ))}
            {partial && (
              <article className="agent-message agent-message--assistant">
                <small>Agent</small>
                <ReactMarkdown>{partial}</ReactMarkdown>
              </article>
            )}
            {activity && (
              <p className="agent-activity" role="status">
                {activity}
              </p>
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
              placeholder="Décris ton projet ou la modification…"
              aria-label="Message à l’agent"
              disabled={busy}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <footer>
              <small>{busy ? 'L’agent travaille sur ce projet' : 'OpenCode · votre modèle'}</small>
              {busy ? (
                <button type="button" onClick={() => void stop()}>
                  <Square size={14} /> Arrêter
                </button>
              ) : (
                <button
                  className="agent-primary"
                  type="submit"
                  disabled={!message.trim() || !settings.model || !settings.available}
                >
                  <Send size={14} /> Envoyer
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
