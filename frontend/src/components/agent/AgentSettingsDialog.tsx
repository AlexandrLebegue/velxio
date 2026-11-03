import { useState } from 'react';
import { agentRequest } from '../../services/agentService';
import type { AgentSettings } from '../../services/agentService';

interface Props {
  settings: AgentSettings;
  onSaved: (settings: AgentSettings) => void;
  onClose: () => void;
}

export function AgentSettingsDialog({ settings, onSaved, onClose }: Props) {
  const [form, setForm] = useState<AgentSettings>({ ...settings, api_key: '' });
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [failed, setFailed] = useState(false);

  async function action(test: boolean) {
    setBusy(true);
    setStatus('');
    setFailed(false);
    const payload = {
      base_url: form.base_url,
      model: form.model,
      api_key: form.api_key || null,
      clear_api_key: !!form.clear_api_key,
      max_steps: form.max_steps,
      timeout_seconds: form.timeout_seconds,
    };
    try {
      if (test) {
        const result = await agentRequest<{ ok: boolean; message: string }>(
          '/settings/test',
          'POST',
          payload,
        );
        setFailed(!result.ok);
        setStatus(result.message);
      } else {
        onSaved(await agentRequest<AgentSettings>('/settings', 'PUT', payload));
        onClose();
      }
    } catch (error) {
      setFailed(true);
      setStatus(error instanceof Error ? error.message : 'La connexion a échoué.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="agent-settings-backdrop" onClick={onClose}>
      <section
        className="agent-settings"
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-settings-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <h2 id="agent-settings-title">Connexion au modèle IA</h2>
          <button type="button" onClick={onClose} aria-label="Fermer les paramètres">
            ×
          </button>
        </header>
        <p>Le moteur OpenCode utilise cette connexion pour modifier et simuler le projet ouvert.</p>
        {!settings.available && (
          <p className="agent-error">
            OpenCode est indisponible sur le serveur Velxio. Installer la version 1.19.3, puis
            vérifier VELXIO_OPENCODE_BIN.
          </p>
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void action(false);
          }}
        >
          <label>
            URL de base du LLM
            <input
              type="url"
              required
              value={form.base_url}
              placeholder="http://127.0.0.1:11434/v1"
              onChange={(event) => setForm({ ...form, base_url: event.target.value })}
            />
          </label>
          <small>
            API compatible Chat Completions. L’adresse doit être accessible depuis le serveur Velxio
            ; localhost désigne la machine du moteur, ou son conteneur.
          </small>
          <label>
            Identifiant du modèle
            <input
              required
              value={form.model}
              placeholder="Nom exact du modèle servi"
              onChange={(event) => setForm({ ...form, model: event.target.value })}
            />
          </label>
          <label>
            Clé API <span>(facultative)</span>
            <input
              type="password"
              autoComplete="new-password"
              value={form.api_key}
              placeholder={
                settings.has_api_key
                  ? 'Clé enregistrée ; laisser vide pour la conserver'
                  : 'Aucune clé pour un serveur local sans authentification'
              }
              onChange={(event) =>
                setForm({ ...form, api_key: event.target.value, clear_api_key: false })
              }
            />
          </label>
          {settings.has_api_key && (
            <label className="agent-checkbox">
              <input
                type="checkbox"
                checked={!!form.clear_api_key}
                onChange={(event) => setForm({ ...form, clear_api_key: event.target.checked })}
              />{' '}
              Supprimer la clé enregistrée
            </label>
          )}
          <details>
            <summary>Limites du moteur</summary>
            <label>
              Étapes maximum
              <input
                type="number"
                min={1}
                max={100}
                value={form.max_steps}
                onChange={(event) => setForm({ ...form, max_steps: Number(event.target.value) })}
              />
            </label>
            <label>
              Durée maximum d’un tour (secondes)
              <input
                type="number"
                min={30}
                max={1800}
                value={form.timeout_seconds}
                onChange={(event) =>
                  setForm({ ...form, timeout_seconds: Number(event.target.value) })
                }
              />
            </label>
          </details>
          {status && (
            <p role="status" className={failed ? 'agent-error' : 'agent-success'}>
              {status}
            </p>
          )}
          <footer>
            <button type="button" disabled={busy || !form.model} onClick={() => void action(true)}>
              {busy ? 'Connexion…' : 'Tester la connexion'}
            </button>
            <button className="agent-primary" type="submit" disabled={busy}>
              Enregistrer
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}
