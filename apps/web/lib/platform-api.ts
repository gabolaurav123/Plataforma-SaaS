'use client';
import { useCallback, useEffect, useState } from 'react';

export type Row = Record<string, unknown> & { id: string };
export type Call = <T = unknown>(
  path: string,
  options?: { method?: string; body?: unknown; form?: FormData; raw?: boolean },
) => Promise<T>;
type TG = {
  initData: string;
  ready(): void;
  expand(): void;
  isVersionAtLeast?(version: string): boolean;
  openTelegramLink(url: string): void;
  openInvoice(url: string, callback?: (status: string) => void): void;
  requestChat?(id: string, callback?: (sent: boolean) => void): void;
  setHeaderColor?(color: string): void;
};
declare global {
  interface Window {
    Telegram?: { WebApp: TG };
  }
}
export type Workspace = { id: string; name: string; role: string };

export function telegram(): Promise<TG | null> {
  if (window.Telegram?.WebApp) return Promise.resolve(window.Telegram.WebApp);
  return new Promise((resolve) => {
    const existing = document.querySelector('script[data-telegram-sdk]');
    if (existing) {
      existing.addEventListener(
        'load',
        () => resolve(window.Telegram?.WebApp || null),
        { once: true },
      );
      return;
    }
    const script = document.createElement('script');
    script.src = 'https://telegram.org/js/telegram-web-app.js';
    script.dataset.telegramSdk = 'true';
    script.async = true;
    script.onload = () => resolve(window.Telegram?.WebApp || null);
    script.onerror = () => resolve(null);
    document.head.appendChild(script);
  });
}

export function usePlatformSession(publicId?: string) {
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState('');
  const [owner, setOwner] = useState(false);
  const [inTelegram, setInTelegram] = useState(false);
  const [userName, setUserName] = useState('Creator Studio');
  const call: Call = useCallback(
    async <T>(
      path: string,
      options: {
        method?: string;
        body?: unknown;
        form?: FormData;
        raw?: boolean;
      } = {},
    ) => {
      if (!token)
        throw new Error(
          'Abre el panel desde Telegram para guardar los cambios.',
        );
      const response = await fetch('/api/backend/' + path, {
        method: options.method || 'GET',
        headers: {
          Authorization: 'Bearer ' + token,
          ...(!options.form && options.body
            ? { 'Content-Type': 'application/json' }
            : {}),
        },
        body:
          options.form ||
          (options.body ? JSON.stringify(options.body) : undefined),
      });
      if (!response.ok) {
        const data = (await response.json().catch(() => ({}))) as {
          message?: string;
        };
        throw new Error(data.message || 'No se pudo completar la operación.');
      }
      if (options.raw) return response as T;
      return (await response.json()) as T;
    },
    [token],
  );
  useEffect(() => {
    let canceled = false;
    void telegram().then(async (tg) => {
      tg?.ready();
      tg?.expand();
      if (!tg?.initData) {
        if (!canceled) setLoading(false);
        return;
      }
      setInTelegram(true);
      try {
        const response = await fetch(
          '/api/backend/auth/' + (publicId ? 'b/' + publicId : 'master'),
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ init_data: tg.initData }),
          },
        );
        const data = (await response.json()) as {
          message?: string;
          access_token: string;
          user: { first_name: string };
        };
        if (!response.ok)
          throw new Error(data.message || 'No se pudo validar tu sesión.');
        if (!canceled) {
          setToken(data.access_token);
          setUserName(data.user.first_name);
        }
      } catch (e) {
        if (!canceled) setError((e as Error).message);
      } finally {
        if (!canceled) setLoading(false);
      }
    });
    return () => {
      canceled = true;
    };
  }, [publicId]);
  const refreshWorkspaces = useCallback(async () => {
    const data = await call<{
      workspaces: Workspace[];
      platform_owner: boolean;
    }>('me');
    setWorkspaces(data.workspaces);
    setOwner(data.platform_owner);
    setWorkspaceId((current) => current || data.workspaces[0]?.id || '');
  }, [call]);
  useEffect(() => {
    if (token && !publicId)
      void Promise.resolve()
        .then(refreshWorkspaces)
        .catch((e) => setError(e.message));
  }, [token, publicId, refreshWorkspaces]);
  return {
    call,
    loading,
    error,
    live: !!token,
    inTelegram,
    workspaces,
    workspaceId,
    setWorkspaceId,
    owner,
    userName,
    refreshWorkspaces,
  };
}

export function openTelegram(url: string) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' || parsed.hostname !== 't.me')
    throw new Error('Enlace de Telegram no válido.');
  if (window.Telegram?.WebApp) window.Telegram.WebApp.openTelegramLink(url);
  else window.open(url, '_blank', 'noopener,noreferrer');
}
export function invoice(url: string) {
  if (new URL(url).hostname !== 't.me')
    throw new Error('Enlace de pago no válido.');
  if (window.Telegram?.WebApp?.initData)
    window.Telegram.WebApp.openInvoice(url);
  else openTelegram(url);
}
export function display(value: unknown, fallback = '—'): string {
  if (typeof value === 'string') return value;
  if (
    typeof value === 'number' ||
    typeof value === 'bigint' ||
    typeof value === 'boolean'
  )
    return String(value);
  return fallback;
}
export function money(minor: unknown, currency: unknown = 'XTR') {
  const raw = display(minor, '0');
  if (!/^-?\d+$/.test(raw)) return '—';
  const value = BigInt(raw);
  if (currency === 'XTR') return value.toLocaleString('es') + ' XTR';
  const absolute = value < BigInt(0) ? -value : value;
  return `${value < BigInt(0) ? '-' : ''}${absolute / BigInt(100)}.${String(absolute % BigInt(100)).padStart(2, '0')} ${display(currency)}`;
}
export function date(value: unknown) {
  return value ? new Date(Number(value) * 1000).toLocaleDateString('es') : '—';
}
