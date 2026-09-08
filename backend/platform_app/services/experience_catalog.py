"""Native inbox and manual crypto payment copy: Spanish, English, Portuguese."""

CATALOG = {
    "inbox_incoming": (
        "💬 Mensaje de {name} ({username}) · ID {user_id}\nUsa Responder sobre este mensaje para contestarle desde el bot.",
        "💬 Message from {name} ({username}) · ID {user_id}\nUse Reply on this message to answer through the bot.",
        "💬 Mensagem de {name} ({username}) · ID {user_id}\nUse Responder nesta mensagem para responder pelo bot.",
    ),
    "inbox_reply_queued": (
        "✅ Respuesta en cola para el cliente.",
        "✅ Reply queued for the customer.",
        "✅ Resposta na fila para o cliente.",
    ),
    "inbox_reply_target": (
        "Usa Responder sobre un mensaje de cliente que te haya enviado este bot. Tu formulario sigue abierto.",
        "Use Reply on a customer message delivered to you by this bot. Your form is still open.",
        "Use Responder em uma mensagem de cliente enviada a você por este bot. Seu formulário continua aberto.",
    ),
    "inbox_supported": (
        "Envía texto, foto, video, documento, audio, nota de voz, animación, sticker o videomensaje.",
        "Send text, a photo, video, document, audio, voice note, animation, sticker or video note.",
        "Envie texto, foto, vídeo, documento, áudio, nota de voz, animação, figurinha ou mensagem de vídeo.",
    ),
    "crypto_label": ("🪙 Cripto / Binance", "🪙 Crypto / Binance", "🪙 Cripto / Binance"),
    "crypto_intro": (
        "🪙 Cripto / Binance\nGuarda tus direcciones públicas de depósito por moneda y red. El cliente envía un comprobante y tu equipo aprueba o rechaza el pago. No necesitas conectar una API de Binance.",
        "🪙 Crypto / Binance\nSave your public deposit addresses by asset and network. The customer sends proof and your team approves or rejects the payment. No Binance API connection is needed.",
        "🪙 Cripto / Binance\nSalve seus endereços públicos de depósito por moeda e rede. O cliente envia um comprovante e sua equipe aprova ou rejeita o pagamento. Não é preciso conectar uma API da Binance.",
    ),
    "crypto_add": ("➕ Añadir billetera", "➕ Add wallet", "➕ Adicionar carteira"),
    "crypto_enable": ("✅ Habilitar", "✅ Enable", "✅ Ativar"),
    "crypto_disable": ("⬜ Deshabilitar", "⬜ Disable", "⬜ Desativar"),
    "crypto_asset": (
        "Selecciona la moneda que recibirás:",
        "Select the asset you will receive:",
        "Selecione a moeda que você receberá:",
    ),
    "crypto_network_prompt": (
        "Selecciona o escribe la red EXACTA que muestra tu dirección de depósito en Binance o tu billetera. Las opciones del menú son ejemplos; comprueba que el depósito esté habilitado para esa moneda y red.",
        "Select or enter the EXACT network shown for your deposit address in Binance or your wallet. Menu options are examples; check that deposits are enabled for that asset and network.",
        "Selecione ou digite a rede EXATA mostrada no endereço de depósito na Binance ou sua carteira. As opções são exemplos; confira se o depósito está disponível para essa moeda e rede.",
    ),
    "crypto_custom_network": ("✍️ Escribir otra red", "✍️ Enter another network", "✍️ Digitar outra rede"),
    "crypto_address": ("Dirección", "Address", "Endereço"),
    "crypto_address_prompt": (
        "Envía la dirección PÚBLICA de depósito para esa moneda y red. No envíes claves privadas ni frases semilla.",
        "Send the PUBLIC deposit address for that asset and network. Do not send private keys or recovery phrases.",
        "Envie o endereço PÚBLICO de depósito para essa moeda e rede. Não envie chaves privadas nem frases de recuperação.",
    ),
    "crypto_memo_prompt": (
        "Si tu depósito exige Memo / Tag, envíalo exactamente. Si no lo exige, escribe -.",
        "If your deposit requires a Memo / Tag, enter it exactly. Otherwise send -.",
        "Se o depósito exige Memo / Tag, envie exatamente. Caso contrário, envie -.",
    ),
    "crypto_instructions_prompt": (
        "Envía instrucciones adicionales para el cliente (hasta 600 caracteres), o - para omitirlas.",
        "Send additional customer instructions (up to 600 characters), or - to skip.",
        "Envie instruções adicionais ao cliente (até 600 caracteres), ou - para pular.",
    ),
    "crypto_qr_prompt": (
        "Envía una foto del QR de esta dirección, o - para omitirlo.",
        "Send a photo of this address's QR code, or - to skip.",
        "Envie uma foto do QR deste endereço, ou - para pular.",
    ),
    "crypto_review": (
        "Revisa moneda, red, dirección y Memo / Tag contra los datos de depósito de tu billetera antes de confirmar.",
        "Check the asset, network, address and Memo / Tag against your wallet's deposit details before confirming.",
        "Confira moeda, rede, endereço e Memo / Tag com os dados de depósito da carteira antes de confirmar.",
    ),
    "crypto_restart": (
        "Abre Métodos de pago → Cripto / Binance para continuar.",
        "Open Payment methods → Crypto / Binance to continue.",
        "Abra Métodos de pagamento → Cripto / Binance para continuar.",
    ),
    "crypto_press_confirm": (
        "Usa el botón Confirmar después de revisar los datos.",
        "Use Confirm after checking the details.",
        "Use Confirmar após conferir os dados.",
    ),
    "crypto_invalid": (
        "Revisa el dato solicitado y su longitud.",
        "Check the requested value and its length.",
        "Confira o dado solicitado e seu tamanho.",
    ),
    "crypto_choose_network": (
        "Selecciona la red y dirección para este pago:",
        "Select the network and address for this payment:",
        "Selecione a rede e o endereço deste pagamento:",
    ),
    "crypto_payment_notice": (
        "Usa exactamente esta moneda y red, e incluye el Memo / Tag si aparece. Envía el comprobante al terminar. El acceso se activa tras la revisión del administrador.",
        "Use exactly this asset and network, and include the Memo / Tag if shown. Send proof when done. Access starts after the administrator reviews it.",
        "Use exatamente esta moeda e rede e inclua o Memo / Tag se indicado. Envie o comprovante ao terminar. O acesso começa após a análise do administrador.",
    ),
}
