'use client';
import { useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  Bot,
  LayoutDashboard,
  Users,
  CreditCard,
  ReceiptText,
  CalendarCheck,
  MessageCircle,
  Layers,
  Radio,
  Workflow,
  Megaphone,
  Ticket,
  Gift,
  ChartNoAxesCombined,
  UsersRound,
  Settings,
  Wallet,
  ShieldCheck,
  CircleHelp,
  ArrowUpRight,
  Plus,
  ArrowRight,
  Check,
  Send,
} from 'lucide-react';
import {
  SidebarProvider,
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarFooter,
  SidebarInset,
  SidebarTrigger,
} from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import { es as t } from '@/lib/i18n';
import { usePlatformSession } from '@/lib/platform-api';
import { WorkspaceView } from './workspace-view';
import { Wizard } from './wizard';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';

const groups = [
  {
    label: t.operation,
    items: [
      ['home', LayoutDashboard],
      ['bots', Bot],
      ['contacts', Users],
      ['payments', CreditCard],
      ['receipts', ReceiptText],
      ['subscriptions', CalendarCheck],
      ['conversations', MessageCircle],
      ['plans', Layers],
      ['channels', Radio],
    ],
  },
  {
    label: t.growth,
    items: [
      ['automations', Workflow],
      ['campaigns', Megaphone],
      ['coupons', Ticket],
      ['referrals', Gift],
      ['analytics', ChartNoAxesCombined],
    ],
  },
  {
    label: t.workspaceGroup,
    items: [
      ['team', UsersRound],
      ['settings', Settings],
      ['billing', Wallet],
      ['owner', ShieldCheck],
      ['support', CircleHelp],
    ],
  },
] as const;
export function CreatorApp() {
  const params = useSearchParams();
  const target = params.get('section');
  const [sectionOverride, setSection] = useState<string | null>(null);
  const section =
    sectionOverride ??
    (target && groups.some((g) => g.items.some(([key]) => key === target))
      ? target
      : 'home');
  const [wizardOverride, setWizard] = useState<boolean | null>(null);
  const wizard = wizardOverride ?? params.has('onboarding');
  const session = usePlatformSession();
  if (session.inTelegram && (session.loading || session.error))
    return (
      <main className="auth-screen surface">
        <h1>Creator Engine</h1>
        <output>{session.error || t.loading}</output>
        <Button onClick={() => window.location.reload()}>{t.retry}</Button>
      </main>
    );
  return (
    <SidebarProvider>
      <Sidebar className="engine-sidebar">
        <SidebarHeader>
          <div className="brand">
            <span className="brand-icon">
              <Send size={20} />
            </span>
            <span>
              creator<span className="brand-dot">.</span>
            </span>
          </div>
          <div className="workspace-card">
            <span className="avatar">C</span>
            <div>
              <strong>
                {session.workspaces.find((w) => w.id === session.workspaceId)
                  ?.name || 'Creator Studio'}
              </strong>
              <small>{t.workspace}</small>
            </div>
            {!session.live && <span className="tiny-badge">PRO</span>}
          </div>
        </SidebarHeader>
        <SidebarContent>
          {groups.map((g) => (
            <SidebarGroup key={g.label}>
              <SidebarGroupLabel>{g.label}</SidebarGroupLabel>
              <SidebarMenu>
                {g.items.map(([key, Icon]) => (
                  <SidebarMenuItem key={key}>
                    <SidebarMenuButton
                      isActive={section === key}
                      onClick={() => {
                        setSection(key);
                        setWizard(false);
                      }}
                    >
                      <Icon />
                      <span>{t[key]}</span>
                      {key === 'receipts' && !session.live && (
                        <span className="nav-count">3</span>
                      )}
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroup>
          ))}
        </SidebarContent>
        <SidebarFooter>
          <div className="sidebar-person">
            <span className="avatar small">CS</span>
            <div>
              <strong>
                {session.workspaces.find((w) => w.id === session.workspaceId)
                  ?.name || 'Creator Studio'}
              </strong>
              <small>
                {session.live ? session.userName : 'Espacio de ejemplo'}
              </small>
            </div>
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="topbar">
          <div className="row">
            <SidebarTrigger />
            <span className="breadcrumb">
              Tu espacio <span>/</span>{' '}
              <strong>{t[section as keyof typeof t] as string}</strong>
            </span>
          </div>
          <span className="demo-label">
            <span />
            {session.live ? t.connected : t.demo}
          </span>
        </header>
        <main className="workspace-main">
          {session.live && (
            <div className="workspace-switcher">
              <Select
                value={session.workspaceId}
                onValueChange={(value) => session.setWorkspaceId(String(value))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Seleccionar espacio" />
                </SelectTrigger>
                <SelectContent>
                  {session.workspaces.map((w) => (
                    <SelectItem key={w.id} value={w.id}>
                      {w.name} · {w.role}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span className="success-box">
                {t.connected} · {session.userName}
              </span>
            </div>
          )}
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                {session.workspaces.find((w) => w.id === session.workspaceId)
                  ?.name || 'CREATOR STUDIO'}
              </p>
              <h1>
                {wizard
                  ? t.setupTitle
                  : section === 'home'
                    ? t.today
                    : (t[section as keyof typeof t] as string)}
              </h1>
              <p>{wizard ? t.setupBody : t.overview}</p>
            </div>
            <Button className="primary-action" onClick={() => setWizard(true)}>
              <Plus />
              {t.createBot}
            </Button>
          </div>
          {wizard ? (
            <Wizard session={session} finish={() => setWizard(false)} />
          ) : section === 'home' && !session.live ? (
            <>
              <div className="metrics-grid">
                {[
                  [t.revenue, '12.480', 'XTR', '+18,6 %', 'tone-blue'],
                  [t.active, '148', '', '+12 este mes', ''],
                  [t.newClients, '32', '', 'Este mes', ''],
                  [t.pendingReceipts, '3', '', 'Por revisar', 'tone-amber'],
                ].map(([label, value, unit, detail, tone]) => (
                  <section className={'metric surface ' + tone} key={label}>
                    <div className="metric-label">
                      {label}
                      <ArrowUpRight size={17} />
                    </div>
                    <div className="metric-number">
                      {value} <span>{unit}</span>
                    </div>
                    <p>{detail}</p>
                  </section>
                ))}
              </div>
              <div className="dashboard-grid">
                <section className="surface chart-panel">
                  <div className="section-heading">
                    <div>
                      <h2>Ingresos en Stars</h2>
                      <p>Septiembre · Vista de ejemplo</p>
                    </div>
                    <span className="pill">Este mes</span>
                  </div>
                  <div className="chart-y">
                    <span>6.000</span>
                    <span>4.000</span>
                    <span>2.000</span>
                  </div>
                  <div
                    className="bar-chart"
                    aria-label="Gráfico de ingresos ficticios"
                  >
                    {[
                      23, 36, 29, 44, 38, 53, 47, 63, 50, 67, 62, 80, 69, 83,
                      75, 94, 81, 89, 100, 93,
                    ].map((h, i) => (
                      <div key={i} style={{ height: `${h}%` }}>
                        <span>{h * 60} XTR</span>
                      </div>
                    ))}
                  </div>
                  <div className="chart-x">
                    <span>01 SEP</span>
                    <span>10 SEP</span>
                    <span>20 SEP</span>
                    <span>30 SEP</span>
                  </div>
                </section>
                <section className="bot-panel">
                  <div className="section-heading">
                    <p>{t.botStatus}</p>
                    <span className="status-dot" />
                  </div>
                  <div className="bot-avatar">
                    <Bot size={38} />
                  </div>
                  <h2>Studio Club</h2>
                  <p>@studio_club_example_bot</p>
                  <div className="bot-ready">
                    <Check size={15} />
                    {t.ready}
                  </div>
                  <div className="bot-stat">
                    <span>Canal privado</span>
                    <strong>Studio Members</strong>
                  </div>
                  <div className="bot-stat">
                    <span>Plan principal</span>
                    <strong>Premium · 30 días</strong>
                  </div>
                  <Button
                    variant="secondary"
                    className="full"
                    onClick={() => setSection('bots')}
                  >
                    Administrar bot
                    <ArrowRight />
                  </Button>
                </section>
              </div>
              <div className="dashboard-grid">
                <section className="surface">
                  <div className="section-heading">
                    <h2>{t.activity}</h2>
                    <Button
                      variant="ghost"
                      onClick={() => setSection('payments')}
                    >
                      Ver pagos
                      <ArrowUpRight />
                    </Button>
                  </div>
                  {[
                    [
                      'LM',
                      'Lucía M.',
                      'Renovó Premium 30 días',
                      '500 XTR',
                      'Hace 12 min',
                    ],
                    [
                      'DP',
                      'Diego P.',
                      'Se unió a tu comunidad',
                      '500 XTR',
                      'Hace 38 min',
                    ],
                    [
                      'AS',
                      'Ana S.',
                      'Envió un comprobante',
                      'Pendiente',
                      'Hace 1 h',
                    ],
                  ].map(([initial, name, action, amount, time]) => (
                    <div className="activity-row" key={initial}>
                      <span className="avatar">{initial}</span>
                      <div>
                        <strong>{name}</strong>
                        <p>{action}</p>
                      </div>
                      <div className="activity-amount">
                        <strong>{amount}</strong>
                        <p>{time}</p>
                      </div>
                    </div>
                  ))}
                </section>
                <section className="surface next-step">
                  <span className="icon-tile">
                    <Workflow />
                  </span>
                  <h2>Haz que cada bienvenida cuente</h2>
                  <p>
                    Prepara un mensaje para quienes lleguen a tu bot por primera
                    vez.
                  </p>
                  <Button
                    variant="outline"
                    onClick={() => setSection('automations')}
                  >
                    Ver automatizaciones
                    <ArrowRight />
                  </Button>
                </section>
              </div>
            </>
          ) : (
            <WorkspaceView
              key={session.workspaceId + section}
              section={section}
              call={session.call}
              workspaceId={session.workspaceId}
              live={session.live}
              owner={session.owner}
              startWizard={() => setWizard(true)}
            />
          )}
          <footer className="workspace-footer">
            <ShieldCheck size={15} /> {t.security}
            <span>Creator Engine</span>
          </footer>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
