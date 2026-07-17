import os
import asyncio
import json
import logging
import subprocess
from datetime import datetime, timedelta
from typing import Dict, Optional

import requests
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

SHERLOCK_TIMEOUT = 120  # segundos
CACHE_TTL = 300         # 5 minutos
MAX_RESULTS = 20

# ========== LOGS ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========== CACHÉ EN MEMORIA ==========
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
        "🔍 `/search <usuario>` - Buscar usuario en redes sociales\n"
        "🌐 `/ip <dirección>` - Geolocalizar una IP\n"
        "📧 `/email <correo>` - Verificar brechas de datos\n"
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

# ========== SEARCH (SHERLOCK) ==========

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
        f"🔍 Buscando `{username}` en redes sociales...\n⏳ Esto puede tomar hasta 2 minutos.",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        cmd = ["sherlock", username, "--output", "json", "--timeout", "10"]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=SHERLOCK_TIMEOUT)

        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            await status_msg.edit_text(f"❌ Error al ejecutar Sherlock:\n`{error_msg}`", parse_mode=ParseMode.MARKDOWN)
            return

        result = json.loads(stdout.decode())
        if not result or username not in result:
            await status_msg.edit_text(f"❌ No se encontró el usuario `{username}` en ninguna red social.", parse_mode=ParseMode.MARKDOWN)
            return

        data = result[username]
        if not data:
            await status_msg.edit_text(f"❌ No hay datos para `{username}`.", parse_mode=ParseMode.MARKDOWN)
            return

        # Filtrar y ordenar
        plataformas_prioritarias = ["Facebook", "Twitter", "Instagram", "GitHub", "Reddit", "YouTube", "TikTok", "LinkedIn"]
        sorted_data = sorted(data.items(), key=lambda x: (x[0] not in plataformas_prioritarias, x[0]))

        resultado_texto = ""
        count = 0
        for plataforma, url in sorted_data:
            if count >= MAX_RESULTS:
                break
            if url:
                resultado_texto += f"• [{plataforma}]({url})\n"
                count += 1

        if not resultado_texto:
            await status_msg.edit_text(f"❌ No se encontraron redes para `{username}`.", parse_mode=ParseMode.MARKDOWN)
            return

        final_text = f"🔍 *Resultados para `{username}`:*\n\n{resultado_texto}"
        if len(sorted_data) > MAX_RESULTS:
            final_text += f"\n*...y {len(sorted_data) - MAX_RESULTS} redes más.*"

        set_cache(cache_key, final_text)
        await status_msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except asyncio.TimeoutError:
        await status_msg.edit_text(
            f"❌ La búsqueda tomó más de {SHERLOCK_TIMEOUT} segundos. Intenta con un usuario más corto.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except json.JSONDecodeError:
        await status_msg.edit_text("❌ Error al procesar los resultados de Sherlock.", parse_mode=ParseMode.MARKDOWN)
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

    except requests.exceptions.RequestException:
        await status_msg.edit_text("❌ Error al conectar con el servicio de geolocalización.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error en ip_info: {e}")
        await status_msg.edit_text(f"❌ Error inesperado: `{str(e)}`", parse_mode=ParseMode.MARKDOWN)

# ========== EMAIL (Have I Been Pwned) ==========

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

    status_msg = await update.message.reply_text(f"📧 Verificando `{email}` en brechas de datos...", parse_mode=ParseMode.MARKDOWN)

    try:
        response = requests.get(f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}", headers={"hibp-api-key": ""})
        
        if response.status_code == 404:
            await status_msg.edit_text(f"✅ ¡El correo `{email}` no apareció en ninguna brecha de datos conocida!", parse_mode=ParseMode.MARKDOWN)
            set_cache(cache_key, "✅ No se encontraron brechas.")
            return
        
        if response.status_code == 429:
            await status_msg.edit_text("⏳ Demasiadas peticiones. Espera un momento y vuelve a intentar.", parse_mode=ParseMode.MARKDOWN)
            return
        
        if response.status_code != 200:
            await status_msg.edit_text(f"❌ Error al consultar HIBP: Código {response.status_code}", parse_mode=ParseMode.MARKDOWN)
            return

        breaches = response.json()
        resultado = f"🚨 *El correo `{email}` fue comprometido en {len(breaches)} brecha(s):*\n\n"
        for breach in breaches[:10]:
            resultado += f"• *{breach.get('Name', 'Desconocido')}* ({breach.get('BreachDate', 'Fecha desconocida')})\n"
            if breach.get('Description'):
                resultado += f"  _{breach['Description'][:200]}..._\n"
        if len(breaches) > 10:
            resultado += f"\n*...y {len(breaches) - 10} brechas más.*"

        set_cache(cache_key, resultado)
        await status_msg.edit_text(resultado, parse_mode=ParseMode.MARKDOWN)

    except requests.exceptions.RequestException:
        await status_msg.edit_text("❌ Error al conectar con el servicio HIBP.", parse_mode=ParseMode.MARKDOWN)
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

    # Como numverify requiere API key, usamos una API pública gratuita (ejemplo)
    # Puedes reemplazar esto con numverify si tienes clave
    try:
        response = requests.get(f"http://apilayer.net/api/validate?access_key=&number={phone}")
        # Nota: Necesitas una API key de numverify (gratis hasta 100/mes)
        # Por ahora mostramos un mensaje informativo
        await status_msg.edit_text(
            "📱 *Funcionalidad en desarrollo*\n\n"
            "Para usar `/phone`, necesitas una API key de numverify.com (gratis).\n"
            "Mientras tanto, puedes buscar el número en Google o en sitios como `https://www.veriphone.io/`.",
            parse_mode=ParseMode.MARKDOWN
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
        await status_msg.edit_text("❌ La librería `whois` no está instalada. Agrega `python-whois` a requirements.txt.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error en whois_lookup: {e}")
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
    await update.message.reply_text("❌ Comando no reconocido. Usa `/menu` para ver las opciones disponibles.", parse_mode=ParseMode.MARKDOWN)

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