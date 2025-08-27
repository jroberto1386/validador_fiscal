# ==============================================================================
# app.py - v2.1 - Servidor con Lector XML y Motor de Cálculo Fiscal
# ==============================================================================
# Esta versión añade el "Pilar 2": un motor de cálculo que toma los datos
# extraídos del XML y determina los impuestos para RESICO.
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
    
    with zipfile.ZipFile(zip_file, 'r') as zf:
        for nombre_archivo in zf.namelist():
            if nombre_archivo.lower().endswith('.xml'):
                try:
                    contenido_xml = zf.read(nombre_archivo)
                    root = ET.fromstring(contenido_xml)
                    
                    ns = {
                        'cfdi': 'http://www.sat.gob.mx/cfd/4',
                        'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
                    }
                    
                    # Extraemos datos adicionales como la fecha y las retenciones
                    fecha = root.get('Fecha')
                    emisor_rfc = root.find('cfdi:Emisor', ns).get('Rfc')
                    receptor_rfc = root.find('cfdi:Receptor', ns).get('Rfc')
                    subtotal = float(root.get('SubTotal'))
                    total = float(root.get('Total'))
                    
                    # Buscamos las retenciones de ISR
                    isr_retenido = 0.0
                    retenciones_node = root.find('.//cfdi:Retencion', ns)
                    if retenciones_node is not None and retenciones_node.get('Impuesto') == '001': # 001 es el código para ISR
                        isr_retenido = float(retenciones_node.get('Importe'))
                    
                    timbre = root.find('.//tfd:TimbreFiscalDigital', ns)
                    uuid = timbre.get('UUID') if timbre is not None else 'No encontrado'
                    
                    datos_factura = {
                        'archivo': nombre_archivo, 'uuid': uuid, 'fecha': fecha,
                        'emisor_rfc': emisor_rfc, 'receptor_rfc': receptor_rfc,
                        'subtotal': subtotal, 'total': total, 'isr_retenido': isr_retenido
                    }
                    datos_extraidos.append(datos_factura)
                except Exception as e:
                    datos_extraidos.append({'archivo': nombre_archivo, 'error': f'Error al procesar: {e}'})

    return datos_extraidos

# --- 4. NUEVO PILAR 2: Motor de Cálculo Fiscal ---

def calcular_impuestos_resico(lista_facturas, rfc_propio):
    """
    Toma la lista de facturas extraídas y calcula los impuestos para RESICO.
    """
    # Filtramos solo las facturas de ingresos (donde nosotros somos el emisor)
    facturas_ingresos = [f for f in lista_facturas if f.get('emisor_rfc') == rfc_propio]
    
    # 1. Sumamos los ingresos del mes
    total_ingresos = sum(f.get('subtotal', 0) for f in facturas_ingresos)
    
    # 2. Determinamos la tasa de ISR según la tabla de RESICO (simplificada)
    tasa_isr = 0.0
    if total_ingresos <= 25000: tasa_isr = 0.01
    elif total_ingresos <= 50000: tasa_isr = 0.011
    elif total_ingresos <= 83333.33: tasa_isr = 0.015
    elif total_ingresos <= 208333.33: tasa_isr = 0.02
    else: tasa_isr = 0.025
    
    # 3. Calculamos el impuesto causado
    impuesto_causado = total_ingresos * tasa_isr
    
    # 4. Sumamos las retenciones de ISR (solo de facturas a personas morales)
    total_retenciones_isr = sum(f.get('isr_retenido', 0) for f in facturas_ingresos if len(f.get('receptor_rfc', '')) == 12)
    
    # 5. Determinamos el impuesto a pagar
    isr_a_pagar = impuesto_causado - total_retenciones_isr
    
    # 6. Para este caso (Arrendamiento Casa Habitación), el IVA es 0.
    iva_a_pagar = 0.0
    
    # Devolvemos un diccionario con todos los resultados del cálculo
    return {
        'total_ingresos': total_ingresos,
        'tasa_isr_aplicada': tasa_isr,
        'impuesto_causado': impuesto_causado,
        'total_retenciones_isr': total_retenciones_isr,
        'isr_a_pagar': isr_a_pagar,
        'iva_a_pagar': iva_a_pagar
    }

# --- 5. Lógica para el Validador de Excel (sin cambios) ---
def ejecutar_validaciones(df_isr, df_facturacion, df_resumen, df_iva):
    # (El código de esta función no cambia)
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

# --- 6. Definición de Rutas de la Aplicación ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/validar_excel', methods=['POST'])
def validar_excel():
    # (El código de esta función no cambia)
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
    if 'archivo_zip' not in request.files or 'rfc_contribuyente' not in request.form:
        return "Error: Faltan datos (archivo zip o RFC).", 400
    
    file = request.files['archivo_zip']
    rfc = request.form['rfc_contribuyente']
    
    if file.filename == '' or rfc == '':
        return "Error: No se seleccionó archivo o no se ingresó RFC.", 400
        
    if file and file.filename.lower().endswith('.zip'):
        try:
            # Pilar 1: Leemos los XML
            lista_facturas = procesar_zip_con_xml(file)
            
            # Pilar 2: Calculamos los impuestos
            calculo = calcular_impuestos_resico(lista_facturas, rfc.upper())
            
            # Enviamos ambos resultados a la plantilla
            return render_template('resultados_xml.html', 
                                   facturas=lista_facturas, 
                                   nombre_archivo=file.filename,
                                   calculo=calculo)
        except Exception as e:
            return f"Error al procesar el archivo ZIP. Detalle: {e}", 500
            
    return "Error: El archivo debe ser de tipo .zip", 400

# --- 7. Punto de Entrada para Ejecución ---
if __name__ == '__main__':
    app.run(debug=True)
