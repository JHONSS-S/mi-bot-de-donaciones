# telegram_bot.py - VERSIÓN 3 CON MENÚ DE REPORTES INTERACTIVO

import os
import base64
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup # Se importa para los botones
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler # Se importa para manejar botones
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool 
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURACIÓN DE LOGGING Y APIs ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- TUS CLAVES Y IDs ---
TELEGRAM_TOKEN = "8087796067:AAG9jMlLOSvgcxOIXwFQ4av8QmLLmF0Wx4E" 
os.environ["OPENAI_API_KEY"] = ""

# Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive.file']
CREDS_FILE = 'credentials.json' 
SPREADSHEET_ID = '18SLDI7zoQWLFFoPAKtMCvA7Bw8p8NRzW9uz9ol05-AY'
SHEET_NAME = 'Donaciones'

# --- HERRAMIENTA PERSONALIZADA (Sin cambios) ---
@tool("Herramienta de Análisis de Formularios de Donación")
def donation_form_analysis_tool(image_path: str) -> str:
    """Analiza una imagen de un formulario de donación y extrae campos específicos."""
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        return json.dumps({"error": "No se pudo encontrar el archivo de imagen."})
    
    prompt_texto = """Analiza la imagen de este formulario de donación 'S-27-S'.
    Extrae la siguiente información y devuélvela en un formato JSON estricto:
    - 'fecha': Intenta encontrar la fecha en el documento. Puede estar en formato DD/MM/AAAA, DD-MM-AAAA o similar. Normalízala siempre a AAAA-MM-DD.
    - 'transaccion_tipo': Determina si la casilla 'Depósito' o 'Efectivo' está marcada. Devuelve la palabra "Depósito" o "Efectivo".
    - 'donacion_mundial': El valor numérico de la línea 'Donaciones para la obra mundial'.
    - 'donacion_local': El valor numérico de la línea 'Donaciones para la congregación local'.
    - 'total_donado': El valor numérico de la línea 'Total'.
    
    Si algún campo no se encuentra, devuélvelo como 'N/A'. Si un valor numérico es cero, devuelve 0.0."""
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt_texto}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
        max_tokens=500,
    )
    return response.choices[0].message.content

# --- AGENTES Y TAREAS (Sin cambios) ---
form_extractor_agent = Agent(role='Especialista en Formularios', goal='Extraer con precisión los campos de un formulario.', backstory='Eres un asistente administrativo experto en leer formularios.', tools=[donation_form_analysis_tool], verbose=True)
extraction_task = Task(description='Analiza la imagen del formulario. La ruta es: {image_path}', expected_output='Un string JSON con los datos.', agent=form_extractor_agent)

# --- FUNCIONES DEL BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envía un mensaje de bienvenida."""
    # Mensaje de bienvenida modificado para incluir el nuevo comando de reportes
    await update.message.reply_text('¡Hola! Envíame la foto de un formulario o usa /reporte para ver los totales.')

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa la foto de un formulario enviada por el usuario."""
    user = update.message.from_user
    photo_file = await update.message.photo[-1].get_file()
    temp_photo_path = f'temp_receipt_{user.id}.jpg'
    await photo_file.download_to_drive(temp_photo_path)
    await update.message.reply_text('🤖 Formulario recibido. Analizando con la IA...')
    try:
        donation_crew = Crew(agents=[form_extractor_agent], tasks=[extraction_task], process=Process.sequential)
        result = donation_crew.kickoff(inputs={'image_path': temp_photo_path})
        data = json.loads(result.raw)
        fecha_extraida = data.get('fecha', 'N/A')
        fecha_para_guardar = fecha_extraida if fecha_extraida and fecha_extraida != 'N/A' else datetime.now().strftime('%Y-%m-%d')
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        new_row = [fecha_para_guardar, data.get('transaccion_tipo', 'N/A'), data.get('donacion_mundial', 0.0), data.get('donacion_local', 0.0), data.get('total_donado', 0.0)]
        sheet.append_row(new_row)
        await update.message.reply_text(f"✅ ¡Éxito! Formulario guardado con fecha {fecha_para_guardar}. Total: ${data.get('total_donado', 0.0)}")
    except Exception as e:
        logging.error(f"Error procesando el formulario: {e}")
        await update.message.reply_text(f"❌ Hubo un error al procesar tu formulario.")
    finally:
        if os.path.exists(temp_photo_path):
            os.remove(temp_photo_path)

# --- NUEVA FUNCIÓN para el comando /reporte que muestra los botones ---
async def reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra un menú de botones para elegir el tipo de reporte."""
    keyboard = [
        [InlineKeyboardButton("Total Obra Mundial", callback_data='total_mundial')],
        [InlineKeyboardButton("Total Congregación", callback_data='total_local')],
        [InlineKeyboardButton("Gran Total (Ambos)", callback_data='gran_total')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Por favor, elige el reporte que deseas:', reply_markup=reply_markup)

# --- NUEVA FUNCIÓN que maneja los clics en los botones ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa la opción del menú de botones."""
    query = update.callback_query
    await query.answer() # Responde al clic para que el botón deje de cargar

    try:
        # 1. Conectarse a la hoja de cálculo
        creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        registros = sheet.get_all_records()

        # 2. Calcular los totales
        total_mundial = 0.0
        total_local = 0.0
        gran_total = 0.0

        for fila in registros:
            # Usamos .get() para evitar errores si la columna no existe en una fila
            total_mundial += float(fila.get('Donación Mundial', 0))
            total_local += float(fila.get('Donación Local', 0))
            gran_total += float(fila.get('Total', 0))

        # 3. Preparar la respuesta según el botón presionado
        opcion = query.data
        mensaje = ""
        if opcion == 'total_mundial':
            mensaje = f"El total acumulado para la Obra Mundial es: ${total_mundial:,.2f}"
        elif opcion == 'total_local':
            mensaje = f"El total acumulado para la Congregación Local es: ${total_local:,.2f}"
        elif opcion == 'gran_total':
            mensaje = f"El Gran Total de todas las donaciones es: ${gran_total:,.2f}"
        
        # Edita el mensaje original para mostrar el resultado
        await query.edit_message_text(text=mensaje)

    except Exception as e:
        logging.error(f"Error generando reporte: {e}")
        await query.edit_message_text(text="❌ Hubo un error al generar el reporte.")

def main():
    """Inicia el bot de Telegram."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Manejadores para start y fotos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    # --- MANEJADORES NUEVOS PARA LOS REPORTES ---
    application.add_handler(CommandHandler("reporte", reporte))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 El bot de donaciones (v3 con reportes) está en línea...")
    application.run_polling()

if __name__ == '__main__':
    main()