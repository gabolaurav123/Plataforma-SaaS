'use client';
import { display } from '@/lib/platform-api';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import { Form, type Field } from './forms';
import { type Call, type Row } from '@/lib/platform-api';

type Config = { bot: Row; settings: Row; texts: Row[] };
const samples: Record<string, string> = {
  first_name: 'María',
  plan_name: 'Premium',
  price: '500',
  currency: 'XTR',
  expiration_date: '30/09/2026',
  days_remaining: '3',
  support_username: '@soporte',
};
const textNames: Record<string, string> = {
  WELCOME: 'Bienvenida',
  PLAN_LIST: 'Lista de planes',
  PLAN_SELECTED: 'Plan elegido',
  PAYMENT_METHOD: 'Método de pago',
  BANK_DETAILS: 'Datos bancarios',
  RECEIPT_REQUEST: 'Solicitar comprobante',
  RECEIPT_RECEIVED: 'Comprobante recibido',
  PAYMENT_APPROVED: 'Pago aprobado',
  PAYMENT_REJECTED: 'Pago rechazado',
  SUBSCRIPTION_ACTIVE: 'Suscripción activa',
  SUBSCRIPTION_EXPIRING: 'Próximo vencimiento',
  SUBSCRIPTION_EXPIRED: 'Suscripción vencida',
  RENEWAL: 'Renovación',
  SUPPORT: 'Soporte',
  ERROR: 'Error',
};
export function BotEditor({
  botId,
  base,
  call,
  live,
}: {
  botId: string;
  base: string;
  call: Call;
  live: boolean;
}) {
  const [data, setData] = useState<Config | null>(null);
  const [defaults, setDefaults] = useState<Record<string, string>>({
    WELCOME: 'Hola {{first_name}} 👋 Bienvenido a nuestra comunidad.',
  });
  const [key, setKey] = useState('WELCOME');
  const [value, setValue] = useState(defaults.WELCOME);
  const [message, setMessage] = useState('');
  useEffect(() => {
    if (live && botId) {
      void call<Config>(base + '/bots/' + botId + '/settings')
        .then((d) => {
          setData(d);
          setValue(
            display(d.texts.find((t) => t.key === 'WELCOME')?.value || ''),
          );
        })
        .catch((e) => setMessage(e.message));
      void call<Record<string, string>>(base + '/text-defaults')
        .then(setDefaults)
        .catch((e) => setMessage(e.message));
    }
  }, [botId, base, call, live]);
  const settings = data?.settings;
  const policies = (settings?.policies || {}) as Record<string, string>;
  const fields: Field[] = [
    {
      key: 'name',
      label: 'Nombre del bot',
      initial: display(data?.bot.name || 'Studio Club'),
      required: true,
    },
    {
      key: 'description',
      label: 'Descripción',
      type: 'textarea',
      initial: display(settings?.description || ''),
    },
    {
      key: 'short_description',
      label: 'Descripción corta',
      initial: display(settings?.short_description || ''),
    },
    {
      key: 'menu_text',
      label: 'Texto del botón de menú',
      initial: display(settings?.menu_text || 'Mi membresía'),
    },
    {
      key: 'support_username',
      label: 'Usuario de soporte',
      initial: display(settings?.support_username || ''),
    },
    {
      key: 'brand_color',
      label: 'Color de marca',
      initial: display(
        (settings?.branding as Record<string, string>)?.color || '#2864ef',
      ),
    },
    {
      key: 'commands_text',
      label: 'Comandos',
      type: 'textarea',
      hint: 'Un comando por línea: start — Inicio',
      initial: (
        (settings?.commands as { command: string; description: string }[]) || [
          { command: 'start', description: 'Inicio' },
          { command: 'paysupport', description: 'Ayuda con pagos' },
        ]
      )
        .map((x) => `${x.command} — ${x.description}`)
        .join('\n'),
    },
    {
      key: 'terms',
      label: 'Términos del servicio',
      type: 'textarea',
      initial: policies.terms || '',
    },
    {
      key: 'privacy',
      label: 'Política de privacidad',
      type: 'textarea',
      initial: policies.privacy || '',
    },
    {
      key: 'refund',
      label: 'Política de reembolsos',
      type: 'textarea',
      initial: policies.refund || '',
    },
    {
      key: 'remove_expired_members',
      label: 'Retirar el acceso al vencer',
      type: 'switch',
      initial: settings?.remove_expired_members !== false,
    },
  ];
  return (
    <Tabs defaultValue="profile">
      <TabsList>
        <TabsTrigger value="profile">Perfil y marca</TabsTrigger>
        <TabsTrigger value="texts">Mensajes</TabsTrigger>
        <TabsTrigger value="photo">Foto</TabsTrigger>
      </TabsList>
      <TabsContent value="profile">
        <Form
          key={data?.bot.id || 'demo'}
          fields={fields}
          label="Guardar y sincronizar bot"
          submit={async (values) => {
            const { commands_text, ...rest } = values;
            const commands = display(commands_text)
              .split('\n')
              .filter(Boolean)
              .map((line) => {
                const [command, ...parts] = line.split('—');
                return {
                  command: command.trim().replace(/^\//, ''),
                  description: parts.join('—').trim(),
                };
              });
            await call(base + '/bots/' + botId + '/settings', {
              method: 'PUT',
              body: { ...rest, commands },
            });
          }}
        />
      </TabsContent>
      <TabsContent value="texts">
        <div className="editor-layout">
          <div className="engine-form">
            <label className="field" htmlFor="bot-message-type">
              <span>Mensaje</span>
              <Select
                value={key}
                onValueChange={(selected) => {
                  const k = display(selected);
                  setKey(k);
                  setValue(
                    display(
                      data?.texts.find((x) => x.key === k)?.value ||
                        defaults[k] ||
                        '',
                    ),
                  );
                }}
              >
                <SelectTrigger id="bot-message-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(textNames).map(([k, label]) => (
                    <SelectItem value={k} key={k}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <Textarea
              aria-label="Contenido del mensaje"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              rows={8}
            />
            <div className="variable-list">
              {Object.keys(samples).map((k) => (
                <Button
                  variant="outline"
                  key={k}
                  onClick={() => setValue((v) => v + '{{' + k + '}}')}
                >
                  {k}
                </Button>
              ))}
            </div>
            <div className="row wrap">
              <Button
                onClick={() => {
                  void call(base + '/bots/' + botId + '/texts/' + key, {
                    method: 'PUT',
                    body: { value },
                  })
                    .then(() => setMessage('Texto guardado.'))
                    .catch((e) => setMessage(e.message));
                }}
              >
                Guardar texto
              </Button>
              <Button
                variant="outline"
                onClick={() => setValue(defaults[key] || '')}
              >
                Restaurar predeterminado
              </Button>
            </div>
          </div>
          <div className="telegram-preview">
            <p>Vista previa</p>
            <div className="chat-bubble">
              {value.replace(/{{\s*(\w+)\s*}}/g, (_, k) => samples[k] || '')}
            </div>
            <small>Así lo verá tu cliente en Telegram</small>
          </div>
        </div>
      </TabsContent>
      <TabsContent value="photo">
        <div className="engine-form">
          <label className="field" htmlFor="bot-photo">
            <span>Foto de perfil</span>
            <Input
              id="bot-photo"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const form = new FormData();
                form.append('file', file);
                void call(base + '/bots/' + botId + '/photo', {
                  method: 'POST',
                  form,
                })
                  .then(() => setMessage('Foto actualizada en Telegram.'))
                  .catch((error) => setMessage(error.message));
              }}
            />
            <small>JPG, PNG o WebP · hasta 5 MB.</small>
          </label>
        </div>
      </TabsContent>
      {message && <output className="notice">{message}</output>}
    </Tabs>
  );
}
