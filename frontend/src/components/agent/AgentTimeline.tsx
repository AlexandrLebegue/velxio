import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import { Check, ChevronRight, Circle, LoaderCircle, Square, X } from 'lucide-react';
import type { AgentTurn } from '../../services/agentService';
import { splitAgentThinking } from '../../services/agentText';

export function AgentThinking({ text }: { text: string }) {
  const { t } = useTranslation();
  if (!text.trim()) return null;
  return (
    <details className="agent-thinking">
      <summary>
        <ChevronRight size={13} />
        {t('agent.thinking')}
      </summary>
      <div className="agent-thinking-body">
        <ReactMarkdown>{text}</ReactMarkdown>
      </div>
    </details>
  );
}

export function AgentMessageBody({ text }: { text: string }) {
  const parsed = splitAgentThinking(text);
  return (
    <>
      <AgentThinking text={parsed.thinking} />
      <div className="agent-answer">
        <ReactMarkdown>{parsed.answer}</ReactMarkdown>
      </div>
    </>
  );
}

export function AgentTimeline({ turn }: { turn: AgentTurn }) {
  const { t } = useTranslation();
  const reasoning = Object.values(turn.reasoning).join('\n\n');
  return (
    <section className="agent-turn" aria-label={t('agent.steps')}>
      <AgentThinking text={reasoning} />
      {turn.steps.length > 0 && (
        <ol className="agent-steps">
          {turn.steps.map((step) => {
            const running = step.status === 'running' || step.status === 'pending';
            const Icon = running
              ? LoaderCircle
              : step.status === 'completed'
                ? Check
                : step.status === 'error'
                  ? X
                  : Square;
            const label = t(`agent.tools.${step.name}`, { defaultValue: step.title || step.name });
            const details =
              step.summary && step.summary !== '{}'
                ? step.summary
                : step.title !== step.name && step.title !== label
                  ? step.title
                  : '';
            return (
              <li key={step.id} className={`agent-step agent-step--${step.status}`}>
                <Icon size={14} className={running ? 'agent-spin' : ''} />
                <div>
                  {details ? (
                    <details>
                      <summary>
                        <span className="agent-step-name">{label}</span>
                        <span>{t(`agent.status.${step.status}`)}</span>
                      </summary>
                      <pre>{details}</pre>
                    </details>
                  ) : (
                    <div className="agent-step-label">
                      <span className="agent-step-name">{label}</span>
                      <span>{t(`agent.status.${step.status}`)}</span>
                    </div>
                  )}
                </div>
                {step.duration_ms !== undefined && (
                  <time>{(step.duration_ms / 1000).toFixed(1)}s</time>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {turn.status === 'running' && (
        <div className="agent-phase" role="status">
          <Circle size={9} />
          {t(
            `agent.phase.${turn.steps.some((step) => step.status === 'running') ? 'executing' : turn.phase}`,
          )}
        </div>
      )}
    </section>
  );
}
