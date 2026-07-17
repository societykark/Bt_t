import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ========== CONFIGURACIÓN SEGURA ==========
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("❌ La variable de entorno TOKEN no está configurada.")

CACHE_TTL = 300
MAX_RESULTS = 20

# ========== LOGS ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========== CACHÉ ==========
cache: Dict[str, Dict] = {}

def get_cache(key: str) -> Optional[Dict]:
    if key in cache:
        data, timestamp = cache[key]
        if datetime.now() - timestamp < timedelta(seconds=CACHE_TTL):
            return data
        del cache[key]
    return None

def set_cache(key: str, data: Dict):
    cache[key] = (data, datetime.now())

# ========== COMANDOS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🕵️ *Bot OSINT - Investigación en fuentes abiertas*\n\n"
        "Comandos disponibles:\n"
        "🔍 `/search <usuario>` - Buscar usuario en redes sociales (WhatsMyName)\n"
        "🌐 `/ip <dirección>` - Geolocalizar una IP\n"
        "📧 `/email <correo>` - Verificar brechas de datos (emailrep.io)\n"
        "📱 `/phone <número>` - Buscar información de un teléfono\n"
        "🏛️ `/web <dominio>` - Obtener WHOIS de un dominio\n"
        "🗺️ `/map <ip>` - Mostrar ubicación en mapa\n"
        "📋 `/menu` - Mostrar este menú\n\n"
        "👨‍💻 Creado por societykark",
        parse_mode=ParseMode.MARKDOWN,
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("🔍 Buscar usuario", callback_data="search")],
        [InlineKeyboardButton("🌐 Geolocalizar IP", callback_data="ip")],
        [InlineKeyboardButton("📧 Verificar email", callback_data="email")],
        [InlineKeyboardButton("📱 Buscar teléfono", callback_data="phone")],
        [InlineKeyboardButton("🏛️ WHOIS dominio", callback_data="web")],
        [InlineKeyboardButton("🗺️ Mapa de IP", callback_data="map")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📋 *Elige una opción:*", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"✏️ Escribe el comando con el dato:\n\n`/{query.data} <valor>`",
        parse_mode=ParseMode.MARKDOWN,
    )

# ========== SEARCH (WHATS MY NAME - API PÚBLICA) ==========

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("❌ Uso: `/search <nombre_usuario>`", parse_mode=ParseMode.MARKDOWN)
        return

    username = context.args[0].strip()
    cache_key = f"search_{username}"
    cached = get_cache(cache_key)
    if cached:
        await update.message.reply_text(
            f"🔍 *Resultados para `{username}` (desde caché):*\n\n{cached}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    status_msg = await update.message.reply_text(
        f"🔍 Buscando `{username}` en redes sociales...\n⏳ Esto puede tomar unos segundos.",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        url = f"https://whatsmyname.app/api/v1/username/{username}"
        response = requests.get(url, timeout=30)
        
        if response.status_code != 200:
            await status_msg.edit_text(
                f"❌ Error al consultar WhatsMyName: Código {response.status_code}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        data = response.json()
        if not data.get("sites") or len(data["sites"]) == 0:
            await status_msg.edit_text(f"❌ No se encontró el usuario `{username}` en ninguna red social.", parse_mode=ParseMode.MARKDOWN)
            return

        sites = [site for site in data["sites"] if site.get("username_found", False)]
        if not sites:
            await status_msg.edit_text(f"❌ No se encontró el usuario `{username}` en ninguna red social.", parse_mode=ParseMode.MARKDOWN)
            return

        sites.sort(key=lambda x: x.get("name", "").lower())

        resultado_texto = ""
        count = 0
        for site in sites:
            if count >= MAX_RESULTS:
                break
            name = site.get("name", "Desconocido")
            uri = site.get("uri", "")
            if uri:
                resultado_texto += f"• [{name}]({uri})\n"
            else:
                resultado_texto += f"• {name}\n"
            count += 1

        final_text = f"🔍 *Resultados para `{username}`:*\n\n{resultado_texto}"
        if len(sites) > MAX_RESULTS:
            final_text += f"\n*...y {len(sites) - MAX_RESULTS} redes más.*"

        set_cache(cache_key, final_text)
        await status_msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except requests.exceptions.Timeout:
        await status_msg.edit_text("❌ La búsqueda tomó demasiado tiempo. Intenta más tarde.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error en search: {e}")
        await status_msg.edit_text(f"❌ Error inesperado: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

# ========== IP GEOLOCALIZACIÓN ==========

async def ip_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("❌ Uso: `/ip <dirección_IP>`", parse_mode=ParseMode.MARKDOWN)
        return

    ip = context.args[0].strip()
    cache_key = f"ip_{ip}"
    cached = get_cache(cache_key)
    if cached:
        await update.message.reply_text(f"🌐 *Información de IP `{ip}` (desde caché):*\n\n{cached}", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await update.message.reply_text(f"🌐 Consultando información de `{ip}`...", parse_mode=ParseMode.MARKDOWN)

    try:
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,zip,lat,lon,isp,org,as,timezone")
        data = response.json()

        if data.get("status") == "fail":
            await status_msg.edit_text(f"❌ No se pudo geolocalizar `{ip}`: {data.get('message', 'Desconocido')}", parse_mode=ParseMode.MARKDOWN)
            return

        resultado = (
            f"📌 *IP:* `{ip}`\n"
            f"📍 *País:* {data.get('country', 'N/A')}\n"
            f"🏙️ *Región:* {data.get('regionName', 'N/A')}\n"
            f"🌆 *Ciudad:* {data.get('city', 'N/A')}\n"
            f"📮 *Código Postal:* {data.get('zip', 'N/A')}\n"
            f"🗺️ *Coordenadas:* {data.get('lat', 'N/A')}, {data.get('lon', 'N/A')}\n"
            f"🕒 *Huso horario:* {data.get('timezone', 'N/A')}\n"
            f"🛜 *ISP:* {data.get('isp', 'N/A')}\n"
            f"🏢 *Organización:* {data.get('org', 'N/A')}\n"
            f"🔢 *AS:* {data.get('as', 'N/A')}"
        )

        if data.get("lat") and data.get("lon"):
            maps_link = f"https://www.google.com/maps?q={data['lat']},{data['lon']}"
            resultado += f"\n\n🗺️ [Ver en Google Maps]({maps_link})"

        set_cache(cache_key, resultado)
        await status_msg.edit_text(resultado, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Error en ip_info: {e}")
        await status_msg.edit_text(f"❌ Error inesperado: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

# ========== EMAIL (EMAILREP.IO - SIN API KEY) ==========

async def email_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("❌ Uso: `/email <correo>`", parse_mode=ParseMode.MARKDOWN)
        return

    email = context.args[0].strip()
    cache_key = f"email_{email}"
    cached = get_cache(cache_key)
    if cached:
        await update.message.reply_text(f"📧 *Resultados para `{email}` (desde caché):*\n\n{cached}", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await update.message.reply_text(f"📧 Verificando `{email}` en bases de datos...", parse_mode=ParseMode.MARKDOWN)

    try:
        url = f"https://emailrep.io/{email}"
        response = requests.get(url, timeout=30)

        if response.status_code == 404:
            await status_msg.edit_text(f"✅ No se encontró información sobre `{email}` en las bases de datos públicas.", parse_mode=ParseMode.MARKDOWN)
            set_cache(cache_key, "✅ Sin información pública.")
            return

        if response.status_code == 429:
            await status_msg.edit_text("⏳ Demasiadas peticiones. Espera un momento.", parse_mode=ParseMode.MARKDOWN)
            return

        if response.status_code != 200:
            await status_msg.edit_text(f"❌ Error al consultar emailrep.io: Código {response.status_code}", parse_mode=ParseMode.MARKDOWN)
            return

        data = response.json()
        
        reputation = data.get("reputation", "N/A")
        suspicious = data.get("suspicious", False)
        references = data.get("references", 0)
        details = data.get("details", {})

        resultado = f"📧 *Información sobre `{email}`:*\n\n"
        resultado += f"• *Reputación:* {reputation}\n"
        resultado += f"• *Sospechoso:* {'Sí' if suspicious else 'No'}\n"
        resultado += f"• *Referencias en internet:* {references}\n"

        if details:
            if details.get("email_provider"):
                resultado += f"• *Proveedor de email:* {details['email_provider']}\n"
            if details.get("domain_exists"):
                resultado += f"• *Dominio existe:* {'Sí' if details['domain_exists'] else 'No'}\n"
            if details.get("valid_mx"):
                resultado += f"• *MX válido:* {'Sí' if details['valid_mx'] else 'No'}\n"
            if details.get("free_provider"):
                resultado += f"• *Proveedor gratuito:* {'Sí' if details['free_provider'] else 'No'}\n"
            if details.get("leaked"):
                resultado += f"• *Filtrado en brechas:* {'Sí' if details['leaked'] else 'No'}\n"

        if data.get("breaches"):
            resultado += "\n🚨 *Brechas encontradas:*\n"
            for breach in data["breaches"][:5]:
                resultado += f"• {breach}\n"
            if len(data["breaches"]) > 5:
                resultado += f"*...y {len(data['breaches']) - 5} más.*\n"

        set_cache(cache_key, resultado)
        await status_msg.edit_text(resultado, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error en email_check: {e}")
        await status_msg.edit_text(f"❌ Error inesperado: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

# ========== PHONE (FUNCIONALIDAD BÁSICA) ==========

async def phone_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("❌ Uso: `/phone <número_internacional>`\nEjemplo: `/phone +521234567890`", parse_mode=ParseMode.MARKDOWN)
        return

    phone = context.args[0].strip()
    cache_key = f"phone_{phone}"
    cached = get_cache(cache_key)
    if cached:
        await update.message.reply_text(f"📱 *Información de `{phone}` (desde caché):*\n\n{cached}", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await update.message.reply_text(f"📱 Consultando información de `{phone}`...", parse_mode=ParseMode.MARKDOWN)

    try:
        await status_msg.edit_text(
            "📱 *Funcionalidad en desarrollo*\n\n"
            "Para usar `/phone`, necesitas una API key de numverify.com (gratis).\n"
            "Mientras tanto, puedes buscar el número en Google.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"Error en phone_lookup: {e}")
        await status_msg.edit_text(f"❌ Error: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

# ========== WHOIS ==========

async def whois_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("❌ Uso: `/web <dominio>`\nEjemplo: `/web google.com`", parse_mode=ParseMode.MARKDOWN)
        return

    domain = context.args[0].strip()
    cache_key = f"whois_{domain}"
    cached = get_cache(cache_key)
    if cached:
        await update.message.reply_text(f"🏛️ *WHOIS de `{domain}` (desde caché):*\n\n{cached}", parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await update.message.reply_text(f"🏛️ Consultando WHOIS de `{domain}`...", parse_mode=ParseMode.MARKDOWN)

    try:
        import whois
        w = whois.whois(domain)

        if not w.name and not w.org and not w.emails:
            await status_msg.edit_text(
                f"❌ No se encontró información WHOIS para `{domain}`.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        resultado = f"🏛️ *WHOIS de `{domain}`:*\n\n"
        resultado += f"• *Registrante:* {w.name if w.name else 'N/A'}\n"
        resultado += f"• *Organización:* {w.org if w.org else 'N/A'}\n"
        resultado += f"• *Email:* {w.emails if w.emails else 'N/A'}\n"
        resultado += f"• *Teléfono:* {w.phone if w.phone else 'N/A'}\n"
        resultado += f"• *Creación:* {w.creation_date if w.creation_date else 'N/A'}\n"
        resultado += f"• *Expiración:* {w.expiration_date if w.expiration_date else 'N/A'}\n"
        resultado += f"• *Servidores NS:* {', '.join(w.name_servers) if w.name_servers else 'N/A'}\n"
        if w.status:
            resultado += f"• *Estado:* {', '.join(w.status) if isinstance(w.status, list) else w.status}\n"

        set_cache(cache_key, resultado)
        await status_msg.edit_text(resultado, parse_mode=ParseMode.MARKDOWN)

    except ImportError:
        await status_msg.edit_text("❌ La librería `whois` no está instalada.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error en whois_lookup: {e}")
        if "No match for" in str(e):
            await status_msg.edit_text(
                f"❌ El dominio `{domain}` no tiene registro WHOIS público.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await status_msg.edit_text(f"❌ Error al obtener WHOIS: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

# ========== MAP ==========

async def map_ip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("❌ Uso: `/map <dirección_IP>`", parse_mode=ParseMode.MARKDOWN)
        return

    ip = context.args[0].strip()
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}?fields=lat,lon")
        data = response.json()
        if data.get("lat") and data.get("lon"):
            maps_link = f"https://www.google.com/maps?q={data['lat']},{data['lon']}"
            await update.message.reply_text(
                f"🗺️ *Ubicación de IP `{ip}`:*\n\n{data['lat']}, {data['lon']}\n\n[Ver en Google Maps]({maps_link})",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(f"❌ No se pudo obtener la ubicación de `{ip}`.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

# ========== UNKNOWN COMMAND ==========

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("❌ Comando no reconocido. Usa `/menu`.", parse_mode=ParseMode.MARKDOWN)

# ========== MAIN ==========

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CommandHandler("ip", ip_info))
    application.add_handler(CommandHandler("email", email_check))
    application.add_handler(CommandHandler("phone", phone_lookup))
    application.add_handler(CommandHandler("web", whois_lookup))
    application.add_handler(CommandHandler("map", map_ip))

    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()