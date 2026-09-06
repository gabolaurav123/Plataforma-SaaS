'use client';
import { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, RefreshCw, Rocket } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Form } from './forms';
import { BotEditor } from './bot-editor';
import { WorkspaceView } from './workspace-view';
import { type Row, usePlatformSession, openTelegram } from '@/lib/platform-api';
import { es as t } from '@/lib/i18n';

const checkLabels: Record<string, string> = {
  managed_bot: 'Identidad del bot',
  token: 'Credencial protegida',
  webhook: 'Conexión con Telegram',
  welcome: 'Bienvenida',
  plan: 'Plan con precio en Stars',
  payment_method: 'Método de pago',
  channel_permissions: 'Permisos del canal',
  support_and_policies: 'Soporte y políticas',
  test_message: 'Mensaje de prueba',
};
export function Wizard({
  session,
  finish,
}: {
  session: ReturnType<typeof usePlatformSession>;
  finish: () => void;
}) {
  const [step, setStep] = useState(1);
  const [botId, setBotId] = useState('');
  const [bots, setBots] = useState<Row[]>([]);
  const [message, setMessage] = useState('');
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [published, setPublished] = useState('');
  const { call, workspaceId, live } = session;
  const base = 't/' + workspaceId;
  const bot = bots.find((b) => b.id === botId);
  useEffect(() => {
    if (!live || !workspaceId) return;
    void Promise.all([
      call<{ step: number; data: { bot_id?: string } } | null>(
        base + '/onboarding',
      ),
      call<{ items: Row[] }>(base + '/resources/bots'),
    ])
      .then(([saved, list]) => {
        setBots(list.items);
        setBotId(saved?.data?.bot_id || list.items[0]?.id || '');
        setStep(saved?.step || 1);
      })
      .catch((e) => setMessage(e.message));
  }, [live, workspaceId, call, base]);
  useEffect(() => {
    if (step !== 3 || !live || !workspaceId) return;
    const timer = setInterval(() => {
      void call<{ items: Row[] }>(base + '/resources/bots')
        .then((result) => {
          setBots(result.items);
          setBotId((current) => current || result.items[0]?.id || '');
        })
        .catch((e) => setMessage(e.message));
    }, 3500);
    return () => clearInterval(timer);
  }, [step, live, workspaceId, call, base]);
  async function move(next: number) {
    setBusy(true);
    try {
      if (live && workspaceId)
        await call(base + '/onboarding', {
          method: 'PUT',
          body: { step: next, bot_id: botId || null },
        });
      setStep(next);
      setMessage('');
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function verify() {
    try {
      const result = await call<{ checks: Record<string, boolean> }>(
        base + '/bots/' + botId + '/readiness',
      );
      setChecks(result.checks);
    } catch (e) {
      setMessage((e as Error).message);
    }
  }
  return (
    <div className="onboarding-layout">
      <aside className="surface wizard-rail">
        <p className="eyebrow">TU NEGOCIO · {step}/9</p>
        <Progress value={(step / 9) * 100} aria-label="Progreso de creación" />
        <ol>
          {t.wizard.map((label, i) => (
            <li
              className={
                step === i + 1 ? 'current' : step > i + 1 ? 'complete' : ''
              }
              key={label}
            >
              <span>{step > i + 1 ? <Check size={14} /> : i + 1}</span>
              {label}
            </li>
          ))}
        </ol>
        <p className="muted">Tu avance se guarda en tu cuenta.</p>
      </aside>
      <section className="surface wizard-body">
        <p className="eyebrow">PASO {step} DE 9</p>
        <h2>{t.wizard[step - 1]}</h2>
        {!live && (
          <p className="notice">
            Recorre el asistente de ejemplo. Para crear un bot real, abre la
            Mini App desde tu Master Bot.
          </p>
        )}
        {step === 1 &&
          (workspaceId ? (
            <div className="notice">
              Tu cuenta está vinculada a Telegram y tu espacio está creado.
              Puedes continuar.
            </div>
          ) : (
            <Form
              fields={[
                { key: 'name', label: 'Nombre de tu negocio', required: true },
              ]}
              label="Crear mi espacio"
              submit={async (body) => {
                const result = await call<Row>('workspaces', {
                  method: 'POST',
                  body,
                });
                await session.refreshWorkspaces();
                session.setWorkspaceId(result.id);
                setMessage('Espacio creado.');
              }}
            />
          ))}
        {step === 2 && (
          <>
            <p className="muted">
              Empieza con el plan Starter y su prueba configurable. Puedes
              cambiar de plan en Facturación.
            </p>
            <WorkspaceView
              section="billing"
              call={call}
              workspaceId={workspaceId}
              live={live}
              owner={session.owner}
              startWizard={() => {}}
            />
          </>
        )}
        {step === 3 && (
          <>
            <Form
              fields={[
                {
                  key: 'name',
                  label: 'Nombre para tu bot',
                  initial: 'Mi comunidad',
                  required: true,
                },
                {
                  key: 'username',
                  label: 'Nombre de usuario de Telegram',
                  initial: 'mi_comunidad_bot',
                  required: true,
                  hint: 'Debe terminar en bot. Telegram confirmará la disponibilidad.',
                },
              ]}
              label="Crear con Telegram"
              submit={async (body) => {
                const result = await call<{
                  url: string;
                  prepared_button_id: string;
                }>(base + '/bots/create', { method: 'POST', body });
                const tg = window.Telegram?.WebApp;
                if (tg?.requestChat && tg.isVersionAtLeast?.('9.6'))
                  tg.requestChat(result.prepared_button_id);
                else openTelegram(result.url);
                setMessage(
                  'Confirma la creación en Telegram. El bot aparecerá aquí automáticamente.',
                );
              }}
            />
            {bots.map((item) => (
              <Button
                key={item.id}
                variant={item.id === botId ? 'secondary' : 'outline'}
                onClick={() => setBotId(item.id)}
                className="bot-option"
              >
                {String(item.name)} · {String(item.status)}
              </Button>
            ))}
          </>
        )}
        {step === 4 && (
          <BotEditor
            botId={botId || 'demo-bot'}
            base={base}
            call={call}
            live={live}
          />
        )}
        {step === 5 && (
          <WorkspaceView
            section="channels"
            call={call}
            workspaceId={workspaceId}
            live={live}
            owner={session.owner}
            startWizard={() => {}}
          />
        )}
        {step === 6 && (
          <WorkspaceView
            section="plans"
            call={call}
            workspaceId={workspaceId}
            live={live}
            owner={session.owner}
            startWizard={() => {}}
          />
        )}
        {step === 7 && (
          <WorkspaceView
            section="settings"
            call={call}
            workspaceId={workspaceId}
            live={live}
            owner={session.owner}
            startWizard={() => {}}
          />
        )}
        {step === 8 && (
          <>
            <p className="muted">
              Abre tu bot y pulsa Start para que pueda enviarte el mensaje de
              prueba. El sistema revisará la conexión y todos los requisitos al
              publicar.
            </p>
            {bot?.username && (
              <Button
                variant="outline"
                onClick={() =>
                  openTelegram('https://t.me/' + String(bot.username))
                }
              >
                Abrir mi bot
              </Button>
            )}
            <Button
              variant="outline"
              onClick={() => {
                void verify();
              }}
            >
              <RefreshCw />
              Revisar requisitos
            </Button>
            <div className="checklist">
              {Object.entries(checks).map(([key, ok]) => (
                <div key={key} className={ok ? 'check-ok' : 'check-pending'}>
                  <span>{ok ? '✓' : '○'}</span>
                  {checkLabels[key] || key}
                </div>
              ))}
            </div>
          </>
        )}
        {step === 9 && (
          <div className="publish-step">
            <Rocket size={46} />
            <h2>
              {published
                ? 'Tu bot está listo'
                : 'Todo listo para la última revisión'}
            </h2>
            <p>
              Comprobaremos tu bot, sus permisos y métodos de pago antes de
              abrirlo a tus clientes.
            </p>
            {published ? (
              <div className="row">
                <Button onClick={() => openTelegram(published)}>
                  Abrir mi bot
                </Button>
                <Button variant="outline" onClick={finish}>
                  Volver al panel
                </Button>
              </div>
            ) : (
              <Button
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const result = await call<{
                      ready: boolean;
                      url?: string;
                      checks: Record<string, boolean>;
                    }>(base + '/bots/' + botId + '/publish', {
                      method: 'POST',
                    });
                    setChecks(result.checks);
                    if (result.ready && result.url) setPublished(result.url);
                    else {
                      setStep(8);
                      setMessage(
                        'Completa los requisitos pendientes antes de publicar.',
                      );
                    }
                  } catch (e) {
                    setMessage((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Publicar mi bot
                <Rocket />
              </Button>
            )}
          </div>
        )}
        {message && <output className="notice">{message}</output>}
        <div className="wizard-controls">
          <Button
            variant="outline"
            onClick={() => {
              void move(Math.max(1, step - 1));
            }}
            disabled={step === 1 || busy}
          >
            <ArrowLeft />
            Atrás
          </Button>
          {step < 9 && (
            <Button
              onClick={() => {
                void move(step + 1);
              }}
              disabled={
                busy || (live && !workspaceId) || (live && step === 3 && !botId)
              }
            >
              Continuar
              <ArrowRight />
            </Button>
          )}
        </div>
      </section>
    </div>
  );
}
