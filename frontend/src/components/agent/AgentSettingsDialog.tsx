import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { agentRequest } from '../../services/agentService';
import type { AgentSettings } from '../../services/agentService';

interface Props {
  settings: AgentSettings;
  onSaved: (settings: AgentSettings) => void;
  onClose: () => void;
}

export function AgentSettingsDialog({ settings, onSaved, onClose }: Props) {
  const { t, i18n } = useTranslation();
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
      max_output_tokens: form.max_output_tokens ?? 8192,
      context_window: form.context_window ?? 65536,
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
        setStatus(t(result.ok ? 'agent.testPassed' : 'agent.testMissingTools'));
      } else {
        onSaved(await agentRequest<AgentSettings>('/settings', 'PUT', payload));
        onClose();
      }
    } catch (error) {
      setFailed(true);
      const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : '';
      setStatus(
        code && i18n.exists(`agent.errors.${code}`)
          ? t(`agent.errors.${code}`)
          : error instanceof Error
            ? error.message
            : t('agent.errors.generic'),
      );
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
          <h2 id="agent-settings-title">{t('agent.settingsTitle')}</h2>
          <button type="button" onClick={onClose} aria-label={t('agent.closeSettings')}>
            ×
          </button>
        </header>
        <p>{t('agent.settingsBody')}</p>
        {!settings.available && <p className="agent-error">{t('agent.unavailable')}</p>}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void action(false);
          }}
        >
          <label>
            {t('agent.baseUrl')}
            <input
              type="url"
              required
              value={form.base_url}
              placeholder="http://127.0.0.1:11434/v1"
              onChange={(event) => setForm({ ...form, base_url: event.target.value })}
            />
          </label>
          <small>{t('agent.urlHelp')}</small>
          <label>
            {t('agent.model')}
            <input
              required
              value={form.model}
              placeholder={t('agent.modelPlaceholder')}
              onChange={(event) => setForm({ ...form, model: event.target.value })}
            />
          </label>
          <label>
            <span>
              {t('agent.apiKey')} ({t('agent.optional')})
            </span>
            <input
              type="password"
              autoComplete="new-password"
              value={form.api_key}
              placeholder={settings.has_api_key ? t('agent.keySaved') : t('agent.keyEmpty')}
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
              {t('agent.removeKey')}
            </label>
          )}
          <details>
            <summary>{t('agent.limits')}</summary>
            <label>
              {t('agent.maxOutputTokens')}
              <input
                type="number"
                min={512}
                max={32768}
                value={form.max_output_tokens ?? 8192}
                onChange={(event) =>
                  setForm({ ...form, max_output_tokens: Number(event.target.value) })
                }
              />
            </label>
            <small>{t('agent.outputTokensHelp')}</small>
            <label>
              {t('agent.contextWindow')}
              <input
                type="number"
                min={4096}
                max={2000000}
                value={form.context_window ?? 65536}
                onChange={(event) =>
                  setForm({ ...form, context_window: Number(event.target.value) })
                }
              />
            </label>
            <small>{t('agent.contextWindowHelp')}</small>
            <label>
              {t('agent.maxSteps')}
              <input
                type="number"
                min={1}
                max={100}
                value={form.max_steps}
                onChange={(event) => setForm({ ...form, max_steps: Number(event.target.value) })}
              />
            </label>
            <label>
              {t('agent.timeout')}
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
              {busy ? t('agent.testing') : t('agent.test')}
            </button>
            <button className="agent-primary" type="submit" disabled={busy}>
              {t('agent.save')}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}
