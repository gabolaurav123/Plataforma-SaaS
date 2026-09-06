'use client';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  Table,
  TableHeader,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from '@/components/ui/table';
import { Form } from './forms';
import { type Call, type Row, display, date } from '@/lib/platform-api';

const sections = [
  ['tenants', 'Creadores'],
  ['bots', 'Bots'],
  ['saas-plans', 'Planes SaaS'],
  ['jobs', 'Trabajos'],
  ['support', 'Soporte'],
  ['audit', 'Auditoría'],
] as const;
const features = [
  'bank_payments',
  'stars',
  'campaigns',
  'automations',
  'coupons',
  'referrals',
  'team_members',
  'custom_branding',
  'multiple_bots',
];

export function OwnerPanel({
  call,
  live,
  owner,
}: {
  call: Call;
  live: boolean;
  owner: boolean;
}) {
  const [section, setSection] = useState('tenants');
  const [rows, setRows] = useState<Row[]>([]);
  const [selected, setSelected] = useState<Row | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (live && owner)
      void call<{ items: Row[]; next_cursor: string | null }>(
        'owner/resources/' + section,
      )
        .then((data) => {
          setRows(data.items);
          setNext(data.next_cursor);
        })
        .catch((error) => setMessage(error.message));
  }, [call, live, owner, section, revision]);
  const limits = (selected?.limits || {}) as Record<string, number>;
  return (
    <section className="surface">
      <div className="section-heading">
        <h2>Administración de la plataforma</h2>
        <Button variant="outline" onClick={() => setRevision((v) => v + 1)}>
          Actualizar
        </Button>
      </div>
      {!owner && (
        <p className="notice">
          Disponible para el propietario autenticado en el Master Bot.
        </p>
      )}
      <div className="row wrap">
        <Button
          disabled={!owner}
          onClick={async () => {
            try {
              const result = await call<{
                message: string;
                instructions: string[];
              }>('owner/master/capabilities');
              setMessage([result.message, ...result.instructions].join(' '));
            } catch (e) {
              setMessage((e as Error).message);
            }
          }}
        >
          Verificar Master Bot
        </Button>
        <Button
          disabled={!owner}
          variant="outline"
          onClick={async () => {
            try {
              await call('owner/master/configure', { method: 'POST' });
              setMessage('Webhook, menú y comandos del Master configurados.');
            } catch (e) {
              setMessage((e as Error).message);
            }
          }}
        >
          Configurar Master Bot
        </Button>
      </div>
      {message && <output className="notice">{message}</output>}
      <Tabs
        value={section}
        onValueChange={(value) => {
          setSection(display(value));
          setSelected(null);
        }}
      >
        <TabsList className="row wrap">
          {sections.map(([key, label]) => (
            <TabsTrigger key={key} value={key}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nombre o acción</TableHead>
            <TableHead>Estado</TableHead>
            <TableHead>Fecha</TableHead>
            <TableHead>Detalle</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell>
                {display(
                  row.name ||
                    row.subject ||
                    row.action ||
                    row.kind ||
                    row.username,
                )}
              </TableCell>
              <TableCell>
                {display(row.status || row.last_error_code)}
              </TableCell>
              <TableCell>{date(row.created_at)}</TableCell>
              <TableCell>
                <Button variant="ghost" onClick={() => setSelected(row)}>
                  Ver
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!rows.length && (
        <p className="empty-state">No hay registros para mostrar.</p>
      )}
      {next && (
        <Button
          variant="outline"
          onClick={async () => {
            try {
              const data = await call<{
                items: Row[];
                next_cursor: string | null;
              }>(
                'owner/resources/' +
                  section +
                  '?after=' +
                  encodeURIComponent(next),
              );
              setRows((current) => [...current, ...data.items]);
              setNext(data.next_cursor);
            } catch (e) {
              setMessage((e as Error).message);
            }
          }}
        >
          Cargar más
        </Button>
      )}
      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent className="wide-dialog">
          <DialogHeader>
            <DialogTitle>
              {display(
                selected?.name ||
                  selected?.subject ||
                  selected?.kind ||
                  selected?.action,
                'Detalle',
              )}
            </DialogTitle>
            <DialogDescription>
              Los cambios se registran en la auditoría de la plataforma.
            </DialogDescription>
          </DialogHeader>
          {selected && section === 'tenants' ? (
            <div className="details-grid">
              <Form
                label="Aplicar estado"
                fields={[
                  {
                    key: 'action',
                    label: 'Acción',
                    type: 'select',
                    initial:
                      selected.status === 'SUSPENDED'
                        ? 'REACTIVATE'
                        : 'SUSPEND',
                    options: [
                      { value: 'SUSPEND', label: 'Suspender' },
                      {
                        value: 'REACTIVATE',
                        label: 'Reactivar periodo vigente',
                      },
                    ],
                  },
                  {
                    key: 'reason',
                    label: 'Motivo',
                    type: 'textarea',
                    required: true,
                  },
                ]}
                submit={async (body) => {
                  await call('owner/tenants/' + selected.id + '/action', {
                    method: 'POST',
                    body,
                  });
                  setRevision((v) => v + 1);
                }}
              />
              <Form
                label="Guardar función"
                fields={[
                  {
                    key: 'key',
                    label: 'Función',
                    type: 'select',
                    initial: 'campaigns',
                    options: features.map((key) => ({
                      value: key,
                      label: key,
                    })),
                  },
                  { key: 'enabled', label: 'Habilitada', type: 'switch' },
                ]}
                submit={async (body) => {
                  await call(
                    'owner/tenants/' +
                      selected.id +
                      '/features/' +
                      display(body.key),
                    { method: 'PUT', body: { enabled: body.enabled } },
                  );
                }}
              />
            </div>
          ) : selected && section === 'saas-plans' ? (
            <Form
              label="Guardar plan SaaS"
              fields={[
                {
                  key: 'amount_xtr',
                  label: 'Precio mensual en Stars',
                  type: 'number',
                  initial: Number(
                    (selected.prices as Record<string, number>)?.XTR || 0,
                  ),
                  required: true,
                },
                ...[
                  ['bots', 'Bots'],
                  ['admins', 'Miembros del equipo'],
                  ['active_contacts', 'Contactos'],
                  ['campaigns_month', 'Campañas por mes'],
                ].map(([key, label]) => ({
                  key,
                  label,
                  type: 'number' as const,
                  initial: limits[key] || 0,
                  required: true,
                })),
              ]}
              submit={async (body) => {
                await call('owner/saas-plans/' + selected.id, {
                  method: 'PUT',
                  body,
                });
                setRevision((v) => v + 1);
              }}
            />
          ) : selected && section === 'support' ? (
            <p className="policy-text">{display(selected.text)}</p>
          ) : (
            <pre className="code-preview">
              {JSON.stringify(selected, null, 2)}
            </pre>
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
