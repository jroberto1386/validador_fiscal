# ==============================================================================
# app.py - v2.0 - Servidor con Validador Excel y Lector de XML
# ==============================================================================
# Esta versión añade la capacidad de procesar un archivo ZIP con facturas XML,
# extraer sus datos clave y mostrarlos en pantalla.
# ==============================================================================

# --- 1. Importación de Librerías ---
import pandas as pd
from flask import Flask, render_template, request
import xml.etree.ElementTree as ET # Para leer XML
import zipfile # Para manejar archivos ZIP
import io # Para leer archivos en memoria

# --- 2. Inicialización de la Aplicación ---
app = Flask(__name__)

# --- 3. Lógica para el Lector de XML ---

def procesar_zip_con_xml(zip_file):
    """
    Recibe un archivo ZIP, lo descomprime en memoria, lee cada XML,
    extrae datos clave y los devuelve en una lista.
    """
    datos_extraidos = []
    
    # Abrimos el archivo ZIP en modo lectura
    with zipfile.ZipFile(zip_file, 'r') as zf:
        # Iteramos sobre cada archivo dentro del ZIP
        for nombre_archivo in zf.namelist():
            if nombre_archivo.lower().endswith('.xml'):
                try:
                    # Leemos el contenido del XML
                    contenido_xml = zf.read(nombre_archivo)
                    
                    # Parseamos el XML
                    root = ET.fromstring(contenido_xml)
                    
                    # Los CFDI usan 'namespaces', debemos definirlos para poder buscar etiquetas
                    ns = {
                        'cfdi': 'http://www.sat.gob.mx/cfd/4',
                        'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
                    }
                    
                    # Extraemos los datos usando los namespaces
                    emisor_rfc = root.find('cfdi:Emisor', ns).get('Rfc')
                    receptor_rfc = root.find('cfdi:Receptor', ns).get('Rfc')
                    subtotal = root.get('SubTotal')
                    total = root.get('Total')
                    
                    # El UUID está en un nodo anidado
                    timbre = root.find('.//tfd:TimbreFiscalDigital', ns)
                    uuid = timbre.get('UUID') if timbre is not None else 'No encontrado'
                    
                    # Guardamos los datos en un diccionario
                    datos_factura = {
                        'archivo': nombre_archivo,
                        'uuid': uuid,
                        'emisor_rfc': emisor_rfc,
                        'receptor_rfc': receptor_rfc,
                        'subtotal': float(subtotal),
                        'total': float(total)
                    }
                    datos_extraidos.append(datos_factura)
                except Exception as e:
                    # Si un archivo no es un CFDI válido, lo registramos
                    datos_extraidos.append({
                        'archivo': nombre_archivo,
                        'error': f'Error al procesar: {e}'
                    })

    return datos_extraidos

# --- 4. Lógica para el Validador de Excel (sin cambios) ---
# (Aquí va la función ejecutar_validaciones que ya teníamos)
def ejecutar_validaciones(df_isr, df_facturacion, df_resumen, df_iva):
    resultados = []
    meses_a_validar = ['6', '7']
    df_isr.columns = df_isr.columns.map(str)
    df_iva.columns = df_iva.columns.map(str)
    for mes_idx in meses_a_validar:
        ingresos_calculo = df_isr.loc['Ingresos cobrados del mes', mes_idx]
        if ingresos_calculo == 0: continue
        try:
            facturas_mes = df_facturacion[df_facturacion['Mes'] == int(mes_idx)]
            ingresos_facturas = facturas_mes[facturas_mes['Estado SAT'] == 'Vigente']['SubTotal'].sum()
            if abs(ingresos_calculo - ingresos_facturas) < 0.01:
                resultados.append({'id': 1, 'punto': f'Conciliación de Ingresos (Mes {mes_idx})', 'status': '✅ Correcto', 'obs': f'Los ingresos (${ingresos_calculo:,.2f}) coinciden con los CFDI.'})
            else:
                resultados.append({'id': 1, 'punto': f'Conciliación de Ingresos (Mes {mes_idx})', 'status': '❌ Error', 'obs': f'Ingresos del cálculo (${ingresos_calculo:,.2f}) no coinciden con los CFDI (${ingresos_facturas:,.2f}).'})
        except Exception as e:
            resultados.append({'id': 1, 'punto': f'Conciliación de Ingresos (Mes {mes_idx})', 'status': '⚠️ Advertencia', 'obs': f'No se pudo realizar la validación. Error: {e}'})
        try:
            iva_a_cargo = df_iva.loc['IVA a cargo (a favor)', mes_idx]
            if iva_a_cargo == 0:
                 resultados.append({'id': 2, 'punto': f'Validación de IVA Exento (Mes {mes_idx})', 'status': '✅ Correcto', 'obs': 'El IVA a cargo es $0.00, acorde a la actividad exenta.'})
            else:
                 resultados.append({'id': 2, 'punto': f'Validación de IVA Exento (Mes {mes_idx})', 'status': '❌ Error', 'obs': f'Se calculó un IVA a cargo de ${iva_a_cargo:,.2f} para una actividad exenta.'})
        except Exception as e:
            resultados.append({'id': 2, 'punto': f'Validación de IVA Exento (Mes {mes_idx})', 'status': '⚠️ Advertencia', 'obs': f'No se pudo verificar el IVA. Error: {e}'})
        try:
            pago_calculo = df_isr.loc['Total a pagar', mes_idx]
            pago_resumen = df_resumen.iloc[7, 3 + int(mes_idx)]
            if abs(pago_calculo - pago_resumen) < 0.01:
                resultados.append({'id': 3, 'punto': f'Consistencia del Saldo a Pagar (Mes {mes_idx})', 'status': '✅ Correcto', 'obs': f'El saldo a pagar (${pago_calculo:,.2f}) es consistente.'})
            else:
                resultados.append({'id': 3, 'punto': f'Consistencia del Saldo a Pagar (Mes {mes_idx})', 'status': '❌ Error', 'obs': f'El pago del cálculo (${pago_calculo:,.2f}) no coincide con el resumen (${pago_resumen:,.2f}).'})
        except Exception as e:
            resultados.append({'id': 3, 'punto': f'Consistencia del Saldo a Pagar (Mes {mes_idx})', 'status': '⚠️ Advertencia', 'obs': f'No se pudo realizar la validación. Error: {e}'})
        try:
            retencion_calculo = df_isr.loc['ISR retenido', mes_idx]
            facturas_mes_vigentes = facturas_mes[facturas_mes['Estado SAT'] == 'Vigente']
            facturas_pm = facturas_mes_vigentes[facturas_mes_vigentes['RFC Receptor'].str.len() == 12]
            retencion_facturas = facturas_pm['Retenido ISR'].sum()
            if abs(retencion_calculo - retencion_facturas) < 0.01:
                resultados.append({'id': 4, 'punto': f'Verificación de Retenciones (Mes {mes_idx})', 'status': '✅ Correcto', 'obs': f'La retención (${retencion_calculo:,.2f}) es consistente con los CFDI.'})
            else:
                resultados.append({'id': 4, 'punto': f'Verificación de Retenciones (Mes {mes_idx})', 'status': '❌ Error', 'obs': f'La retención del cálculo (${retencion_calculo:,.2f}) no coincide con la de los CFDI (${retencion_facturas:,.2f}).'})
        except Exception as e:
            resultados.append({'id': 4, 'punto': f'Verificación de Retenciones (Mes {mes_idx})', 'status': '⚠️ Advertencia', 'obs': f'No se pudo realizar la validación. Error: {e}'})
    return resultados

# --- 5. Definición de Rutas de la Aplicación ---

# Ruta para la página principal. Ahora mostrará ambas opciones.
@app.route('/')
def index():
    return render_template('index.html')

# Ruta para el Validador de Excel
@app.route('/validar_excel', methods=['POST'])
def validar_excel():
    if 'archivo_excel' not in request.files: return "Error: No se encontró el archivo.", 400
    file = request.files['archivo_excel']
    if file.filename == '': return "Error: No se seleccionó ningún archivo.", 400
    if file:
        try:
            df_isr = pd.read_excel(file, sheet_name='Calculo ISR', index_col=0, header=3)
            df_facturacion = pd.read_excel(file, sheet_name='Facturacion', header=5)
            df_resumen = pd.read_excel(file, sheet_name='RESUMEN', header=None)
            df_iva = pd.read_excel(file, sheet_name='Calculo IVA', index_col=1, header=5)
            resultados_validacion = ejecutar_validaciones(df_isr, df_facturacion, df_resumen, df_iva)
            return render_template('resultados_excel.html', resultados=resultados_validacion, nombre_archivo=file.filename)
        except Exception as e:
            return f"Error al procesar el archivo Excel. Detalle: {e}", 500
    return "Error inesperado.", 500

# NUEVA RUTA para el Procesador de XML
@app.route('/procesar_zip', methods=['POST'])
def procesar_zip():
    if 'archivo_zip' not in request.files: return "Error: No se encontró el archivo.", 400
    file = request.files['archivo_zip']
    if file.filename == '': return "Error: No se seleccionó ningún archivo.", 400
    if file and file.filename.lower().endswith('.zip'):
        try:
            # Llamamos a nuestra nueva función para leer el ZIP
            lista_facturas = procesar_zip_con_xml(file)
            # Calculamos los totales para un resumen rápido
            total_facturado = sum(f.get('total', 0) for f in lista_facturas)
            return render_template('resultados_xml.html', 
                                   facturas=lista_facturas, 
                                   nombre_archivo=file.filename,
                                   total_facturado=total_facturado,
                                   cantidad_facturas=len(lista_facturas))
        except Exception as e:
            return f"Error al procesar el archivo ZIP. Detalle: {e}", 500
    return "Error: El archivo debe ser de tipo .zip", 400

# --- 6. Punto de Entrada para Ejecución ---
if __name__ == '__main__':
    app.run(debug=True)
