'use client';
import Image from 'next/image';
import { display } from '@/lib/platform-api';
import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, RefreshCw, Plus, Download, Star } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableHeader,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from '@/components/ui/table';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Form, type Field } from './forms';
import { BotEditor } from './bot-editor';
import { OwnerPanel } from './owner-panel';
import {
  type Call,
  type Row,
  money,
  date,
  openTelegram,
  invoice,
} from '@/lib/platform-api';
import { es as t } from '@/lib/i18n';

const states: Record<string, string> = {
  READY: 'Listo',
  ACTIVE: 'Activo',
  LEAD: 'Nuevo',
  TRIAL: 'Prueba',
  PENDING: 'Pendiente',
  APPROVED: 'Aprobado',
  REJECTED: 'Rechazado',
  RECEIPT_SUBMITTED: 'Comprobante recibido',
  EXPIRED: 'Vencido',
  DRAFT: 'Borrador',
  SCHEDULED: 'Programada',
  RUNNING: 'En curso',
  PAUSED: 'Pausada',
  COMPLETED: 'Completada',
  CONNECTED: 'Conectado',
  PERMISSIONS_MISSING: 'Faltan permisos',
  SUSPENDED: 'Suspendido',
  PROVISIONING: 'Configurando',
  PROVISIONING_FAILED: 'Configuración fallida',
  OPEN: 'Abierta',
  REFUNDED: 'Reembolsado',
  DELIVERY_UNKNOWN: 'Entrega por verificar',
};
const demoRows: Record<string, Row[]> = {
  bots: [
    {
      id: 'demo-bot',
      name: 'Studio Club',
      username: 'studio_club_example_bot',
      status: 'READY',
      public_id: 'demo',
    },
  ],
  contacts: [
    { id: 'c1', first_name: 'Lucía M.', stage: 'ACTIVE', source: 'instagram' },
    { id: 'c2', first_name: 'Diego P.', stage: 'ACTIVE', source: 'telegram' },
    {
      id: 'c3',
      first_name: 'Ana S.',
      stage: 'RECEIPT_SUBMITTED',
      source: 'instagram',
    },
  ],
  plans: [
    { id: 'p1', name: 'Premium · 30 días', duration_days: 30, active: true },
  ],
  payments: [
    {
      id: 'p2',
      provider: 'TELEGRAM_STARS',
      amount_minor: '500',
      currency: 'XTR',
      status: 'APPROVED',
    },
  ],
  receipts: [
    { id: 'r1', status: 'PENDING', duplicate: false },
    { id: 'r2', status: 'PENDING', duplicate: true },
  ],
  subscriptions: [
    { id: 's1', status: 'ACTIVE', expires_at: 1790726400, auto_renew: true },
  ],
  channels: [
    {
      id: 'ch1',
      title: 'Studio Members',
      status: 'CONNECTED',
      access_mode: 'PLATFORM',
    },
  ],
  campaigns: [
    {
      id: 'ca1',
      name: 'Bienvenida de septiembre',
      status: 'DRAFT',
      text: 'Hola {{first_name}}, descubre las novedades del club.',
    },
  ],
  automations: [
    {
      id: 'au1',
      name: 'Bienvenida a nuevos clientes',
      trigger: 'START',
      action: 'SEND_MESSAGE',
      active: true,
    },
  ],
  conversations: [{ id: 'cv1', contact_id: 'Lucía M.', status: 'OPEN' }],
  team: [{ id: 'tm1', role: 'OWNER', active: true }],
  billing: [{ id: 'bs1', status: 'TRIAL', kind: 'SAAS_SUBSCRIPTION' }],
};
const columns: Record<string, [string, string][]> = {
  bots: [
    ['name', 'Bot'],
    ['username', 'Usuario'],
    ['status', 'Estado'],
  ],
  contacts: [
    ['first_name', 'Cliente'],
    ['stage', 'Etapa'],
    ['source', 'Origen'],
  ],
  plans: [
    ['name', 'Plan'],
    ['duration_days', 'Días'],
    ['active', 'Activo'],
  ],
  payments: [
    ['provider', 'Método'],
    ['amount_minor', 'Importe'],
    ['status', 'Estado'],
  ],
  receipts: [
    ['created_at', 'Recibido'],
    ['status', 'Estado'],
    ['duplicate', 'Posible duplicado'],
  ],
  subscriptions: [
    ['status', 'Estado'],
    ['expires_at', 'Vencimiento'],
    ['auto_renew', 'Renovación automática'],
  ],
  channels: [
    ['title', 'Canal'],
    ['status', 'Estado'],
    ['access_mode', 'Gestión'],
  ],
  conversations: [
    ['contact_id', 'Cliente'],
    ['status', 'Estado'],
  ],
  campaigns: [
    ['name', 'Campaña'],
    ['status', 'Estado'],
    ['scheduled_at', 'Programada'],
  ],
  automations: [
    ['name', 'Regla'],
    ['trigger', 'Cuando'],
    ['action', 'Acción'],
  ],
  coupons: [
    ['code', 'Cupón'],
    ['percent_off', 'Descuento %'],
    ['expires_at', 'Vencimiento'],
  ],
  referrals: [
    ['referrer_id', 'Recomendó'],
    ['referred_id', 'Nuevo cliente'],
    ['status', 'Estado'],
  ],
  team: [
    ['user_id', 'Miembro'],
    ['role', 'Rol'],
    ['active', 'Activo'],
  ],
  billing: [
    ['status', 'Estado'],
    ['trial_ends_at', 'Fin de prueba'],
    ['current_period_end', 'Fin del periodo'],
  ],
};
type Props = {
  section: string;
  call: Call;
  workspaceId: string;
  live: boolean;
  owner: boolean;
  startWizard: () => void;
};
export function WorkspaceView({
  section,
  call,
  workspaceId,
  live,
  owner,
  startWizard,
}: Props) {
  const base = `t/${workspaceId}`;
  const [rows, setRows] = useState<Row[]>([]);
  const [bots, setBots] = useState<Row[]>([]);
  const [channels, setChannels] = useState<Row[]>([]);
  const [botId, setBotId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [after, setAfter] = useState<string | null>(null);
  const [dialog, setDialog] = useState(false);
  const [selected, setSelected] = useState<Row | null>(null);
  const [search, setSearch] = useState('');
  const [stats, setStats] = useState<Record<string, unknown>>({});
  const refresh = useCallback(
    async (cursor?: string) => {
      setError('');
      setBusy(true);
      try {
        if (!live) {
          setRows(demoRows[section] || []);
          setBots(demoRows.bots);
          setChannels(demoRows.channels);
          setBotId('demo-bot');
          return;
        }
        if (!workspaceId && section !== 'owner' && section !== 'support')
          return;
        if (section === 'owner') {
          if (owner) setStats(await call('owner/health'));
          return;
        }
        if (section === 'settings' || section === 'support') return;
        const list = await call<{ items: Row[] }>(base + '/resources/bots');
        setBots(list.items);
        if (section === 'plans') {
          const channelList = await call<{ items: Row[] }>(
            base + '/resources/channels',
          );
          setChannels(channelList.items);
        }
        setBotId((current) => current || list.items[0]?.id || '');
        if (section === 'analytics' || section === 'home') {
          setStats(await call(base + '/analytics'));
          return;
        }
        const result = await call<{ items: Row[]; next_cursor: string | null }>(
          base +
            '/resources/' +
            section +
            (cursor ? '?after=' + encodeURIComponent(cursor) : ''),
        );
        setRows((current) =>
          cursor ? [...current, ...result.items] : result.items,
        );
        setAfter(result.next_cursor);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [live, section, call, base, workspaceId, owner],
  );
  useEffect(() => {
    void Promise.resolve().then(() => refresh());
  }, [refresh]);
  const act = async (path: string, body?: unknown, method = 'POST') => {
    try {
      const result = await call<Record<string, unknown>>(path, {
        method,
        body,
      });
      setError('');
      await refresh();
      return result;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  };
  const botField: Field = {
    key: 'bot_id',
    label: 'Bot',
    type: 'select',
    initial: botId,
    required: true,
    options: bots.map((b) => ({ value: b.id, label: display(b.name) })),
  };
  const fields: Record<string, Field[]> = {
    plans: [
      botField,
      { key: 'name', label: 'Nombre del plan', required: true },
      { key: 'description', label: 'Descripción', type: 'textarea' },
      {
        key: 'benefits_text',
        label: 'Beneficios (uno por línea)',
        type: 'textarea',
      },
      {
        key: 'channel_id',
        label: 'Canal privado',
        type: 'select',
        options: channels.map((channel) => ({
          value: channel.id,
          label: display(channel.title),
        })),
        hint: 'Elige un canal conectado al bot de este plan.',
      },
      {
        key: 'duration_days',
        label: 'Duración en días',
        type: 'number',
        initial: 30,
      },
      {
        key: 'amount_xtr',
        label: 'Precio en Stars',
        type: 'number',
        required: true,
        initial: 500,
      },
      {
        key: 'amount_mxn',
        label: 'Precio en MXN, solo pedidos externos',
        type: 'text',
        hint: 'Opcional. Usa punto decimal, por ejemplo 499.00.',
      },
      {
        key: 'recurring',
        label: 'Renovación automática cada 30 días',
        type: 'switch',
      },
    ],
    campaigns: [
      botField,
      { key: 'name', label: 'Nombre de campaña', required: true },
      { key: 'text', label: 'Mensaje', type: 'textarea', required: true },
      {
        key: 'stage',
        label: 'Etapa del cliente',
        type: 'select',
        initial: '',
        options: [
          { value: '', label: 'Todos' },
          ...['LEAD', 'ACTIVE', 'EXPIRED', 'VIP'].map((v) => ({
            value: v,
            label: states[v] || v,
          })),
        ],
      },
      { key: 'source', label: 'Origen (opcional)' },
    ],
    automations: [
      botField,
      { key: 'name', label: 'Nombre de la regla', required: true },
      {
        key: 'trigger',
        label: 'Cuando ocurra',
        type: 'select',
        initial: 'START',
        options: [
          ['START', 'Inicio del bot'],
          ['PAYMENT_APPROVED', 'Pago aprobado'],
          ['SUBSCRIPTION_EXPIRING', 'Próximo vencimiento'],
          ['SUBSCRIPTION_EXPIRED', 'Suscripción vencida'],
          ['SUBSCRIPTION_RENEWED', 'Renovación'],
        ].map(([value, label]) => ({ value, label })),
      },
      {
        key: 'action',
        label: 'Acción',
        type: 'select',
        initial: 'SEND_MESSAGE',
        options: [
          ['SEND_MESSAGE', 'Enviar mensaje'],
          ['ADD_TAG', 'Añadir etiqueta'],
          ['CHANGE_CRM_STAGE', 'Cambiar etapa'],
          ['NOTIFY_ADMIN', 'Avisar al equipo'],
          ['CREATE_TASK', 'Crear tarea'],
          ['SEND_PROMOTION', 'Enviar promoción'],
        ].map(([value, label]) => ({ value, label })),
      },
      { key: 'text', label: 'Mensaje', type: 'textarea' },
      { key: 'tag', label: 'Etiqueta (para añadir etiqueta)' },
      {
        key: 'stage',
        label: 'Etapa (para cambiar etapa)',
        type: 'select',
        options: ['LEAD', 'INTERESTED', 'ACTIVE', 'EXPIRED', 'VIP'].map(
          (v) => ({ value: v, label: states[v] || v }),
        ),
      },
      { key: 'title', label: 'Título (para crear tarea)' },
      {
        key: 'delay_seconds',
        label: 'Esperar segundos',
        type: 'number',
        initial: 0,
      },
    ],
    coupons: [
      { key: 'code', label: 'Código del cupón', required: true },
      { key: 'percent_off', label: 'Descuento %', type: 'number', initial: 10 },
      {
        key: 'max_redemptions',
        label: 'Máximo de usos',
        type: 'number',
        initial: 100,
      },
      {
        key: 'expiry_date',
        label: 'Fecha de vencimiento',
        type: 'date',
        required: true,
      },
    ],
    team: [
      {
        key: 'telegram_user_id',
        label: 'ID de Telegram del miembro',
        type: 'number',
        required: true,
        hint: 'La persona debe abrir primero el Master Bot.',
      },
      {
        key: 'role',
        label: 'Rol',
        type: 'select',
        initial: 'SUPPORT',
        options: [
          ['SUPERVISOR', 'Supervisor'],
          ['PAYMENTS', 'Pagos'],
          ['SALES', 'Ventas'],
          ['SUPPORT', 'Soporte'],
          ['READ_ONLY', 'Solo lectura'],
        ].map(([value, label]) => ({ value, label })),
      },
    ],
    referrals: [
      botField,
      {
        key: 'source',
        label: 'Origen del enlace',
        required: true,
        initial: 'telegram',
      },
      { key: 'campaign', label: 'Campaña (opcional)' },
      { key: 'referrer_id', label: 'ID del cliente que recomienda (opcional)' },
    ],
  };
  async function create(values: Record<string, string | number | boolean>) {
    let body: Record<string, unknown> = { ...values };
    if (section === 'plans') {
      const { amount_xtr, amount_mxn, benefits_text, ...rest } = body;
      const prices = [
        {
          provider: 'TELEGRAM_STARS',
          currency: 'XTR',
          amount_minor: Number(amount_xtr),
        },
      ];
      if (amount_mxn) {
        if (!/^\d+(\.\d{1,2})?$/.test(display(amount_mxn)))
          throw new Error('Introduce un importe MXN válido.');
        const [whole, cents = ''] = display(amount_mxn).split('.');
        prices.push({
          provider: 'BANK_TRANSFER',
          currency: 'MXN',
          amount_minor: Number(
            BigInt(whole) * BigInt(100) + BigInt(cents.padEnd(2, '0')),
          ),
        });
      }
      body = {
        ...rest,
        channel_id: rest.channel_id || null,
        benefits: display(benefits_text).split('\n').filter(Boolean),
        prices,
      };
    }
    if (section === 'coupons') {
      const { expiry_date, ...rest } = body;
      body = {
        ...rest,
        expires_at: Math.floor(
          new Date(display(expiry_date) + 'T23:59:59').getTime() / 1000,
        ),
      };
    }
    for (const key of ['stage', 'source', 'campaign', 'referrer_id'])
      if (key in body && !body[key]) body[key] = null;
    const result = await call<Row>(
      base + '/' + (section === 'referrals' ? 'links' : section),
      { method: 'POST', body },
    );
    if (result.url) setError('Enlace creado: ' + display(result.url));
    setDialog(false);
    await refresh();
  }
  if (live && !workspaceId && section !== 'owner' && section !== 'support')
    return (
      <section className="surface">
        <h2>Crea tu primer espacio</h2>
        <p className="muted">
          Tu cuenta de Telegram está lista. Continúa con la creación de tu
          negocio.
        </p>
        <Button onClick={startWizard}>
          Crear mi bot
          <ArrowRight />
        </Button>
      </section>
    );
  const botPicker = (
    <Select value={botId} onValueChange={(v) => setBotId(display(v))}>
      <SelectTrigger>
        <SelectValue placeholder="Seleccionar bot" />
      </SelectTrigger>
      <SelectContent>
        {bots.map((b) => (
          <SelectItem key={b.id} value={b.id}>
            {display(b.name)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
  if (section === 'home' || section === 'analytics')
    return (
      <div>
        <div className="metrics-grid">
          {[
            [
              t.revenue,
              money((stats.revenue_minor as Record<string, string>)?.XTR || 0),
            ],
            [t.active, stats.active_subscriptions || 0],
            [t.newClients, stats.new_clients || 0],
            [t.pendingReceipts, stats.pending_receipts || 0],
          ].map(([label, value]) => (
            <section className="surface metric" key={display(label)}>
              <p className="metric-label">{display(label)}</p>
              <strong className="metric-number">{display(value)}</strong>
            </section>
          ))}
        </div>
        <section className="surface">
          <h2>Conversión y renovaciones</h2>
          <div className="details-grid">
            <div>
              <small>Conversión de contactos a clientes de pago</small>
              <h2>{display(stats.conversion_percent || 0)} %</h2>
            </div>
            <div>
              <small>Renovaciones · últimos 30 días</small>
              <h2>{display(stats.renewals || 0)}</h2>
            </div>
          </div>
          <p className="muted">
            Cada moneda se calcula por separado. Las cifras incluyen pagos
            confirmados y excluyen cargos reembolsados.
          </p>
          {Object.entries(
            (stats.revenue_minor || {}) as Record<string, string>,
          ).map(([c, v]) => (
            <p key={c}>{money(v, c)}</p>
          ))}
        </section>
        {error && <p className="error-box">{error}</p>}
      </div>
    );
  if (section === 'support')
    return (
      <section className="surface">
        <h2>Ayuda para tu negocio</h2>
        <div className="notice">
          Crea tu bot desde el asistente, ábrelo y pulsa Start. Después conecta
          tu canal, añade un plan y configura Stars. El chequeo de publicación
          te indicará si falta algo.
        </div>
        <Form
          fields={[
            { key: 'subject', label: 'Asunto', required: true },
            {
              key: 'text',
              label: 'Cuéntanos qué necesitas',
              type: 'textarea',
              required: true,
            },
          ]}
          label="Contactar soporte de plataforma"
          submit={async (body) => {
            await call('support/tickets', { method: 'POST', body });
          }}
        />
      </section>
    );
  if (section === 'owner')
    return <OwnerPanel call={call} live={live} owner={owner} />;
  if (section === 'settings')
    return (
      <section className="surface">
        <h2>Configuración de pagos</h2>
        <p className="notice">
          Las membresías digitales dentro de Telegram se cobran con Stars. Las
          transferencias se registran para pedidos realizados fuera de Telegram.
        </p>
        <div className="details-grid">
          <div>
            <h2>
              <Star size={18} /> Telegram Stars
            </h2>
            <Form
              fields={[
                {
                  key: 'enabled',
                  label: 'Aceptar Stars',
                  type: 'switch',
                  initial: true,
                },
              ]}
              submit={async (body) => {
                await call(base + '/providers/TELEGRAM_STARS', {
                  method: 'PUT',
                  body,
                });
              }}
            />
          </div>
          <div>
            <h2>Transferencias</h2>
            <Form
              fields={[
                {
                  key: 'enabled',
                  label: 'Habilitar registro de transferencias',
                  type: 'switch',
                },
                ...['bank_name', 'account_holder', 'account', 'clabe'].map(
                  (key, i) => ({
                    key,
                    label: ['Banco', 'Titular', 'Cuenta', 'CLABE'][i],
                    type: (i > 1 ? 'password' : 'text') as 'password' | 'text',
                  }),
                ),
                {
                  key: 'currency',
                  label: 'Moneda',
                  type: 'select',
                  initial: 'MXN',
                  options: [
                    { value: 'MXN', label: 'MXN' },
                    { value: 'USD', label: 'USD' },
                  ],
                },
                {
                  key: 'instructions',
                  label: 'Instrucciones',
                  type: 'textarea',
                },
              ]}
              submit={async (body) => {
                await call(base + '/providers/BANK_TRANSFER', {
                  method: 'PUT',
                  body,
                });
              }}
            />
          </div>
        </div>
        <div className="notice">
          Proveedor externo: requiere un adaptador específico y aprobación del
          proveedor. IA y OCR: desactivados.
        </div>
      </section>
    );
  return (
    <section className="surface">
      <div className="section-heading">
        <h2>{t[section as keyof typeof t] as string}</h2>
        <div className="row wrap">
          {['bots', 'channels'].includes(section) && botPicker}
          <Button
            variant="ghost"
            onClick={() => {
              void refresh();
            }}
            disabled={busy}
            aria-label="Actualizar"
          >
            <RefreshCw size={16} />
          </Button>
          {fields[section] && (
            <Button onClick={() => setDialog(true)}>
              <Plus />
              Crear
            </Button>
          )}
          {['contacts', 'payments', 'subscriptions', 'campaigns'].includes(
            section,
          ) && (
            <Button
              variant="outline"
              onClick={async () => {
                try {
                  const response = await call<Response>(
                    base + '/export/' + section,
                    { raw: true },
                  );
                  const url = URL.createObjectURL(await response.blob());
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = section + '.csv';
                  a.click();
                  URL.revokeObjectURL(url);
                  if (response.headers.get('X-Next-Cursor'))
                    setError(
                      'Se descargó la primera página de 1.000 registros. Continúa la exportación con el cursor de la API.',
                    );
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              <Download />
              Exportar
            </Button>
          )}
        </div>
      </div>
      {error && <output className="notice">{error}</output>}
      {busy && <output className="muted">Cargando…</output>}
      {section === 'bots' && (
        <>
          <div className="bot-actions row wrap">
            <Button
              variant="outline"
              onClick={() => {
                void act(base + '/bots/' + botId + '/repair');
              }}
            >
              Reparar bot
            </Button>
            <Button
              variant="outline"
              onClick={async () => {
                const result = await act(
                  base + '/bots/' + botId + '/readiness',
                  undefined,
                  'GET',
                );
                if (result)
                  setError(
                    Object.entries(result.checks as Record<string, boolean>)
                      .map(
                        ([k, v]) => (v ? '✓ ' : '✕ ') + k.replaceAll('_', ' '),
                      )
                      .join(' · '),
                  );
              }}
            >
              Verificar publicación
            </Button>
            <Button onClick={startWizard}>
              Asistente de publicación
              <ArrowRight />
            </Button>
          </div>
          {botId ? (
            <BotEditor
              key={botId}
              botId={botId}
              base={base}
              call={call}
              live={live}
            />
          ) : (
            <p className="muted">Crea tu primer bot con el asistente.</p>
          )}
        </>
      )}
      {section === 'channels' && (
        <div className="notice">
          <p>
            Conecta un canal privado y permite invitar y gestionar miembros.
          </p>
          <Button
            className="mt-3"
            onClick={async () => {
              const result = await act(
                base + '/bots/' + botId + '/connect-channel',
                undefined,
                'GET',
              );
              if (result?.url) openTelegram(display(result.url));
            }}
          >
            Conectar canal
          </Button>
        </div>
      )}
      {section === 'billing' && <Billing base={base} call={call} live={live} />}
      {section !== 'bots' && (
        <>
          <Input
            className="list-search"
            placeholder="Buscar en esta página…"
            aria-label="Buscar registros"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Table>
            <TableHeader>
              <TableRow>
                {(columns[section] || []).map(([k, label]) => (
                  <TableHead key={k}>{label}</TableHead>
                ))}
                <TableHead>Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows
                .filter((row) =>
                  JSON.stringify(row)
                    .toLowerCase()
                    .includes(search.toLowerCase()),
                )
                .map((row) => (
                  <TableRow key={row.id}>
                    {(columns[section] || []).map(([key]) => (
                      <TableCell key={key}>
                        {key === 'amount_minor'
                          ? money(row[key], row.currency)
                          : key.endsWith('_at') || key.endsWith('_end')
                            ? date(row[key])
                            : typeof row[key] === 'boolean'
                              ? row[key]
                                ? 'Sí'
                                : 'No'
                              : states[display(row[key])] ||
                                display(row[key] || '—')}
                      </TableCell>
                    ))}
                    <TableCell>
                      <div className="row wrap">
                        {section === 'receipts' && (
                          <>
                            <Button
                              variant="outline"
                              onClick={() => setSelected(row)}
                            >
                              Revisar
                            </Button>
                          </>
                        )}
                        {section === 'contacts' && (
                          <Button
                            variant="outline"
                            onClick={() => setSelected(row)}
                          >
                            Ver cliente
                          </Button>
                        )}
                        {section === 'conversations' && (
                          <Button
                            variant="outline"
                            onClick={() => setSelected(row)}
                          >
                            Responder
                          </Button>
                        )}
                        {section === 'campaigns' && (
                          <>
                            <Button
                              variant="outline"
                              onClick={() => {
                                void act(
                                  base + '/campaigns/' + row.id + '/action',
                                  {
                                    action:
                                      row.status === 'RUNNING'
                                        ? 'PAUSE'
                                        : 'START',
                                  },
                                );
                              }}
                            >
                              {row.status === 'RUNNING' ? 'Pausar' : 'Iniciar'}
                            </Button>
                          </>
                        )}
                        {section === 'channels' && (
                          <Button
                            variant="outline"
                            onClick={async () => {
                              const result = await act(
                                base + '/channels/' + row.id + '/test',
                              );
                              if (result)
                                setError(
                                  result.connected
                                    ? 'Canal conectado. Permisos correctos.'
                                    : 'Faltan permisos: ' +
                                        (result.missing as string[]).join(', '),
                                );
                            }}
                          >
                            Probar acceso
                          </Button>
                        )}
                        {section === 'team' && row.role !== 'OWNER' && (
                          <Button
                            variant="outline"
                            onClick={() => {
                              void act(
                                base + '/team/' + row.id,
                                undefined,
                                'DELETE',
                              );
                            }}
                          >
                            Revocar acceso
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
          {!rows.length && !busy && <p className="empty-state">{t.empty}</p>}
          {after && (
            <Button
              variant="outline"
              onClick={() => {
                void refresh(after);
              }}
            >
              Cargar más
            </Button>
          )}
        </>
      )}
      <Dialog open={dialog} onOpenChange={setDialog}>
        <DialogContent className="editor-dialog">
          <DialogHeader>
            <DialogTitle>
              Crear · {t[section as keyof typeof t] as string}
            </DialogTitle>
            <DialogDescription>
              Configura los datos para tu espacio de trabajo.
            </DialogDescription>
          </DialogHeader>
          {fields[section] && (
            <Form key={section} fields={fields[section]} submit={create} />
          )}
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent className="editor-dialog">
          <DialogHeader>
            <DialogTitle>
              {section === 'receipts'
                ? 'Revisar comprobante'
                : section === 'contacts'
                  ? display(selected?.first_name || 'Cliente')
                  : 'Conversación'}
            </DialogTitle>
            <DialogDescription>
              Datos de tu espacio de trabajo.
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <Detail
              section={section}
              row={selected}
              base={base}
              call={call}
              done={() => {
                setSelected(null);
                void refresh();
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}

function Billing({
  base,
  call,
  live,
}: {
  base: string;
  call: Call;
  live: boolean;
}) {
  const [plans, setPlans] = useState<Row[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    if (live)
      void call<Row[]>('saas-plans')
        .then(setPlans)
        .catch((e) => setError(e.message));
  }, [call, live]);
  return (
    <div className="plan-grid">
      {plans.map((plan) => (
        <div className="plan-card" key={plan.id}>
          <h2>{display(plan.name)}</h2>
          <p>{display((plan.limits as Record<string, number>)?.bots)} bots</p>
          <p>
            {(plan.prices as Record<string, number>)?.XTR
              ? money((plan.prices as Record<string, number>).XTR)
              : 'Precio pendiente de configurar'}
          </p>
          <Button
            variant="outline"
            onClick={() => {
              void call<Row>(base + '/billing/checkout/' + plan.id, {
                method: 'POST',
              })
                .then((result) => invoice(display(result.checkout_url)))
                .catch((e) => setError(e.message));
            }}
          >
            Elegir plan
          </Button>
        </div>
      ))}
      {error && <p className="error-box">{error}</p>}
    </div>
  );
}

function Detail({
  section,
  row,
  base,
  call,
  done,
}: {
  section: string;
  row: Row;
  base: string;
  call: Call;
  done: () => void;
}) {
  const [image, setImage] = useState('');
  const [messages, setMessages] = useState<Row[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let imageUrl = '';
    if (section === 'receipts')
      void call<Response>(base + '/receipts/' + row.id + '/image', {
        raw: true,
      })
        .then((r) => r.blob())
        .then((blob) => {
          imageUrl = URL.createObjectURL(blob);
          setImage(imageUrl);
        })
        .catch((e) => setError(e.message));
    if (section === 'conversations')
      void call<Row[]>(base + '/conversations/' + row.id + '/messages')
        .then(setMessages)
        .catch((e) => setError(e.message));
    return () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [section, row.id, base, call]);
  if (section === 'receipts')
    return (
      <>
        {image && (
          <Image
            unoptimized
            width={800}
            height={1000}
            className="receipt-image"
            src={image}
            alt="Comprobante de pago"
          />
        )}
        {row.duplicate === true && (
          <p className="error-box">
            Posible comprobante duplicado. Verifica antes de aprobar.
          </p>
        )}
        <Form
          fields={[
            {
              key: 'decision',
              label: 'Decisión',
              type: 'select',
              initial: 'APPROVE',
              options: [
                ['APPROVE', 'Aprobar'],
                ['REJECT', 'Rechazar'],
                ['REQUEST_NEW', 'Pedir otro comprobante'],
                ['SUSPICIOUS', 'Marcar sospechoso'],
              ].map(([value, label]) => ({ value, label })),
            },
            { key: 'note', label: 'Nota de revisión', type: 'textarea' },
            {
              key: 'accept_duplicate',
              label: 'Revisé la alerta y confirmo la aprobación',
              type: 'switch',
            },
          ]}
          submit={async (body) => {
            await call(base + '/receipts/' + row.id + '/review', {
              method: 'POST',
              body,
            });
            done();
          }}
        />
        {error && <p className="error-box">{error}</p>}
      </>
    );
  if (section === 'contacts')
    return (
      <>
        <p className="muted">
          Telegram ID: {display(row.telegram_user_id || '—')} · @
          {display(row.username || 'sin usuario')}
        </p>
        <Form
          fields={[
            {
              key: 'stage',
              label: 'Etapa',
              type: 'select',
              initial: display(row.stage || 'LEAD'),
              options: [
                'LEAD',
                'INTERESTED',
                'PLAN_SELECTED',
                'PAYMENT_PENDING',
                'RECEIPT_SUBMITTED',
                'ACTIVE',
                'EXPIRING',
                'EXPIRED',
                'RECOVERED',
                'VIP',
                'BLOCKED',
              ].map((v) => ({ value: v, label: states[v] || v })),
            },
            {
              key: 'opted_out',
              label: 'Excluir de campañas',
              type: 'switch',
              initial: Boolean(row.opted_out),
            },
          ]}
          submit={async (body) => {
            await call(base + '/contacts/' + row.id, { method: 'PATCH', body });
            done();
          }}
        />
        <Form
          fields={[
            {
              key: 'text',
              label: 'Nota interna',
              type: 'textarea',
              required: true,
            },
          ]}
          label="Añadir nota"
          submit={async (body) => {
            await call(base + '/contacts/' + row.id + '/notes', {
              method: 'POST',
              body,
            });
          }}
        />
      </>
    );
  return (
    <>
      <div className="message-history">
        {messages.toReversed().map((message) => (
          <div
            className={
              'chat-bubble ' + (message.direction === 'OUT' ? 'outgoing' : '')
            }
            key={message.id}
          >
            {display(message.text)}
            <small>{display(message.status)}</small>
          </div>
        ))}
      </div>
      <Form
        fields={[
          {
            key: 'text',
            label: 'Respuesta desde tu bot',
            type: 'textarea',
            required: true,
          },
        ]}
        label="Enviar respuesta"
        submit={async (body) => {
          await call(base + '/conversations/' + row.id + '/messages', {
            method: 'POST',
            body: { ...body, idempotency_key: crypto.randomUUID() },
          });
          done();
        }}
      />
      {error && <p className="error-box">{error}</p>}
    </>
  );
}
