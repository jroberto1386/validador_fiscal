# ==============================================================================
# app.py - v2.4 - Servidor con Corrección de Sintaxis
# ==============================================================================
# Esta versión corrige un error de sintaxis en el formateo de texto
# que impedía el despliegue de la aplicación.
# ==============================================================================

# --- 1. Importación de Librerías ---
import pandas as pd
from flask import Flask, render_template, request
import xml.etree.ElementTree as ET
import zipfile
import io
from datetime import datetime

# --- 2. Inicialización de la Aplicación ---
app = Flask(__name__)

# --- 3. Lógica para el Lector de XML (sin cambios) ---
def procesar_zip_con_xml(zip_file):
    datos_extraidos = []
    with zipfile.ZipFile(zip_file, 'r') as zf:
        for nombre_archivo in zf.namelist():
            if nombre_archivo.lower().endswith('.xml') and not nombre_archivo.startswith('__MACOSX'):
                try:
                    contenido_xml = zf.read(nombre_archivo)
                    root = ET.fromstring(contenido_xml)
                    ns = {'cfdi': 'http://www.sat.gob.mx/cfd/4', 'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'}
                    fecha_str = root.get('Fecha')
                    fecha_dt = datetime.fromisoformat(fecha_str.replace('T', ' '))
                    emisor_rfc = root.find('cfdi:Emisor', ns).get('Rfc')
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
    return datos_extraidos

# --- 4. Motor de Cálculo Fiscal (sin cambios) ---
def calcular_impuestos_resico(lista_facturas, rfc_propio, mes, anio):
    """
    Toma la lista de facturas y calcula los impuestos para un mes y año específicos.
    """
    facturas_del_periodo = [
        f for f in lista_facturas 
        if f.get('fecha') and f.get('fecha').month == mes and f.get('fecha').year == anio
    ]
    
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

# --- 5. Lógica para el Validador de Excel (CORREGIDA) ---
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
                # --- CORRECCIÓN DE SINTAXIS AQUÍ ---
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

# --- 6. Definición de Rutas de la Aplicación (sin cambios) ---
@app.route('/')
def index():
    return render_template('index.html')

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

@app.route('/procesar_zip', methods=['POST'])
def procesar_zip():
    if 'archivo_zip' not in request.files or 'rfc_contribuyente' not in request.form or 'periodo' not in request.form:
        return "Error: Faltan datos (archivo, RFC o periodo).", 400
    
    file = request.files['archivo_zip']
    rfc = request.form['rfc_contribuyente']
    periodo = request.form['periodo'] # Formato "YYYY-MM"
    
    if file.filename == '' or rfc == '' or periodo == '':
        return "Error: Debes completar todos los campos.", 400
        
    if file and file.filename.lower().endswith('.zip'):
        try:
            anio, mes = map(int, periodo.split('-'))
            
            lista_facturas_total = procesar_zip_con_xml(file)
            calculo = calcular_impuestos_resico(lista_facturas_total, rfc.upper(), mes, anio)
            
            facturas_a_mostrar = [f for f in lista_facturas_total if not f.get('fecha') or (f.get('fecha').month == mes and f.get('fecha').year == anio)]

            return render_template('resultados_xml.html', 
                                   facturas=facturas_a_mostrar, 
                                   nombre_archivo=file.filename,
                                   calculo=calculo,
                                   periodo=f'{mes}/{anio}')
        except Exception as e:
            return f"Error al procesar el archivo ZIP. Detalle: {e}", 500
            
    return "Error: El archivo debe ser de tipo .zip", 400

# --- 7. Punto de Entrada para Ejecución ---
if __name__ == '__main__':
    app.run(debug=True)
