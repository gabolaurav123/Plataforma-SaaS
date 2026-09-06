"""Language catalogs shared by admin navigation and customer messages."""

from .ui_catalog import UI_CATALOG

LANGUAGES = {"es": "Español", "en": "English", "pt": "Português"}
CATALOG = {
    "home": ("🏠 Inicio", "🏠 Home", "🏠 Início"),
    "back": ("⬅️ Atrás", "⬅️ Back", "⬅️ Voltar"),
    "cancel": ("❌ Cancelar", "❌ Cancel", "❌ Cancelar"),
    "admin": ("⚙️ Panel de administración", "⚙️ Administration", "⚙️ Administração"),
    "admin_mode": ("👤 Modo administrador", "👤 Administrator mode", "👤 Modo administrador"),
    "dashboard": ("🏠 Dashboard", "🏠 Dashboard", "🏠 Painel"),
    "users": ("👥 Usuarios", "👥 Users", "👥 Usuários"),
    "subscriptions": ("💳 Suscripciones", "💳 Subscriptions", "💳 Assinaturas"),
    "plans": ("📦 Planes", "📦 Plans", "📦 Planos"),
    "payments": ("💰 Pagos", "💰 Payments", "💰 Pagamentos"),
    "methods": ("🏦 Métodos de pago", "🏦 Payment methods", "🏦 Métodos de pagamento"),
    "channels": ("📺 Canales", "📺 Channels", "📺 Canais"),
    "invitations": ("🔗 Invitaciones", "🔗 Invitations", "🔗 Convites"),
    "broadcasts": ("📢 Difusiones", "📢 Broadcasts", "📢 Transmissões"),
    "messages": ("📝 Mensajes", "📝 Messages", "📝 Mensagens"),
    "languages": ("🌎 Idiomas", "🌎 Languages", "🌎 Idiomas"),
    "stats": ("📊 Estadísticas", "📊 Statistics", "📊 Estatísticas"),
    "reports": ("📄 Reportes", "📄 Reports", "📄 Relatórios"),
    "settings": ("⚙️ Configuración", "⚙️ Settings", "⚙️ Configurações"),
    "help": ("🆘 Ayuda", "🆘 Help", "🆘 Ajuda"),
    "team": ("👤 Administradores", "👤 Administrators", "👤 Administradores"),
    "receipts": ("🧾 Comprobantes", "🧾 Receipts", "🧾 Comprovantes"),
    "automation": ("⏱ Automatizaciones", "⏱ Automations", "⏱ Automações"),
    "inbox": ("💬 Conversaciones", "💬 Inbox", "💬 Conversas"),
    "audit": ("📋 Historial", "📋 History", "📋 Histórico"),
    "preview": ("👁 Ver como usuario", "👁 View as customer", "👁 Ver como cliente"),
    "checklist": ("🚀 Configuración inicial", "🚀 Setup checklist", "🚀 Configuração inicial"),
    "new": ("➕ Crear", "➕ Create", "➕ Criar"),
    "edit": ("✏️ Editar", "✏️ Edit", "✏️ Editar"),
    "next": ("Siguiente →", "Next →", "Próximo →"),
    "confirm": ("✅ Confirmar", "✅ Confirm", "✅ Confirmar"),
    "saved": ("✅ Configuración guardada.", "✅ Settings saved.", "✅ Configuração salva."),
    "empty": ("Sin registros.", "No records.", "Sem registros."),
    "select": ("Selecciona una opción:", "Select an option:", "Selecione uma opção:"),
    "language_saved": ("Idioma guardado.", "Language saved.", "Idioma salvo."),
    "admin_language": ("Idioma de administración", "Administration language", "Idioma da administração"),
    "customer_language": ("Idioma de mis mensajes", "My message language", "Idioma das minhas mensagens"),
    "default_language": (
        "Idioma predeterminado del negocio",
        "Business default language",
        "Idioma padrão do negócio",
    ),
    "view_plans": ("💎 Ver planes", "💎 View plans", "💎 Ver planos"),
    "membership": ("👤 Mi suscripción", "👤 My subscription", "👤 Minha assinatura"),
    "renew": ("💳 Renovar", "💳 Renew", "💳 Renovar"),
    "support": ("🆘 Soporte", "🆘 Support", "🆘 Suporte"),
    "policies": ("📜 Políticas", "📜 Policies", "📜 Políticas"),
    "opt_out": ("🔕 No recibir difusiones", "🔕 Unsubscribe from broadcasts", "🔕 Desativar transmissões"),
    "received": (
        "Mensaje recibido. Nuestro equipo podrá responderte aquí.",
        "Message received. Our team can reply here.",
        "Mensagem recebida. Nossa equipe poderá responder aqui.",
    ),
    "no_membership": (
        "Aún no tienes suscripciones.",
        "You have no subscriptions yet.",
        "Você ainda não tem assinaturas.",
    ),
    "not_ready": (
        "Este bot está en preparación. Vuelve pronto.",
        "This bot is being prepared. Please return soon.",
        "Este bot está sendo preparado. Volte em breve.",
    ),
    "choose_plan": (
        "Selecciona un plan para ver sus condiciones.",
        "Select a plan to view its terms.",
        "Selecione um plano para ver suas condições.",
    ),
    "checkout_queued": (
        "Estamos preparando tu pago. Te enviaremos el enlace aquí.",
        "We are preparing your payment. The link will arrive here.",
        "Estamos preparando seu pagamento. O link chegará aqui.",
    ),
    "receipt_received": (
        "Comprobante recibido. Te avisaremos cuando sea revisado.",
        "Receipt received. We will notify you after review.",
        "Comprovante recebido. Avisaremos após a revisão.",
    ),
    "restore": ("Restaurar mensaje predeterminado", "Restore default message", "Restaurar mensagem padrão"),
    "report_queued": (
        "📄 Reporte solicitado. Lo recibirás aquí cuando esté listo.",
        "📄 Report requested. It will arrive here when ready.",
        "📄 Relatório solicitado. Você o receberá aqui.",
    ),
    "broadcast_queued": (
        "✅ Difusión programada correctamente.",
        "✅ Broadcast successfully scheduled.",
        "✅ Transmissão agendada com sucesso.",
    ),
    "error": (
        "⚠️ No pudimos procesar esta operación. Inténtalo nuevamente.",
        "⚠️ We could not process this operation. Please try again.",
        "⚠️ Não foi possível processar esta operação. Tente novamente.",
    ),
}


CATALOG.update(
    {
        "send_receipt": ("📎 Enviar comprobante", "📎 Send receipt", "📎 Enviar comprovante"),
        "pay_now": ("Pagar", "Pay", "Pagar"),
        "pay_with": ("{method} · {amount}", "{method} · {amount}", "{method} · {amount}"),
        "choose_receipt_payment": (
            "Selecciona el pago de este comprobante:",
            "Select the payment for this receipt:",
            "Selecione o pagamento deste comprovante:",
        ),
        "no_pending_transfer": (
            "No tienes una transferencia pendiente. Abre el plan para iniciar un pago.",
            "You have no pending transfer. Open a plan to start payment.",
            "Você não tem transferências pendentes. Abra um plano para iniciar o pagamento.",
        ),
        "receipt_queued": (
            "📎 Estamos revisando el archivo. Te avisaremos cuando se registre.",
            "📎 We are checking the file and will notify you when it is recorded.",
            "📎 Estamos verificando o arquivo. Avisaremos quando for registrado.",
        ),
        "plan_duration": ("Duración: {days} días", "Duration: {days} days", "Duração: {days} dias"),
        "automatic_renewal": (
            "Renovación automática cada 30 días con Stars.",
            "Automatic renewal every 30 days with Stars.",
            "Renovação automática a cada 30 dias com Stars.",
        ),
        "manual_renewal": ("Renovación manual.", "Manual renewal.", "Renovação manual."),
        "payment_terms": (
            "Al continuar al pago aceptas las condiciones del negocio.",
            "By proceeding to payment you accept the business terms.",
            "Ao continuar para o pagamento, você aceita os termos do negócio.",
        ),
        "terms": ("Términos", "Terms", "Termos"),
        "privacy": ("Privacidad", "Privacy", "Privacidade"),
        "refund": ("Reembolsos", "Refunds", "Reembolsos"),
        "active": ("Activa", "Active", "Ativa"),
        "inactive": ("Vencida o inactiva", "Expired or inactive", "Vencida ou inativa"),
        "membership_line": (
            "{plan}: {status} · hasta {end}",
            "{plan}: {status} · until {end}",
            "{plan}: {status} · até {end}",
        ),
        "cancel_renewal": (
            "Cancelar renovación automática",
            "Cancel automatic renewal",
            "Cancelar renovação automática",
        ),
        "enable_renewal": (
            "Activar renovación automática",
            "Enable automatic renewal",
            "Ativar renovação automática",
        ),
        "renewal_confirm": (
            "Confirma el cambio. Se conserva el periodo ya pagado.",
            "Confirm the change. Your paid period is preserved.",
            "Confirme a alteração. O período já pago será mantido.",
        ),
        "change_queued": (
            "Cambio solicitado. Te avisaremos cuando se complete.",
            "Change requested. We will notify you when complete.",
            "Alteração solicitada. Avisaremos quando estiver concluída.",
        ),
        "access_queued": (
            "Preparando tus enlaces personales de acceso.",
            "Preparing your personal access links.",
            "Preparando seus links pessoais de acesso.",
        ),
        "opt_out_saved": (
            "Desactivaste las difusiones. Seguirás recibiendo avisos de pago y acceso.",
            "Broadcasts disabled. Payment and access messages remain enabled.",
            "Transmissões desativadas. Avisos de pagamento e acesso continuam ativos.",
        ),
    }
)


CATALOG.update(
    {
        "report_ready": (
            "📄 Reporte generado con los registros del periodo solicitado.",
            "📄 Report generated from records in the requested period.",
            "📄 Relatório gerado com os registros do período solicitado.",
        ),
        "summary_title": (
            "📊 {name}\nPeriodo: {start} → {end}",
            "📊 {name}\nPeriod: {start} → {end}",
            "📊 {name}\nPeríodo: {start} → {end}",
        ),
        "current_state": ("Estado actual", "Current status", "Estado atual"),
        "period_metrics": ("Resultados del periodo", "Period results", "Resultados do período"),
        "users_total": ("Usuarios", "Users", "Usuários"),
        "users_new": ("Nuevos usuarios", "New users", "Novos usuários"),
        "users_active_7d": ("Activos en 7 días", "Active in 7 days", "Ativos em 7 dias"),
        "users_without_active_subscription": (
            "Sin suscripción activa",
            "Without active subscription",
            "Sem assinatura ativa",
        ),
        "subscriptions_active": ("Suscripciones activas", "Active subscriptions", "Assinaturas ativas"),
        "subscriptions_expiring_7d": ("Vencen en 7 días", "Expire within 7 days", "Vencem em 7 dias"),
        "subscriptions_expired": ("Suscripciones vencidas", "Expired subscriptions", "Assinaturas vencidas"),
        "payments_pending": ("Pagos pendientes", "Pending payments", "Pagamentos pendentes"),
        "receipts_pending": ("Comprobantes pendientes", "Pending receipts", "Comprovantes pendentes"),
        "renewals": (
            "Compras repetidas del mismo plan",
            "Repeat purchases of the same plan",
            "Compras repetidas do mesmo plano",
        ),
        "renewal_share_percent": (
            "Renovaciones entre compras (%)",
            "Renewals among purchases (%)",
            "Renovações entre compras (%)",
        ),
        "cancellations": ("Cancelaciones", "Cancellations", "Cancelamentos"),
        "invitations_used": ("Invitaciones usadas", "Invitations used", "Convites usados"),
        "conversion_percent": (
            "Conversión acumulada (%)",
            "Lifetime conversion (%)",
            "Conversão acumulada (%)",
        ),
        "growth_percent": ("Crecimiento de usuarios (%)", "User growth (%)", "Crescimento de usuários (%)"),
        "churn_percent": (
            "Bajas de clientes de pago (%)",
            "Paid customer churn (%)",
            "Perda de clientes pagantes (%)",
        ),
        "money_totals": (
            "Bruto: {gross}\nDevoluciones: {refund}\nNeto: {net}\nCompra media: {average}",
            "Gross: {gross}\nRefunds: {refund}\nNet: {net}\nAverage purchase: {average}",
            "Bruto: {gross}\nReembolsos: {refund}\nLíquido: {net}\nCompra média: {average}",
        ),
        "report_basis": (
            "Cobros y devoluciones según su fecha. Neto antes de comisiones de procesamiento, impuestos y facturas SaaS. N/D: sin base histórica suficiente.",
            "Captures and refunds by their recognition date. Net before processor fees, taxes and SaaS invoices. N/A: insufficient historical baseline.",
            "Cobranças e reembolsos pela data de registro. Líquido antes de taxas, impostos e faturas SaaS. N/D: histórico insuficiente.",
        ),
        "mrr_label": (
            "MRR de renovaciones automáticas Stars",
            "MRR from automatic Stars renewals",
            "MRR de renovações automáticas Stars",
        ),
        "operation_failed": (
            "⚠️ No pudimos completar la operación. Revisa la configuración o inténtalo nuevamente.",
            "⚠️ We could not complete the operation. Check the settings or try again.",
            "⚠️ Não foi possível concluir a operação. Verifique a configuração ou tente novamente.",
        ),
    }
)


CATALOG.update(UI_CATALOG)

CATALOG.update(
    {
        "bank_transfer": ("Transferencia bancaria", "Bank transfer", "Transferência bancária"),
        "saas_summary_queued": (
            "📋 Preparando tu resumen de consumo y facturación.",
            "📋 Preparing your usage and billing summary.",
            "📋 Preparando seu resumo de uso e faturamento.",
        ),
        "saas_revenue_line": (
            "{currency} · Ventas: {sales} · Devoluciones: {refunds} · Base neta: {net}",
            "{currency} · Sales: {sales} · Refunds: {refunds} · Net base: {net}",
            "{currency} · Vendas: {sales} · Reembolsos: {refunds} · Base líquida: {net}",
        ),
        "saas_usage_summary": (
            "📊 Recursos utilizados · {measured}\nBots: {bots}/{bots_limit}\nContactos registrados: {contacts}/{contacts_limit}\nAdministradores: {admins}/{admins_limit}\nCuotas del mes {month} UTC:\nDifusiones: {campaigns}/{campaigns_limit}\nExportaciones: {exports}/{exports_limit}",
            "📊 Resources used · {measured}\nBots: {bots}/{bots_limit}\nRegistered contacts: {contacts}/{contacts_limit}\nAdministrators: {admins}/{admins_limit}\nCalendar-month quotas {month} UTC:\nBroadcasts: {campaigns}/{campaigns_limit}\nExports: {exports}/{exports_limit}",
            "📊 Recursos utilizados · {measured}\nBots: {bots}/{bots_limit}\nContatos registrados: {contacts}/{contacts_limit}\nAdministradores: {admins}/{admins_limit}\nCotas do mês {month} UTC:\nTransmissões: {campaigns}/{campaigns_limit}\nExportações: {exports}/{exports_limit}",
        ),
        "saas_invoice_summary": (
            "🧾 {number} · {state}\nPlan: {plan}\nPeriodo: {start} → {end}\n\nCuota fija: USD {fixed:.2f}\nComisión del plan: {rate:g}%\nComisión calculada: {commission}\nAjustes/descuentos: USD {adjustment:.2f}\nTotal facturado: {total}\nPagos registrados: USD {paid:.2f}\n💳 SALDO A PAGAR: {due}\nFecha límite: {deadline}",
            "🧾 {number} · {state}\nPlan: {plan}\nPeriod: {start} → {end}\n\nFixed fee: USD {fixed:.2f}\nPlan commission: {rate:g}%\nCalculated commission: {commission}\nAdjustments/discounts: USD {adjustment:.2f}\nInvoice total: {total}\nRecorded payments: USD {paid:.2f}\n💳 BALANCE DUE: {due}\nDue date: {deadline}",
            "🧾 {number} · {state}\nPlano: {plan}\nPeríodo: {start} → {end}\n\nTaxa fixa: USD {fixed:.2f}\nComissão do plano: {rate:g}%\nComissão calculada: {commission}\nAjustes/descontos: USD {adjustment:.2f}\nTotal faturado: {total}\nPagamentos registrados: USD {paid:.2f}\n💳 SALDO A PAGAR: {due}\nPrazo: {deadline}",
        ),
        "saas_billing_basis": (
            "Se cobra cuota fija + comisión sobre ventas confirmadas; las devoluciones conservan su tasa original. Los recursos muestran uso/límite, sin cargos adicionales por unidad. Las monedas se mantienen separadas. Abre Mi plan SaaS → Facturas para pagar.",
            "Billing is fixed fee + commission on confirmed sales; refunds retain their original rate. Resources show usage/limit, with no extra per-unit charge. Currencies remain separate. Open My SaaS plan → Invoices to pay.",
            "A cobrança é taxa fixa + comissão sobre vendas confirmadas; reembolsos mantêm a taxa original. Recursos mostram uso/limite, sem cobranças adicionais por unidade. As moedas permanecem separadas. Abra Meu plano SaaS → Faturas para pagar.",
        ),
        "connection_valid": (
            "🤖 {name}\n@{username}\nID: {identifier}\nToken válido. Confirma para que esta plataforma opere el bot.",
            "🤖 {name}\n@{username}\nID: {identifier}\nValid token. Confirm to let this platform operate the bot.",
            "🤖 {name}\n@{username}\nID: {identifier}\nToken válido. Confirme para esta plataforma operar o bot.",
        ),
        "replace_webhook": (
            "\nLa conexión actual por webhook será reemplazada.",
            "\nThe current webhook connection will be replaced.",
            "\nA conexão atual por webhook será substituída.",
        ),
        "stop_other_polling": (
            "\nDetén cualquier otro proceso que use este token antes de confirmar.",
            "\nStop any other process using this token before confirming.",
            "\nPare qualquer outro processo que use este token antes de confirmar.",
        ),
        "confirm_connection": ("✅ Confirmar conexión", "✅ Confirm connection", "✅ Confirmar conexão"),
        "connection_failed": (
            "No se pudo conectar el bot. {reason}",
            "Could not connect the bot. {reason}",
            "Não foi possível conectar o bot. {reason}",
        ),
        "token_invalid": (
            "BotFather indica que el token no es válido o fue revocado.",
            "BotFather reports an invalid or revoked token.",
            "O BotFather informa que o token é inválido ou foi revogado.",
        ),
        "renewal_updated": ("✅ Renovación actualizada.", "✅ Renewal updated.", "✅ Renovação atualizada."),
        "platform_state_summary": (
            "🛡 Plataforma · estado actual\nNegocios: {tenants}\nNuevos este mes (UTC): {new}\nUsuarios de plataforma: {users}\nBots: {bots}\nClientes de los negocios: {contacts}\n\nEstados SaaS:\n{states}",
            "🛡 Platform · current status\nBusinesses: {tenants}\nNew this month (UTC): {new}\nPlatform users: {users}\nBots: {bots}\nBusiness customers: {contacts}\n\nSaaS states:\n{states}",
            "🛡 Plataforma · estado atual\nNegócios: {tenants}\nNovos neste mês (UTC): {new}\nUsuários da plataforma: {users}\nBots: {bots}\nClientes dos negócios: {contacts}\n\nEstados SaaS:\n{states}",
        ),
        "platform_money_summary": (
            "\n\nFinanzas de plataforma (acumulado)\nCobros verificados: {receipts}\nCuotas facturadas: {fixed}\nComisiones facturadas: {commission}\nSaldo pendiente: {pending}\nFacturas con conversión pendiente: {unpriced}\n\nCola: {queue}",
            "\n\nPlatform finances (lifetime)\nVerified payments: {receipts}\nInvoiced fixed fees: {fixed}\nInvoiced commissions: {commission}\nOutstanding balance: {pending}\nInvoices awaiting conversion: {unpriced}\n\nQueue: {queue}",
            "\n\nFinanças da plataforma (acumulado)\nPagamentos verificados: {receipts}\nTaxas fixas faturadas: {fixed}\nComissões faturadas: {commission}\nSaldo pendente: {pending}\nFaturas aguardando conversão: {unpriced}\n\nFila: {queue}",
        ),
        "failed_payment_notice": (
            "⚠️ Pago fallido · {reference}",
            "⚠️ Failed payment · {reference}",
            "⚠️ Pagamento falhou · {reference}",
        ),
        "provider_review_notice": (
            "⚠️ Una confirmación no coincide con un cobro de este bot. Revisa el proveedor. Referencia: {reference}",
            "⚠️ A confirmation does not match a payment in this bot. Check the provider. Reference: {reference}",
            "⚠️ Uma confirmação não corresponde a um pagamento deste bot. Verifique o provedor. Referência: {reference}",
        ),
        "receipt_notice": (
            "🧾 Comprobante pendiente · {bot}\n{name}",
            "🧾 Receipt awaiting review · {bot}\n{name}",
            "🧾 Comprovante aguardando revisão · {bot}\n{name}",
        ),
        "duplicate_receipt_notice": (
            "🧾 Comprobante pendiente · {bot}\n{name}\n⚠️ Posible duplicado",
            "🧾 Receipt awaiting review · {bot}\n{name}\n⚠️ Possible duplicate",
            "🧾 Comprovante aguardando revisão · {bot}\n{name}\n⚠️ Possível duplicado",
        ),
        "vip_notice": (
            "⭐ Usuario marcado VIP: {name}",
            "⭐ User marked VIP: {name}",
            "⭐ Usuário marcado como VIP: {name}",
        ),
        "cancel_notice": (
            "Suscripción cancelada · {name} · {plan}",
            "Subscription cancelled · {name} · {plan}",
            "Assinatura cancelada · {name} · {plan}",
        ),
        "trial_ended_notice": (
            "Tu prueba gratuita terminó. Conservamos tus datos y configuración. Selecciona un plan para continuar.",
            "Your free trial ended. Your data and settings are preserved. Select a plan to continue.",
            "Seu teste gratuito terminou. Seus dados e configurações foram mantidos. Selecione um plano para continuar.",
        ),
        "trial_reminder_notice": (
            "Tu prueba termina en menos de {hours} horas. Abre Mi plan SaaS para continuar.",
            "Your trial ends in less than {hours} hours. Open My SaaS plan to continue.",
            "Seu teste termina em menos de {hours} horas. Abra Meu plano SaaS para continuar.",
        ),
        "cycle_reminder_notice": (
            "Tu ciclo SaaS termina mañana. Revisa cuota y comisión en Mi plan SaaS.",
            "Your SaaS cycle ends tomorrow. Review your fee and commission in My SaaS plan.",
            "Seu ciclo SaaS termina amanhã. Revise a taxa e a comissão em Meu plano SaaS.",
        ),
        "invoice_notice": (
            "Factura de plataforma: {number}\nCuota USD {fixed:.2f}\nComisión USD {commission:.2f}\nAbre Mi plan SaaS → Facturas.",
            "Platform invoice: {number}\nFixed fee USD {fixed:.2f}\nCommission USD {commission:.2f}\nOpen My SaaS plan → Invoices.",
            "Fatura da plataforma: {number}\nTaxa fixa USD {fixed:.2f}\nComissão USD {commission:.2f}\nAbra Meu plano SaaS → Faturas.",
        ),
        "invoice_rate_notice": (
            "La conversión de tu factura está pendiente. Soporte debe completarla antes del cobro.",
            "Your invoice conversion is pending. Support must complete it before payment.",
            "A conversão da sua fatura está pendente. O suporte precisa concluí-la antes do pagamento.",
        ),
        "invoice_overdue_notice": (
            "Tu factura SaaS venció. Las funciones comerciales están suspendidas y los datos se conservan. Abre Mi plan SaaS → Facturas.",
            "Your SaaS invoice is overdue. Commercial functions are suspended and your data is preserved. Open My SaaS plan → Invoices.",
            "Sua fatura SaaS venceu. As funções comerciais estão suspensas e seus dados foram mantidos. Abra Meu plano SaaS → Faturas.",
        ),
        "invoice_pending_notice": (
            "Tienes una factura SaaS pendiente. Continúas dentro del periodo de tolerancia.",
            "You have an unpaid SaaS invoice. Your grace period is still active.",
            "Você tem uma fatura SaaS pendente. Seu período de tolerância continua ativo.",
        ),
        "settlement_pending_notice": (
            "💰 Pago de plataforma pendiente de revisión. Abre /admin → Pagos SaaS.",
            "💰 Platform payment awaiting review. Open /admin → SaaS payments.",
            "💰 Pagamento da plataforma aguardando revisão. Abra /admin → Pagamentos SaaS.",
        ),
        "settlement_approved_notice": (
            "✅ Pago de plataforma aprobado.",
            "✅ Platform payment approved.",
            "✅ Pagamento da plataforma aprovado.",
        ),
        "settlement_rejected_notice": (
            "Pago de plataforma rechazado. {note}",
            "Platform payment rejected. {note}",
            "Pagamento da plataforma rejeitado. {note}",
        ),
        "refund_requested_notice": (
            "✅ Solicitud procesada. Consulta el historial del cobro para ver devoluciones confirmadas.",
            "✅ Request processed. See the payment history for confirmed refunds.",
            "✅ Solicitação processada. Consulte o histórico do pagamento para ver os reembolsos confirmados.",
        ),
        "error_reference": (
            "Revisa el formato y los permisos de la operación. Referencia: {code}",
            "Check the requested format and your permissions. Reference: {code}",
            "Verifique o formato solicitado e suas permissões. Referência: {code}",
        ),
        "access_error": (
            "No tienes acceso a esta operación.",
            "You do not have access to this operation.",
            "Você não tem acesso a esta operação.",
        ),
        "billing_error": (
            "Revisa las facturas y el estado de tu cuenta SaaS para continuar.",
            "Review your invoices and SaaS account status to continue.",
            "Revise suas faturas e o estado da conta SaaS para continuar.",
        ),
        "format_error": (
            "Dato no válido. Revisa el formato indicado.",
            "Invalid value. Check the requested format.",
            "Valor inválido. Verifique o formato solicitado.",
        ),
        "trial_error": (
            "La prueba gratuita ya se utilizó o no está disponible. Selecciona un plan.",
            "Your free trial has already been used or is unavailable. Select a plan.",
            "Seu teste gratuito já foi usado ou não está disponível. Selecione um plano.",
        ),
        "limit_error": (
            "Alcanzaste el límite de tu plan. Revisa Mi cuenta SaaS.",
            "You reached your plan limit. Review My SaaS account.",
            "Você atingiu o limite do plano. Revise Minha conta SaaS.",
        ),
    }
)


CATALOG.update(
    {
        "campaign_preview_notice": (
            "👁 Vista previa\nEnviar a {count} usuarios que aceptan difusiones. La audiencia se guardará al comenzar el envío.\nTelegram permite confirmar el envío; no informa de lecturas.",
            "👁 Preview\nSend to {count} users who accept broadcasts. The audience will be saved when sending begins.\nTelegram confirms sending, but does not report reads.",
            "👁 Prévia\nEnviar para {count} usuários que aceitam transmissões. O público será salvo no início do envio.\nO Telegram confirma o envio, mas não informa leituras.",
        ),
        "campaign_confirm_label": ("✅ Confirmar envío", "✅ Confirm sending", "✅ Confirmar envio"),
        "bot_published_notice": (
            "🎉 Tu bot está publicado.",
            "🎉 Your bot is published.",
            "🎉 Seu bot está publicado.",
        ),
        "publish_missing_notice": ("Faltan pasos:\n", "Steps to complete:\n", "Etapas pendentes:\n"),
        "channel_required_notice": (
            "Añade primero un canal o grupo.",
            "Add a channel or group first.",
            "Adicione um canal ou grupo primeiro.",
        ),
        "publish_test_notice": (
            "✅ El bot pudo enviarte este mensaje de prueba.",
            "✅ The bot successfully sent you this test message.",
            "✅ O bot conseguiu enviar esta mensagem de teste.",
        ),
        "publish_check_managed_bot": (
            "Revisar la conexión del bot",
            "Check the bot connection",
            "Verificar a conexão do bot",
        ),
        "publish_check_token": (
            "Conectar un token válido",
            "Connect a valid token",
            "Conectar um token válido",
        ),
        "publish_check_webhook": (
            "Verificar la recepción de mensajes",
            "Verify message reception",
            "Verificar o recebimento de mensagens",
        ),
        "publish_check_welcome": (
            "Configurar la bienvenida",
            "Configure the welcome message",
            "Configurar a mensagem de boas-vindas",
        ),
        "publish_check_plan": (
            "Crear un plan con precio y método de pago válidos",
            "Create a plan with a valid price and payment method",
            "Criar um plano com preço e forma de pagamento válidos",
        ),
        "publish_check_payment_method": (
            "Habilitar un método de pago",
            "Enable a payment method",
            "Ativar uma forma de pagamento",
        ),
        "publish_check_channel_permissions": (
            "Corregir los permisos de los canales",
            "Correct the channel permissions",
            "Corrigir as permissões dos canais",
        ),
        "publish_check_support_and_policies": (
            "Completar soporte, términos, privacidad y reembolsos",
            "Complete support, terms, privacy and refunds",
            "Completar suporte, termos, privacidade e reembolsos",
        ),
        "publish_check_test_message": (
            "Enviar el mensaje de prueba",
            "Send the test message",
            "Enviar a mensagem de teste",
        ),
        "billing_field_banco": ("banco", "bank", "banco"),
        "billing_field_titular": ("titular", "account holder", "titular"),
        "billing_field_cuenta": ("cuenta", "account number", "conta"),
        "billing_field_moneda": ("moneda", "currency", "moeda"),
        "billing_field_instrucciones": ("instrucciones", "instructions", "instruções"),
        "billing_field_activo": (
            "moneda o activo cripto",
            "cryptocurrency or asset",
            "moeda ou ativo cripto",
        ),
        "billing_field_red": ("red", "network", "rede"),
        "billing_field_direccion": ("dirección pública", "public address", "endereço público"),
        "billing_field_enabled": ("habilitado", "enabled", "ativado"),
        "template_WELCOME": ("Bienvenida", "Welcome", "Boas-vindas"),
        "template_PRESENTATION": ("Presentación", "Introduction", "Apresentação"),
        "template_PLAN_LIST": ("Lista de planes", "Plan list", "Lista de planos"),
        "template_PLAN_SELECTED": ("Plan seleccionado", "Selected plan", "Plano selecionado"),
        "template_PAYMENT_METHOD": (
            "Instrucciones de pago",
            "Payment instructions",
            "Instruções de pagamento",
        ),
        "template_BANK_DETAILS": ("Datos de transferencia", "Transfer details", "Dados de transferência"),
        "template_RECEIPT_REQUEST": ("Solicitar comprobante", "Request receipt", "Solicitar comprovante"),
        "template_RECEIPT_RECEIVED": ("Comprobante recibido", "Receipt received", "Comprovante recebido"),
        "template_PAYMENT_APPROVED": ("Pago aprobado", "Payment approved", "Pagamento aprovado"),
        "template_PAYMENT_REJECTED": ("Pago rechazado", "Payment rejected", "Pagamento rejeitado"),
        "template_PURCHASE_COMPLETED": ("Compra completada", "Purchase completed", "Compra concluída"),
        "template_SUBSCRIPTION_ACTIVE": ("Suscripción activa", "Active subscription", "Assinatura ativa"),
        "template_ACCESS_GRANTED": ("Acceso concedido", "Access granted", "Acesso concedido"),
        "template_SUBSCRIPTION_EXPIRING": (
            "Suscripción por vencer",
            "Expiring subscription",
            "Assinatura a vencer",
        ),
        "template_SUBSCRIPTION_EXPIRED": (
            "Suscripción vencida",
            "Expired subscription",
            "Assinatura vencida",
        ),
        "template_RENEWAL": ("Renovación", "Renewal", "Renovação"),
        "template_SUPPORT": ("Soporte", "Support", "Suporte"),
        "template_ERROR": ("Error", "Error", "Erro"),
    }
)


def message(value, language="es"):
    return t(value["key"], language, **value.get("values", {})) if isinstance(value, dict) else value


def error_text(error, language="es"):
    from ..errors import DomainError

    if not isinstance(error, DomainError):
        return t("format_error", language)
    if locale(language) == "es":
        return error.message
    groups = {
        "access_error": {
            "NOT_FOUND",
            "OWNER_REQUIRED",
            "CHILD_BOT_REQUIRED",
            "FORBIDDEN",
            "ROLE_REQUIRED",
            "ADMIN_SUSPENDED",
        },
        "billing_error": {
            "INVOICE_OUTSTANDING",
            "INVOICE_NOT_READY",
            "SAAS_SUSPENDED",
            "EXCESS_PAYMENT",
            "REFERENCE_USED",
        },
        "trial_error": {"TRIAL_UNAVAILABLE", "TRIAL_ALREADY_USED"},
        "limit_error": {"PLAN_LIMIT", "PLATFORM_CAPACITY", "WORKSPACE_LIMIT", "FEATURE_DISABLED"},
    }
    for key, codes in groups.items():
        if error.code in codes:
            return t(key, language)
    return t("error_reference", language, code=error.code)


def locale(value):
    value = (value or "es").split("-")[0].lower()
    return value if value in LANGUAGES else "es"


def t(key, language="es", **values):
    index = {"es": 0, "en": 1, "pt": 2}[locale(language)]
    if key not in CATALOG:
        raise KeyError("Translation key missing: " + key)
    return CATALOG[key][index].format(**values)
