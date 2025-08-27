# ==============================================================================
# app.py - v4.0 - Versión Final con Ciclo de Validación Completo
# ==============================================================================
# Esta versión finaliza el proyecto:
# 1. Lee XML y calcula impuestos.
# 2. Genera y permite descargar un Papel de Trabajo en Excel.
# 3. La función de validación ahora puede leer y verificar la consistencia
#    de ese mismo Papel de Trabajo generado, cerrando el ciclo.
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
app.secret_key = os.urandom(24)

# --- 3. Lógica para el Lector de XML (sin cambios) ---
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
                    emisor_node = root.find('cfdi:Emisor', ns)
                    emisor_rfc = emisor_node.get('Rfc')
                    if nombre_contribuyente == "No identificado": nombre_contribuyente = emisor_node.get('Nombre')
                    fecha_str = root.get('Fecha')
                    if fecha_str.endswith('Z'): fecha_str = fecha_str[:-1]
                    fecha_dt = datetime.fromisoformat(fecha_str)
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

# --- 5. Generador de Papel de Trabajo Excel (sin cambios) ---
def generar_papel_de_trabajo_excel(facturas, calculo, rfc, nombre, periodo):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        facturas_para_excel = [dict(f) for f in facturas]
        for factura in facturas_para_excel:
            if factura.get('fecha') and factura['fecha'].tzinfo is not None:
                factura['fecha'] = factura['fecha'].replace(tzinfo=None)
        df_facturacion = pd.DataFrame(facturas_para_excel)
        df_facturacion.to_excel(writer, sheet_name='Facturacion', index=False)
        datos_isr = {
            'Concepto': ['Ingresos cobrados del mes', 'Tasa aplicable', 'Impuesto Causado', 'ISR retenido', 'Total a pagar'],
            periodo: [calculo['total_ingresos'], calculo['tasa_isr_aplicada'], calculo['impuesto_causado'], calculo['total_retenciones_isr'], calculo['isr_a_pagar']]
        }
        df_isr = pd.DataFrame(datos_isr)
        df_isr.to_excel(writer, sheet_name='Calculo ISR', index=False)
        datos_resumen = { 'Impuesto': ['ISR a Pagar', 'IVA a Pagar'], 'Monto': [calculo['isr_a_pagar'], calculo['iva_a_pagar']] }
        df_resumen = pd.DataFrame(datos_resumen)
        df_resumen.to_excel(writer, sheet_name='RESUMEN', index=False)
    output.seek(0)
    return output

# --- 6. Lógica para el Validador de Excel (RECONSTRUIDA) ---
def ejecutar_validacion_de_pt_generado(file):
    resultados = []
    # Leemos las hojas del papel de trabajo generado
    df_facturacion = pd.read_excel(file, sheet_name='Facturacion')
    df_isr = pd.read_excel(file, sheet_name='Calculo ISR', index_col=0)
    df_resumen = pd.read_excel(file, sheet_name='RESUMEN', index_col=0)

    # Re-calculamos los totales desde la hoja de facturación para comparar
    ingresos_recalculados = df_facturacion['subtotal'].sum()
    retenciones_recalculadas = df_facturacion[df_facturacion['receptor_rfc'].str.len() == 12]['isr_retenido'].sum()

    # Extraemos los valores de la hoja de cálculo
    ingresos_en_pt = df_isr.iloc[0, 0]
    retenciones_en_pt = df_isr.iloc[3, 0]
    pago_final_en_pt = df_isr.iloc[4, 0]
    pago_final_en_resumen = df_resumen.iloc[0, 0]

    # Validación 1: Ingresos
    if abs(ingresos_recalculados - ingresos_en_pt) < 0.01:
        resultados.append({'id': 1, 'punto': 'Conciliación de Ingresos (Facturación vs. Cálculo)', 'status': '✅ Correcto', 'obs': f'Los ingresos (${ingresos_en_pt:,.2f}) son consistentes.'})
    else:
        resultados.append({'id': 1, 'punto': 'Conciliación de Ingresos (Facturación vs. Cálculo)', 'status': '❌ Error', 'obs': f'Ingresos en cálculo (${ingresos_en_pt:,.2f}) no coinciden con la suma de facturas (${ingresos_recalculados:,.2f}).'})

    # Validación 2: Retenciones
    if abs(retenciones_recalculadas - retenciones_en_pt) < 0.01:
        resultados.append({'id': 2, 'punto': 'Conciliación de Retenciones (Facturación vs. Cálculo)', 'status': '✅ Correcto', 'obs': f'Las retenciones (${retenciones_en_pt:,.2f}) son consistentes.'})
    else:
        resultados.append({'id': 2, 'punto': 'Conciliación de Retenciones (Facturación vs. Cálculo)', 'status': '❌ Error', 'obs': f'Retenciones en cálculo (${retenciones_en_pt:,.2f}) no coinciden con la suma de facturas (${retenciones_recalculadas:,.2f}).'})
        
    # Validación 3: Consistencia del Pago Final
    if abs(pago_final_en_pt - pago_final_en_resumen) < 0.01:
        resultados.append({'id': 3, 'punto': 'Consistencia del Saldo a Pagar (Cálculo vs. Resumen)', 'status': '✅ Correcto', 'obs': f'El saldo a pagar (${pago_final_en_pt:,.2f}) es consistente.'})
    else:
        resultados.append({'id': 3, 'punto': 'Consistencia del Saldo a Pagar (Cálculo vs. Resumen)', 'status': '❌ Error', 'obs': f'El pago del cálculo (${pago_final_en_pt:,.2f}) no coincide con el resumen (${pago_final_en_resumen:,.2f}).'})

    return resultados

# --- 7. Definición de Rutas de la Aplicación ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/procesar_zip', methods=['POST'])
def procesar_zip():
    # (El código de esta función no cambia)
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
            session['datos_para_excel'] = {
                'facturas': facturas_a_mostrar, 'calculo': calculo, 'rfc': rfc,
                'nombre': nombre_contribuyente, 'periodo': f'{mes}-{anio}'
            }
            return render_template('resultados_xml.html', 
                                   facturas=facturas_a_mostrar, nombre_archivo=file.filename,
                                   calculo=calculo, periodo=f'{mes}/{anio}',
                                   nombre_contribuyente=nombre_contribuyente)
        except Exception as e:
            return f"Error al procesar el archivo ZIP. Detalle: {e}", 500
    return "Error: El archivo debe ser de tipo .zip", 400

@app.route('/descargar_excel')
def descargar_excel():
    # (El código de esta función no cambia)
    datos = session.get('datos_para_excel', None)
    if not datos:
        return "Error: No hay datos para generar el archivo.", 404
    try:
        archivo_excel = generar_papel_de_trabajo_excel(
            datos['facturas'], datos['calculo'], datos['rfc'], datos['nombre'], datos['periodo']
        )
        nombre_archivo_salida = f"PT_{datos['rfc']}_{datos['periodo']}.xlsx"
        return send_file(archivo_excel, 
                         download_name=nombre_archivo_salida, as_attachment=True,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except Exception as e:
        return f"Error al generar el archivo Excel: {e}", 500

@app.route('/validar_excel', methods=['POST'])
def validar_excel():
    # --- CÓDIGO RECONSTRUIDO ---
    if 'archivo_excel' not in request.files: return "Error: No se encontró el archivo.", 400
    file = request.files['archivo_excel']
    if file.filename == '': return "Error: No se seleccionó ningún archivo.", 400
    if file:
        try:
            # Llamamos a nuestra nueva función de validación
            resultados_validacion = ejecutar_validacion_de_pt_generado(file)
            # Mostramos los resultados en la plantilla que ya teníamos
            return render_template('resultados_excel.html', 
                                   resultados=resultados_validacion, 
                                   nombre_archivo=file.filename)
        except Exception as e:
            return f"Error al procesar el archivo Excel. Detalle: {e}", 500
    return "Error inesperado.", 500

# --- Punto de Entrada para Ejecución ---
if __name__ == '__main__':
    app.run(debug=True)
