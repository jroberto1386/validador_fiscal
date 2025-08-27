# ==============================================================================
# app.py - v3.0 - Versión Final con Generación de Papel de Trabajo
# ==============================================================================
# Esta versión completa el ciclo:
# 1. Lee XML desde un ZIP.
# 2. Calcula los impuestos.
# 3. Muestra un reporte personalizado con el nombre del contribuyente.
# 4. Permite descargar el papel de trabajo generado en formato Excel.
# ==============================================================================

# --- 1. Importación de Librerías ---
import pandas as pd
from flask import Flask, render_template, request, send_file, session
import xml.etree.ElementTree as ET
import zipfile
import io
from datetime import datetime
import os

# --- 2. Inicialización de la Aplicación ---
app = Flask(__name__)
# Se necesita una 'secret_key' para usar sesiones en Flask
app.secret_key = os.urandom(24)

# --- 3. Lógica para el Lector de XML ---
def procesar_zip_con_xml(zip_file):
    datos_extraidos = []
    nombre_contribuyente = "No identificado"
    with zipfile.ZipFile(zip_file, 'r') as zf:
        for nombre_archivo in zf.namelist():
            if nombre_archivo.lower().endswith('.xml') and not nombre_archivo.startswith('__MACOSX'):
                try:
                    contenido_xml = zf.read(nombre_archivo)
                    root = ET.fromstring(contenido_xml)
                    ns = {'cfdi': 'http://www.sat.gob.mx/cfd/4', 'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'}
                    
                    # Extraemos el nombre del emisor (contribuyente)
                    emisor_node = root.find('cfdi:Emisor', ns)
                    emisor_rfc = emisor_node.get('Rfc')
                    if nombre_contribuyente == "No identificado": # Tomamos el primer nombre que encontremos
                        nombre_contribuyente = emisor_node.get('Nombre')

                    fecha_str = root.get('Fecha')
                    fecha_dt = datetime.fromisoformat(fecha_str.replace('T', ' '))
                    receptor_rfc = root.find('cfdi:Receptor', ns).get('Rfc')
                    subtotal = float(root.get('SubTotal'))
                    total = float(root.get('Total'))
                    isr_retenido = 0.0
                    retenciones_node = root.find('.//cfdi:Retenciones/cfdi:Retencion[@Impuesto="001"]', ns)
                    if retenciones_node is not None: isr_retenido = float(retenciones_node.get('Importe'))
                    timbre = root.find('.//tfd:TimbreFiscalDigital', ns)
                    uuid = timbre.get('UUID') if timbre is not None else 'No encontrado'
                    datos_factura = {
                        'archivo': nombre_archivo, 'uuid': uuid, 'fecha': fecha_dt,
                        'emisor_rfc': emisor_rfc, 'receptor_rfc': receptor_rfc,
                        'subtotal': subtotal, 'total': total, 'isr_retenido': isr_retenido,
                        'error': None
                    }
                    datos_extraidos.append(datos_factura)
                except Exception as e:
                    datos_extraidos.append({
                        'archivo': nombre_archivo, 'uuid': 'Error de Lectura', 'fecha': None,
                        'emisor_rfc': '', 'receptor_rfc': '', 'subtotal': 0, 'total': 0,
                        'isr_retenido': 0, 'error': f'No es un CFDI válido: {e}'
                    })
    return datos_extraidos, nombre_contribuyente

# --- 4. Motor de Cálculo Fiscal (sin cambios) ---
def calcular_impuestos_resico(lista_facturas, rfc_propio, mes, anio):
    facturas_del_periodo = [f for f in lista_facturas if f.get('fecha') and f.get('fecha').month == mes and f.get('fecha').year == anio]
    facturas_ingresos = [f for f in facturas_del_periodo if f.get('emisor_rfc') == rfc_propio and f.get('error') is None]
    total_ingresos = sum(f.get('subtotal', 0) for f in facturas_ingresos)
    tasa_isr = 0.0
    if total_ingresos <= 25000: tasa_isr = 0.01
    elif total_ingresos <= 50000: tasa_isr = 0.011
    elif total_ingresos <= 83333.33: tasa_isr = 0.015
    elif total_ingresos <= 208333.33: tasa_isr = 0.02
    else: tasa_isr = 0.025
    impuesto_causado = total_ingresos * tasa_isr
    total_retenciones_isr = sum(f.get('isr_retenido', 0) for f in facturas_ingresos if len(f.get('receptor_rfc', '')) == 12)
    isr_a_pagar = impuesto_causado - total_retenciones_isr
    iva_a_pagar = 0.0
    return {
        'total_ingresos': total_ingresos, 'tasa_isr_aplicada': tasa_isr,
        'impuesto_causado': impuesto_causado, 'total_retenciones_isr': total_retenciones_isr,
        'isr_a_pagar': isr_a_pagar, 'iva_a_pagar': iva_a_pagar,
        'facturas_procesadas_periodo': len(facturas_del_periodo)
    }

# --- 5. NUEVO PILAR 3: Generador de Papel de Trabajo Excel ---
def generar_papel_de_trabajo_excel(facturas, calculo, rfc, nombre, periodo):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Hoja de Facturación
        df_facturacion = pd.DataFrame(facturas)
        df_facturacion.to_excel(writer, sheet_name='Facturacion', index=False)
        
        # Hoja de Cálculo ISR (simplificada)
        datos_isr = {
            'Concepto': ['Ingresos cobrados del mes', 'Tasa aplicable', 'Impuesto Causado', 'ISR retenido', 'Total a pagar'],
            periodo: [calculo['total_ingresos'], calculo['tasa_isr_aplicada'], calculo['impuesto_causado'], calculo['total_retenciones_isr'], calculo['isr_a_pagar']]
        }
        df_isr = pd.DataFrame(datos_isr)
        df_isr.to_excel(writer, sheet_name='Calculo ISR', index=False)
        
        # Hoja Resumen (simplificada)
        datos_resumen = {
            'Impuesto': ['ISR a Pagar', 'IVA a Pagar'],
            'Monto': [calculo['isr_a_pagar'], calculo['iva_a_pagar']]
        }
        df_resumen = pd.DataFrame(datos_resumen)
        df_resumen.to_excel(writer, sheet_name='RESUMEN', index=False)

    output.seek(0)
    return output

# --- 6. Definición de Rutas de la Aplicación ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/procesar_zip', methods=['POST'])
def procesar_zip():
    if 'archivo_zip' not in request.files or 'rfc_contribuyente' not in request.form or 'periodo' not in request.form:
        return "Error: Faltan datos (archivo, RFC o periodo).", 400
    
    file = request.files['archivo_zip']
    rfc = request.form['rfc_contribuyente'].upper()
    periodo = request.form['periodo']
    
    if file.filename == '' or rfc == '' or periodo == '':
        return "Error: Debes completar todos los campos.", 400
        
    if file and file.filename.lower().endswith('.zip'):
        try:
            anio, mes = map(int, periodo.split('-'))
            
            lista_facturas_total, nombre_contribuyente = procesar_zip_con_xml(file)
            calculo = calcular_impuestos_resico(lista_facturas_total, rfc, mes, anio)
            
            facturas_a_mostrar = [f for f in lista_facturas_total if not f.get('fecha') or (f.get('fecha').month == mes and f.get('fecha').year == anio)]
            
            # Guardamos los datos en la sesión para poder descargarlos después
            session['datos_para_excel'] = {
                'facturas': facturas_a_mostrar,
                'calculo': calculo,
                'rfc': rfc,
                'nombre': nombre_contribuyente,
                'periodo': f'{mes}-{anio}'
            }

            return render_template('resultados_xml.html', 
                                   facturas=facturas_a_mostrar, 
                                   nombre_archivo=file.filename,
                                   calculo=calculo,
                                   periodo=f'{mes}/{anio}',
                                   nombre_contribuyente=nombre_contribuyente)
        except Exception as e:
            return f"Error al procesar el archivo ZIP. Detalle: {e}", 500
            
    return "Error: El archivo debe ser de tipo .zip", 400

# --- NUEVA RUTA PARA DESCARGAR EL EXCEL ---
@app.route('/descargar_excel')
def descargar_excel():
    datos = session.get('datos_para_excel', None)
    if not datos:
        return "Error: No hay datos para generar el archivo. Por favor, procese un ZIP primero.", 404
    
    try:
        archivo_excel = generar_papel_de_trabajo_excel(
            datos['facturas'], datos['calculo'], datos['rfc'], datos['nombre'], datos['periodo']
        )
        
        nombre_archivo_salida = f"PT_{datos['rfc']}_{datos['periodo']}.xlsx"
        
        return send_file(archivo_excel, 
                         download_name=nombre_archivo_salida,
                         as_attachment=True,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return f"Error al generar el archivo Excel: {e}", 500

# --- Ruta para Validador de Excel (sin cambios) ---
@app.route('/validar_excel', methods=['POST'])
def validar_excel():
    # El código de esta función no cambia
    if 'archivo_excel' not in request.files: return "Error: No se encontró el archivo.", 400
    file = request.files['archivo_excel']
    if file.filename == '': return "Error: No se seleccionó ningún archivo.", 400
    if file:
        try:
            # ... (código de validación de excel omitido por brevedad) ...
            return "Función de validación de Excel ejecutada."
        except Exception as e:
            return f"Error al procesar el archivo Excel. Detalle: {e}", 500
    return "Error inesperado.", 500

# --- Punto de Entrada para Ejecución ---
if __name__ == '__main__':
    app.run(debug=True)
