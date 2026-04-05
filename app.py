import os
import json
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "yoguringbot123")
OWNER_PSID = os.environ.get("OWNER_PSID", "")  # Tu PSID de Messenger para recibir pedidos

groq_client = Groq(api_key=GROQ_API_KEY)

# Historial de conversación por usuario (en memoria)
conversations = {}

SYSTEM_PROMPT = """Eres el asistente virtual de Lácteos Yoguring Águila, distribuidora de paletas y bolis en Barranquilla, Colombia. Tu nombre es YoguringBot 🧊.

Tu misión: atender clientes que llegan por Facebook Marketplace, mostrarles el catálogo, tomar su pedido y recopilar sus datos de entrega. Sé amable, usa emojis y habla en español colombiano natural.

=== 📦 CATÁLOGO (se vende por paquetes al por mayor) ===

1. 🧊 Boli Yogurt 10cm  — 47 unidades por paquete — $7.000 el paquete
2. 🧊 Boli Yogurt 15cm  — 33 unidades por paquete — $8.000 el paquete
3. 🧊 Boli Yogurt 12cm  — 50 unidades por paquete — $10.000 el paquete
4. 🧊 Boli Yogurt 19cm  — 35 unidades por paquete — $11.000 el paquete
5. 🍮 Boli Gelatina 15cm — 35 unidades por paquete — $8.000 el paquete
6. 🍦 Shupping Bonaice 19cm — 35 unidades por paquete — $8.000 el paquete

=== 🚚 REGLAS DE DOMICILIO ===

Barranquilla y barrios aledaños:
  • 4 paquetes o más → domicilio GRATIS ✅
  • Menos de 4 paquetes → domicilio $4.000

Malambo, Las Flores, Juan Mina, Galapa:
  • Compra mínima 4 paquetes
  • Domicilio $5.000

Puerto Colombia:
  • Compra mínima 5 paquetes
  • Domicilio $10.000

Si la zona no está en la lista, dile con amabilidad que por el momento no se hace domicilio a esa zona.

=== 📋 FLUJO DE ATENCIÓN (sigue este orden) ===

PASO 1: Saluda calurosamente y muestra el catálogo completo con precios.
PASO 2: El cliente elige productos y cantidades. Confirma cada uno.
PASO 3: Muestra el subtotal de los productos seleccionados.
PASO 4: Pide el nombre completo del cliente.
PASO 5: Pide la dirección exacta y el barrio o municipio.
PASO 6: Calcula el domicilio según la zona y muestra el TOTAL FINAL.
PASO 7: Confirma el pedido. Dile que un asesor lo contactará pronto para coordinar la entrega. ¡Gracias por su compra!

=== ⚠️ REGLAS IMPORTANTES ===
- Se vende SOLO por paquetes, no por unidades sueltas.
- Si preguntan precio unitario, explica que es venta al por mayor por paquetes.
- Siempre calcula bien los totales antes de mostrarlos.
- Cuando el pedido esté COMPLETAMENTE confirmado (tienes nombre, dirección y productos), termina tu respuesta con esta etiqueta especial al final:

[PEDIDO_CONFIRMADO]{"nombre": "...", "direccion": "...", "zona": "...", "productos": ["descripcion x cantidad"], "subtotal": 0, "domicilio": 0, "total": 0}

Reemplaza los valores con los datos reales del pedido. No incluyas texto después del JSON.
"""

def send_message(recipient_id, text):
    """Envía un mensaje de texto por Messenger."""
    url = "https://graph.facebook.com/v19.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }
    requests.post(url, params=params, json=data)

def notify_owner(order_data):
    """Notifica al dueño del negocio con el resumen del pedido."""
    if not OWNER_PSID:
        return
    msg = "🛒 ¡NUEVO PEDIDO YOGURING ÁGUILA!\n"
    msg += "─────────────────────────\n"
    msg += f"👤 Cliente: {order_data.get('nombre', 'N/A')}\n"
    msg += f"📍 Dirección: {order_data.get('direccion', 'N/A')}\n"
    msg += f"🏘️ Zona: {order_data.get('zona', 'N/A')}\n"
    msg += "📦 Productos:\n"
    for p in order_data.get("productos", []):
        msg += f"   • {p}\n"
    msg += "─────────────────────────\n"
    subtotal = order_data.get("subtotal", 0)
    domicilio = order_data.get("domicilio", 0)
    total = order_data.get("total", 0)
    msg += f"💰 Subtotal: ${subtotal:,}\n"
    msg += f"🚚 Domicilio: ${domicilio:,}\n"
    msg += f"✅ TOTAL: ${total:,}\n"
    msg += "─────────────────────────\n"
    msg += "¡Confirma y coordina la entrega!"
    send_message(OWNER_PSID, msg)

def chat_with_groq(user_id, user_message):
    """Llama a Groq con historial de conversación."""
    if user_id not in conversations:
        conversations[user_id] = []

    conversations[user_id].append({"role": "user", "content": user_message})

    # Mantener solo los últimos 20 mensajes para evitar overflow
    history = conversations[user_id][-20:]

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        max_tokens=1024,
        temperature=0.7
    )

    reply = response.choices[0].message.content
    conversations[user_id].append({"role": "assistant", "content": reply})
    return reply

def process_reply(user_id, reply):
    """Detecta si el pedido está confirmado, notifica al dueño y limpia la respuesta."""
    if "[PEDIDO_CONFIRMADO]" in reply:
        partes = reply.split("[PEDIDO_CONFIRMADO]")
        clean_reply = partes[0].strip()
        try:
            json_str = partes[1].strip()
            order_data = json.loads(json_str)
            notify_owner(order_data)
        except Exception as e:
            print(f"Error parseando pedido: {e}")
        return clean_reply
    return reply

@app.route("/webhook", methods=["GET"])
def verify():
    """Verificación del webhook de Facebook."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    """Recibe y procesa mensajes entrantes de Messenger."""
    data = request.get_json()
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event["sender"]["id"]
                if "message" in event and "text" in event["message"]:
                    user_text = event["message"]["text"]
                    reply = chat_with_groq(sender_id, user_text)
                    clean_reply = process_reply(sender_id, reply)
                    send_message(sender_id, clean_reply)
    return jsonify({"status": "ok"}), 200

@app.route("/")
def home():
    return "🧊 YoguringBot Marketplace activo ✅", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
