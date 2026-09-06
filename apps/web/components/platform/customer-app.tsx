'use client';
import { display } from '@/lib/platform-api';
import { useCallback, useEffect, useState } from 'react';
import {
  Bot,
  Check,
  ChevronRight,
  Home,
  Layers,
  CalendarCheck,
  CreditCard,
  MessageCircle,
  UserRound,
  Star,
} from 'lucide-react';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Form } from './forms';
import {
  usePlatformSession,
  type Row,
  invoice,
  money,
  date,
} from '@/lib/platform-api';

type Profile = {
  bot: { name: string; username: string };
  branding: { color?: string };
  policies: Record<string, string>;
  contact: Row;
  subscriptions: Row[];
  payments: Row[];
  support_username: string;
};
const nav = [
  ['home', 'Inicio', Home],
  ['plans', 'Planes', Layers],
  ['subscriptions', 'Membresía', CalendarCheck],
  ['payments', 'Pagos', CreditCard],
  ['support', 'Soporte', MessageCircle],
  ['profile', 'Perfil', UserRound],
] as const;
export function CustomerApp({ publicId }: { publicId: string }) {
  const session = usePlatformSession(publicId);
  const [tab, setTab] = useState('home');
  const [profile, setProfile] = useState<Profile | null>(null);
  const [plans, setPlans] = useState<Row[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [coupon, setCoupon] = useState('');
  const { call, live } = session;
  const base = 'b/' + publicId;
  const refresh = useCallback(async () => {
    if (!live) return;
    try {
      const [data, items] = await Promise.all([
        call<Profile>(base + '/me'),
        call<Row[]>(base + '/plans'),
      ]);
      setProfile(data);
      setPlans(items);
      setError('');
    } catch (e) {
      setError((e as Error).message);
    }
  }, [call, base, live]);
  useEffect(() => {
    void Promise.resolve().then(refresh);
  }, [refresh]);
  const demo = publicId === 'demo' && !session.inTelegram;
  const shownPlans = demo
    ? [
        {
          id: 'demo-plan',
          name: 'Premium',
          description:
            'Tu espacio para aprender, compartir y crecer junto a nuestra comunidad.',
          benefits: [
            'Acceso al canal privado',
            'Contenido exclusivo cada semana',
            'Una comunidad para conectar',
          ],
          duration_days: 30,
          prices: [{ amount_minor: '500', currency: 'XTR' }],
        },
      ]
    : plans;
  const brandColor =
    profile?.branding.color && /^#[0-9a-fA-F]{6}$/.test(profile.branding.color)
      ? profile.branding.color
      : '#2864ef';
  if (session.inTelegram && session.error)
    return (
      <main className="auth-screen surface">
        <h1>Tu membresía</h1>
        <p className="error-box">{session.error}</p>
        <Button onClick={() => window.location.reload()}>Reintentar</Button>
      </main>
    );
  return (
    <main
      className="customer-app"
      style={{ '--primary': brandColor } as React.CSSProperties}
    >
      <header className="customer-header">
        <span className="brand-icon">
          <Bot />
        </span>
        <div>
          <h1>{profile?.bot.name || 'Studio Club'}</h1>
          <p>Tu comunidad privada</p>
        </div>
        <span className="customer-avatar">{session.userName.slice(0, 1)}</span>
      </header>
      {!live && (
        <p className="demo-label">
          {demo
            ? 'Vista de ejemplo · Datos ficticios'
            : 'Abre esta Mini App desde su bot en Telegram.'}
        </p>
      )}
      <Tabs value={tab} onValueChange={(v) => setTab(display(v))}>
        <TabsList className="customer-nav">
          {nav.map(([key, label, Icon]) => (
            <TabsTrigger key={key} value={key}>
              <Icon size={18} />
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {session.loading && (
        <output className="muted">Conectando con Telegram…</output>
      )}
      {(error || session.error) && (
        <div className="error-box" role="alert">
          {error || session.error}
        </div>
      )}
      {(tab === 'home' || tab === 'plans') && (
        <>
          <div className="customer-intro">
            <p className="eyebrow">TU SIGUIENTE PASO</p>
            <h2>
              {tab === 'home'
                ? `Hola, ${display(profile?.contact.first_name || 'bienvenido')} 👋`
                : 'Elige tu membresía'}
            </h2>
            <p>Todo lo que necesitas para ser parte de la comunidad.</p>
          </div>
          {shownPlans.map((plan) => (
            <section className="customer-plan surface" key={plan.id}>
              <span className="pill">
                {Number(plan.duration_days)} días de acceso
              </span>
              <h2>{display(plan.name)}</h2>
              <p>{display(plan.description)}</p>
              <div className="customer-price">
                {money((plan.prices as Row[])?.[0]?.amount_minor)}
                <small> / {Number(plan.duration_days)} días</small>
              </div>
              <ul>
                {((plan.benefits || []) as string[]).map((benefit) => (
                  <li key={benefit}>
                    <Check size={18} />
                    {benefit}
                  </li>
                ))}
              </ul>
              <Button
                className="full"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const result = await call<{ url: string }>(
                      base + '/checkout',
                      {
                        method: 'POST',
                        body: {
                          plan_id: plan.id,
                          idempotency_key: crypto.randomUUID(),
                          coupon_code: coupon || null,
                        },
                      },
                    );
                    invoice(result.url);
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Star size={17} />
                Suscribirme con Stars
                <ChevronRight />
              </Button>
              <p className="payment-trust">Pago seguro con Telegram Stars</p>
            </section>
          ))}
          {!shownPlans.length && live && (
            <p className="empty-state">
              No hay planes publicados por el momento.
            </p>
          )}
          <label className="field" htmlFor="coupon-code">
            <span>¿Tienes un cupón?</span>
            <Input
              id="coupon-code"
              value={coupon}
              onChange={(e) => setCoupon(e.target.value)}
              placeholder="Código de promoción"
            />
          </label>
        </>
      )}
      {tab === 'subscriptions' && (
        <>
          <div className="section-heading">
            <h2>Mi suscripción</h2>
            <Button
              variant="outline"
              onClick={() => {
                void refresh();
              }}
            >
              Actualizar
            </Button>
          </div>
          {profile?.subscriptions.map((sub) => (
            <section className="surface" key={sub.id}>
              <h2>
                {sub.status === 'ACTIVE'
                  ? 'Membresía activa'
                  : 'Membresía vencida'}
              </h2>
              <p className="muted">Acceso hasta {date(sub.expires_at)}</p>
              <p>
                Renovación automática:{' '}
                {sub.auto_renew ? 'activada' : 'desactivada'}
              </p>
              {Boolean(sub.initial_charge_id) && (
                <Button
                  variant="outline"
                  onClick={async () => {
                    try {
                      await call(
                        base + '/subscriptions/' + sub.id + '/renewal',
                        {
                          method: 'POST',
                          body: { canceled: Boolean(sub.auto_renew) },
                        },
                      );
                      await refresh();
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  {sub.auto_renew
                    ? 'Cancelar renovación automática'
                    : 'Reactivar renovación'}
                </Button>
              )}
            </section>
          ))}
          {!profile?.subscriptions.length && (
            <p className="empty-state">
              Aún no tienes una membresía. Explora los planes disponibles.
            </p>
          )}
          <p className="notice">
            Al cancelar la renovación conservas el acceso hasta el final del
            periodo pagado.
          </p>
        </>
      )}
      {tab === 'payments' && (
        <>
          <div className="section-heading">
            <h2>Mis pagos</h2>
            <Button
              variant="outline"
              onClick={() => {
                void refresh();
              }}
            >
              Actualizar
            </Button>
          </div>
          {profile?.payments.map((payment) => (
            <section className="surface" key={payment.id}>
              <strong>{money(payment.amount_minor, payment.currency)}</strong>
              <p>
                {display(payment.status)} · {date(payment.created_at)}
              </p>
              {payment.provider === 'BANK_TRANSFER' &&
                ['PENDING', 'RECEIPT_SUBMITTED'].includes(
                  display(payment.status),
                ) && (
                  <label className="field" htmlFor={'receipt-' + payment.id}>
                    <span>Adjuntar comprobante de este pedido externo</span>
                    <Input
                      id={'receipt-' + payment.id}
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        const form = new FormData();
                        form.append('file', file);
                        void call(
                          base + '/payments/' + payment.id + '/receipt',
                          { method: 'POST', form },
                        )
                          .then(refresh)
                          .catch((error) => setError(error.message));
                      }}
                    />
                  </label>
                )}
            </section>
          ))}
          {!profile?.payments.length && (
            <p className="empty-state">Tus pagos aparecerán aquí.</p>
          )}
        </>
      )}
      {tab === 'support' && (
        <section className="surface">
          <h2>Estamos para ayudarte</h2>
          <p className="muted">
            Tu mensaje llegará al equipo de esta comunidad.
          </p>
          <Form
            fields={[
              {
                key: 'text',
                label: 'Tu consulta',
                type: 'textarea',
                required: true,
              },
            ]}
            label="Enviar consulta"
            submit={async (body) => {
              await call(base + '/support', { method: 'POST', body });
            }}
          />
        </section>
      )}
      {tab === 'profile' && (
        <section className="surface">
          <h2>{display(profile?.contact.first_name || 'Tu perfil')}</h2>
          <p className="muted">
            {profile?.contact.username
              ? '@' + display(profile.contact.username)
              : 'Conectado con Telegram'}
          </p>
          {Object.entries(profile?.policies || {}).map(([key, value]) => (
            <details key={key}>
              <summary>
                {{
                  terms: 'Términos',
                  privacy: 'Privacidad',
                  refund: 'Reembolsos',
                }[key] || key}
              </summary>
              <p className="policy-text">{value}</p>
            </details>
          ))}
        </section>
      )}
    </main>
  );
}
